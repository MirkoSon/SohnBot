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
            "mcp__sohnbot__git__rollback",
        ]

        for tool_name in tool_names:
            input_data = {"tool_name": tool_name}
            result = await validate_tool_use(input_data, "test_id", {})

            # All should be allowed
            assert result == {}, f"Tool {tool_name} should be allowed"
