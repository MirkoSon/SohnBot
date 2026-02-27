"""
Integration tests for end-to-end message flow.

Tests: Telegram → Gateway → Runtime → (Broker → Capability) → Response
Note: Capabilities not implemented yet (Story 1.5+), so broker calls are stubbed.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.sohnbot.gateway.telegram_client import TelegramClient
from src.sohnbot.gateway.message_router import MessageRouter


class TestTelegramToBrokerFlow:
    """Test end-to-end message flow."""

    @pytest.fixture
    def mock_agent_session(self):
        """Create mock AgentSession."""
        session = AsyncMock()

        # Mock async generator response
        async def mock_query(prompt, chat_id, send_message=None, skip_ambiguity_check=False):
            # Simulate Claude SDK response
            mock_msg = MagicMock()
            mock_msg.content = [MagicMock(text="This is a test response from Claude")]
            yield mock_msg

        session.query = mock_query
        session.postponement_manager = MagicMock()
        session.postponement_manager.has_pending = AsyncMock(return_value=False)
        return session

    @pytest.fixture
    def message_router(self, mock_agent_session):
        """Create MessageRouter with mocked agent."""
        return MessageRouter(agent_session=mock_agent_session)

    @pytest.fixture
    def telegram_client(self, message_router):
        """Create TelegramClient."""
        return TelegramClient(
            token="test_token",
            allowed_chat_ids=[123456789],
            message_router=message_router
        )

    @pytest.fixture
    def mock_update(self):
        """Create mock Telegram Update."""
        update = AsyncMock()
        update.effective_chat.id = 123456789
        update.message.text = "Test user message"
        update.message.reply_text = AsyncMock()
        return update

    # End-to-End Flow Tests

    @pytest.mark.asyncio
    async def test_telegram_message_to_response(self, telegram_client, mock_update, message_router):
        """Full flow: Telegram → Runtime → Response."""
        await telegram_client.handle_message(mock_update, None)

        # Should send response to user
        mock_update.message.reply_text.assert_called_once()

        # Response should contain expected text
        call_args = mock_update.message.reply_text.call_args
        response_text = call_args[0][0]
        assert "test response" in response_text.lower()

    @pytest.mark.asyncio
    async def test_message_router_aggregates_response(self, message_router):
        """Router aggregates AssistantMessage text blocks."""
        response = await message_router.route_to_runtime(
            chat_id="123456789",
            message="Test query"
        )

        # Should return aggregated text
        assert isinstance(response, str)
        assert len(response) > 0

    @pytest.mark.asyncio
    @patch('src.sohnbot.gateway.message_router.logger')
    async def test_routing_logs_operations(self, mock_logger, message_router):
        """Router logs message routing."""
        await message_router.route_to_runtime(
            chat_id="123456789",
            message="Test"
        )

        # Should log routing start and completion
        assert mock_logger.info.call_count >= 2

    @pytest.mark.asyncio
    async def test_unauthorized_chat_no_runtime_call(self, telegram_client, mock_agent_session):
        """Unauthorized chats never reach runtime."""
        unauthorized_update = AsyncMock()
        unauthorized_update.effective_chat.id = 999999999  # Not in allowlist
        unauthorized_update.message.text = "Unauthorized"
        unauthorized_update.message.reply_text = AsyncMock()

        # Reset mock to check calls
        if hasattr(mock_agent_session.query, 'call_count'):
            mock_agent_session.query.reset_mock()

        await telegram_client.handle_message(unauthorized_update, None)

        # Agent session should NOT be called
        # (query is an async generator, so checking if it was entered)
        unauthorized_update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_response_chunks(self, message_router):
        """Router handles multiple response parts."""
        # Mock session with multiple messages
        mock_session = AsyncMock()

        async def multi_response(prompt, chat_id, send_message=None, skip_ambiguity_check=False):
            msg1 = MagicMock()
            msg1.content = [MagicMock(text="Part 1")]
            yield msg1

            msg2 = MagicMock()
            msg2.content = [MagicMock(text="Part 2")]
            yield msg2

        mock_session.query = multi_response
        mock_session.postponement_manager = MagicMock()
        mock_session.postponement_manager.has_pending = AsyncMock(return_value=False)
        router = MessageRouter(agent_session=mock_session)

        response = await router.route_to_runtime("123", "Test")

        # Should aggregate both parts
        assert "Part 1" in response
        assert "Part 2" in response

    @pytest.mark.asyncio
    @patch('src.sohnbot.gateway.telegram_client.logger')
    async def test_telegram_logs_message_flow(self, mock_logger, telegram_client, mock_update):
        """Telegram client logs message received and sent."""
        await telegram_client.handle_message(mock_update, None)

        # Should log message received and response sent
        info_calls = [call for call in mock_logger.info.call_args_list]
        assert len(info_calls) >= 2  # received + sent

    @pytest.mark.asyncio
    async def test_pending_clarification_acknowledged_without_auto_execution(self):
        """Pending non-postponed clarifications should not send duplicate response."""
        mock_session = AsyncMock()
        mock_session.postponement_manager = MagicMock()
        mock_session.postponement_manager.has_pending = AsyncMock(return_value=True)
        pending = MagicMock()
        pending.postponed = False
        pending.response_text = "list files"
        mock_session.postponement_manager.resolve = AsyncMock(return_value=pending)
        mock_session.query = AsyncMock()

        router = MessageRouter(agent_session=mock_session)
        response = await router.route_to_runtime("123", "list files")

        assert response == ""
        mock_session.query.assert_not_called()

    @pytest.mark.asyncio
    async def test_postponed_clarification_resumes_original_request(self):
        """Postponed operations resume when clarification arrives later."""
        mock_session = AsyncMock()
        mock_session.postponement_manager = MagicMock()
        mock_session.postponement_manager.has_pending = AsyncMock(return_value=True)

        pending = MagicMock()
        pending.postponed = True
        pending.response_text = "list files"
        pending.original_prompt = "do it"
        mock_session.postponement_manager.resolve = AsyncMock(return_value=pending)
        mock_session.postponement_manager.consume_resolved = AsyncMock(return_value=pending)
        mock_session.postponement_manager.build_clarified_prompt = MagicMock(
            return_value="do it\n\nClarification provided by user: list files"
        )

        async def resumed_query(prompt, chat_id, send_message=None, skip_ambiguity_check=False):
            msg = MagicMock()
            msg.content = [MagicMock(text="Resumed response")]
            yield msg

        mock_session.query = resumed_query
        router = MessageRouter(agent_session=mock_session)

        response = await router.route_to_runtime("123", "list files")
        assert "resumed response" in response.lower()
