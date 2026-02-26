"""
Claude Agent SDK Hooks.

PreToolUse hook enforces that only mcp__sohnbot__* tools can be invoked.
This is the architectural gatekeeper for the broker layer.
"""

import structlog

logger = structlog.get_logger(__name__)


async def validate_tool_use(input_data, tool_use_id, context):
    """
    PreToolUse hook - blocks any tool NOT matching mcp__sohnbot__* pattern.

    This is the architectural gatekeeper that enforces broker routing.
    No tool can bypass the broker layer.

    Args:
        input_data: Dict with tool_name and tool_input
        tool_use_id: Unique ID for this tool use
        context: Hook context (unused)

    Returns:
        Empty dict to allow, or dict with permissionDecision: deny to block
    """
    tool_name = input_data["tool_name"]

    # Allow only mcp__sohnbot__* tools
    if not tool_name.startswith("mcp__sohnbot__"):
        logger.warning(
            "blocked_non_sohnbot_tool",
            tool_name=tool_name,
            tool_use_id=tool_use_id
        )

        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Only mcp__sohnbot__* tools are permitted. "
                    f"Attempted: {tool_name}"
                )
            }
        }

    # Tool is allowed - no output needed
    logger.debug(
        "tool_allowed",
        tool_name=tool_name,
        tool_use_id=tool_use_id
    )
    return {}
