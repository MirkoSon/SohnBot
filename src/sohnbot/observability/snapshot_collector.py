"""Background snapshot collector for runtime status.

Runs as an asyncio background task (launched from main.py in a future story),
collecting a full StatusSnapshot every N seconds and storing it in the
module-level in-memory cache defined in capabilities/observe.py.

Design principles:
- Independent failure domain: ALL errors are caught — never crashes the loop
- Non-blocking: CPU-bound / subprocess calls are offloaded via asyncio.to_thread
- Read-only: no side effects on any subsystem
- Performance: full collection must complete in <100ms (NFR-024)
"""

import asyncio
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psutil
import structlog

from ..capabilities.observe import (
    BrokerActivity,
    NotifierState,
    ProcessInfo,
    ResourceUsage,
    SchedulerState,
    StatusSnapshot,
    update_snapshot_cache,
)
from ..persistence.db import get_db

logger = structlog.get_logger(__name__)

# Process handle cached at module level — avoids repeated PID lookups
_process: Optional[psutil.Process] = None


def _get_process() -> psutil.Process:
    """Return a cached psutil.Process handle for this process."""
    global _process
    if _process is None:
        _process = psutil.Process(os.getpid())
    return _process


# ---------------------------------------------------------------------------
# Main background loop
# ---------------------------------------------------------------------------


async def snapshot_collector_loop(interval_seconds: int = 30) -> None:
    """Background task: collect and cache a StatusSnapshot every N seconds.

    Independent failure domain — errors are caught and logged; the loop
    always continues and never propagates exceptions to the caller.

    Args:
        interval_seconds: Collection frequency (default 30, range 5–300).
    """
    logger.info("snapshot_collector_started", interval_seconds=interval_seconds)

    while True:
        try:
            start_ns = time.perf_counter_ns()
            snapshot = await collect_snapshot()
            update_snapshot_cache(snapshot)

            duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            if duration_ms > 100:
                logger.warning(
                    "snapshot_collection_slow",
                    duration_ms=round(duration_ms, 1),
                    threshold_ms=100,
                )
            else:
                logger.debug(
                    "snapshot_collected",
                    duration_ms=round(duration_ms, 1),
                    timestamp=snapshot.timestamp,
                )

            # Optional SQLite persistence (disabled by default)
            await _maybe_persist_snapshot(snapshot)

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "snapshot_collection_failed",
                error=str(exc),
                exc_info=True,
            )

        await asyncio.sleep(interval_seconds)


# ---------------------------------------------------------------------------
# Top-level snapshot assembly
# ---------------------------------------------------------------------------


async def collect_snapshot() -> StatusSnapshot:
    """Assemble a full StatusSnapshot from all subsystems.

    All collection calls are read-only. Async calls that need DB access
    are awaited; blocking calls are wrapped in asyncio.to_thread.

    Returns:
        Fresh StatusSnapshot with current system state.
    """
    timestamp = int(datetime.now(timezone.utc).timestamp())

    process_info = await asyncio.to_thread(collect_process_info)
    broker_activity = await collect_broker_activity()
    scheduler_state = collect_scheduler_state()
    notifier_state = await collect_notifier_state()
    resources = await collect_resource_usage()
    recent_ops = await query_recent_operations(limit=100)

    return StatusSnapshot(
        timestamp=timestamp,
        process=process_info,
        broker=broker_activity,
        scheduler=scheduler_state,
        notifier=notifier_state,
        resources=resources,
        health=[],  # Populated in Story 3.2
        recent_operations=recent_ops,
    )


# ---------------------------------------------------------------------------
# Individual collection functions
# ---------------------------------------------------------------------------


def collect_process_info() -> ProcessInfo:
    """Collect process and supervisor information (synchronous, fast).

    Returns:
        ProcessInfo with pid, uptime, version, and supervisor details.
    """
    proc = _get_process()
    pid = os.getpid()
    uptime_seconds = int(time.time() - proc.create_time())
    version = _get_version()
    supervisor, supervisor_status, restart_count = _detect_supervisor()

    return ProcessInfo(
        pid=pid,
        uptime_seconds=uptime_seconds,
        version=version,
        supervisor=supervisor,
        supervisor_status=supervisor_status,
        restart_count=restart_count,
    )


async def collect_broker_activity() -> BrokerActivity:
    """Query execution_log for recent broker activity (async, read-only).

    Returns:
        BrokerActivity with in-flight operations and recent result summary.
    """
    try:
        db = await get_db()

        # In-flight operations (status = 'in_progress')
        cursor = await db.execute(
            """
            SELECT operation_id, capability, action, tier,
                   (unixepoch() - timestamp) AS elapsed_seconds
            FROM execution_log
            WHERE status = 'in_progress'
            ORDER BY timestamp DESC
            LIMIT 20
            """
        )
        in_flight_rows = await cursor.fetchall()
        await cursor.close()

        in_flight = [
            {
                "operation_id": row[0],
                "tool": f"{row[1]}__{row[2]}",
                "tier": row[3],
                "elapsed_s": row[4],
            }
            for row in in_flight_rows
        ]

        # Last 10 completed operation results grouped by status
        cursor = await db.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM (
                SELECT status FROM execution_log
                WHERE status != 'in_progress'
                ORDER BY timestamp DESC
                LIMIT 10
            )
            GROUP BY status
            """
        )
        result_rows = await cursor.fetchall()
        await cursor.close()
        last_10_results = dict(result_rows)

        # Most recent operation timestamp
        cursor = await db.execute("SELECT MAX(timestamp) FROM execution_log")
        row = await cursor.fetchone()
        await cursor.close()
        last_op_ts = row[0] if row and row[0] is not None else 0

    except Exception as exc:  # noqa: BLE001
        logger.debug("collect_broker_activity_failed", error=str(exc))
        return BrokerActivity(
            last_operation_timestamp=0,
            in_flight_operations=[],
            last_10_results={},
        )

    return BrokerActivity(
        last_operation_timestamp=last_op_ts,
        in_flight_operations=in_flight,
        last_10_results=last_10_results,
    )


def collect_scheduler_state() -> SchedulerState:
    """Return a placeholder SchedulerState (Epic 4 not yet implemented).

    The scheduler (jobs table) does not exist until Epic 4. This stub
    prevents OperationalError from querying a non-existent table.

    Returns:
        SchedulerState with safe placeholder values.
    """
    # TODO: Epic 4 will implement the scheduler; update this to query the
    # jobs table and return real state once the scheduler is implemented.
    return SchedulerState(
        last_tick_timestamp=0,
        last_tick_local="N/A (scheduler not yet implemented)",
        next_jobs=[],
        active_jobs_count=0,
    )


async def collect_notifier_state() -> NotifierState:
    """Query notification_outbox for current notifier state (async, read-only).

    Returns:
        NotifierState with pending count and oldest pending age.
    """
    try:
        db = await get_db()

        cursor = await db.execute(
            "SELECT COUNT(*) FROM notification_outbox WHERE status = 'pending'"
        )
        row = await cursor.fetchone()
        await cursor.close()
        pending_count = row[0] if row else 0

        cursor = await db.execute(
            "SELECT MIN(created_at) FROM notification_outbox WHERE status = 'pending'"
        )
        row = await cursor.fetchone()
        await cursor.close()
        oldest_pending_ts = row[0] if row and row[0] is not None else None

        cursor = await db.execute("SELECT MAX(created_at) FROM notification_outbox")
        row = await cursor.fetchone()
        await cursor.close()
        last_attempt_ts = row[0] if row and row[0] is not None else 0

    except Exception as exc:  # noqa: BLE001
        logger.debug("collect_notifier_state_failed", error=str(exc))
        return NotifierState(
            last_attempt_timestamp=0,
            pending_count=0,
            oldest_pending_age_seconds=None,
        )

    oldest_age: Optional[int] = None
    if oldest_pending_ts is not None:
        oldest_age = max(0, int(time.time()) - oldest_pending_ts)

    return NotifierState(
        last_attempt_timestamp=last_attempt_ts,
        pending_count=pending_count,
        oldest_pending_age_seconds=oldest_age,
    )


async def collect_resource_usage() -> ResourceUsage:
    """Collect process resource metrics (async to avoid blocking event loop).

    cpu_percent uses interval=None (non-blocking; returns 0.0 on very first
    call, then the average since the previous call — perfect for a 30s loop).
    File-system reads and snapshot counting are done in asyncio.to_thread.

    Returns:
        ResourceUsage with CPU, RAM, disk sizes, snapshot count, loop lag.
    """
    proc = _get_process()

    # Non-blocking CPU % (uses delta since last call, 0.0 on first call)
    cpu_pct: float = proc.cpu_percent(interval=None)
    ram_mb: int = int(proc.memory_info().rss) // (1024 * 1024)

    # Disk sizes are blocking (filesystem stat) — run in thread pool
    db_size_mb, log_size_mb, snapshot_count = await asyncio.to_thread(
        _collect_disk_metrics
    )

    # Measure event loop lag
    loop_lag_ms = await _measure_event_loop_lag()

    return ResourceUsage(
        cpu_percent=cpu_pct,
        cpu_1m_avg=None,  # Requires external tracking — deferred
        ram_mb=ram_mb,
        db_size_mb=db_size_mb,
        log_size_mb=log_size_mb,
        snapshot_count=snapshot_count,
        event_loop_lag_ms=loop_lag_ms,
    )


async def query_recent_operations(limit: int = 100) -> list[dict]:
    """Query the last N completed operations from execution_log (async).

    Args:
        limit: Maximum number of operations to return.

    Returns:
        List of operation dicts ordered by timestamp descending.
    """
    try:
        db = await get_db()
        cursor = await db.execute(
            """
            SELECT operation_id, timestamp, capability, action, tier,
                   status, duration_ms, snapshot_ref
            FROM execution_log
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("query_recent_operations_failed", error=str(exc))
        return []

    return [
        {
            "operation_id": row[0],
            "timestamp": row[1],
            "capability": row[2],
            "action": row[3],
            "tier": row[4],
            "status": row[5],
            "duration_ms": row[6],
            "snapshot_ref": row[7],
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _get_version() -> str:
    """Get application version from importlib.metadata or git hash fallback.

    Returns:
        Version string like "0.1.0" or "git:<hash>" or "unknown".
    """
    try:
        import importlib.metadata  # noqa: PLC0415

        return importlib.metadata.version("sohnbot")
    except Exception:  # noqa: BLE001
        pass

    # Fallback: git hash
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return f"git:{result.stdout.decode().strip()}"
    except Exception:  # noqa: BLE001
        pass

    return "unknown"


def _detect_supervisor() -> tuple[Optional[str], Optional[str], Optional[int]]:
    """Detect if running under pm2 or systemd supervision.

    Returns:
        Tuple of (supervisor_name, supervisor_status, restart_count).
        All values are None if no recognized supervisor is detected.
    """
    # Check for pm2 environment variable first (fastest, no subprocess)
    if os.environ.get("PM2_HOME") or os.environ.get("pm_id") is not None:
        name, status, restarts = _get_pm2_info()
        return name, status, restarts

    # Check for pm2 binary
    if shutil.which("pm2"):
        name, status, restarts = _get_pm2_info()
        return name, status, restarts

    # Check for systemd (process parent is systemd or INVOCATION_ID set)
    if os.environ.get("INVOCATION_ID"):
        return "systemd", "active", None

    return "none", None, None


def _get_pm2_info() -> tuple[str, Optional[str], Optional[int]]:
    """Attempt to get pm2 process info via CLI.

    Returns:
        Tuple of ("pm2", status_str_or_None, restart_count_or_None).
    """
    try:
        result = subprocess.run(
            ["pm2", "show", str(os.getpid())],
            capture_output=True,
            timeout=3,
            check=False,
        )
        if result.returncode == 0:
            output = result.stdout.decode("utf-8", errors="replace")
            # Extract status line: "│ status           │ online       │"
            status: Optional[str] = None
            restarts: Optional[int] = None
            for line in output.splitlines():
                if "status" in line.lower() and "online" in line.lower():
                    status = "online"
                if "restarts" in line.lower():
                    parts = line.split("│")
                    for part in parts:
                        stripped = part.strip()
                        if stripped.isdigit():
                            restarts = int(stripped)
                            break
            return "pm2", status, restarts
    except Exception:  # noqa: BLE001
        pass
    return "pm2", None, None


def _collect_disk_metrics() -> tuple[float, float, int]:
    """Collect database size, log directory size, and snapshot count.

    Runs in a thread (blocking filesystem I/O + subprocess).

    Returns:
        Tuple of (db_size_mb, log_size_mb, snapshot_count).
    """
    # Database size
    db_size_mb = 0.0
    try:
        from ..config.manager import get_config_manager  # noqa: PLC0415

        config = get_config_manager()
        db_path = config.get("database.path")
        if db_path and os.path.exists(db_path):
            db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
    except Exception:  # noqa: BLE001
        pass

    # Log directory size
    log_size_mb = 0.0
    try:
        from ..config.manager import get_config_manager  # noqa: PLC0415

        config = get_config_manager()
        log_file_path = config.get("logging.file_path")
        if log_file_path:
            log_dir = Path(log_file_path).parent
            if log_dir.exists():
                log_size_mb = sum(
                    f.stat().st_size for f in log_dir.iterdir() if f.is_file()
                ) / (1024 * 1024)
    except Exception:  # noqa: BLE001
        pass

    # Snapshot count (count git snapshot/* branches in first scope root)
    snapshot_count = 0
    try:
        from ..config.manager import get_config_manager  # noqa: PLC0415

        config = get_config_manager()
        scope_roots = config.get("scope.allowed_roots")
        if scope_roots:
            repo_path = os.path.expanduser(scope_roots[0])
            if os.path.isdir(repo_path):
                result = subprocess.run(
                    ["git", "-C", repo_path, "branch", "--list", "snapshot/*"],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0:
                    output = result.stdout.decode("utf-8", errors="replace").strip()
                    snapshot_count = len([l for l in output.splitlines() if l.strip()])
    except Exception:  # noqa: BLE001
        pass

    return db_size_mb, log_size_mb, snapshot_count


async def _measure_event_loop_lag() -> Optional[float]:
    """Estimate asyncio event loop lag by measuring sleep(0) round-trip.

    asyncio.sleep(0) ideally returns near-instantly; measurable delay
    indicates a busy or lagging event loop.

    Returns:
        Lag in milliseconds rounded to 2 decimal places, or None on error.
    """
    try:
        start = time.perf_counter()
        await asyncio.sleep(0)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return round(elapsed_ms, 2)
    except Exception:  # noqa: BLE001
        return None


async def _maybe_persist_snapshot(snapshot: StatusSnapshot) -> None:
    """Persist snapshot to SQLite if enabled in config (disabled by default).

    Args:
        snapshot: The snapshot to persist.
    """
    try:
        from ..config.manager import get_config_manager  # noqa: PLC0415

        config = get_config_manager()
        if not config.get("observability.persist_snapshots"):
            return
        # Full persistence implementation deferred — placeholder for future use
        logger.debug("snapshot_persistence_skipped", reason="not_yet_implemented")
    except Exception:  # noqa: BLE001
        pass  # Config not initialized in tests — silently skip
