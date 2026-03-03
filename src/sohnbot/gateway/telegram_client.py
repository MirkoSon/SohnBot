"""
Telegram Bot Client.

Handles Telegram Bot API integration with chat ID authentication.
"""

import asyncio
from uuid import uuid4

import structlog
from structlog.contextvars import bind_contextvars, unbind_contextvars
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from .commands import (
    handle_agent_command,
    handle_config_command,
    handle_heartbeat_command,
    handle_health_command,
    handle_help_command,
    handle_logs_command,
    handle_notify_command,
    handle_schedule_command,
    handle_status_command,
    set_schedule_broker,
)
from .formatters import format_for_telegram
from .notification_worker import NotificationWorker
from .rate_limiter import RateLimiter

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
        max_messages_per_minute = 30
        config = getattr(getattr(message_router, "agent_session", None), "config", None)
        if config is not None:
            try:
                max_messages_per_minute = int(config.get("telegram.max_messages_per_minute"))
            except Exception:  # noqa: BLE001
                max_messages_per_minute = 30
        self._rate_limiter = RateLimiter(max_per_minute=max_messages_per_minute)
        broker = getattr(getattr(message_router, "agent_session", None), "broker", None)
        set_schedule_broker(broker)

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
        self.application.add_handler(CommandHandler("agent", self.cmd_agent))
        self.application.add_handler(CommandHandler("notify", self.cmd_notify))
        self.application.add_handler(CommandHandler("status", self.cmd_status))
        self.application.add_handler(CommandHandler("health", self.cmd_health))
        self.application.add_handler(CommandHandler("logs", self.cmd_logs))
        self.application.add_handler(CommandHandler("schedule", self.cmd_schedule))
        self.application.add_handler(CommandHandler("heartbeat", self.cmd_heartbeat))
        self.application.add_handler(CommandHandler("config", self.cmd_config))
        self.application.add_handler(CommandHandler("dryrun", self.cmd_dryrun))

        # Start polling
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

        if self.notification_worker is None:
            self.notification_worker = NotificationWorker(self)
        await self.notification_worker.start()

        logger.info("telegram_bot_started")

        # Keep this coroutine alive while polling runs. If polling stops,
        # return so the supervisor can apply restart/backoff policy.
        wait_until_closed = getattr(self.application.updater, "wait_until_closed", None)
        if callable(wait_until_closed):
            await wait_until_closed()
        else:
            await asyncio.Event().wait()

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

        correlation_id = str(uuid4())
        ack_msg = None
        ack_finalized = False
        try:
            bind_contextvars(correlation_id=correlation_id)
            ack_msg = await update.message.reply_text("Processing...")

            # Route to Claude Agent SDK runtime
            response = await self.message_router.route_to_runtime(
                chat_id=str(chat_id),
                message=message_text,
                send_message=self.send_message,
                correlation_id=correlation_id,
            )

            if not response.strip():
                if ack_msg is not None:
                    try:
                        await ack_msg.delete()
                        ack_finalized = True
                    except BadRequest:
                        pass
                logger.info("telegram_response_suppressed", chat_id=chat_id)
                return

            if ack_msg is not None:
                try:
                    await ack_msg.delete()
                    ack_finalized = True
                except BadRequest:
                    pass

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
            if ack_msg is not None:
                try:
                    await ack_msg.edit_text("❌ An error occurred processing your request.")
                    ack_finalized = True
                    return
                except BadRequest:
                    pass
            await update.message.reply_text("❌ An error occurred processing your request.")
        finally:
            unbind_contextvars("correlation_id")
            if ack_msg is not None and not ack_finalized:
                try:
                    await ack_msg.delete()
                except BadRequest:
                    pass

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

        response = await handle_help_command()
        await update.message.reply_text(response)

    async def cmd_agent(self, update: Update, context):
        """Handle /agent command."""
        if not update.message or not update.effective_chat:
            return

        chat_id = update.effective_chat.id

        # Check authorization
        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            logger.warning("unauthorized_agent_command", chat_id=chat_id)
            return

        response = await handle_agent_command()
        await update.message.reply_text(response)

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

    async def cmd_status(self, update: Update, context):
        """Handle /status [resources] command."""
        if not update.message or not update.effective_chat:
            return

        chat_id = update.effective_chat.id

        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            logger.warning("unauthorized_status_command", chat_id=chat_id)
            return

        response = await handle_status_command(str(chat_id), update.message.text or "")
        await update.message.reply_text(response)

    async def cmd_health(self, update: Update, context):
        """Handle /health command."""
        if not update.message or not update.effective_chat:
            return

        chat_id = update.effective_chat.id

        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            logger.warning("unauthorized_health_command", chat_id=chat_id)
            return

        response = await handle_health_command(str(chat_id))
        await update.message.reply_text(response)

    async def cmd_logs(self, update: Update, context):
        """Handle /logs [hours] command."""
        if not update.message or not update.effective_chat:
            return

        chat_id = update.effective_chat.id

        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            logger.warning("unauthorized_logs_command", chat_id=chat_id)
            return

        db_path = "data/sohnbot.db"
        agent_session = getattr(self.message_router, "agent_session", None)
        config = getattr(agent_session, "config", None)
        if config is not None:
            try:
                db_path = str(config.get("database.path"))
            except (TypeError, ValueError, KeyError) as exc:
                logger.warning("logs_command_db_path_config_invalid", error=str(exc))
                db_path = "data/sohnbot.db"
            except RuntimeError as exc:
                logger.warning("logs_command_db_path_config_error", error=str(exc))
                db_path = "data/sohnbot.db"

        response = await handle_logs_command(
            str(chat_id),
            update.message.text or "",
            db_path,
        )
        await update.message.reply_text(response)

    async def cmd_schedule(self, update: Update, context):
        """Handle /schedule create <name> \"<cron_expr>\" <timezone> <action> command."""
        if not update.message or not update.effective_chat:
            return

        chat_id = update.effective_chat.id

        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            logger.warning("unauthorized_schedule_command", chat_id=chat_id)
            return

        response = await handle_schedule_command(str(chat_id), update.message.text or "")
        await update.message.reply_text(response)

    async def cmd_heartbeat(self, update: Update, context):
        """Handle /heartbeat status|configure|disable|enable command."""
        if not update.message or not update.effective_chat:
            return

        chat_id = update.effective_chat.id

        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            logger.warning("unauthorized_heartbeat_command", chat_id=chat_id)
            return

        response = await handle_heartbeat_command(str(chat_id), update.message.text or "")
        await update.message.reply_text(response)

    async def cmd_config(self, update: Update, context):
        """Handle /config show|set|reset command."""
        if not update.message or not update.effective_chat:
            return

        chat_id = update.effective_chat.id

        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            logger.warning("unauthorized_config_command", chat_id=chat_id)
            return

        response = await handle_config_command(str(chat_id), update.message.text or "")
        await update.message.reply_text(response)

    async def cmd_dryrun(self, update: Update, context):
        """Handle /dryrun <prompt> by routing through runtime with dry-run marker."""
        if not update.message or not update.effective_chat:
            return

        chat_id = update.effective_chat.id

        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            logger.warning("unauthorized_dryrun_command", chat_id=chat_id)
            return

        raw = (update.message.text or "").strip()
        if raw == "/dryrun":
            await update.message.reply_text("Usage: /dryrun <request>")
            return

        try:
            response = await self.message_router.route_to_runtime(
                chat_id=str(chat_id),
                message=raw,
                send_message=self.send_message,
            )
            if not response.strip():
                return
            formatted_messages = format_for_telegram(response)
            for msg in formatted_messages:
                await update.message.reply_text(msg)
        except Exception as e:
            logger.error(
                "dryrun_message_handling_error",
                chat_id=chat_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            await update.message.reply_text("❌ An error occurred processing your dry-run request.")

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
            await self._rate_limiter.acquire()
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
