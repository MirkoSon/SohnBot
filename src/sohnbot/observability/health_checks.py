"""Health checks for observability snapshots."""

from __future__ import annotations

import time

from ..capabilities.observe import HealthCheckResult, NotifierState, ResourceUsage, SchedulerState
from ..config.manager import get_config_manager
from ..persistence.db import get_db


def _now() -> int:
    return int(time.time())


def _cfg_int(key: str, default: int) -> int:
    try:
        return int(get_config_manager().get(key))
    except Exception:
        return default


def _cfg_bool(key: str, default: bool) -> bool:
    try:
        return bool(get_config_manager().get(key))
    except Exception:
        return default


def _failed_result(name: str, message: str, exc: Exception) -> HealthCheckResult:
    return HealthCheckResult(
        name=name,
        status="fail",
        message=f"{message}: {exc}",
        timestamp=_now(),
        details={"error": str(exc)},
    )


async def check_sqlite_writable() -> HealthCheckResult:
    """Verify SQLite is writable and in WAL mode."""
    now = _now()
    try:
        db = await get_db()
        await db.execute("CREATE TEMP TABLE IF NOT EXISTS _health_check_test (id INTEGER)")
        await db.execute("INSERT INTO _health_check_test VALUES (1)")
        await db.execute("DELETE FROM _health_check_test WHERE 1=1")

        cursor = await db.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        await cursor.close()
        journal_mode = str(row[0]) if row else "unknown"

        if journal_mode.lower() != "wal":
            return HealthCheckResult(
                name="sqlite_writable",
                status="warn",
                message=f"SQLite writable but not in WAL mode (current: {journal_mode})",
                timestamp=now,
                details={"journal_mode": journal_mode},
            )
        return HealthCheckResult(
            name="sqlite_writable",
            status="pass",
            message="SQLite writable and WAL enabled",
            timestamp=now,
            details=None,
        )
    except Exception as exc:
        return HealthCheckResult(
            name="sqlite_writable",
            status="fail",
            message=f"SQLite write test failed: {exc}",
            timestamp=now,
            details={"error": str(exc)},
        )


def check_scheduler_lag(scheduler_state: SchedulerState) -> HealthCheckResult:
    """Check if scheduler is running and not lagging behind."""
    now = _now()
    try:
        if scheduler_state.last_tick_timestamp == 0:
            return HealthCheckResult(
                name="scheduler_lag",
                status="pass",
                message="Scheduler not yet implemented (Epic 4 pending)",
                timestamp=now,
                details=None,
            )

        lag_seconds = max(0, now - scheduler_state.last_tick_timestamp)
        threshold = _cfg_int("observability.scheduler_lag_threshold", 300)

        if lag_seconds > threshold:
            return HealthCheckResult(
                name="scheduler_lag",
                status="fail",
                message=f"Scheduler lag {lag_seconds}s exceeds threshold {threshold}s",
                timestamp=now,
                details={"lag_seconds": lag_seconds, "threshold": threshold},
            )
        if lag_seconds > threshold * 0.5:
            return HealthCheckResult(
                name="scheduler_lag",
                status="warn",
                message=f"Scheduler lag {lag_seconds}s approaching threshold {threshold}s",
                timestamp=now,
                details={"lag_seconds": lag_seconds, "threshold": threshold},
            )
        return HealthCheckResult(
            name="scheduler_lag",
            status="pass",
            message=f"Scheduler healthy (lag: {lag_seconds}s)",
            timestamp=now,
            details=None,
        )
    except Exception as exc:
        return HealthCheckResult(
            name="scheduler_lag",
            status="fail",
            message=f"Scheduler lag check failed: {exc}",
            timestamp=now,
            details={"error": str(exc)},
        )


def check_job_timeouts() -> HealthCheckResult:
    """Check if scheduler jobs are exceeding timeout (stub until Epic 4)."""
    now = _now()
    try:
        return HealthCheckResult(
            name="job_timeouts",
            status="pass",
            message="Scheduler not yet implemented (Epic 4 pending)",
            timestamp=now,
            details=None,
        )
    except Exception as exc:
        return HealthCheckResult(
            name="job_timeouts",
            status="fail",
            message=f"Job timeout check failed: {exc}",
            timestamp=now,
            details={"error": str(exc)},
        )


def check_notifier_alive(notifier_state: NotifierState) -> HealthCheckResult:
    """Check if notification worker is making progress."""
    now = _now()
    try:
        if notifier_state.last_attempt_timestamp == 0:
            return HealthCheckResult(
                name="notifier_alive",
                status="pass",
                message="Notifier ready (no notifications sent yet)",
                timestamp=now,
                details=None,
            )

        lag = max(0, now - notifier_state.last_attempt_timestamp)
        threshold = _cfg_int("observability.notifier_lag_threshold", 120)

        if lag > threshold:
            return HealthCheckResult(
                name="notifier_alive",
                status="fail",
                message=f"Notifier last attempt {lag}s ago (threshold: {threshold}s)",
                timestamp=now,
                details={"lag_seconds": lag, "threshold": threshold},
            )
        return HealthCheckResult(
            name="notifier_alive",
            status="pass",
            message=f"Notifier active (last attempt {lag}s ago)",
            timestamp=now,
            details=None,
        )
    except Exception as exc:
        return HealthCheckResult(
            name="notifier_alive",
            status="fail",
            message=f"Notifier check failed: {exc}",
            timestamp=now,
            details={"error": str(exc)},
        )


def check_outbox_stuck(notifier_state: NotifierState) -> HealthCheckResult:
    """Check if notification outbox has stuck pending messages."""
    now = _now()
    try:
        if notifier_state.oldest_pending_age_seconds is None:
            return HealthCheckResult(
                name="outbox_stuck",
                status="pass",
                message="Outbox empty",
                timestamp=now,
                details=None,
            )

        threshold = _cfg_int("observability.outbox_stuck_threshold", 3600)
        age = max(0, notifier_state.oldest_pending_age_seconds)

        if age > threshold:
            return HealthCheckResult(
                name="outbox_stuck",
                status="warn",
                message=f"Oldest pending notification {age}s old (threshold: {threshold}s)",
                timestamp=now,
                details={"oldest_age_seconds": age, "threshold": threshold},
            )
        return HealthCheckResult(
            name="outbox_stuck",
            status="pass",
            message=f"Outbox healthy (oldest pending: {age}s)",
            timestamp=now,
            details=None,
        )
    except Exception as exc:
        return HealthCheckResult(
            name="outbox_stuck",
            status="fail",
            message=f"Outbox check failed: {exc}",
            timestamp=now,
            details={"error": str(exc)},
        )


def check_disk_usage(resources: ResourceUsage) -> HealthCheckResult:
    """Optional disk usage check against configured cap (disabled by default)."""
    now = _now()
    try:
        disk_cap_enabled = _cfg_bool("observability.disk_cap_enabled", False)
        if not disk_cap_enabled:
            return HealthCheckResult(
                name="disk_usage",
                status="pass",
                message="Disk usage check disabled (set observability.disk_cap_enabled=true to enable)",
                timestamp=now,
                details=None,
            )

        total_mb = float(resources.db_size_mb) + float(resources.log_size_mb)
        cap_mb = _cfg_int("observability.disk_cap_mb", 1000)

        if total_mb > cap_mb:
            return HealthCheckResult(
                name="disk_usage",
                status="warn",
                message=f"Disk usage {total_mb:.1f}MB exceeds cap {cap_mb}MB",
                timestamp=now,
                details={"total_mb": round(total_mb, 2), "cap_mb": cap_mb},
            )
        return HealthCheckResult(
            name="disk_usage",
            status="pass",
            message=f"Disk usage {total_mb:.1f}MB within cap {cap_mb}MB",
            timestamp=now,
            details=None,
        )
    except Exception as exc:
        return HealthCheckResult(
            name="disk_usage",
            status="fail",
            message=f"Disk usage check failed: {exc}",
            timestamp=now,
            details={"error": str(exc)},
        )


async def run_all_health_checks(
    scheduler_state: SchedulerState,
    notifier_state: NotifierState,
    resources: ResourceUsage,
) -> list[HealthCheckResult]:
    """Run all health checks and return results in stable order."""
    results: list[HealthCheckResult] = []
    try:
        results.append(await check_sqlite_writable())
    except Exception as exc:
        results.append(_failed_result("sqlite_writable", "SQLite health check failed", exc))

    try:
        results.append(check_scheduler_lag(scheduler_state))
    except Exception as exc:
        results.append(_failed_result("scheduler_lag", "Scheduler lag check failed", exc))

    try:
        results.append(check_job_timeouts())
    except Exception as exc:
        results.append(_failed_result("job_timeouts", "Job timeout check failed", exc))

    try:
        results.append(check_notifier_alive(notifier_state))
    except Exception as exc:
        results.append(_failed_result("notifier_alive", "Notifier check failed", exc))

    try:
        results.append(check_outbox_stuck(notifier_state))
    except Exception as exc:
        results.append(_failed_result("outbox_stuck", "Outbox check failed", exc))

    try:
        results.append(check_disk_usage(resources))
    except Exception as exc:
        results.append(_failed_result("disk_usage", "Disk usage check failed", exc))

    return results
