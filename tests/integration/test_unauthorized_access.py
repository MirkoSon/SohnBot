"""
Integration tests for unauthorized access handling.

Tests security boundary: chat_id allowlist enforcement.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.sohnbot.gateway.telegram_client import TelegramClient


class TestUnauthorizedAccess:
    """Test chat_id allowlist security."""

    @pytest.fixture
    def message_router(self):
        """Create mock MessageRouter."""
        router = AsyncMock()
        router.route_to_runtime.return_value = "Test response"
        return router

    @pytest.fixture
    def mock_update_unauthorized(self):
        """Create unauthorized update."""
        update = AsyncMock()
        update.effective_chat.id = 999999999  # Not in allowlist
        update.message.text = "Unauthorized message"
        update.message.reply_text = AsyncMock()
        return update

    @pytest.fixture
    def mock_update_authorized(self):
        """Create authorized update."""
        update = AsyncMock()
        update.effective_chat.id = 123456789  # In allowlist
        update.message.text = "Authorized message"
        update.message.reply_text = AsyncMock()
        return update

    @pytest.mark.asyncio
    async def test_unauthorized_chat_silent_ignore(self, message_router, mock_update_unauthorized):
        """No response sent to unauthorized users."""
        client = TelegramClient(
            token="test_token",
            allowed_chat_ids=[123456789],  # Different ID
            message_router=message_router
        )

        await client.handle_message(mock_update_unauthorized, None)

        # Should NOT send any response
        mock_update_unauthorized.message.reply_text.assert_not_called()

        # Should NOT route to runtime
        message_router.route_to_runtime.assert_not_called()

    @pytest.mark.asyncio
    @patch('src.sohnbot.gateway.telegram_client.logger')
    async def test_unauthorized_attempt_logged(self, mock_logger, message_router, mock_update_unauthorized):
        """Attempt logged with chat_id and message preview."""
        client = TelegramClient(
            token="test_token",
            allowed_chat_ids=[123456789],
            message_router=message_router
        )

        await client.handle_message(mock_update_unauthorized, None)

        # Should log warning with details
        mock_logger.warning.assert_called_once()
        call_kwargs = mock_logger.warning.call_args.kwargs

        assert call_kwargs["chat_id"] == 999999999
        assert "message_preview" in call_kwargs

    @pytest.mark.asyncio
    async def test_authorized_chat_processes_message(self, message_router, mock_update_authorized):
        """Authorized users can send messages."""
        client = TelegramClient(
            token="test_token",
            allowed_chat_ids=[123456789],  # Matches update
            message_router=message_router
        )

        await client.handle_message(mock_update_authorized, None)

        # Should route to runtime
        message_router.route_to_runtime.assert_called_once()

        # Should send response
        mock_update_authorized.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_multiple_allowed_ids(self, message_router):
        """Multiple chat IDs in allowlist all work."""
        client = TelegramClient(
            token="test_token",
            allowed_chat_ids=[111111111, 222222222, 333333333],
            message_router=message_router
        )

        for chat_id in [111111111, 222222222, 333333333]:
            update = AsyncMock()
            update.effective_chat.id = chat_id
            update.message.text = "Test"
            update.message.reply_text = AsyncMock()

            await client.handle_message(update, None)

            # Should process all allowed IDs
            update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_empty_allowlist_security_bypass(self, message_router, mock_update_unauthorized):
        """Empty allowlist allows any chat (for testing only)."""
        client = TelegramClient(
            token="test_token",
            allowed_chat_ids=[],  # Empty = allow all
            message_router=message_router
        )

        await client.handle_message(mock_update_unauthorized, None)

        # Should process (security bypass for dev/test)
        message_router.route_to_runtime.assert_called_once()
