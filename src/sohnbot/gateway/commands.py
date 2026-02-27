"""Gateway command handlers."""

from __future__ import annotations

from ..persistence.notification import (
    get_notifications_enabled,
    set_notifications_enabled,
)


async def handle_notify_command(chat_id: str, command_text: str) -> str:
    """Handle /notify on|off|status command."""
    parts = command_text.strip().split()
    if len(parts) < 2:
        return "Usage: /notify on|off|status"

    action = parts[1].lower()
    if action == "on":
        await set_notifications_enabled(chat_id, True)
        return "Notifications enabled."
    if action == "off":
        await set_notifications_enabled(chat_id, False)
        return "Notifications disabled."
    if action == "status":
        enabled = await get_notifications_enabled(chat_id)
        return "Notifications are ON." if enabled else "Notifications are OFF."
    return "Usage: /notify on|off|status"
