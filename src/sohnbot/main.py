"""Runtime startup orchestration for SohnBot."""

from __future__ import annotations

import asyncio
from datetime import datetime

import structlog

from .capabilities.scheduler import create_job, get_job_by_name
from .config.manager import get_config_manager
from .capabilities.scheduler.executor import scheduler_executor_loop
from .observability.http_server import http_server_loop
from .observability.snapshot_collector import snapshot_collector_loop

logger = structlog.get_logger(__name__)


async def initialize_heartbeat_job() -> None:
    """Create default Daily Heartbeat job if it does not already exist."""
    logger.info("heartbeat_initialization_started")

    try:
        existing = await get_job_by_name("Daily Heartbeat")
        if existing is not None:
            logger.info("heartbeat_job_already_exists", job_id=existing.get("id"))
            return

        config = None
        try:
            config = get_config_manager()
        except Exception:  # noqa: BLE001
            config = None

        heartbeat_cron = "0 18 * * *"
        heartbeat_timezone = "UTC"
        timezone_from_config = False

        if config is not None:
            try:
                heartbeat_cron = str(config.get("heartbeat.cron"))
            except Exception:  # noqa: BLE001
                pass

            try:
                heartbeat_timezone = str(config.get("heartbeat.timezone"))
                timezone_from_config = True
            except Exception:  # noqa: BLE001
                pass

        if not timezone_from_config:
            # Best-effort local timezone fallback when config isn't present.
            local_tz_name = getattr(datetime.now().astimezone().tzinfo, "key", None)
            if isinstance(local_tz_name, str) and local_tz_name:
                heartbeat_timezone = local_tz_name

        job = await create_job(
            name="Daily Heartbeat",
            cron_expr=heartbeat_cron,
            timezone=heartbeat_timezone,
            action="heartbeat",
            action_params=None,
            enabled=True,
        )
        logger.info(
            "heartbeat_job_created",
            job_id=job.get("id"),
            cron=heartbeat_cron,
            timezone=heartbeat_timezone,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("heartbeat_initialization_failed", error=str(exc), exc_info=True)


async def initialize_operation_logs_cleanup_job() -> None:
    """Create default weekly operation logs cleanup job if missing."""
    logger.info("operation_logs_cleanup_initialization_started")
    try:
        existing = await get_job_by_name("Operation Logs Cleanup")
        if existing is not None:
            logger.info("operation_logs_cleanup_job_already_exists", job_id=existing.get("id"))
            return

        job = await create_job(
            name="Operation Logs Cleanup",
            cron_expr="0 3 * * 0",
            timezone="UTC",
            action="cleanup_operation_logs",
            action_params={"retention_days": 90},
            enabled=True,
        )
        logger.info("operation_logs_cleanup_job_created", job_id=job.get("id"))
    except Exception as exc:  # noqa: BLE001
        logger.error("operation_logs_cleanup_initialization_failed", error=str(exc), exc_info=True)


async def run_main() -> None:
    """Run background runtime tasks for SohnBot."""
    config = get_config_manager()
    interval = int(config.get("observability.collection_interval_seconds"))
    scheduler_tick = int(config.get("scheduler.tick_seconds"))

    async with asyncio.TaskGroup() as tg:
        tg.create_task(
            snapshot_collector_loop(interval_seconds=interval),
            name="snapshot-collector",
        )
        tg.create_task(
            scheduler_executor_loop(tick_seconds=scheduler_tick),
            name="scheduler-executor",
        )
        await initialize_heartbeat_job()
        await initialize_operation_logs_cleanup_job()

        http_enabled = bool(config.get("observability.http_enabled"))
        if http_enabled:
            host = str(config.get("observability.http_host"))
            port = int(config.get("observability.http_port"))
            tg.create_task(
                _safe_http_server_loop(host=host, port=port),
                name="http-observability",
            )
            logger.info("http_observability_task_started", host=host, port=port)

        logger.info(
            "runtime_tasks_started",
            snapshot_interval_seconds=interval,
            scheduler_tick_seconds=scheduler_tick,
            http_enabled=http_enabled,
        )


async def _safe_http_server_loop(host: str, port: int) -> None:
    """Run HTTP server loop and surface errors with structured logging."""
    try:
        await http_server_loop(host=host, port=port)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "http_server_task_failed",
            host=host,
            port=port,
            error=str(exc),
            exc_info=True,
        )
