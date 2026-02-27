"""
Claude Agent SDK Session Management.

Wrapper for ClaudeSDKClient with SohnBot-specific configuration.
"""

from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

import structlog
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from structlog.contextvars import bind_contextvars

from ..persistence.audit import log_operation_end, log_operation_start
from .hooks import validate_tool_use
from .mcp_tools import create_sohnbot_mcp_server
from .postponement_manager import PostponementManager

logger = structlog.get_logger(__name__)

SendMessageFn = Callable[[int, str], Awaitable[bool]]


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

        # Build options
        options = ClaudeAgentOptions(
            model=model,
            max_thinking_tokens=max_thinking,
            max_turns=max_turns,
            mcp_servers={"sohnbot": mcp_server},
            allowed_tools=[
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
            ],
            hooks={
                "PreToolUse": [validate_tool_use]
            },
            setting_sources=["project"],  # Load CLAUDE.md
            cwd=str(Path.cwd())
        )

        # Initialize client
        self.client = ClaudeSDKClient(options=options)
        await self.client.__aenter__()
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

        # Bind chat_id to context for logging
        bind_contextvars(chat_id=chat_id)

        logger.info(
            "agent_query_start",
            chat_id=chat_id,
            prompt_length=len(prompt)
        )

        if not skip_ambiguity_check and send_message and self._is_ambiguous_prompt(prompt):
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
