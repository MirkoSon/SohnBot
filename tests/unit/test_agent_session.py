"""
Unit tests for Agent Session.

Tests Claude SDK initialization, MCP server registration, and hooks.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.sohnbot.runtime.agent_session import AgentSession


class TestAgentSession:
    """Test AgentSession initialization and configuration."""

    @pytest.fixture
    def mock_config(self):
        """Create mock ConfigManager."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "models.telegram_default": "claude-haiku-4-5-20251001",
            "runtime.telegram_max_thinking_tokens": 4000,
            "runtime.telegram_max_turns": 10,
        }.get(key, default)
        return config

    @pytest.fixture
    def mock_broker(self):
        """Create mock BrokerRouter."""
        return AsyncMock()

    @pytest.fixture
    def agent_session(self, mock_config, mock_broker):
        """Create AgentSession instance."""
        return AgentSession(
            config_manager=mock_config,
            broker_router=mock_broker
        )

    # SDK Initialization Tests

    @pytest.mark.asyncio
    @patch('src.sohnbot.runtime.agent_session.ClaudeSDKClient')
    @patch('src.sohnbot.runtime.agent_session.create_sohnbot_mcp_server')
    async def test_initialize_creates_client(self, mock_mcp, mock_sdk, agent_session):
        """ClaudeSDKClient initialized with options."""
        mock_mcp.return_value = MagicMock()
        mock_client = AsyncMock()
        mock_sdk.return_value = mock_client

        with patch.object(agent_session.postponement_manager, "recover_pending", AsyncMock()) as mock_recover:
            await agent_session.initialize()

        # Should create SDK client
        mock_sdk.assert_called_once()

        # Should enter context
        mock_client.__aenter__.assert_called_once()
        mock_recover.assert_called_once()

        assert agent_session.client is not None

    @pytest.mark.asyncio
    @patch('src.sohnbot.runtime.agent_session.ClaudeSDKClient')
    @patch('src.sohnbot.runtime.agent_session.create_sohnbot_mcp_server')
    async def test_initialize_registers_mcp_server(self, mock_mcp, mock_sdk, agent_session, mock_broker, mock_config):
        """In-process MCP server registered."""
        mock_server = MagicMock()
        mock_mcp.return_value = mock_server
        mock_client = AsyncMock()
        mock_sdk.return_value = mock_client

        await agent_session.initialize()

        # Should create MCP server with broker and config
        mock_mcp.assert_called_once_with(
            broker=mock_broker,
            config=mock_config
        )

    @pytest.mark.asyncio
    @patch('src.sohnbot.runtime.agent_session.ClaudeSDKClient')
    @patch('src.sohnbot.runtime.agent_session.create_sohnbot_mcp_server')
    @patch('src.sohnbot.runtime.agent_session.ClaudeAgentOptions')
    async def test_initialize_registers_hooks(self, mock_options, mock_mcp, mock_sdk, agent_session):
        """PreToolUse hook registered."""
        mock_mcp.return_value = MagicMock()
        mock_client = AsyncMock()
        mock_sdk.return_value = mock_client

        await agent_session.initialize()

        # Should create options with hooks
        mock_options.assert_called_once()
        call_kwargs = mock_options.call_args.kwargs

        assert "hooks" in call_kwargs
        assert "PreToolUse" in call_kwargs["hooks"]

    @pytest.mark.asyncio
    @patch('src.sohnbot.runtime.agent_session.ClaudeSDKClient')
    @patch('src.sohnbot.runtime.agent_session.create_sohnbot_mcp_server')
    async def test_initialize_loads_config(self, mock_mcp, mock_sdk, agent_session, mock_config):
        """Model config loaded from ConfigManager."""
        mock_mcp.return_value = MagicMock()
        mock_client = AsyncMock()
        mock_sdk.return_value = mock_client

        await agent_session.initialize()

        # Should get model configuration
        mock_config.get.assert_any_call("models.telegram_default")
        mock_config.get.assert_any_call("runtime.telegram_max_thinking_tokens")
        mock_config.get.assert_any_call("runtime.telegram_max_turns")

    # Query Tests

    @pytest.mark.asyncio
    async def test_query_binds_chat_id(self, agent_session):
        """chat_id bound to structlog context."""
        agent_session.client = AsyncMock()
        agent_session.client.query = AsyncMock()

        # Mock async generator
        async def mock_responses():
            yield MagicMock()

        agent_session.client.receive_response = mock_responses

        with patch('src.sohnbot.runtime.agent_session.bind_contextvars') as mock_bind:
            responses = []
            async for msg in agent_session.query("Test prompt", "123456789"):
                responses.append(msg)

            # Should bind chat_id
            mock_bind.assert_called_once_with(chat_id="123456789")

    @pytest.mark.asyncio
    async def test_query_streams_response(self, agent_session):
        """Response messages streamed via async iterator."""
        agent_session.client = AsyncMock()
        agent_session.client.query = AsyncMock()

        # Mock async generator with multiple messages
        async def mock_responses():
            yield MagicMock(content=[MagicMock(text="Part 1")])
            yield MagicMock(content=[MagicMock(text="Part 2")])

        agent_session.client.receive_response = mock_responses

        responses = []
        async for msg in agent_session.query("Test prompt", "123456789"):
            responses.append(msg)

        # Should yield all messages
        assert len(responses) == 2

    @pytest.mark.asyncio
    async def test_query_ambiguous_prompt_sends_clarification(self, agent_session):
        """Ambiguous prompt triggers clarification request path."""
        agent_session.client = AsyncMock()
        agent_session.client.query = AsyncMock()
        agent_session.client.receive_response = AsyncMock()

        send_message = AsyncMock(return_value=True)

        with (
            patch("src.sohnbot.runtime.agent_session.log_operation_start", AsyncMock()),
            patch.object(agent_session.postponement_manager, "add_pending", AsyncMock()),
            patch.object(agent_session.postponement_manager, "wait_for_clarification", AsyncMock(return_value=None)),
            patch.object(agent_session.postponement_manager, "get_pending", AsyncMock(return_value=None)),
        ):
            responses = []
            async for msg in agent_session.query("do it", "123456789", send_message=send_message):
                responses.append(msg)

        send_message.assert_called_once()
        assert responses
        assert "postponed" in responses[0].lower()

    @pytest.mark.asyncio
    async def test_query_ambiguous_prompt_postpones_on_timeout(self, agent_session):
        """Timed-out clarification marks operation postponed."""
        agent_session.client = AsyncMock()
        agent_session.client.query = AsyncMock()
        agent_session.client.receive_response = AsyncMock()
        send_message = AsyncMock(return_value=True)

        pending = MagicMock()
        with (
            patch("src.sohnbot.runtime.agent_session.log_operation_start", AsyncMock()),
            patch.object(agent_session.postponement_manager, "add_pending", AsyncMock()),
            patch.object(agent_session.postponement_manager, "wait_for_clarification", AsyncMock(return_value=None)),
            patch.object(agent_session.postponement_manager, "get_pending", AsyncMock(return_value=pending)),
            patch.object(agent_session.postponement_manager, "postpone_and_schedule", AsyncMock()) as mock_postpone,
        ):
            async for _ in agent_session.query("fix it", "123456789", send_message=send_message):
                pass

        mock_postpone.assert_called_once_with(pending)

    @pytest.mark.asyncio
    async def test_query_ambiguous_prompt_resolves_and_runs(self, agent_session):
        """Resolved clarification continues with clarified prompt."""
        agent_session.client = AsyncMock()
        agent_session.client.query = AsyncMock()

        async def mock_responses():
            yield MagicMock(content=[MagicMock(text="ok")])

        agent_session.client.receive_response = mock_responses
        send_message = AsyncMock(return_value=True)

        resolved = MagicMock()
        resolved.original_prompt = "do it"
        resolved.response_text = "list files"
        with (
            patch("src.sohnbot.runtime.agent_session.log_operation_start", AsyncMock()),
            patch("src.sohnbot.runtime.agent_session.log_operation_end", AsyncMock()),
            patch.object(agent_session.postponement_manager, "add_pending", AsyncMock()),
            patch.object(agent_session.postponement_manager, "wait_for_clarification", AsyncMock(return_value=resolved)),
            patch.object(agent_session.postponement_manager, "consume_resolved", AsyncMock(return_value=resolved)),
        ):
            async for _ in agent_session.query("do it", "123456789", send_message=send_message):
                pass

        assert agent_session.client.query.call_count == 1
        queried_prompt = agent_session.client.query.call_args[0][0]
        assert "Clarification provided by user" in queried_prompt

    @pytest.mark.asyncio
    async def test_query_error_handling(self, agent_session):
        """SDK errors caught and logged."""
        # Client not initialized
        agent_session.client = None

        with pytest.raises(RuntimeError, match="not initialized"):
            async for _ in agent_session.query("Test", "123"):
                pass

    @pytest.mark.asyncio
    async def test_query_uses_custom_ambiguity_evaluator(self, mock_config, mock_broker):
        """Custom ambiguity evaluator overrides default heuristic."""
        session = AgentSession(
            config_manager=mock_config,
            broker_router=mock_broker,
            ambiguity_evaluator=lambda _: True,
        )
        session.client = AsyncMock()
        session.client.query = AsyncMock()
        session.client.receive_response = AsyncMock()

        send_message = AsyncMock(return_value=True)
        with (
            patch("src.sohnbot.runtime.agent_session.log_operation_start", AsyncMock()),
            patch.object(session.postponement_manager, "add_pending", AsyncMock()),
            patch.object(session.postponement_manager, "wait_for_clarification", AsyncMock(return_value=None)),
            patch.object(session.postponement_manager, "get_pending", AsyncMock(return_value=None)),
        ):
            responses = []
            async for msg in session.query("this-is-normally-clear", "123456789", send_message=send_message):
                responses.append(msg)

        send_message.assert_called_once()
        assert responses

    # Cleanup Tests

    @pytest.mark.asyncio
    async def test_close_cleanup(self, agent_session):
        """Client properly cleaned up."""
        mock_client = AsyncMock()
        agent_session.client = mock_client

        await agent_session.close()

        # Should exit context
        mock_client.__aexit__.assert_called_once()

        # Should clear client
        assert agent_session.client is None
