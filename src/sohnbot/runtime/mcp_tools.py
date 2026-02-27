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

        return await _run_file_tool(
            action="apply_patch",
            params={"path": path, "patch": patch_content},
            chat_id=chat_id,
        )

    # Git operations (Epic 2 - stubs for now)
    @tool("git__status", "Get git status", {"repo_path": str})
    async def git_status(args):
        """Git status via broker."""
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")
        repo_path = args.get("repo_path")

        logger.info("mcp_tool_invoked", tool="git__status", repo_path=repo_path, chat_id=chat_id)

        result = await broker.route_operation(
            capability="git",
            action="status",
            params={"repo_path": repo_path, "timeout_seconds": 10},
            chat_id=chat_id
        )

        if not result.allowed:
            error_msg = result.error.get("message", "Operation denied")
            logger.warning("mcp_tool_denied", tool="git__status", error=error_msg)
            return _as_mcp_text(f"❌ Operation denied: {error_msg}")

        data = result.result or {}
        text = (
            f"Branch: {data.get('branch', 'HEAD')}\n"
            f"Ahead/Behind: +{data.get('ahead', 0)}/-{data.get('behind', 0)}\n"
            f"Modified: {len(data.get('modified', []))}\n"
            f"Staged: {len(data.get('staged', []))}\n"
            f"Untracked: {len(data.get('untracked', []))}"
        )
        return _as_mcp_text(text)

    @tool(
        "git__diff",
        "Get git diff",
        {"repo_path": str, "diff_type": str, "file_path": str, "commit_refs": list},
    )
    async def git_diff(args):
        """Git diff via broker."""
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")
        repo_path = args.get("repo_path")
        diff_type = args.get("diff_type", "working_tree")
        file_path = args.get("file_path")
        commit_refs = args.get("commit_refs")

        logger.info(
            "mcp_tool_invoked",
            tool="git__diff",
            repo_path=repo_path,
            diff_type=diff_type,
            chat_id=chat_id,
        )

        result = await broker.route_operation(
            capability="git",
            action="diff",
            params={
                "repo_path": repo_path,
                "diff_type": diff_type,
                "file_path": file_path,
                "commit_refs": commit_refs,
                "timeout_seconds": 30,
            },
            chat_id=chat_id
        )

        if not result.allowed:
            error_msg = result.error.get("message", "Operation denied")
            logger.warning("mcp_tool_denied", tool="git__diff", error=error_msg)
            return _as_mcp_text(f"❌ Operation denied: {error_msg}")

        data = result.result or {}
        return _as_mcp_text(data.get("diff", ""))

    @tool(
        "git__commit",
        "Create git commit",
        {"repo_path": str, "message": str, "file_paths": list},
    )
    async def git_commit(args):
        """Git commit via broker."""
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")

        repo_path = args.get("repo_path")
        message = args.get("message")
        file_paths = args.get("file_paths")
        logger.info(
            "mcp_tool_invoked",
            tool="git__commit",
            repo_path=repo_path,
            message=message,
            chat_id=chat_id,
        )

        result = await broker.route_operation(
            capability="git",
            action="commit",
            params={
                "repo_path": repo_path,
                "message": message,
                "file_paths": file_paths,
                "timeout_seconds": 30,
            },
            chat_id=chat_id
        )

        if not result.allowed:
            error_msg = result.error.get("message", "Operation denied")
            logger.warning("mcp_tool_denied", tool="git__commit", error=error_msg)
            return _as_mcp_text(f"❌ Operation denied: {error_msg}")

        data = result.result or {}
        if not data.get("commit_hash"):
            return _as_mcp_text("ℹ️ No changes to commit")
        return _as_mcp_text(
            f"✅ Commit created: {data.get('commit_hash')}. Message: \"{data.get('message', message)}\". Files: {data.get('files_changed', 0)}"
        )

    @tool("git__list_snapshots", "List available snapshot branches", {"repo_path": str})
    async def git_list_snapshots(args):
        """List snapshots via broker."""
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")

        repo_path = args.get("repo_path")
        logger.info("mcp_tool_invoked", tool="git__list_snapshots", repo_path=repo_path, chat_id=chat_id)

        result = await broker.route_operation(
            capability="git",
            action="list_snapshots",
            params={"repo_path": repo_path},
            chat_id=chat_id
        )

        if not result.allowed:
            error_msg = result.error.get("message", "Operation denied")
            logger.warning("mcp_tool_denied", tool="git__list_snapshots", error=error_msg)
            return _as_mcp_text(f"❌ Operation denied: {error_msg}")

        snapshots = result.result.get("snapshots", [])
        total_count = result.result.get("total_count", len(snapshots))
        if not snapshots:
            return _as_mcp_text("No snapshots found.")

        lines = [f"Available snapshots (total: {total_count}):"]
        for i, snap in enumerate(snapshots, 1):
            lines.append(f"{i}. {snap['ref']} ({snap['timestamp']})")

        return _as_mcp_text("\n".join(lines))

    @tool(
        "git__prune_snapshots",
        "Prune old snapshot branches",
        {"repo_path": str, "retention_days": int},
    )
    async def git_prune_snapshots(args):
        """Prune old snapshots via broker."""
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")

        repo_path = args.get("repo_path")
        retention_days = args.get("retention_days")
        logger.info(
            "mcp_tool_invoked",
            tool="git__prune_snapshots",
            repo_path=repo_path,
            retention_days=retention_days,
            chat_id=chat_id,
        )

        result = await broker.route_operation(
            capability="git",
            action="prune_snapshots",
            params={
                "repo_path": repo_path,
                "retention_days": retention_days,
                "timeout_seconds": 60,
            },
            chat_id=chat_id
        )

        if not result.allowed:
            error_msg = result.error.get("message", "Operation denied")
            logger.warning("mcp_tool_denied", tool="git__prune_snapshots", error=error_msg)
            return _as_mcp_text(f"❌ Operation denied: {error_msg}")

        data = result.result or {}
        return _as_mcp_text(
            f"✅ Snapshot prune completed. Pruned: {data.get('pruned_count', 0)}. "
            f"Retained: {data.get('retained_count', 0)}."
        )

    @tool("git__rollback", "Rollback to snapshot", {"snapshot_ref": str, "repo_path": str})
    async def git_rollback(args):
        """Rollback to snapshot via broker."""
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")

        snapshot_ref = args.get("snapshot_ref")
        repo_path = args.get("repo_path")
        logger.info(
            "mcp_tool_invoked",
            tool="git__rollback",
            snapshot_ref=snapshot_ref,
            repo_path=repo_path,
            chat_id=chat_id
        )

        result = await broker.route_operation(
            capability="git",
            action="rollback",
            params={"snapshot_ref": snapshot_ref, "repo_path": repo_path},
            chat_id=chat_id
        )

        if not result.allowed:
            error_msg = result.error.get("message", "Operation denied")
            logger.warning("mcp_tool_denied", tool="git__rollback", error=error_msg)
            return _as_mcp_text(f"❌ Operation denied: {error_msg}")

        data = result.result
        commit_hash = data.get("commit_hash", "?")
        files_restored = data.get("files_restored", 0)
        return _as_mcp_text(
            f"✅ Restored to snapshot: {snapshot_ref}. Commit: {commit_hash}. Files: {files_restored}"
        )

    @tool(
        "git__checkout",
        "Checkout local git branch (local branches only)",
        {"repo_path": str, "branch_name": str},
    )
    async def git_checkout(args):
        """Checkout local branch via broker."""
        ctx = get_contextvars()
        chat_id = ctx.get("chat_id", "unknown")

        repo_path = args.get("repo_path")
        branch_name = args.get("branch_name")
        logger.info(
            "mcp_tool_invoked",
            tool="git__checkout",
            repo_path=repo_path,
            branch_name=branch_name,
            chat_id=chat_id,
        )

        result = await broker.route_operation(
            capability="git",
            action="checkout",
            params={
                "repo_path": repo_path,
                "branch_name": branch_name,
                "timeout_seconds": 10,
            },
            chat_id=chat_id
        )

        if not result.allowed:
            error_msg = result.error.get("message", "Operation denied")
            logger.warning("mcp_tool_denied", tool="git__checkout", error=error_msg)
            return _as_mcp_text(f"❌ Operation denied: {error_msg}")

        data = result.result or {}
        return _as_mcp_text(
            f"✅ Checked out local branch {data.get('branch', branch_name)} at {data.get('commit_hash', '?')}"
        )

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
            git_list_snapshots,
            git_prune_snapshots,
            git_rollback,
            git_checkout,
        ]
    )
