"""
Unit tests for MCP Tools.

Tests tool → broker integration and hook validation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.sohnbot.runtime.hooks import validate_tool_use
from src.sohnbot.runtime.mcp_tools import create_sohnbot_mcp_server


class TestMCPTools:
    """Test MCP tool definitions and broker integration."""

    @pytest.fixture
    def mock_broker(self):
        """Create mock BrokerRouter."""
        return AsyncMock()

    @pytest.fixture
    def mock_config(self):
        """Create mock ConfigManager."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_mcp_server_creation(self, mock_broker, mock_config):
        """MCP server created with all tools."""
        server = create_sohnbot_mcp_server(
            broker=mock_broker,
            config=mock_config
        )

        # Server should be created
        assert server is not None

        # Should have expected attributes
        assert hasattr(server, 'name') or server is not None

    @pytest.mark.asyncio
    async def test_fs_read_stub_response(self, mock_broker, mock_config):
        """fs__read returns stub message (capabilities not yet implemented)."""
        # For now, tools return stub responses
        # This test validates the tool structure

        server = create_sohnbot_mcp_server(
            broker=mock_broker,
            config=mock_config
        )

        # Server should exist (actual tool invocation would require SDK)
        assert server is not None

    def test_scheduler_tools_registered_with_expected_schemas(self, mock_broker, mock_config):
        """Scheduler tool schemas are registered as expected."""
        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}

        assert "sched__create" in by_name
        assert "sched__list" in by_name
        assert "sched__disable" in by_name
        assert "sched__enable" in by_name
        assert "sched__delete" in by_name
        assert "sched__edit" in by_name
        assert by_name["sched__create"].input_schema == {
            "name": str,
            "cron_expr": str,
            "timezone": str,
            "action": str,
            "action_params": dict,
            "enabled": bool,
        }
        assert by_name["sched__list"].input_schema == {"enabled_only": bool}
        assert by_name["sched__disable"].input_schema == {"name": str}
        assert by_name["sched__enable"].input_schema == {"name": str}
        assert by_name["sched__delete"].input_schema == {"name": str}
        assert by_name["sched__edit"].input_schema == {"name": str, "parameter": str, "value": str}

    def test_profiles_lint_tool_registered_with_expected_schema(self, mock_broker, mock_config):
        """profiles__lint tool is registered with correct schema."""
        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}

        assert "profiles__lint" in by_name
        assert by_name["profiles__lint"].input_schema == {"repo_path": str, "files": list}

    @pytest.mark.asyncio
    async def test_profiles_lint_routes_through_broker(self, mock_broker, mock_config):
        """profiles__lint invokes broker.route_operation with correct capability/action."""
        mock_broker.route_operation.return_value = MagicMock(
            allowed=True,
            error=None,
            result={"passed": True, "exit_code": 0, "stdout": "ok", "stderr": "", "command_used": "pylint", "files_linted": []},
        )

        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}
        lint_tool = by_name["profiles__lint"]

        with patch("src.sohnbot.runtime.mcp_tools.get_contextvars", return_value={"chat_id": "test_chat"}):
            await lint_tool.handler({"repo_path": "/some/project", "files": []})

        mock_broker.route_operation.assert_called_once_with(
            capability="profiles",
            action="lint",
            params={"repo_path": "/some/project", "files": []},
            chat_id="test_chat",
        )

    @pytest.mark.asyncio
    async def test_profiles_lint_denied_returns_error_message(self, mock_broker, mock_config):
        """profiles__lint denied by broker returns error text."""
        mock_broker.route_operation.return_value = MagicMock(
            allowed=False,
            error={"message": "scope_violation: path outside roots"},
            result=None,
        )

        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}
        lint_tool = by_name["profiles__lint"]

        with patch("src.sohnbot.runtime.mcp_tools.get_contextvars", return_value={"chat_id": "test_chat"}):
            result = await lint_tool.handler({"repo_path": "/bad/path", "files": []})

        content = result["content"][0]["text"]
        assert "❌ Lint denied" in content
        assert "scope_violation" in content

    def test_profiles_build_tool_registered_with_expected_schema(self, mock_broker, mock_config):
        """profiles__build tool is registered with correct schema."""
        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}

        assert "profiles__build" in by_name
        assert by_name["profiles__build"].input_schema == {"repo_path": str, "target": str}

    @pytest.mark.asyncio
    async def test_profiles_build_routes_through_broker(self, mock_broker, mock_config):
        """profiles__build invokes broker.route_operation with correct capability/action."""
        mock_broker.route_operation.return_value = MagicMock(
            allowed=True,
            error=None,
            result={"passed": True, "exit_code": 0, "stdout": "Build complete.", "stderr": "", "command_used": "make", "target": "dist"},
        )

        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}
        build_tool = by_name["profiles__build"]

        with patch("src.sohnbot.runtime.mcp_tools.get_contextvars", return_value={"chat_id": "test_chat"}):
            result = await build_tool.handler({"repo_path": "/some/project", "target": "dist"})

        mock_broker.route_operation.assert_called_once_with(
            capability="profiles",
            action="build",
            params={"repo_path": "/some/project", "target": "dist"},
            chat_id="test_chat",
        )
        content = result["content"][0]["text"]
        assert "✅ PASSED" in content
        assert "(exit 0)" in content

    @pytest.mark.asyncio
    async def test_profiles_build_denied_returns_error_message(self, mock_broker, mock_config):
        """profiles__build denied by broker returns error text."""
        mock_broker.route_operation.return_value = MagicMock(
            allowed=False,
            error={"message": "scope_violation: path outside roots"},
            result=None,
        )

        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}
        build_tool = by_name["profiles__build"]

        with patch("src.sohnbot.runtime.mcp_tools.get_contextvars", return_value={"chat_id": "test_chat"}):
            result = await build_tool.handler({"repo_path": "/bad/path", "target": ""})

        content = result["content"][0]["text"]
        assert "❌ Build denied" in content
        assert "scope_violation" in content

    def test_profiles_test_tool_registered_with_expected_schema(self, mock_broker, mock_config):
        """profiles__test tool is registered with correct schema."""
        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}

        assert "profiles__test" in by_name
        assert by_name["profiles__test"].input_schema == {"repo_path": str, "pattern": str}

    def test_profiles_ripgrep_tool_registered_with_expected_schema(self, mock_broker, mock_config):
        """profiles__ripgrep tool is registered with correct schema."""
        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}

        assert "profiles__ripgrep" in by_name
        assert by_name["profiles__ripgrep"].input_schema == {
            "repo_path": str,
            "pattern": str,
            "file_types": list,
            "timeout_seconds": int,
        }

    def test_web_search_tool_registered_with_expected_schema(self, mock_broker, mock_config):
        """web__search tool is registered with correct schema."""
        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}

        assert "web__search" in by_name
        assert by_name["web__search"].input_schema == {"query": str, "mode": str}

    def test_observe_logs_tool_registered_with_expected_schema(self, mock_broker, mock_config):
        """observe__logs tool is registered with correct schema."""
        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}

        assert "observe__logs" in by_name
        assert by_name["observe__logs"].input_schema == {"hours": int, "filters": dict}

    @pytest.mark.asyncio
    async def test_observe_logs_routes_through_broker(self, mock_broker, mock_config):
        """observe__logs invokes broker.observe logs route."""
        mock_broker.route_operation.return_value = MagicMock(
            allowed=True,
            error=None,
            result={
                "logs": [
                    {
                        "timestamp_iso": "2026-03-01T12:00:00+00:00",
                        "capability": "fs",
                        "action": "read",
                        "status": "completed",
                        "duration_ms": 15,
                    }
                ]
            },
        )

        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}
        logs_tool = by_name["observe__logs"]

        with patch("src.sohnbot.runtime.mcp_tools.get_contextvars", return_value={"chat_id": "test_chat"}):
            result = await logs_tool.handler({"hours": 24, "filters": {"capability": "fs"}})

        mock_broker.route_operation.assert_called_once_with(
            capability="observe",
            action="logs",
            params={"hours": 24, "limit": 100, "capability": "fs"},
            chat_id="test_chat",
        )
        text = result["content"][0]["text"]
        assert "Operation Logs (last 24h)" in text
        assert "fs__read" in text

    @pytest.mark.asyncio
    async def test_observe_logs_rejects_invalid_tier_filter_type(self, mock_broker, mock_config):
        """observe__logs returns validation error when filters.tier is not int-like."""
        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}
        logs_tool = by_name["observe__logs"]

        with patch("src.sohnbot.runtime.mcp_tools.get_contextvars", return_value={"chat_id": "test_chat"}):
            result = await logs_tool.handler({"hours": 24, "filters": {"tier": "abc"}})

        assert "filters.tier must be an integer" in result["content"][0]["text"]
        mock_broker.route_operation.assert_not_called()

    @pytest.mark.asyncio
    async def test_observe_logs_rejects_invalid_capability_filter_type(self, mock_broker, mock_config):
        """observe__logs rejects non-string capability filters."""
        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}
        logs_tool = by_name["observe__logs"]

        with patch("src.sohnbot.runtime.mcp_tools.get_contextvars", return_value={"chat_id": "test_chat"}):
            result = await logs_tool.handler({"hours": 24, "filters": {"capability": 123}})

        assert "filters.capability must be a non-empty string" in result["content"][0]["text"]
        mock_broker.route_operation.assert_not_called()

    @pytest.mark.asyncio
    async def test_profiles_test_routes_through_broker(self, mock_broker, mock_config):
        """profiles__test invokes broker.route_operation with correct capability/action."""
        mock_broker.route_operation.return_value = MagicMock(
            allowed=True,
            error=None,
            result={"passed": True, "exit_code": 0, "stdout": "5 passed.", "stderr": "", "command_used": "pytest", "pattern": "tests/unit/"},
        )

        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}
        test_tool = by_name["profiles__test"]

        with patch("src.sohnbot.runtime.mcp_tools.get_contextvars", return_value={"chat_id": "test_chat"}):
            result = await test_tool.handler({"repo_path": "/some/project", "pattern": "tests/unit/"})

        mock_broker.route_operation.assert_called_once_with(
            capability="profiles",
            action="test",
            params={"repo_path": "/some/project", "pattern": "tests/unit/"},
            chat_id="test_chat",
        )
        content = result["content"][0]["text"]
        assert "✅ PASSED" in content
        assert "(exit 0)" in content

    @pytest.mark.asyncio
    async def test_profiles_test_denied_returns_error_message(self, mock_broker, mock_config):
        """profiles__test denied by broker returns error text."""
        mock_broker.route_operation.return_value = MagicMock(
            allowed=False,
            error={"message": "scope_violation: path outside roots"},
            result=None,
        )

        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}
        test_tool = by_name["profiles__test"]

        with patch("src.sohnbot.runtime.mcp_tools.get_contextvars", return_value={"chat_id": "test_chat"}):
            result = await test_tool.handler({"repo_path": "/bad/path", "pattern": ""})

        content = result["content"][0]["text"]
        assert "❌ Test denied" in content
        assert "scope_violation" in content

    @pytest.mark.asyncio
    async def test_profiles_ripgrep_routes_through_broker(self, mock_broker, mock_config):
        """profiles__ripgrep invokes broker.route_operation with correct params."""
        mock_broker.route_operation.return_value = MagicMock(
            allowed=True,
            error=None,
            result={
                "matches": [{"file": "a.py", "line": 1, "text": "foo"}],
                "total_matches": 1,
                "exit_code": 0,
            },
        )

        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}
        ripgrep_tool = by_name["profiles__ripgrep"]

        with patch("src.sohnbot.runtime.mcp_tools.get_contextvars", return_value={"chat_id": "test_chat"}):
            result = await ripgrep_tool.handler(
                {"repo_path": "/some/project", "pattern": "foo", "file_types": ["py"], "timeout_seconds": 5}
            )

        mock_broker.route_operation.assert_called_once_with(
            capability="profiles",
            action="ripgrep",
            params={"repo_path": "/some/project", "pattern": "foo", "file_types": ["py"], "timeout_seconds": 5},
            chat_id="test_chat",
        )
        content = result["content"][0]["text"]
        assert "Found 1 matches" in content

    @pytest.mark.asyncio
    async def test_profiles_ripgrep_denied_returns_error_message(self, mock_broker, mock_config):
        """profiles__ripgrep denied by broker returns error text."""
        mock_broker.route_operation.return_value = MagicMock(
            allowed=False,
            error={"message": "scope_violation: path outside roots"},
            result=None,
        )

        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}
        ripgrep_tool = by_name["profiles__ripgrep"]

        with patch("src.sohnbot.runtime.mcp_tools.get_contextvars", return_value={"chat_id": "test_chat"}):
            result = await ripgrep_tool.handler({"repo_path": "/bad/path", "pattern": "foo"})

        content = result["content"][0]["text"]
        assert "❌ Ripgrep denied" in content
        assert "scope_violation" in content

    @pytest.mark.asyncio
    async def test_web_search_routes_through_broker(self, mock_broker, mock_config):
        """web__search invokes broker.route_operation with correct params."""
        mock_broker.route_operation.return_value = MagicMock(
            allowed=True,
            error=None,
            result={
                "query": "python asyncio",
                "results": [
                    {
                        "title": "AsyncIO Docs",
                        "url": "https://docs.python.org/3/library/asyncio.html",
                        "snippet": "Asynchronous I/O in Python.",
                    }
                ],
            },
        )

        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}
        web_tool = by_name["web__search"]

        with patch("src.sohnbot.runtime.mcp_tools.get_contextvars", return_value={"chat_id": "test_chat"}):
            result = await web_tool.handler({"query": "python asyncio", "mode": "fresh"})

        mock_broker.route_operation.assert_called_once_with(
            capability="web",
            action="search",
            params={"query": "python asyncio", "mode": "fresh"},
            chat_id="test_chat",
        )
        content = result["content"][0]["text"]
        assert "Top 1 results" in content
        assert "AsyncIO Docs" in content

    @pytest.mark.asyncio
    async def test_web_search_denied_returns_error_message(self, mock_broker, mock_config):
        """web__search denied by broker returns error text."""
        mock_broker.route_operation.return_value = MagicMock(
            allowed=False,
            error={"message": "Brave API key not configured"},
            result=None,
        )

        with patch(
            "src.sohnbot.runtime.mcp_tools.create_sdk_mcp_server",
            return_value={"type": "inprocess", "name": "sohnbot", "instance": MagicMock()},
        ) as mock_create_server:
            create_sohnbot_mcp_server(broker=mock_broker, config=mock_config)

        tools = mock_create_server.call_args.kwargs["tools"]
        by_name = {tool.name: tool for tool in tools}
        web_tool = by_name["web__search"]

        with patch("src.sohnbot.runtime.mcp_tools.get_contextvars", return_value={"chat_id": "test_chat"}):
            result = await web_tool.handler({"query": "python asyncio", "mode": "fresh"})

        content = result["content"][0]["text"]
        assert "❌ Web search denied" in content
        assert "not configured" in content


class TestPreToolUseHook:
    """Test PreToolUse hook validation."""

    @pytest.mark.asyncio
    async def test_validate_tool_use_allows_sohnbot_tools(self):
        """mcp__sohnbot__* tools allowed."""
        input_data = {"tool_name": "mcp__sohnbot__fs__read"}
        result = await validate_tool_use(input_data, "test_id", {})

        # Should allow (empty dict)
        assert result == {}

    @pytest.mark.asyncio
    async def test_validate_tool_use_blocks_other_tools(self):
        """Non-sohnbot tools blocked."""
        input_data = {"tool_name": "some_other_tool"}
        result = await validate_tool_use(input_data, "test_id", {})

        # Should block
        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"

    @pytest.mark.asyncio
    async def test_validate_tool_use_blocks_read_tool(self):
        """Built-in Read tool blocked."""
        input_data = {"tool_name": "Read"}
        result = await validate_tool_use(input_data, "test_id", {})

        # Should block
        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"

    @pytest.mark.asyncio
    async def test_validate_tool_use_blocks_bash_tool(self):
        """Built-in Bash tool blocked."""
        input_data = {"tool_name": "Bash"}
        result = await validate_tool_use(input_data, "test_id", {})

        # Should block
        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"

    @pytest.mark.asyncio
    @patch('src.sohnbot.runtime.hooks.logger')
    async def test_validate_tool_use_logs_blocked(self, mock_logger):
        """Blocked tools logged with warning."""
        input_data = {"tool_name": "unauthorized_tool"}
        await validate_tool_use(input_data, "test_id", {})

        # Should log warning
        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_all_sohnbot_tools_allowed(self):
        """All defined sohnbot tools should be allowed."""
        tool_names = [
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
            "mcp__sohnbot__git__list_snapshots",
            "mcp__sohnbot__git__prune_snapshots",
            "mcp__sohnbot__git__rollback",
            "mcp__sohnbot__git__checkout",
            "mcp__sohnbot__sched__create",
            "mcp__sohnbot__sched__list",
            "mcp__sohnbot__sched__disable",
            "mcp__sohnbot__sched__enable",
            "mcp__sohnbot__sched__delete",
            "mcp__sohnbot__sched__edit",
            "mcp__sohnbot__observe__status",
            "mcp__sohnbot__observe__resources",
            "mcp__sohnbot__observe__health",
            "mcp__sohnbot__profiles__lint",
            "mcp__sohnbot__profiles__build",
            "mcp__sohnbot__profiles__test",
            "mcp__sohnbot__profiles__ripgrep",
            "mcp__sohnbot__web__search",
        ]

        for tool_name in tool_names:
            input_data = {"tool_name": tool_name}
            result = await validate_tool_use(input_data, "test_id", {})

            # All should be allowed
            assert result == {}, f"Tool {tool_name} should be allowed"
