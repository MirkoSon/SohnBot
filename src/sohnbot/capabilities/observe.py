"""Observability data models and in-memory snapshot cache.

Provides the StatusSnapshot dataclass hierarchy and a module-level
in-memory cache that the snapshot_collector background task updates
every N seconds. All downstream observability consumers (Telegram
commands, HTTP server) read from this cache.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ProcessInfo:
    """Current process and supervisor information."""

    pid: int
    uptime_seconds: int
    version: str  # From pyproject.toml or git hash
    supervisor: Optional[str]  # "pm2" | "systemd" | "none"
    supervisor_status: Optional[str]  # pm2/systemd status string if available
    restart_count: Optional[int]


@dataclass
class BrokerActivity:
    """Recent broker operation activity summary."""

    last_operation_timestamp: int  # Unix epoch of most recent operation
    in_flight_operations: list[dict]  # [{operation_id, tool, tier, elapsed_s}]
    last_10_results: dict  # {"completed": 8, "failed": 1, "timeout": 1}


@dataclass
class SchedulerState:
    """Current scheduler state (placeholder until Epic 4)."""

    last_tick_timestamp: int  # Unix epoch of last scheduler tick
    last_tick_local: str  # Human-readable local time string
    next_jobs: list[dict]  # [{job_name, next_run_utc, next_run_local}]
    active_jobs_count: int


@dataclass
class NotifierState:
    """Current notification outbox state."""

    last_attempt_timestamp: int  # Unix epoch
    pending_count: int
    oldest_pending_age_seconds: Optional[int]


@dataclass
class ResourceUsage:
    """Current process resource consumption."""

    cpu_percent: float  # Instant CPU %
    cpu_1m_avg: Optional[float]  # 1-min average (None if not tracked)
    ram_mb: int  # RSS in MB
    db_size_mb: float
    log_size_mb: float
    snapshot_count: int  # Total git snapshot branches
    event_loop_lag_ms: Optional[float]  # Estimated event loop lag


@dataclass
class HealthCheckResult:
    """Result of a single health check."""

    name: str  # e.g. "sqlite_writable", "scheduler_lag"
    status: str  # "pass" | "fail" | "warn"
    message: str
    timestamp: int  # Unix epoch
    details: Optional[dict]  # Additional diagnostic context


@dataclass
class StatusSnapshot:
    """Complete runtime status snapshot collected at a point in time."""

    timestamp: int  # UTC epoch when snapshot was created
    process: ProcessInfo
    broker: BrokerActivity
    scheduler: SchedulerState
    notifier: NotifierState
    resources: ResourceUsage
    health: list[HealthCheckResult]  # Health check results from health_checks.py
    recent_operations: list[dict]  # Last 100 operations from execution_log


# ---------------------------------------------------------------------------
# Module-level in-memory snapshot cache
# ---------------------------------------------------------------------------

_snapshot_cache: Optional[StatusSnapshot] = None


def get_current_snapshot() -> Optional[StatusSnapshot]:
    """Return the latest cached snapshot, or None if not yet collected."""
    return _snapshot_cache


def update_snapshot_cache(snapshot: StatusSnapshot) -> None:
    """Update the global in-memory snapshot cache (called by snapshot_collector)."""
    global _snapshot_cache
    _snapshot_cache = snapshot
