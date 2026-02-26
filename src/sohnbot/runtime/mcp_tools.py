"""
MCP Tool Definitions.

In-process MCP server with @tool decorators for Claude Agent SDK.
All tools route through the Broker layer for policy enforcement.
"""

import structlog
from claude_agent_sdk import create_sdk_mcp_server, tool
from structlog.contextvars import get_contextvars

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

    def _as_mcp_text(text: str) -> dict:
        return {"content": [{"type": "text", "text": text}]}

    def _format_file_result(action: str, result: dict) -> str:
        if action == "read":
            return result.get("content", "")
        if action == "list":
            files = result.get("files", [])
            if not files:
                return "No files found."
            lines = [
                f'{item["path"]} | {item["size"]} bytes | mtime={item["modified_at"]}'
                for item in files
            ]
            return "\n".join(lines)
        if action == "search":
            matches = result.get("matches", [])
            if not matches:
                return "No matches found."
            lines = [
                f'{item["path"]}:{item["line"]}: {item["content"]}'
                for item in matches
            ]
            return "\n".join(lines)
        if action == "apply_patch":
            path = result.get("path", "?")
            added = result.get("lines_added", 0)
            removed = result.get("lines_removed", 0)
            return f"Patch applied to {path}. Lines: +{added}/-{removed}"
        return str(result)

    async def _run_file_tool(action: str, params: dict, chat_id: str) -> dict:
        result = await broker.route_operation(
            capability="fs",
            action=action,
            params=params,
            chat_id=chat_id,
        )

        if not result.allowed:
            error_msg = (result.error or {}).get("message", "Operation denied")
            logger.warning("mcp_tool_denied", tool=f"fs__{action}", error=error_msg)
            return _as_mcp_text(f"❌ Operation denied: {error_msg}")

        return _as_mcp_text(_format_file_result(action, result.result or {}))

    # File operations (Story 1.5 - stubs for now)
    @tool("fs__read", "Read file contents", {"path": str})
    async def fs_read(args):
        """Read file via broker."""
        # Get chat_id from context (bound in agent_session.py)
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")

        path = args.get("path")
        logger.info("mcp_tool_invoked", tool="fs__read", path=path, chat_id=chat_id)
        max_size_mb = config.get("files.max_size_mb")
        return await _run_file_tool(
            action="read",
            params={"path": path, "max_size_mb": max_size_mb},
            chat_id=chat_id,
        )

    @tool("fs__list", "List files in directory", {"path": str})
    async def fs_list(args):
        """List files via broker."""
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")

        path = args.get("path")
        logger.info("mcp_tool_invoked", tool="fs__list", path=path, chat_id=chat_id)
        return await _run_file_tool(
            action="list",
            params={"path": path},
            chat_id=chat_id,
        )

    @tool("fs__search", "Search file contents", {"pattern": str, "path": str})
    async def fs_search(args):
        """Search files via broker."""
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")

        pattern = args.get("pattern")
        path = args.get("path")
        logger.info(
            "mcp_tool_invoked",
            tool="fs__search",
            pattern=pattern,
            path=path,
            chat_id=chat_id
        )

        timeout_seconds = config.get("files.search_timeout_seconds")
        return await _run_file_tool(
            action="search",
            params={
                "pattern": pattern,
                "path": path,
                "timeout_seconds": timeout_seconds,
            },
            chat_id=chat_id,
        )

    # Alias names expected by architecture/story docs.
    @tool("files__read", "Read file contents", {"path": str})
    async def files_read(args):
        return await fs_read(args)

    @tool("files__list", "List files in directory", {"path": str})
    async def files_list(args):
        return await fs_list(args)

    @tool("files__search", "Search file contents", {"pattern": str, "path": str})
    async def files_search(args):
        return await fs_search(args)

    @tool("fs__apply_patch", "Apply unified diff patch", {"path": str, "patch": str})
    async def fs_apply_patch(args):
        """Apply unified diff patch via broker with snapshot creation."""
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")

        path = args.get("path")
        patch_content = args.get("patch")
        logger.info("mcp_tool_invoked", tool="fs__apply_patch", path=path, chat_id=chat_id)

        patch_max_kb = config.get("files.patch_max_size_kb")
        return await _run_file_tool(
            action="apply_patch",
            params={"path": path, "patch": patch_content, "patch_max_size_kb": patch_max_kb},
            chat_id=chat_id,
        )

    # Git operations (Epic 2 - stubs for now)
    @tool("git__status", "Get git status", {})
    async def git_status(args):
        """Git status via broker (Epic 2 will implement actual capability)."""
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")

        logger.info("mcp_tool_invoked", tool="git__status", chat_id=chat_id)

        result = await broker.route_operation(
            capability="git",
            action="status",
            params={},
            chat_id=chat_id
        )

        if not result.allowed:
            error_msg = result.error.get("message", "Operation denied")
            logger.warning("mcp_tool_denied", tool="git__status", error=error_msg)
            return {
                "content": [{
                    "type": "text",
                    "text": f"❌ Operation denied: {error_msg}"
                }]
            }

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
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")

        logger.info("mcp_tool_invoked", tool="git__diff", chat_id=chat_id)

        result = await broker.route_operation(
            capability="git",
            action="diff",
            params={},
            chat_id=chat_id
        )

        if not result.allowed:
            error_msg = result.error.get("message", "Operation denied")
            logger.warning("mcp_tool_denied", tool="git__diff", error=error_msg)
            return {
                "content": [{
                    "type": "text",
                    "text": f"❌ Operation denied: {error_msg}"
                }]
            }

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
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")

        message = args.get("message")
        logger.info("mcp_tool_invoked", tool="git__commit", message=message, chat_id=chat_id)

        result = await broker.route_operation(
            capability="git",
            action="commit",
            params={"message": message},
            chat_id=chat_id
        )

        if not result.allowed:
            error_msg = result.error.get("message", "Operation denied")
            logger.warning("mcp_tool_denied", tool="git__commit", error=error_msg)
            return {
                "content": [{
                    "type": "text",
                    "text": f"❌ Operation denied: {error_msg}"
                }]
            }

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
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")

        snapshot_ref = args.get("snapshot_ref")
        logger.info("mcp_tool_invoked", tool="git__rollback", snapshot_ref=snapshot_ref, chat_id=chat_id)

        result = await broker.route_operation(
            capability="git",
            action="rollback",
            params={"snapshot_ref": snapshot_ref},
            chat_id=chat_id
        )

        if not result.allowed:
            error_msg = result.error.get("message", "Operation denied")
            logger.warning("mcp_tool_denied", tool="git__rollback", error=error_msg)
            return {
                "content": [{
                    "type": "text",
                    "text": f"❌ Operation denied: {error_msg}"
                }]
            }

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
            files_read,
            files_list,
            files_search,
            fs_apply_patch,
            git_status,
            git_diff,
            git_commit,
            git_rollback,
        ]
    )
