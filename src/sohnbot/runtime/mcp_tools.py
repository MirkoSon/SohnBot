"""
MCP Tool Definitions.

In-process MCP server with @tool decorators for Claude Agent SDK.
All tools route through the Broker layer for policy enforcement.
"""

import structlog
from claude_agent_sdk import create_sdk_mcp_server, tool

logger = structlog.get_logger(__name__)


def create_sohnbot_mcp_server(broker, config):
    """
    Create in-process MCP server with all SohnBot tools.

    Args:
        broker: BrokerRouter instance for routing operations
        config: ConfigManager instance for configuration

    Returns:
        SDK MCP server instance
    """

    # File operations (Story 1.5 - stubs for now)
    @tool("fs__read", "Read file contents", {"path": str})
    async def fs_read(args):
        """Read file via broker (Story 1.5 will implement actual capability)."""
        logger.info("mcp_tool_invoked", tool="fs__read", path=args.get("path"))

        # NOTE: Broker routes to capability which doesn't exist yet (Story 1.5)
        # For now, return mock response
        return {
            "content": [{
                "type": "text",
                "text": (
                    "File read capability not yet implemented (Story 1.5). "
                    "This is a stub for testing gateway/runtime integration."
                )
            }]
        }

    @tool("fs__list", "List files in directory", {"path": str})
    async def fs_list(args):
        """List files via broker (Story 1.5 will implement actual capability)."""
        logger.info("mcp_tool_invoked", tool="fs__list", path=args.get("path"))

        return {
            "content": [{
                "type": "text",
                "text": (
                    "File list capability not yet implemented (Story 1.5). "
                    "This is a stub for testing gateway/runtime integration."
                )
            }]
        }

    @tool("fs__search", "Search file contents", {"pattern": str, "path": str})
    async def fs_search(args):
        """Search files via broker (Story 1.5 will implement actual capability)."""
        logger.info(
            "mcp_tool_invoked",
            tool="fs__search",
            pattern=args.get("pattern"),
            path=args.get("path")
        )

        return {
            "content": [{
                "type": "text",
                "text": (
                    "File search capability not yet implemented (Story 1.5). "
                    "This is a stub for testing gateway/runtime integration."
                )
            }]
        }

    @tool("fs__apply_patch", "Apply unified diff patch", {"path": str, "patch": str})
    async def fs_apply_patch(args):
        """Apply patch via broker (Story 1.6 will implement actual capability)."""
        logger.info("mcp_tool_invoked", tool="fs__apply_patch", path=args.get("path"))

        return {
            "content": [{
                "type": "text",
                "text": (
                    "File patch capability not yet implemented (Story 1.6). "
                    "This is a stub for testing gateway/runtime integration."
                )
            }]
        }

    # Git operations (Epic 2 - stubs for now)
    @tool("git__status", "Get git status", {})
    async def git_status(args):
        """Git status via broker (Epic 2 will implement actual capability)."""
        logger.info("mcp_tool_invoked", tool="git__status")

        return {
            "content": [{
                "type": "text",
                "text": (
                    "Git status capability not yet implemented (Epic 2). "
                    "This is a stub for testing gateway/runtime integration."
                )
            }]
        }

    @tool("git__diff", "Get git diff", {})
    async def git_diff(args):
        """Git diff via broker (Epic 2 will implement actual capability)."""
        logger.info("mcp_tool_invoked", tool="git__diff")

        return {
            "content": [{
                "type": "text",
                "text": (
                    "Git diff capability not yet implemented (Epic 2). "
                    "This is a stub for testing gateway/runtime integration."
                )
            }]
        }

    @tool("git__commit", "Create git commit", {"message": str})
    async def git_commit(args):
        """Git commit via broker (Epic 2 will implement actual capability)."""
        logger.info("mcp_tool_invoked", tool="git__commit", message=args.get("message"))

        return {
            "content": [{
                "type": "text",
                "text": (
                    "Git commit capability not yet implemented (Epic 2). "
                    "This is a stub for testing gateway/runtime integration."
                )
            }]
        }

    @tool("git__rollback", "Rollback to snapshot", {"snapshot_ref": str})
    async def git_rollback(args):
        """Rollback via broker (Epic 2 will implement actual capability)."""
        logger.info("mcp_tool_invoked", tool="git__rollback", snapshot_ref=args.get("snapshot_ref"))

        return {
            "content": [{
                "type": "text",
                "text": (
                    "Git rollback capability not yet implemented (Epic 2). "
                    "This is a stub for testing gateway/runtime integration."
                )
            }]
        }

    # Create and return server
    return create_sdk_mcp_server(
        name="sohnbot",
        version="0.1.0",
        tools=[
            fs_read,
            fs_list,
            fs_search,
            fs_apply_patch,
            git_status,
            git_diff,
            git_commit,
            git_rollback,
        ]
    )
