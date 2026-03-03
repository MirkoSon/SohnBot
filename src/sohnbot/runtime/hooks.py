"""
Claude Agent SDK Hooks.

PreToolUse hook enforces that only mcp__sohnbot__* tools (plus explicit
native allowlist entries) can be invoked.
"""

import os
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

ALLOWED_NATIVE_TOOLS = frozenset({"WebFetch", "WebSearch", "Read", "Write", "Edit"})
NATIVE_FILE_TOOLS = frozenset({"Read", "Write", "Edit"})
NATIVE_RW_ROOT_ENV = "SOHNBOT_NATIVE_RW_ROOT"
NATIVE_RW_ROOT_DEFAULT = "D:/SohnBot"
MCP_POLICY_MODE_ENV = "SOHNBOT_MCP_POLICY_MODE"
MCP_POLICY_GOVERNED = "governed"
MCP_POLICY_SETTINGS = "settings"


def _native_rw_root() -> Path:
    raw = (os.getenv(NATIVE_RW_ROOT_ENV) or NATIVE_RW_ROOT_DEFAULT).strip()
    return Path(raw).expanduser().resolve()


def _mcp_policy_mode() -> str:
    raw = (os.getenv(MCP_POLICY_MODE_ENV) or MCP_POLICY_GOVERNED).strip().lower()
    if raw in {MCP_POLICY_GOVERNED, MCP_POLICY_SETTINGS}:
        return raw
    return MCP_POLICY_GOVERNED


def _is_allowed_mcp_tool(tool_name: str, mode: str) -> bool:
    if tool_name.startswith("mcp__sohnbot__"):
        return True
    if mode == MCP_POLICY_SETTINGS and tool_name.startswith("mcp__"):
        return True
    return False


def _extract_candidate_paths(tool_name: str, tool_input: dict[str, Any]) -> list[str]:
    if tool_name == "Read":
        for key in ("file_path", "path"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return [value.strip()]
    if tool_name in {"Write", "Edit"}:
        for key in ("file_path", "path"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return [value.strip()]
    return []


def _is_path_within_root(path_text: str, root: Path) -> bool:
    raw = Path(path_text).expanduser()
    candidate = raw if raw.is_absolute() else (root / raw)
    resolved = candidate.resolve()
    normalized_root = str(root).casefold().rstrip("\\/")
    normalized_path = str(resolved).casefold()
    return normalized_path == normalized_root or normalized_path.startswith(normalized_root + os.sep)


async def validate_tool_use(input_data, tool_use_id, context):
    """
    PreToolUse hook - blocks any tool not in the approved allowlist.

    This is the architectural gatekeeper that enforces broker routing.
    Native Claude tools are denied by default and must be explicitly
    allowlisted here.

    Args:
        input_data: Dict with tool_name and tool_input
        tool_use_id: Unique ID for this tool use
        context: Hook context (unused)

    Returns:
        Empty dict to allow, or dict with permissionDecision: deny to block
    """
    tool_name = input_data["tool_name"]
    mode = _mcp_policy_mode()

    # Allow mcp__sohnbot__* always; optionally allow all mcp__* in settings mode.
    if not _is_allowed_mcp_tool(tool_name, mode) and tool_name not in ALLOWED_NATIVE_TOOLS:
        logger.warning(
            "blocked_non_sohnbot_tool",
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            policy_mode=mode,
        )

        if mode == MCP_POLICY_SETTINGS:
            reason = (
                f"Only mcp__* tools and approved native tools are permitted in settings mode. "
                f"Attempted: {tool_name}"
            )
        else:
            reason = (
                f"Only mcp__sohnbot__* tools and approved native tools are permitted in governed mode. "
                f"Attempted: {tool_name}"
            )

        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    if tool_name in NATIVE_FILE_TOOLS:
        tool_input = input_data.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            tool_input = {}
        paths = _extract_candidate_paths(tool_name, tool_input)
        root = _native_rw_root()
        if not paths or any(not _is_path_within_root(path, root) for path in paths):
            logger.warning(
                "blocked_native_file_tool_out_of_scope",
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                root=str(root),
                paths=paths,
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Native file tools are restricted to {root}. "
                        f"Attempted: {paths or '[missing path]'}"
                    ),
                }
            }

    # Tool is allowed - no output needed
    logger.debug(
        "tool_allowed",
        tool_name=tool_name,
        tool_use_id=tool_use_id
    )
    return {}
