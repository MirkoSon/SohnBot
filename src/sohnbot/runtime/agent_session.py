"""
Claude Agent SDK Session Management.

Wrapper for ClaudeSDKClient with SohnBot-specific configuration.
"""

import json
import os
from pathlib import Path
import inspect
from typing import Awaitable, Callable
from uuid import uuid4

import structlog
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from structlog.contextvars import bind_contextvars

from ..persistence.audit import log_operation_end, log_operation_start
from .gemini_adapter_mcp import create_gemini_adapter_mcp_server
from .hooks import validate_tool_use
from .mcp_tools import create_sohnbot_mcp_server
from .postponement_manager import PostponementManager

logger = structlog.get_logger(__name__)

SendMessageFn = Callable[[int, str], Awaitable[bool]]

MCP_POLICY_MODE_ENV = "SOHNBOT_MCP_POLICY_MODE"
MCP_POLICY_GOVERNED = "governed"
MCP_POLICY_SETTINGS = "settings"
LOAD_SETTINGS_MCPS_ENV = "SOHNBOT_LOAD_SETTINGS_MCPS"
ENABLE_GEMINI_MCP_ENV = "SOHNBOT_ENABLE_GEMINI_MCP"
ENABLE_GEMINI_ADAPTER_ENV = "SOHNBOT_ENABLE_GEMINI_ADAPTER"


def _mcp_policy_mode() -> str:
    raw = (os.getenv(MCP_POLICY_MODE_ENV) or MCP_POLICY_GOVERNED).strip().lower()
    if raw in {MCP_POLICY_GOVERNED, MCP_POLICY_SETTINGS}:
        return raw
    return MCP_POLICY_GOVERNED


def _load_settings_mcps_enabled() -> bool:
    raw = (os.getenv(LOAD_SETTINGS_MCPS_ENV) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _gemini_mcp_enabled() -> bool:
    raw = (os.getenv(ENABLE_GEMINI_MCP_ENV) or "").strip().lower()
    # Default off: raw Gemini MCP schemas may be incompatible with Claude Agent SDK.
    if not raw:
        return False
    return raw in {"1", "true", "yes", "on"}


def _gemini_adapter_enabled() -> bool:
    raw = (os.getenv(ENABLE_GEMINI_ADAPTER_ENV) or "").strip().lower()
    # Default on: adapter exposes Claude-safe schemas.
    if not raw:
        return True
    return raw in {"1", "true", "yes", "on"}


def _load_mcp_servers_from_settings(root: str) -> dict[str, dict]:
    """Load mcpServers maps from .claude/settings.json and settings.local.json."""
    base = Path(root)
    settings_files = [
        base / ".claude" / "settings.json",
        base / ".claude" / "settings.local.json",
    ]
    combined: dict[str, dict] = {}
    for settings_path in settings_files:
        try:
            if not settings_path.exists():
                continue
            raw = json.loads(settings_path.read_text(encoding="utf-8"))
            mcp_servers = raw.get("mcpServers")
            if not isinstance(mcp_servers, dict):
                continue
            for name, spec in mcp_servers.items():
                if isinstance(name, str) and isinstance(spec, dict):
                    combined[name] = spec
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_settings_parse_failed", path=str(settings_path), error=str(exc))
    return combined


def _normalize_external_mcp_spec(spec: dict) -> dict | None:
    """Convert settings-style MCP spec into Claude SDK mcp_servers config dict."""
    mcp_type = str(spec.get("type", "")).strip().lower()
    command = spec.get("command")
    url = spec.get("url")
    args = spec.get("args", [])
    env = spec.get("env", {})
    headers = spec.get("headers", {})

    if not isinstance(args, list):
        args = []
    if not isinstance(env, dict):
        env = {}
    if not isinstance(headers, dict):
        headers = {}

    # Infer stdio if type omitted but command is present.
    if not mcp_type and isinstance(command, str) and command.strip():
        mcp_type = "stdio"

    if mcp_type == "stdio":
        if not isinstance(command, str) or not command.strip():
            return None
        return {
            "type": "stdio",
            "command": command,
            "args": [str(arg) for arg in args],
            "env": {str(k): str(v) for k, v in env.items()},
        }

    if mcp_type in {"http", "sse"}:
        if not isinstance(url, str) or not url.strip():
            return None
        normalized = {"type": mcp_type, "url": url}
        if headers:
            normalized["headers"] = {str(k): str(v) for k, v in headers.items()}
        if env:
            normalized["env"] = {str(k): str(v) for k, v in env.items()}
        return normalized

    return None
class AgentSession:
    """Wrapper for Claude Agent SDK with SohnBot-specific configuration."""

    def __init__(self, config_manager, broker_router, ambiguity_evaluator: Callable[[str], bool] | None = None):
        """
        Initialize AgentSession.

        Args:
            config_manager: ConfigManager instance for config values
            broker_router: BrokerRouter instance for capability routing
        """
        self.config = config_manager
        self.broker = broker_router
        self.client = None
        self.postponement_manager = PostponementManager()
        self.ambiguity_evaluator = ambiguity_evaluator
        # Ambiguity guard is intentionally disabled: Claude should decide whether
        # to ask follow-up questions or proceed with tool selection.
        self.enable_ambiguity_guard = False

    async def initialize(self):
        """Initialize Claude SDK client with MCP server and hooks."""
        logger.info("initializing_agent_session")

        # Create in-process MCP server
        mcp_server = create_sohnbot_mcp_server(
            broker=self.broker,
            config=self.config
        )

        # Load model configuration
        model = self.config.get("models.telegram_default")
        max_thinking = self.config.get("runtime.telegram_max_thinking_tokens")
        max_turns = self.config.get("runtime.telegram_max_turns")

        logger.info(
            "agent_config_loaded",
            model=model,
            max_thinking_tokens=max_thinking,
            max_turns=max_turns
        )

        # Configure MCP servers
        mcp_servers = {"sohnbot": mcp_server}
        settings_external_server_names: list[str] = []

        # Add Gemini adapter (Claude-safe MCP schemas) when API key exists.
        gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        gemini_mcp_path = os.getenv("GEMINI_MCP_SERVER_PATH")

        if _gemini_adapter_enabled() and gemini_api_key:
            mcp_servers["gemini_adapter"] = create_gemini_adapter_mcp_server()
            logger.info("gemini_adapter_mcp_server_configured")
        elif gemini_api_key:
            logger.info("gemini_adapter_mcp_server_disabled_by_env", env=ENABLE_GEMINI_ADAPTER_ENV)

        # Raw external Gemini MCP is optional and disabled by default.
        if _gemini_mcp_enabled() and gemini_mcp_path and gemini_api_key:
            mcp_servers["gemini"] = {
                "type": "stdio",
                "command": "npx",
                "args": ["tsx", gemini_mcp_path],
                "env": {"GEMINI_API_KEY": gemini_api_key},
            }
            logger.info("gemini_mcp_server_configured", path=gemini_mcp_path)
        elif gemini_api_key and gemini_mcp_path:
            logger.info("gemini_mcp_server_disabled_by_env", env=ENABLE_GEMINI_MCP_ENV)

        claude_project_root = (os.getenv("SOHNBOT_CLAUDE_PROJECT_ROOT") or "").strip()
        if claude_project_root:
            setting_sources = ["project", "local"]
            session_cwd = claude_project_root
            logger.info("claude_project_settings_enabled", claude_project_root=claude_project_root)
        else:
            setting_sources = []
            session_cwd = str(Path.cwd())
            logger.info("claude_project_settings_disabled")

        if claude_project_root and _load_settings_mcps_enabled():
            settings_mcps = _load_mcp_servers_from_settings(claude_project_root)
            for name, spec in settings_mcps.items():
                if name in mcp_servers:
                    continue
                normalized = _normalize_external_mcp_spec(spec)
                if normalized is None:
                    logger.warning("settings_mcp_server_invalid", name=name)
                    continue
                mcp_servers[name] = normalized
                settings_external_server_names.append(name)
                logger.info("settings_mcp_server_configured", name=name, type=normalized.get("type"))
        elif claude_project_root:
            logger.info("settings_mcp_servers_disabled", env=LOAD_SETTINGS_MCPS_ENV)

        policy_mode = _mcp_policy_mode()
        # Build options
        allowed_tools = [
            "mcp__sohnbot__fs__read",
            "mcp__sohnbot__fs__list",
            "mcp__sohnbot__fs__search",
            "mcp__sohnbot__files__read",
            "mcp__sohnbot__files__list",
            "mcp__sohnbot__files__search",
            "mcp__sohnbot__fs__apply_patch",
            "mcp__sohnbot__git__status",
            "mcp__sohnbot__git__diff",
            "mcp__sohnbot__git__commit",
            "mcp__sohnbot__git__rollback",
            "mcp__sohnbot__git__checkout",
            "mcp__sohnbot__sched__create",
            "mcp__sohnbot__sched__list",
            "mcp__sohnbot__sched__disable",
            "mcp__sohnbot__sched__enable",
            "mcp__sohnbot__sched__delete",
            "mcp__sohnbot__sched__edit",
            "mcp__sohnbot__profiles__lint",
            "mcp__sohnbot__profiles__build",
            "mcp__sohnbot__profiles__test",
            "mcp__sohnbot__profiles__ripgrep",
            "mcp__sohnbot__web__search",
            "mcp__sohnbot__web__research",
            "mcp__sohnbot__ai__delegate_to_gemini",
            "mcp__sohnbot__observe__status",
            "mcp__sohnbot__observe__resources",
            "mcp__sohnbot__observe__health",
            "mcp__sohnbot__observe__logs",
            "mcp__gemini_adapter__generate",
            "WebSearch",
            "WebFetch",
            "Read",
            "Write",
            "Edit",
        ]
        if policy_mode == MCP_POLICY_SETTINGS:
            for server_name in settings_external_server_names:
                allowed_tools.append(f"mcp__{server_name}__*")

        options = ClaudeAgentOptions(
            model=model,
            max_thinking_tokens=max_thinking,
            max_turns=max_turns,
            mcp_servers=mcp_servers,
            allowed_tools=allowed_tools,
            hooks={
                "PreToolUse": [validate_tool_use]
            },
            # Enable CLAUDE.md/.claude skills only when a dedicated project root is configured.
            setting_sources=setting_sources,
            cwd=session_cwd,
        )

        # Initialize client, recovering to SohnBot-only MCP on external MCP startup failures.
        try:
            self.client = ClaudeSDKClient(options=options)
            await self.client.__aenter__()
        except Exception as exc:  # noqa: BLE001
            logger.error("agent_session_init_failed", error=str(exc), exc_info=True)
            fallback_options = ClaudeAgentOptions(
                model=model,
                max_thinking_tokens=max_thinking,
                max_turns=max_turns,
                mcp_servers={"sohnbot": mcp_server},
                allowed_tools=[tool for tool in allowed_tools if tool.startswith("mcp__sohnbot__") or not tool.startswith("mcp__")],
                hooks={"PreToolUse": [validate_tool_use]},
                setting_sources=setting_sources,
                cwd=session_cwd,
            )
            self.client = ClaudeSDKClient(options=fallback_options)
            await self.client.__aenter__()
            logger.warning(
                "agent_session_init_recovered_with_minimal_mcp",
                dropped_mcp_servers=sorted([name for name in mcp_servers if name != "sohnbot"]),
            )
        if self.enable_ambiguity_guard:
            await self.postponement_manager.recover_pending()

        logger.info("agent_session_initialized")

    async def query(
        self,
        prompt: str,
        chat_id: str,
        send_message: SendMessageFn | None = None,
        skip_ambiguity_check: bool = False,
    ):
        """
        Query Claude with context.

        Args:
            prompt: User prompt text
            chat_id: Telegram chat ID for context
            send_message: Telegram sender callback used for clarification prompts
            skip_ambiguity_check: Skip ambiguity check for already-clarified prompts

        Yields:
            Response messages from Claude SDK

        Raises:
            RuntimeError: If client not initialized
        """
        if not self.client:
            raise RuntimeError("AgentSession not initialized. Call initialize() first.")

        # Reset profile chain counter at request boundary (new user message).
        if hasattr(self.broker, "reset_profile_counter"):
            reset_result = self.broker.reset_profile_counter(chat_id)
            if inspect.isawaitable(reset_result):
                await reset_result

        # Detect dry-run request styles and strip markers from the prompt.
        dry_run = False
        normalized = prompt.strip()
        if normalized.startswith("/dryrun "):
            dry_run = True
            prompt = normalized[8:].strip()
        if "--dry-run" in prompt:
            dry_run = True
            prompt = prompt.replace("--dry-run", "").strip()

        # Bind chat_id to context for logging
        bind_contextvars(chat_id=chat_id, dry_run=dry_run)

        logger.info(
            "agent_query_start",
            chat_id=chat_id,
            prompt_length=len(prompt),
            dry_run=dry_run,
        )

        if (
            self.enable_ambiguity_guard
            and not skip_ambiguity_check
            and send_message
            and self._is_ambiguous_prompt(prompt)
        ):
            options = self._generate_clarification_options(prompt)
            operation_id = str(uuid4())
            await log_operation_start(
                operation_id=operation_id,
                capability="runtime",
                action="clarification",
                chat_id=chat_id,
                tier=0,
            )
            await self.postponement_manager.add_pending(
                operation_id=operation_id,
                chat_id=chat_id,
                original_prompt=prompt,
                options=options,
            )

            clarification_text = (
                f"Did you mean '{options[0]}' or '{options[1]}'? "
                "Reply with one option within 60 seconds."
            )
            try:
                chat_id_int = int(chat_id)
            except (TypeError, ValueError):
                logger.error("invalid_chat_id_for_clarification", chat_id=chat_id)
                yield "Unable to send clarification request due to invalid chat context."
                return
            await send_message(chat_id_int, clarification_text)

            resolved = await self.postponement_manager.wait_for_clarification(
                chat_id=chat_id,
                timeout_seconds=self.postponement_manager.clarification_timeout_seconds,
            )
            if resolved is None:
                pending = await self.postponement_manager.get_pending(chat_id)
                if pending is not None:
                    await self.postponement_manager.postpone_and_schedule(pending)
                yield (
                    "I could not determine your intent safely. "
                    "This operation is postponed for now and will be retried later."
                )
                logger.info("agent_query_postponed", chat_id=chat_id, operation_id=operation_id)
                return

            completed = await self.postponement_manager.consume_resolved(chat_id)
            if completed is None or not completed.response_text:
                yield "Clarification was received but empty. Please try your request again."
                return

            await log_operation_end(operation_id=operation_id, status="completed")
            prompt = self.postponement_manager.build_clarified_prompt(
                original_prompt=completed.original_prompt,
                clarification_response=completed.response_text,
            )
            skip_ambiguity_check = True

        # Send query
        await self.client.query(prompt)

        # Stream response
        async for message in self.client.receive_response():
            yield message

        logger.info("agent_query_complete", chat_id=chat_id)

    def _is_ambiguous_prompt(self, prompt: str) -> bool:
        """
        Ambiguity detector to avoid unsafe auto-approval.

        Uses an injectable evaluator when provided; otherwise falls back
        to deterministic heuristics.
        """
        if self.ambiguity_evaluator is not None:
            return bool(self.ambiguity_evaluator(prompt))

        normalized = " ".join(prompt.lower().split())
        if len(normalized) < 8:
            return True

        vague_phrases = ("do it", "fix it", "run it", "that one", "same as before")
        if any(phrase in normalized for phrase in vague_phrases):
            return True

        operation_markers = (
            "read", "list", "search", "patch", "edit", "rollback", "commit", "status", "diff"
        )
        marker_count = sum(1 for marker in operation_markers if marker in normalized)
        return marker_count == 0

    @staticmethod
    def _generate_clarification_options(prompt: str) -> tuple[str, str]:
        """Return two concrete options for ambiguous file operation intents."""
        text = prompt.lower()
        if "git" in text or "commit" in text or "rollback" in text or "status" in text:
            return ("show git status", "show git diff")
        if "file" in text or "read" in text or "list" in text:
            return ("list files", "read a specific file")
        return ("list files", "search in files")

    async def close(self):
        """Cleanup SDK client."""
        if self.client:
            logger.info("closing_agent_session")
            await self.client.__aexit__(None, None, None)
            self.client = None
            logger.info("agent_session_closed")
