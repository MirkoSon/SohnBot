"""
Telegram Gateway module.

Handles incoming messages from Telegram Bot API, authenticates users,
and routes messages to the Claude Agent SDK runtime.
"""

from .formatters import format_for_telegram
from .message_router import MessageRouter
from .telegram_client import TelegramClient

__all__ = ["format_for_telegram", "MessageRouter", "TelegramClient"]
