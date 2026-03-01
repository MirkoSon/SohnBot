"""Daily search volume tracking and alert state persistence."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite
import structlog

logger = structlog.get_logger(__name__)


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


async def increment_daily_search_count(db_path: str) -> tuple[int, bool] | None:
    """Increment today's counter and return (count, alert_sent), or None on DB error."""
    today = _today_utc()
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                INSERT INTO daily_search_volume (date, search_count)
                VALUES (?, 1)
                ON CONFLICT(date) DO UPDATE SET
                    search_count = search_count + 1,
                    updated_at = datetime('now')
                """,
                (today,),
            )
            await db.commit()
            cursor = await db.execute(
                "SELECT search_count, alert_sent FROM daily_search_volume WHERE date = ?",
                (today,),
            )
            row = await cursor.fetchone()
            await cursor.close()
        if row is None:
            return 0, False
        return int(row[0]), bool(row[1])
    except aiosqlite.Error as exc:
        logger.warning("search_volume_increment_error", error=str(exc), date=today)
        return None


async def mark_alert_sent(db_path: str) -> bool:
    """Mark today's row as alerted; returns True when row updated."""
    today = _today_utc()
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                """
                UPDATE daily_search_volume
                SET
                    alert_sent = 1,
                    updated_at = datetime('now')
                WHERE date = ?
                """,
                (today,),
            )
            await db.commit()
            updated = int(cursor.rowcount or 0) > 0
            await cursor.close()
        return updated
    except aiosqlite.Error as exc:
        logger.warning("search_volume_mark_alert_error", error=str(exc), date=today)
        return False


async def claim_alert_slot(db_path: str, threshold: int) -> int | None:
    """
    Atomically claim today's alert slot once threshold is exceeded.

    Returns today's count if this caller claimed the slot; otherwise None.
    """
    today = _today_utc()
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT search_count, alert_sent FROM daily_search_volume WHERE date = ?",
                (today,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                return None

            count = int(row[0])
            alert_sent = bool(row[1])
            if count <= threshold or alert_sent:
                return None

            update_cursor = await db.execute(
                """
                UPDATE daily_search_volume
                SET alert_sent = 1, updated_at = datetime('now')
                WHERE date = ? AND alert_sent = 0
                """,
                (today,),
            )
            await db.commit()
            claimed = int(update_cursor.rowcount or 0) > 0
            await update_cursor.close()
            if claimed:
                return count
            return None
    except aiosqlite.Error as exc:
        logger.warning("search_volume_claim_alert_error", error=str(exc), date=today)
        return None


async def cleanup_old_volume_records(db_path: str, retention_days: int = 30) -> int:
    """Delete rows older than retention_days and return deleted count."""
    try:
        retention = int(retention_days)
    except (TypeError, ValueError):
        retention = 30

    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "DELETE FROM daily_search_volume WHERE date < date('now', ?)",
                (f"-{retention} days",),
            )
            await db.commit()
            deleted = int(cursor.rowcount or 0)
            await cursor.close()
        return deleted
    except aiosqlite.Error as exc:
        logger.warning("search_volume_cleanup_error", error=str(exc))
        return 0
