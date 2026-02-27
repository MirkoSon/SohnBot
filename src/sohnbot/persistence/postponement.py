"""Persistence helpers for ambiguous-request postponement lifecycle."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .db import get_db


def _now_ts() -> int:
    return int(datetime.now().timestamp())


async def save_pending_operation(
    operation_id: str,
    chat_id: str,
    original_prompt: str,
    option_a: str,
    option_b: str,
    clarification_deadline_at: int,
) -> None:
    db = await get_db()
    now = _now_ts()
    await db.execute(
        """
        INSERT INTO postponed_operation (
            operation_id, chat_id, original_prompt, option_a, option_b, status,
            clarification_response, retry_enqueued, created_at, updated_at,
            clarification_deadline_at, retry_at, cancel_at
        ) VALUES (?, ?, ?, ?, ?, 'waiting', NULL, 0, ?, ?, ?, NULL, NULL)
        ON CONFLICT(operation_id) DO UPDATE SET
            chat_id = excluded.chat_id,
            original_prompt = excluded.original_prompt,
            option_a = excluded.option_a,
            option_b = excluded.option_b,
            status = excluded.status,
            clarification_response = NULL,
            retry_enqueued = 0,
            updated_at = excluded.updated_at,
            clarification_deadline_at = excluded.clarification_deadline_at,
            retry_at = NULL,
            cancel_at = NULL
        """,
        (operation_id, chat_id, original_prompt, option_a, option_b, now, now, clarification_deadline_at),
    )
    await db.commit()


async def mark_operation_postponed(operation_id: str, retry_at: int, cancel_at: int) -> None:
    db = await get_db()
    now = _now_ts()
    await db.execute(
        """
        UPDATE postponed_operation
        SET status = 'postponed',
            retry_at = ?,
            cancel_at = ?,
            updated_at = ?
        WHERE operation_id = ?
        """,
        (retry_at, cancel_at, now, operation_id),
    )
    await db.commit()


async def mark_operation_resolved(operation_id: str, clarification_response: str) -> None:
    db = await get_db()
    now = _now_ts()
    await db.execute(
        """
        UPDATE postponed_operation
        SET status = 'resolved',
            clarification_response = ?,
            updated_at = ?
        WHERE operation_id = ?
        """,
        (clarification_response, now, operation_id),
    )
    await db.commit()


async def mark_retry_enqueued(operation_id: str) -> None:
    db = await get_db()
    now = _now_ts()
    await db.execute(
        """
        UPDATE postponed_operation
        SET retry_enqueued = 1,
            updated_at = ?
        WHERE operation_id = ?
        """,
        (now, operation_id),
    )
    await db.commit()


async def mark_operation_cancelled(operation_id: str) -> None:
    db = await get_db()
    now = _now_ts()
    await db.execute(
        """
        UPDATE postponed_operation
        SET status = 'cancelled',
            updated_at = ?
        WHERE operation_id = ?
        """,
        (now, operation_id),
    )
    await db.commit()


async def get_active_operation_by_chat(chat_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT operation_id, chat_id, original_prompt, option_a, option_b, status,
               clarification_response, retry_enqueued, created_at, updated_at,
               clarification_deadline_at, retry_at, cancel_at
        FROM postponed_operation
        WHERE chat_id = ?
          AND status IN ('waiting', 'postponed', 'resolved')
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (chat_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None
    return {
        "operation_id": row[0],
        "chat_id": row[1],
        "original_prompt": row[2],
        "option_a": row[3],
        "option_b": row[4],
        "status": row[5],
        "clarification_response": row[6],
        "retry_enqueued": int(row[7]),
        "created_at": row[8],
        "updated_at": row[9],
        "clarification_deadline_at": row[10],
        "retry_at": row[11],
        "cancel_at": row[12],
    }


async def list_active_operations() -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT operation_id, chat_id, original_prompt, option_a, option_b, status,
               clarification_response, retry_enqueued, created_at, updated_at,
               clarification_deadline_at, retry_at, cancel_at
        FROM postponed_operation
        WHERE status IN ('waiting', 'postponed')
        ORDER BY updated_at ASC
        """
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        {
            "operation_id": row[0],
            "chat_id": row[1],
            "original_prompt": row[2],
            "option_a": row[3],
            "option_b": row[4],
            "status": row[5],
            "clarification_response": row[6],
            "retry_enqueued": int(row[7]),
            "created_at": row[8],
            "updated_at": row[9],
            "clarification_deadline_at": row[10],
            "retry_at": row[11],
            "cancel_at": row[12],
        }
        for row in rows
    ]


async def delete_operation(operation_id: str) -> None:
    db = await get_db()
    await db.execute("DELETE FROM postponed_operation WHERE operation_id = ?", (operation_id,))
    await db.commit()
