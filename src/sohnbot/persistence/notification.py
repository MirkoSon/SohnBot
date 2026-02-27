"""Notification outbox persistence operations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import structlog

from .db import get_db

logger = structlog.get_logger(__name__)

_NOTIFY_KEY_PREFIX = "notifications."
_NOTIFY_KEY_SUFFIX = ".enabled"


def _notify_config_key(chat_id: str) -> str:
    return f"{_NOTIFY_KEY_PREFIX}{chat_id}{_NOTIFY_KEY_SUFFIX}"


async def enqueue_notification(operation_id: str, chat_id: str, message_text: str) -> int:
    """Insert a pending notification into outbox."""
    db = await get_db()
    cursor = await db.execute(
        """
        INSERT INTO notification_outbox
            (operation_id, chat_id, status, message_text, created_at, retry_count)
        VALUES
            (?, ?, 'pending', ?, ?, 0)
        """,
        (operation_id, chat_id, message_text, int(datetime.now().timestamp())),
    )
    await db.commit()
    notification_id = int(cursor.lastrowid)
    await cursor.close()

    logger.info(
        "notification_enqueued",
        notification_id=notification_id,
        operation_id=operation_id,
        chat_id=chat_id,
    )
    return notification_id


async def get_pending_notifications(limit: int = 10) -> list[dict[str, Any]]:
    """Fetch oldest pending notifications for worker processing."""
    db = await get_db()
    now = int(datetime.now().timestamp())
    cursor = await db.execute(
        """
        SELECT id, operation_id, chat_id, status, message_text, created_at, sent_at, retry_count, error_details
        FROM notification_outbox
        WHERE status = 'pending'
          AND created_at <= ?
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (now, limit),
    )
    rows = await cursor.fetchall()
    await cursor.close()

    return [
        {
            "id": row[0],
            "operation_id": row[1],
            "chat_id": row[2],
            "status": row[3],
            "message_text": row[4],
            "created_at": row[5],
            "sent_at": row[6],
            "retry_count": row[7],
            "error_details": row[8],
        }
        for row in rows
    ]


async def mark_notification_sent(notification_id: int) -> None:
    """Mark notification as sent."""
    db = await get_db()
    await db.execute(
        """
        UPDATE notification_outbox
        SET status = 'sent',
            sent_at = ?,
            error_details = NULL
        WHERE id = ?
        """,
        (int(datetime.now().timestamp()), notification_id),
    )
    await db.commit()


async def mark_notification_failed(notification_id: int, error_details: str) -> None:
    """Mark notification as failed and increment retry count."""
    db = await get_db()
    await db.execute(
        """
        UPDATE notification_outbox
        SET status = 'failed',
            retry_count = retry_count + 1,
            error_details = ?
        WHERE id = ?
        """,
        (error_details, notification_id),
    )
    await db.commit()


async def requeue_notification(notification_id: int) -> None:
    """Set notification back to pending for retry."""
    db = await get_db()
    await db.execute(
        """
        UPDATE notification_outbox
        SET status = 'pending'
        WHERE id = ?
        """,
        (notification_id,),
    )
    await db.commit()


async def schedule_notification_retry(notification_id: int, delay_seconds: int) -> None:
    """Set notification to pending with next eligibility time."""
    db = await get_db()
    next_attempt_at = int(datetime.now().timestamp()) + max(0, delay_seconds)
    await db.execute(
        """
        UPDATE notification_outbox
        SET status = 'pending',
            created_at = ?
        WHERE id = ?
        """,
        (next_attempt_at, notification_id),
    )
    await db.commit()


async def get_notifications_enabled(chat_id: str) -> bool:
    """Read per-chat notification setting from config table (default True)."""
    db = await get_db()
    key = _notify_config_key(chat_id)
    cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = await cursor.fetchone()
    await cursor.close()

    if row is None:
        return True

    try:
        value = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        value = row[0]
    return str(value).lower() in {"1", "true", "yes", "on"}


async def set_notifications_enabled(chat_id: str, enabled: bool) -> None:
    """Set per-chat notification setting in config table."""
    db = await get_db()
    key = _notify_config_key(chat_id)
    value = json.dumps(bool(enabled))
    now = int(datetime.now().timestamp())
    await db.execute(
        """
        INSERT INTO config (key, value, updated_at, updated_by, tier)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at,
            updated_by = excluded.updated_by,
            tier = excluded.tier
        """,
        (key, value, now, chat_id, "dynamic"),
    )
    await db.commit()


async def get_notification_lag_seconds() -> int | None:
    """Return age of oldest pending notification for observability."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT created_at
        FROM notification_outbox
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT 1
        """
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None
    return max(0, int(datetime.now().timestamp()) - int(row[0]))
