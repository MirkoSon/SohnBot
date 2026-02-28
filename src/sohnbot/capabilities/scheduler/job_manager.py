"""Scheduler job persistence and validation helpers."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiosqlite
import structlog
from croniter import CroniterBadCronError, croniter

from ...persistence.db import get_db
from .timezone_handler import get_next_run_time

logger = structlog.get_logger(__name__)

ALLOWED_ACTIONS = {"agent_query", "profile_execute", "heartbeat"}


def _validate_cron(cron_expr: str) -> None:
    try:
        croniter(cron_expr)
    except (CroniterBadCronError, ValueError) as exc:
        raise ValueError(f"Invalid cron expression: {cron_expr}") from exc


def _validate_timezone(timezone: str) -> None:
    try:
        # zoneinfo resolves from system tzdata (or tzdata package when available).
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone: {timezone}. Use an IANA timezone like 'America/New_York'.") from exc


def _validate_action(action: str) -> None:
    if action not in ALLOWED_ACTIONS:
        allowed = ", ".join(sorted(ALLOWED_ACTIONS))
        raise ValueError(f"Invalid action '{action}'. Allowed actions: {allowed}")


def _row_to_job(row: tuple[Any, ...]) -> dict[str, Any]:
    action_params = json.loads(row[5]) if row[5] else None
    return {
        "id": row[0],
        "name": row[1],
        "cron_expr": row[2],
        "timezone": row[3],
        "action": row[4],
        "action_params": action_params,
        "enabled": bool(row[6]),
        "created_at": row[7],
        "last_completed_slot": row[8],
    }


async def create_job(
    name: str,
    cron_expr: str,
    timezone: str,
    action: str,
    action_params: dict[str, Any] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """Create a scheduler job after validating cron/timezone/action inputs."""
    _validate_cron(cron_expr)
    _validate_timezone(timezone)
    _validate_action(action)

    job_id = str(uuid.uuid4())
    created_at = int(time.time())
    enabled_int = 1 if enabled else 0
    action_params_json = json.dumps(action_params) if action_params is not None else None

    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO jobs (
                id, name, cron_expr, timezone, action, action_params, enabled, created_at, last_completed_slot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                job_id,
                name,
                cron_expr,
                timezone,
                action,
                action_params_json,
                enabled_int,
                created_at,
            ),
        )
        await db.commit()
    except aiosqlite.IntegrityError as exc:
        logger.warning("job_create_integrity_error", name=name, error=str(exc))
        raise ValueError(f"Failed to create job '{name}': {exc}") from exc
    except Exception as exc:
        logger.error("job_create_db_error", name=name, error=str(exc))
        raise RuntimeError(f"Database error while creating job '{name}'") from exc

    return {
        "id": job_id,
        "name": name,
        "cron_expr": cron_expr,
        "timezone": timezone,
        "action": action,
        "action_params": action_params,
        "enabled": enabled,
        "created_at": created_at,
        "last_completed_slot": None,
    }


async def list_jobs(enabled_only: bool = False) -> list[dict[str, Any]]:
    """List scheduler jobs ordered by newest first."""
    db = await get_db()

    query = """
        SELECT id, name, cron_expr, timezone, action, action_params, enabled, created_at, last_completed_slot
        FROM jobs
    """
    params: tuple[Any, ...] = ()
    if enabled_only:
        query += " WHERE enabled = 1"
    query += " ORDER BY created_at DESC"

    try:
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()
    except Exception as exc:
        logger.error("job_list_db_error", enabled_only=enabled_only, error=str(exc))
        raise RuntimeError("Database error while listing jobs") from exc

    jobs: list[dict[str, Any]] = []
    for row in rows:
        job = _row_to_job(row)
        try:
            next_run = get_next_run_time(
                cron_expr=str(job["cron_expr"]),
                timezone_name=str(job.get("timezone") or "UTC"),
                last_completed_slot=job.get("last_completed_slot"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "job_next_run_calculation_failed",
                name=job.get("name"),
                timezone=job.get("timezone"),
                error=str(exc),
            )
            next_run = get_next_run_time(
                cron_expr=str(job["cron_expr"]),
                timezone_name="UTC",
                last_completed_slot=job.get("last_completed_slot"),
            )
        job["next_run_local"] = next_run
        jobs.append(job)
    return jobs


async def delete_job(job_id: str) -> bool:
    """Delete scheduler job by ID."""
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        deleted = cursor.rowcount > 0
        await cursor.close()
        await db.commit()
    except Exception as exc:
        logger.error("job_delete_db_error", job_id=job_id, error=str(exc))
        raise RuntimeError(f"Database error while deleting job '{job_id}'") from exc

    return deleted


async def disable_job(job_id: str) -> bool:
    """Disable scheduler job by ID."""
    db = await get_db()
    try:
        cursor = await db.execute("UPDATE jobs SET enabled = 0 WHERE id = ?", (job_id,))
        updated = cursor.rowcount > 0
        await cursor.close()
        await db.commit()
    except Exception as exc:
        logger.error("job_disable_db_error", job_id=job_id, error=str(exc))
        raise RuntimeError(f"Database error while disabling job '{job_id}'") from exc
    return updated


async def enable_job(job_id: str) -> bool:
    """Enable scheduler job by ID."""
    db = await get_db()
    try:
        cursor = await db.execute("UPDATE jobs SET enabled = 1 WHERE id = ?", (job_id,))
        updated = cursor.rowcount > 0
        await cursor.close()
        await db.commit()
    except Exception as exc:
        logger.error("job_enable_db_error", job_id=job_id, error=str(exc))
        raise RuntimeError(f"Database error while enabling job '{job_id}'") from exc
    return updated


async def get_job_by_name(name: str) -> dict[str, Any] | None:
    """Fetch one scheduler job by unique name."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT id, name, cron_expr, timezone, action, action_params, enabled, created_at, last_completed_slot
            FROM jobs
            WHERE name = ?
            LIMIT 1
            """,
            (name,),
        )
        row = await cursor.fetchone()
        await cursor.close()
    except Exception as exc:
        logger.error("job_get_by_name_db_error", name=name, error=str(exc))
        raise RuntimeError(f"Database error while fetching job '{name}'") from exc

    if row is None:
        return None
    return _row_to_job(row)


async def get_job_by_id(job_id: str) -> dict[str, Any] | None:
    """Fetch one scheduler job by UUID."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT id, name, cron_expr, timezone, action, action_params, enabled, created_at, last_completed_slot
            FROM jobs
            WHERE id = ?
            LIMIT 1
            """,
            (job_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
    except Exception as exc:
        logger.error("job_get_by_id_db_error", job_id=job_id, error=str(exc))
        raise RuntimeError(f"Database error while fetching job '{job_id}'") from exc

    if row is None:
        return None
    job = _row_to_job(row)
    try:
        job["next_run_local"] = get_next_run_time(
            cron_expr=str(job["cron_expr"]),
            timezone_name=str(job.get("timezone") or "UTC"),
            last_completed_slot=job.get("last_completed_slot"),
        )
    except Exception:
        job["next_run_local"] = get_next_run_time(
            cron_expr=str(job["cron_expr"]),
            timezone_name="UTC",
            last_completed_slot=job.get("last_completed_slot"),
        )
    return job


async def edit_job(job_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    """Edit scheduler job fields with validation."""
    if "cron_expr" in updates:
        _validate_cron(str(updates["cron_expr"]))
    if "timezone" in updates:
        _validate_timezone(str(updates["timezone"]))
    if "action" in updates:
        _validate_action(str(updates["action"]))

    set_clauses: list[str] = []
    params: list[Any] = []

    if "cron_expr" in updates:
        set_clauses.append("cron_expr = ?")
        params.append(str(updates["cron_expr"]))
    if "timezone" in updates:
        set_clauses.append("timezone = ?")
        params.append(str(updates["timezone"]))
    if "action" in updates:
        set_clauses.append("action = ?")
        params.append(str(updates["action"]))
    if "action_params" in updates:
        set_clauses.append("action_params = ?")
        params.append(json.dumps(updates["action_params"]) if updates["action_params"] is not None else None)

    if not set_clauses:
        return await get_job_by_id(job_id)

    params.append(job_id)
    query = f"UPDATE jobs SET {', '.join(set_clauses)} WHERE id = ?"

    db = await get_db()
    try:
        cursor = await db.execute(query, tuple(params))
        updated = cursor.rowcount > 0
        await cursor.close()
        await db.commit()
    except Exception as exc:
        logger.error("job_edit_db_error", job_id=job_id, error=str(exc))
        raise RuntimeError(f"Database error while editing job '{job_id}'") from exc

    if not updated:
        return None
    return await get_job_by_id(job_id)
