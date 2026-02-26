"""Audit logging for all operations."""

import json
from datetime import datetime
from typing import Optional
import structlog

from .db import get_db

logger = structlog.get_logger(__name__)


async def log_operation_start(
    operation_id: str,
    capability: str,
    action: str,
    chat_id: str,
    tier: int,
    file_paths: Optional[str | list[str]] = None,
) -> None:
    """
    Log operation start to execution_log table.

    Args:
        operation_id: UUID tracking ID for operation
        capability: Capability module (fs, git, sched, web, profiles)
        action: Operation action (read, patch, commit, etc.)
        chat_id: Telegram chat ID (user identifier)
        tier: Operation risk tier (0/1/2/3)
        file_paths: File path(s) affected by operation
    """
    # Normalize file_paths to JSON array
    if isinstance(file_paths, str):
        file_paths_json = json.dumps([file_paths])
    elif isinstance(file_paths, list):
        file_paths_json = json.dumps(file_paths)
    elif file_paths is None:
        file_paths_json = None
    else:
        file_paths_json = json.dumps([str(file_paths)])

    # Get database connection
    db = await get_db()

    # Insert operation start record
    try:
        await db.execute(
            """
            INSERT INTO execution_log (
                operation_id, timestamp, capability, action, chat_id, tier, status, file_paths
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operation_id,
                int(datetime.now().timestamp()),
                capability,
                action,
                chat_id,
                tier,
                "in_progress",
                file_paths_json,
            ),
        )
        await db.commit()
    except Exception as e:
        raise RuntimeError(
            f"Failed to log operation start. "
            f"Ensure database migrations have been applied (run scripts/migrate.py). "
            f"Original error: {e}"
        ) from e

    # Structured logging
    logger.info(
        "operation_started",
        operation_id=operation_id,
        capability=capability,
        action=action,
        tier=tier,
        chat_id=chat_id,
    )


async def log_operation_end(
    operation_id: str,
    status: str,
    snapshot_ref: Optional[str] = None,
    duration_ms: Optional[int] = None,
    error_details: Optional[dict] = None,
) -> None:
    """
    Log operation completion to execution_log table.

    Args:
        operation_id: UUID tracking ID for operation
        status: Final status ('completed' or 'failed')
        snapshot_ref: Git snapshot branch reference (if Tier 1/2)
        duration_ms: Operation duration in milliseconds
        error_details: Error details if status='failed'
    """
    # Convert error_details to JSON
    error_details_json = json.dumps(error_details) if error_details else None

    # Get database connection
    db = await get_db()

    # Update operation record
    try:
        await db.execute(
            """
            UPDATE execution_log
            SET status = ?, snapshot_ref = ?, duration_ms = ?, error_details = ?
            WHERE operation_id = ?
            """,
            (status, snapshot_ref, duration_ms, error_details_json, operation_id),
        )
        await db.commit()
    except Exception as e:
        raise RuntimeError(
            f"Failed to log operation end. "
            f"Ensure database migrations have been applied (run scripts/migrate.py). "
            f"Original error: {e}"
        ) from e

    # Structured logging
    if status == "completed":
        logger.info(
            "operation_completed",
            operation_id=operation_id,
            duration_ms=duration_ms,
            snapshot_ref=snapshot_ref,
        )
    else:
        logger.error(
            "operation_failed",
            operation_id=operation_id,
            duration_ms=duration_ms,
            error_details=error_details,
        )
