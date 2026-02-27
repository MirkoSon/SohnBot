"""
Telegram Bot Client.

Handles Telegram Bot API integration with chat ID authentication.
"""

import structlog
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from .commands import handle_notify_command
from .formatters import format_for_telegram
from .notification_worker import NotificationWorker

logger = structlog.get_logger(__name__)


class TelegramClient:
    """Async Telegram Bot API integration with authentication."""

    def __init__(
        self,
        token: str,
        allowed_chat_ids: list[int],
        message_router,
        notification_worker: NotificationWorker | None = None,
    ):
        """
        Initialize TelegramClient.

        Args:
            token: Telegram bot token from @BotFather
            allowed_chat_ids: List of authorized Telegram chat IDs (FR-033)
            message_router: MessageRouter instance for routing to runtime
            notification_worker: Optional worker override (used by tests)
        """
        self.token = token
        self.allowed_chat_ids = allowed_chat_ids
        self.message_router = message_router
        self.application = None
        self.notification_worker = notification_worker

    async def start(self):
        """Initialize and start the bot with polling."""
        logger.info(
            "telegram_bot_starting",
            allowed_chat_count=len(self.allowed_chat_ids) if self.allowed_chat_ids else 0
        )

        # Build application
        self.application = Application.builder().token(self.token).build()

        # Register handlers
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("help", self.cmd_help))
        self.application.add_handler(CommandHandler("notify", self.cmd_notify))

        # Start polling
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

        if self.notification_worker is None:
            self.notification_worker = NotificationWorker(self)
        await self.notification_worker.start()

        logger.info("telegram_bot_started")

    async def stop(self):
        """Stop the bot gracefully."""
        if self.notification_worker:
            await self.notification_worker.stop()
        if self.application:
            logger.info("telegram_bot_stopping")
            await self.application.stop()
            await self.application.shutdown()
            logger.info("telegram_bot_stopped")

    async def handle_message(self, update: Update, context):
        """
        Handle incoming text messages with authentication.

        Args:
            update: Telegram Update object
            context: Telegram context (unused)
        """
        # Null-safety check
        if not update.message or not update.effective_chat:
            logger.warning("received_update_without_message_or_chat")
            return

        chat_id = update.effective_chat.id
        message_text = update.message.text

        # Authenticate against allowlist (FR-033)
        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            logger.warning(
                "unauthorized_chat_attempt",
                chat_id=chat_id,
                message_preview=message_text[:50] if message_text else ""
            )
            # Silent ignore - don't respond to unauthorized users
            return

        # Log authorized message
        logger.info(
            "telegram_message_received",
            chat_id=chat_id,
            message_length=len(message_text) if message_text else 0
        )

        try:
            # Route to Claude Agent SDK runtime
            response = await self.message_router.route_to_runtime(
                chat_id=str(chat_id),
                message=message_text,
                send_message=self.send_message,
            )

            if not response.strip():
                logger.info("telegram_response_suppressed", chat_id=chat_id)
                return

            # Format and send response (handle 4096-char limit)
            formatted_messages = format_for_telegram(response)
            for msg in formatted_messages:
                # Use plain text (no parse_mode) to avoid Markdown escaping issues
                await update.message.reply_text(msg)

            logger.info(
                "telegram_response_sent",
                chat_id=chat_id,
                message_count=len(formatted_messages)
            )

        except Exception as e:
            logger.error(
                "message_handling_error",
                chat_id=chat_id,
                error=str(e),
                error_type=type(e).__name__
            )
            await update.message.reply_text(
                "❌ An error occurred processing your request."
            )

    async def cmd_start(self, update: Update, context):
        """Handle /start command."""
        if not update.message or not update.effective_chat:
            return

        chat_id = update.effective_chat.id

        # Check authorization
        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            logger.warning("unauthorized_start_command", chat_id=chat_id)
            return

        await update.message.reply_text(
            "👋 Welcome to SohnBot!\n\n"
            "I'm an AI assistant with local file management capabilities.\n\n"
            "Send me a message to get started!"
        )

    async def cmd_help(self, update: Update, context):
        """Handle /help command."""
        if not update.message or not update.effective_chat:
            return

        chat_id = update.effective_chat.id

        # Check authorization
        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            logger.warning("unauthorized_help_command", chat_id=chat_id)
            return

        await update.message.reply_text(
            "📚 SohnBot Help\n\n"
            "Just send me a message describing what you want to do!\n\n"
            "Examples:\n"
            "- List files in ~/Projects\n"
            "- Read README.md\n"
            "- Show git status\n\n"
            "All operations are logged and scoped to authorized directories."
        )

    async def cmd_notify(self, update: Update, context):
        """Handle /notify on|off|status command."""
        if not update.message or not update.effective_chat:
            return

        chat_id = update.effective_chat.id

        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            logger.warning("unauthorized_notify_command", chat_id=chat_id)
            return

        response = await handle_notify_command(str(chat_id), update.message.text or "")
        await update.message.reply_text(response)

    async def send_message(self, chat_id: int, text: str) -> bool:
        """
        Send message to specific chat (for notifications).

        Args:
            chat_id: Telegram chat ID
            text: Message text to send

        Returns:
            True if successful, False otherwise
        """
        try:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=text
            )
            logger.info("notification_sent", chat_id=chat_id)
            return True
        except Exception as e:
            logger.error(
                "send_message_error",
                chat_id=chat_id,
                error=str(e),
                error_type=type(e).__name__
            )
            return False
