"""Query and cleanup helpers for operation execution logs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite
import structlog

logger = structlog.get_logger(__name__)

_ALLOWED_STATUS_FILTERS = {
    "in_progress",
    "completed",
    "failed",
    "postponed",
    "cancelled",
}
_STATUS_FILTER_ERROR = f"status must be one of: {', '.join(sorted(_ALLOWED_STATUS_FILTERS))}"


def _to_local_iso(timestamp: int) -> str:
    dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).astimezone()
    return dt.isoformat(timespec="seconds")


def _decode_json_field(raw: str | None, default: Any) -> Any:
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


async def query_operation_logs(
    db_path: str,
    hours: int = 24,
    capability: str | None = None,
    status: str | None = None,
    chat_id: str | None = None,
    tier: int | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Query execution_log rows for the last N hours with optional filters."""
    hours_int = int(hours)
    if hours_int < 1 or hours_int > 720:
        raise ValueError("hours must be between 1 and 720")

    if status is not None and status not in _ALLOWED_STATUS_FILTERS:
        raise ValueError(_STATUS_FILTER_ERROR)

    if tier is not None and int(tier) not in {0, 1, 2, 3}:
        raise ValueError("tier must be one of: 0, 1, 2, 3")

    max_rows = max(1, min(int(limit), 1000))
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours_int)).timestamp())

    query = """
        SELECT
            operation_id,
            timestamp,
            capability,
            action,
            chat_id,
            tier,
            status,
            file_paths,
            snapshot_ref,
            duration_ms,
            error_details
        FROM execution_log
        WHERE timestamp >= ?
    """
    params: list[Any] = [cutoff_ts]

    if capability is not None:
        query += " AND capability = ?"
        params.append(capability)
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    if chat_id is not None:
        query += " AND chat_id = ?"
        params.append(chat_id)
    if tier is not None:
        query += " AND tier = ?"
        params.append(int(tier))

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(max_rows)

    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(query, tuple(params))
            rows = await cursor.fetchall()
            await cursor.close()
    except aiosqlite.Error as exc:
        logger.error(
            "operation_logs_query_error",
            error=str(exc),
            hours=hours_int,
            capability=capability,
            status=status,
            chat_id=chat_id,
            tier=tier,
        )
        raise RuntimeError(f"Failed to query operation logs: {exc}") from exc

    results: list[dict[str, Any]] = []
    for row in rows:
        timestamp = int(row[1])
        file_paths = _decode_json_field(row[7], [])
        if not isinstance(file_paths, list):
            file_paths = []
        error_details = _decode_json_field(row[10], None)
        if error_details is not None and not isinstance(error_details, dict):
            error_details = {"raw": str(row[10])}

        results.append(
            {
                "operation_id": row[0],
                "timestamp": timestamp,
                "timestamp_iso": _to_local_iso(timestamp),
                "capability": row[2],
                "action": row[3],
                "chat_id": row[4],
                "tier": row[5],
                "status": row[6],
                "file_paths": file_paths,
                "snapshot_ref": row[8],
                "duration_ms": row[9],
                "error_details": error_details,
            }
        )

    logger.info(
        "operation_logs_query_completed",
        hours=hours_int,
        capability=capability,
        status=status,
        chat_id=chat_id,
        tier=tier,
        count=len(results),
    )
    return results


async def cleanup_old_operation_logs(db_path: str, retention_days: int = 90) -> int:
    """Delete execution_log rows older than retention_days and return deleted row count."""
    try:
        retention = int(retention_days)
    except (TypeError, ValueError):
        retention = 90
    retention = max(1, retention)
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(days=retention)).timestamp())

    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "DELETE FROM execution_log WHERE timestamp < ?",
                (cutoff_ts,),
            )
            await db.commit()
            deleted = int(cursor.rowcount or 0)
            await cursor.close()
    except aiosqlite.Error as exc:
        logger.warning(
            "operation_logs_cleanup_error",
            error=str(exc),
            retention_days=retention,
        )
        return 0

    logger.info(
        "operation_logs_cleanup_completed",
        deleted=deleted,
        retention_days=retention,
    )
    return deleted
