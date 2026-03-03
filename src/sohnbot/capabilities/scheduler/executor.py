"""Scheduler executor loop with idempotent catch-up execution."""

from __future__ import annotations

import asyncio
import json
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from croniter import croniter

from ...config.manager import get_config_manager
from ...persistence.audit import log_operation_end, log_operation_start
from ...persistence.db import get_db
from ...persistence.notification import enqueue_notification
from .job_manager import list_jobs
from .timezone_handler import handle_dst_transition

logger = structlog.get_logger(__name__)
_background_tasks: set[asyncio.Task[Any]] = set()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _seconds_until_next_minute(now: datetime | None = None) -> float:
    """Return seconds until next :00 boundary."""
    moment = now or _utc_now()
    return max(0.0, 60.0 - (moment.second + (moment.microsecond / 1_000_000)))


def _seconds_until_next_tick(tick_seconds: int, now: datetime | None = None) -> float:
    moment = now or _utc_now()
    now_ts = moment.timestamp()
    aligned = ((int(now_ts) // tick_seconds) + 1) * tick_seconds
    return max(0.0, aligned - now_ts)


def _calculate_current_slot(cron_expr: str, now: datetime) -> int:
    """Return Unix epoch for current/previous cron slot relative to `now`."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if croniter.match(cron_expr, now):
        slot_dt = now.replace(microsecond=0)
    else:
        slot_dt = croniter(cron_expr, now).get_prev(datetime)
        if slot_dt.tzinfo is None:
            slot_dt = slot_dt.replace(tzinfo=now.tzinfo)

    adjusted = handle_dst_transition(slot_dt, getattr(slot_dt.tzinfo, "key", "UTC"))
    if adjusted != slot_dt:
        logger.info(
            "dst_transition_detected",
            cron_expr=cron_expr,
            original=str(slot_dt),
            adjusted=str(adjusted),
        )
    slot_dt = adjusted

    return int(slot_dt.astimezone(timezone.utc).timestamp())


async def scheduler_executor_loop(tick_seconds: int = 60) -> None:
    """Run scheduler evaluation forever with independent failure domain."""
    logger.info("scheduler_executor_started", tick_seconds=tick_seconds)

    while True:
        try:
            await _scheduler_tick()
        except Exception as exc:  # noqa: BLE001
            logger.error("scheduler_tick_failed", error=str(exc), exc_info=True)

        sleep_seconds = (
            _seconds_until_next_minute()
            if tick_seconds == 60
            else _seconds_until_next_tick(max(1, int(tick_seconds)))
        )
        await asyncio.sleep(sleep_seconds)


async def _scheduler_tick(now: datetime | None = None, max_concurrent_jobs: int | None = None) -> None:
    """Execute one scheduler evaluation tick."""
    current = now or _utc_now()
    jobs = await list_jobs(enabled_only=True)

    due_jobs: list[dict[str, Any]] = []
    for job in jobs:
        job_tz_name = str(job.get("timezone") or "UTC")
        try:
            job_tz_now = current.astimezone(ZoneInfo(job_tz_name))
        except Exception:  # noqa: BLE001
            operation_id = str(uuid.uuid4())
            logger.error(
                "scheduler_invalid_timezone",
                timezone=job_tz_name,
                job_name=job.get("name"),
            )
            await log_operation_start(
                operation_id=operation_id,
                capability="scheduler",
                action=str(job.get("action") or "unknown"),
                chat_id="scheduler",
                tier=1,
            )
            await log_operation_end(
                operation_id=operation_id,
                status="failed",
                duration_ms=0,
                error_details={
                    "message": f"Invalid timezone: {job_tz_name}",
                    "job_name": job.get("name"),
                    "timezone": job_tz_name,
                },
            )
            try:
                await enqueue_notification(
                    operation_id=operation_id,
                    chat_id="scheduler",
                    message_text=f"Job [{job.get('name')}] skipped: invalid timezone [{job_tz_name}]",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "scheduler_invalid_timezone_notification_failed",
                    job_name=job.get("name"),
                    timezone=job_tz_name,
                    error=str(exc),
                )
            continue
        current_slot = _calculate_current_slot(str(job["cron_expr"]), job_tz_now)
        last_completed = int(job["last_completed_slot"] or 0)
        if current_slot > last_completed:
            due_jobs.append({**job, "_slot_timestamp": current_slot})

    if not due_jobs:
        return

    limit = max_concurrent_jobs
    if limit is None:
        try:
            limit = int(get_config_manager().get("scheduler.max_concurrent_jobs"))
        except Exception:  # noqa: BLE001
            limit = 3

    await _execute_job_batch(due_jobs, max_concurrent_jobs=max(1, int(limit)))


async def _execute_job_batch(jobs_to_run: list[dict[str, Any]], max_concurrent_jobs: int = 3) -> None:
    """Execute due jobs with bounded concurrency."""
    if len(jobs_to_run) > max_concurrent_jobs:
        logger.warning(
            "scheduler_concurrency_pressure",
            due_jobs=len(jobs_to_run),
            max_concurrent_jobs=max_concurrent_jobs,
        )

    semaphore = asyncio.Semaphore(max_concurrent_jobs)

    async def _run_with_limit(job: dict[str, Any]) -> None:
        async with semaphore:
            await _execute_single_job(job)

    async with asyncio.TaskGroup() as tg:
        for job in jobs_to_run:
            tg.create_task(_run_with_limit(job), name=str(job.get("name", "scheduler-job")))


async def _get_last_completed_slot(job_id: str) -> int | None:
    db = await get_db()
    cursor = await db.execute("SELECT last_completed_slot FROM jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None or row[0] is None:
        return None
    return int(row[0])


async def _update_last_completed_slot(job_id: str, slot_timestamp: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE jobs SET last_completed_slot = ? WHERE id = ?",
        (slot_timestamp, job_id),
    )
    await db.commit()


async def _update_execution_log_details(operation_id: str, details: dict[str, Any]) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE execution_log SET details = ? WHERE operation_id = ?",
        (json.dumps(details), operation_id),
    )
    await db.commit()


def _get_job_timeout_seconds() -> int:
    try:
        timeout_seconds = int(get_config_manager().get("scheduler.job_timeout_seconds"))
    except Exception:  # noqa: BLE001
        timeout_seconds = 600
    return max(1, timeout_seconds)


def _resolve_timeout_notification_chat_id() -> str | None:
    try:
        allowed_chat_ids = get_config_manager().get("telegram.allowed_chat_ids")
        if isinstance(allowed_chat_ids, list) and allowed_chat_ids:
            return str(allowed_chat_ids[0])
    except Exception:  # noqa: BLE001
        pass
    return None


async def _enqueue_timeout_notification(
    *,
    job: dict[str, Any],
    timeout_seconds: int,
    duration_ms: int,
    slot_timestamp: int,
    operation_id: str,
) -> None:
    chat_id = _resolve_timeout_notification_chat_id()
    if not chat_id:
        logger.warning("scheduler_timeout_notification_skipped_no_admin_chat", job_name=job.get("name"))
        return

    message = (
        f"⚠️ Scheduled job timeout: [{job.get('name', 'unknown')}] exceeded {timeout_seconds}s limit\n"
        f"action={job.get('action', 'unknown')} slot={slot_timestamp} elapsed_ms={duration_ms}"
    )
    await enqueue_notification(
        operation_id=operation_id,
        chat_id=chat_id,
        message_text=message,
    )
    logger.info(
        "scheduler_timeout_notification_sent",
        job_name=job.get("name"),
        chat_id=chat_id,
        timeout_seconds=timeout_seconds,
    )


def _send_timeout_notification(
    *,
    job: dict[str, Any],
    timeout_seconds: int,
    duration_ms: int,
    slot_timestamp: int,
    operation_id: str,
) -> None:
    """Send timeout notifications without blocking scheduler execution flow."""
    async def _runner() -> None:
        try:
            await _enqueue_timeout_notification(
                job=job,
                timeout_seconds=timeout_seconds,
                duration_ms=duration_ms,
                slot_timestamp=slot_timestamp,
                operation_id=operation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "notification_delivery_failed",
                job_name=job.get("name"),
                error=str(exc),
            )

    task = asyncio.create_task(_runner(), name=f"scheduler-timeout-notify-{job.get('name', 'unknown')}")
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _execute_single_job(job: dict[str, Any]) -> None:
    """Execute one job with idempotency guard and audit logging."""
    operation_id = str(uuid.uuid4())
    started = time.perf_counter()
    timeout_seconds = _get_job_timeout_seconds()

    job_tz_name = str(job.get("timezone") or "UTC")
    try:
        job_now = _utc_now().astimezone(ZoneInfo(job_tz_name))
    except (KeyError, Exception) as exc:
        logger.error(
            "scheduler_job_timezone_failed",
            timezone=job_tz_name,
            job_name=job.get("name"),
            error=str(exc),
        )
        await log_operation_end(
            operation_id=operation_id,
            status="failed",
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_details={"message": f"Invalid timezone in execution: {job_tz_name}"},
        )
        return
    slot_timestamp = int(job.get("_slot_timestamp") or _calculate_current_slot(str(job["cron_expr"]), job_now))

    await log_operation_start(
        operation_id=operation_id,
        capability="scheduler",
        action=str(job["action"]),
        chat_id="scheduler",
        tier=1,
    )

    try:
        latest_last_completed = await _get_last_completed_slot(str(job["id"]))
        if latest_last_completed is not None and slot_timestamp <= int(latest_last_completed):
            duration_ms = int((time.perf_counter() - started) * 1000)
            await log_operation_end(
                operation_id=operation_id,
                status="completed",
                duration_ms=duration_ms,
            )
            await _update_execution_log_details(
                operation_id,
                {
                    "job_id": job["id"],
                    "job_name": job["name"],
                    "slot_timestamp": slot_timestamp,
                    "skipped": True,
                    "reason": "already_completed",
                },
            )
            logger.info("scheduler_job_skipped_duplicate", job_name=job["name"], slot_timestamp=slot_timestamp)
            return

        try:
            await asyncio.wait_for(
                _dispatch_job_action(job, operation_id=operation_id),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            duration_ms = int((time.perf_counter() - started) * 1000)
            await _update_last_completed_slot(str(job["id"]), slot_timestamp)
            await log_operation_end(
                operation_id=operation_id,
                status="failed",
                duration_ms=duration_ms,
                error_details={
                    "timeout": True,
                    "timeout_seconds": timeout_seconds,
                    "job_name": job.get("name"),
                    "slot_timestamp": slot_timestamp,
                    "elapsed_ms": duration_ms,
                },
            )
            await _update_execution_log_details(
                operation_id,
                {
                    "job_id": job.get("id"),
                    "job_name": job.get("name"),
                    "slot_timestamp": slot_timestamp,
                    "skipped": False,
                    "timeout": True,
                    "timeout_seconds": timeout_seconds,
                },
            )
            logger.error(
                "scheduler_job_timeout",
                job_name=job.get("name"),
                timeout_seconds=timeout_seconds,
                elapsed_ms=duration_ms,
                slot_timestamp=slot_timestamp,
            )
            _send_timeout_notification(
                job=job,
                timeout_seconds=timeout_seconds,
                duration_ms=duration_ms,
                slot_timestamp=slot_timestamp,
                operation_id=operation_id,
            )
            return

        await _update_last_completed_slot(str(job["id"]), slot_timestamp)

        duration_ms = int((time.perf_counter() - started) * 1000)
        await log_operation_end(
            operation_id=operation_id,
            status="completed",
            duration_ms=duration_ms,
        )
        await _update_execution_log_details(
            operation_id,
            {
                "job_id": job["id"],
                "job_name": job["name"],
                "slot_timestamp": slot_timestamp,
                "skipped": False,
            },
        )
        logger.info("scheduler_job_completed", job_name=job["name"], slot_timestamp=slot_timestamp)

    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.perf_counter() - started) * 1000)
        await log_operation_end(
            operation_id=operation_id,
            status="failed",
            duration_ms=duration_ms,
            error_details={
                "message": str(exc),
                "traceback": traceback.format_exc(),
                "job_name": job.get("name"),
                "slot_timestamp": slot_timestamp,
            },
        )
        await _update_execution_log_details(
            operation_id,
            {
                "job_id": job.get("id"),
                "job_name": job.get("name"),
                "slot_timestamp": slot_timestamp,
                "skipped": False,
            },
        )
        logger.error(
            "scheduler_job_failed",
            job_name=job.get("name"),
            slot_timestamp=slot_timestamp,
            error=str(exc),
            exc_info=True,
        )


async def _dispatch_job_action(job: dict[str, Any], operation_id: str) -> None:
    """Dispatch scheduler action type for one job execution."""
    action = str(job["action"])
    params = job.get("action_params") or {}
    context = {
        "job_name": job.get("name"),
        "scheduled_slot": job.get("_slot_timestamp"),
        "executed_at": int(_utc_now().timestamp()),
    }

    logger.info("scheduler_job_start", job_name=job.get("name"), action=action, context=context)

    if action == "agent_query":
        prompt = params.get("prompt")
        if not prompt:
            raise ValueError("agent_query action requires action_params.prompt")
        logger.info("scheduler_agent_query_stub", job_name=job.get("name"), prompt=prompt)
        return

    if action == "profile_execute":
        profile = params.get("profile")
        if not profile:
            raise ValueError("profile_execute action requires action_params.profile")
        logger.info("scheduler_profile_execute_stub", job_name=job.get("name"), profile=profile)
        return

    if action == "heartbeat":
        from ...capabilities.heartbeat import generate_heartbeat_report

        report = await asyncio.wait_for(generate_heartbeat_report(), timeout=10)

        admin_chat_id: str | None = None
        try:
            configured_chat_id = get_config_manager().get("telegram.admin_chat_id")
            if configured_chat_id is not None and str(configured_chat_id).strip():
                admin_chat_id = str(configured_chat_id)
        except Exception:  # noqa: BLE001
            admin_chat_id = None

        if not admin_chat_id:
            admin_chat_id = _resolve_timeout_notification_chat_id()

        if not admin_chat_id:
            logger.warning("heartbeat_no_admin_chat_configured", job_name=job.get("name"))
            return

        await enqueue_notification(
            operation_id=operation_id,
            chat_id=admin_chat_id,
            message_text=report,
        )
        logger.info("heartbeat_report_enqueued", job_name=job.get("name"), admin_chat_id=admin_chat_id)
        return

    if action == "cleanup_operation_logs":
        from ...persistence.operation_logs import cleanup_old_operation_logs

        retention_days = params.get("retention_days", 90)
        try:
            retention_days = int(retention_days)
        except (TypeError, ValueError):
            retention_days = 90

        db_path = "data/sohnbot.db"
        try:
            db_path = str(get_config_manager().get("database.path"))
        except Exception:  # noqa: BLE001
            db_path = "data/sohnbot.db"

        deleted = await cleanup_old_operation_logs(db_path=db_path, retention_days=retention_days)
        logger.info(
            "operation_logs_cleanup_job_completed",
            job_name=job.get("name"),
            deleted=deleted,
            retention_days=retention_days,
        )
        return

    raise ValueError(f"Unsupported scheduler action: {action}")
