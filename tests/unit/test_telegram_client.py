"""
Unit tests for Telegram Client.

Tests authentication, message handling, and response formatting.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.sohnbot.gateway.telegram_client import TelegramClient
from src.sohnbot.gateway.formatters import format_for_telegram


class TestTelegramClient:
    """Test TelegramClient authentication and message handling."""

    @pytest.fixture
    def message_router(self):
        """Create mock MessageRouter."""
        router = AsyncMock()
        router.route_to_runtime.return_value = "Test response"
        return router

    @pytest.fixture
    async def telegram_client(self, message_router):
        """Create TelegramClient with mocked dependencies."""
        client = TelegramClient(
            token="test_token",
            allowed_chat_ids=[123456789],
            message_router=message_router
        )
        return client

    @pytest.fixture
    def mock_update(self):
        """Create mock Telegram Update."""
        update = AsyncMock()
        update.effective_chat.id = 123456789
        update.message.text = "Test message"
        update.message.reply_text = AsyncMock()
        return update

    # Authentication Tests

    @pytest.mark.asyncio
    async def test_authorized_chat_id_accepted(self, telegram_client, mock_update, message_router):
        """Allowlisted chat ID processes message."""
        await telegram_client.handle_message(mock_update, None)

        # Should route to runtime
        message_router.route_to_runtime.assert_called_once_with(
            chat_id="123456789",
            message="Test message",
            send_message=telegram_client.send_message,
        )

        # Should send response
        mock_update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_unauthorized_chat_id_blocked(self, telegram_client, mock_update, message_router):
        """Non-allowlisted chat ID silently ignored."""
        mock_update.effective_chat.id = 999999999  # Not in allowlist

        await telegram_client.handle_message(mock_update, None)

        # Should NOT route to runtime
        message_router.route_to_runtime.assert_not_called()

        # Should NOT send response
        mock_update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_allowlist_allows_all(self, message_router, mock_update):
        """Empty allowlist allows any chat ID."""
        client = TelegramClient(
            token="test_token",
            allowed_chat_ids=[],  # Empty allowlist
            message_router=message_router
        )

        await client.handle_message(mock_update, None)

        # Should route to runtime
        message_router.route_to_runtime.assert_called_once()

    @pytest.mark.asyncio
    async def test_unauthorized_logged_not_responded(self, telegram_client, mock_update, message_router):
        """Unauthorized attempts logged but no Telegram response."""
        mock_update.effective_chat.id = 999999999  # Not in allowlist

        with patch('src.sohnbot.gateway.telegram_client.logger') as mock_logger:
            await telegram_client.handle_message(mock_update, None)

            # Should log warning
            mock_logger.warning.assert_called_once()

            # Should NOT send response
            mock_update.message.reply_text.assert_not_called()

    # Message Handling Tests

    @pytest.mark.asyncio
    async def test_handle_message_routes_to_runtime(self, telegram_client, mock_update, message_router):
        """Message routed to agent session."""
        await telegram_client.handle_message(mock_update, None)

        message_router.route_to_runtime.assert_called_once_with(
            chat_id="123456789",
            message="Test message",
            send_message=telegram_client.send_message,
        )

    @pytest.mark.asyncio
    async def test_handle_message_formats_response(self, telegram_client, mock_update, message_router):
        """Response formatted for Telegram limits."""
        # Return long response
        long_response = "A" * 5000  # Exceeds 4096 char limit
        message_router.route_to_runtime.return_value = long_response

        await telegram_client.handle_message(mock_update, None)

        # Should split and send multiple messages
        assert mock_update.message.reply_text.call_count > 1

    @pytest.mark.asyncio
    async def test_handle_message_error_handling(self, telegram_client, mock_update, message_router):
        """Exceptions return error message to user."""
        message_router.route_to_runtime.side_effect = Exception("Test error")

        await telegram_client.handle_message(mock_update, None)

        # Should send error message
        mock_update.message.reply_text.assert_called_once()
        args = mock_update.message.reply_text.call_args[0]
        assert "error" in args[0].lower()

    @pytest.mark.asyncio
    async def test_handle_message_suppresses_empty_response(self, telegram_client, mock_update, message_router):
        """Empty runtime response should not produce a Telegram reply."""
        message_router.route_to_runtime.return_value = ""

        await telegram_client.handle_message(mock_update, None)

        mock_update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_message_success(self, telegram_client):
        """Notification successfully sent."""
        telegram_client.application = AsyncMock()
        telegram_client.application.bot.send_message = AsyncMock()

        result = await telegram_client.send_message(123456789, "Test notification")

        assert result is True
        telegram_client.application.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_failure_logged(self, telegram_client):
        """Failed sends logged with error."""
        telegram_client.application = AsyncMock()
        telegram_client.application.bot.send_message = AsyncMock(
            side_effect=Exception("Send failed")
        )

        with patch('src.sohnbot.gateway.telegram_client.logger') as mock_logger:
            result = await telegram_client.send_message(123456789, "Test")

            assert result is False
            mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_starts_notification_worker(self, message_router):
        """Client startup initializes polling and starts notification worker."""
        worker = AsyncMock()
        worker.start = AsyncMock()
        worker.stop = AsyncMock()
        client = TelegramClient(
            token="test_token",
            allowed_chat_ids=[123456789],
            message_router=message_router,
            notification_worker=worker,
        )

        app = MagicMock()
        app.initialize = AsyncMock()
        app.start = AsyncMock()
        app.updater = MagicMock()
        app.updater.start_polling = AsyncMock()
        app.add_handler = MagicMock()
        builder = MagicMock()
        builder.token.return_value = builder
        builder.build.return_value = app

        with patch("src.sohnbot.gateway.telegram_client.Application.builder", return_value=builder):
            await client.start()

        worker.start.assert_called_once()
        app.initialize.assert_called_once()
        app.start.assert_called_once()
        app.updater.start_polling.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_stops_notification_worker(self, message_router):
        """Client shutdown stops notification worker before app shutdown."""
        worker = AsyncMock()
        worker.start = AsyncMock()
        worker.stop = AsyncMock()
        client = TelegramClient(
            token="test_token",
            allowed_chat_ids=[123456789],
            message_router=message_router,
            notification_worker=worker,
        )
        client.application = AsyncMock()

        await client.stop()

        worker.stop.assert_called_once()
        client.application.stop.assert_called_once()
        client.application.shutdown.assert_called_once()


class TestFormatters:
    """Test message formatting functions."""

    def test_format_short_message(self):
        """Messages <4096 chars returned as-is."""
        short_msg = "Short message"
        result = format_for_telegram(short_msg)

        assert len(result) == 1
        assert result[0] == short_msg

    def test_format_long_message_split(self):
        """Messages >4096 chars split on newlines."""
        # Create message with many lines exceeding 4096 chars
        lines = [f"Line {i}" * 100 for i in range(100)]
        long_msg = "\n".join(lines)

        result = format_for_telegram(long_msg)

        # Should split into multiple messages
        assert len(result) > 1

        # Each message should be under limit
        for msg in result:
            assert len(msg) <= 4096

    def test_format_preserves_markdown(self):
        """Markdown formatting preserved."""
        msg = "**Bold** *italic* `code`"
        result = format_for_telegram(msg)

        assert len(result) == 1
        assert "**Bold**" in result[0]
        assert "*italic*" in result[0]
        assert "`code`" in result[0]

    def test_format_code_blocks(self):
        """Code blocks not split mid-block."""
        msg = "```\n" + ("x" * 3000) + "\n```\nNormal text"
        result = format_for_telegram(msg)

        # Code block should be in one message
        assert any("```" in msg for msg in result)
