"""Unit tests for observability dataclasses and in-memory snapshot cache."""

import time

import pytest

from src.sohnbot.capabilities.observe import (
    BrokerActivity,
    HealthCheckResult,
    NotifierState,
    ProcessInfo,
    ResourceUsage,
    SchedulerState,
    StatusSnapshot,
    get_current_snapshot,
    update_snapshot_cache,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_snapshot_cache():
    """Reset the module-level snapshot cache between tests."""
    import src.sohnbot.capabilities.observe as obs_module

    obs_module._snapshot_cache = None
    yield
    obs_module._snapshot_cache = None


def _make_snapshot(ts: int = 1000) -> StatusSnapshot:
    """Build a minimal but valid StatusSnapshot for testing."""
    return StatusSnapshot(
        timestamp=ts,
        process=ProcessInfo(
            pid=1234,
            uptime_seconds=60,
            version="0.1.0",
            supervisor="none",
            supervisor_status=None,
            restart_count=None,
        ),
        broker=BrokerActivity(
            last_operation_timestamp=ts,
            in_flight_operations=[],
            last_10_results={"completed": 5},
        ),
        scheduler=SchedulerState(
            last_tick_timestamp=0,
            last_tick_local="N/A",
            next_jobs=[],
            active_jobs_count=0,
        ),
        notifier=NotifierState(
            last_attempt_timestamp=0,
            pending_count=0,
            oldest_pending_age_seconds=None,
        ),
        resources=ResourceUsage(
            cpu_percent=0.5,
            cpu_1m_avg=None,
            ram_mb=128,
            db_size_mb=0.5,
            log_size_mb=0.1,
            snapshot_count=3,
            event_loop_lag_ms=0.01,
        ),
        health=[
            HealthCheckResult(
                name="sqlite_writable",
                status="pass",
                message="OK",
                timestamp=ts,
                details=None,
            )
        ],
        recent_operations=[],
    )


# ---------------------------------------------------------------------------
# Dataclass construction tests
# ---------------------------------------------------------------------------


def test_process_info_construction():
    pi = ProcessInfo(
        pid=1,
        uptime_seconds=100,
        version="1.0.0",
        supervisor="pm2",
        supervisor_status="online",
        restart_count=2,
    )
    assert pi.pid == 1
    assert pi.uptime_seconds == 100
    assert pi.version == "1.0.0"
    assert pi.supervisor == "pm2"
    assert pi.restart_count == 2


def test_process_info_optional_fields_none():
    pi = ProcessInfo(
        pid=99,
        uptime_seconds=0,
        version="unknown",
        supervisor=None,
        supervisor_status=None,
        restart_count=None,
    )
    assert pi.supervisor is None
    assert pi.supervisor_status is None
    assert pi.restart_count is None


def test_broker_activity_construction():
    ba = BrokerActivity(
        last_operation_timestamp=1234567890,
        in_flight_operations=[{"operation_id": "abc", "tool": "fs__read", "tier": 0, "elapsed_s": 1}],
        last_10_results={"completed": 8, "failed": 2},
    )
    assert ba.last_operation_timestamp == 1234567890
    assert len(ba.in_flight_operations) == 1
    assert ba.last_10_results["completed"] == 8


def test_scheduler_state_placeholder_construction():
    ss = SchedulerState(
        last_tick_timestamp=0,
        last_tick_local="N/A (scheduler not yet implemented)",
        next_jobs=[],
        active_jobs_count=0,
    )
    assert ss.last_tick_timestamp == 0
    assert ss.next_jobs == []
    assert ss.active_jobs_count == 0


def test_notifier_state_construction():
    ns = NotifierState(
        last_attempt_timestamp=999,
        pending_count=3,
        oldest_pending_age_seconds=120,
    )
    assert ns.pending_count == 3
    assert ns.oldest_pending_age_seconds == 120


def test_notifier_state_no_pending():
    ns = NotifierState(
        last_attempt_timestamp=0,
        pending_count=0,
        oldest_pending_age_seconds=None,
    )
    assert ns.oldest_pending_age_seconds is None


def test_resource_usage_construction():
    ru = ResourceUsage(
        cpu_percent=12.5,
        cpu_1m_avg=None,
        ram_mb=256,
        db_size_mb=1.5,
        log_size_mb=0.3,
        snapshot_count=7,
        event_loop_lag_ms=0.5,
    )
    assert ru.cpu_percent == 12.5
    assert ru.ram_mb == 256
    assert ru.snapshot_count == 7


def test_health_check_result_construction():
    hcr = HealthCheckResult(
        name="sqlite_writable",
        status="pass",
        message="OK",
        timestamp=int(time.time()),
        details=None,
    )
    assert hcr.name == "sqlite_writable"
    assert hcr.status == "pass"
    assert hcr.details is None


def test_health_check_result_with_details():
    hcr = HealthCheckResult(
        name="scheduler_lag",
        status="fail",
        message="Lag 400s exceeds threshold 300s",
        timestamp=int(time.time()),
        details={"lag_seconds": 400, "threshold": 300},
    )
    assert hcr.status == "fail"
    assert hcr.details is not None
    assert hcr.details["lag_seconds"] == 400


def test_status_snapshot_construction():
    snap = _make_snapshot(ts=2000)
    assert snap.timestamp == 2000
    assert snap.process.pid == 1234
    assert snap.broker.last_10_results == {"completed": 5}
    assert snap.scheduler.next_jobs == []
    assert snap.notifier.pending_count == 0
    assert snap.resources.ram_mb == 128
    assert len(snap.health) == 1
    assert snap.recent_operations == []


def test_status_snapshot_empty_health():
    """Story 3.1 should produce snapshots with health=[] (Story 3.2 adds checks)."""
    snap = _make_snapshot()
    snap_empty = StatusSnapshot(
        timestamp=snap.timestamp,
        process=snap.process,
        broker=snap.broker,
        scheduler=snap.scheduler,
        notifier=snap.notifier,
        resources=snap.resources,
        health=[],
        recent_operations=[],
    )
    assert snap_empty.health == []


# ---------------------------------------------------------------------------
# In-memory cache tests
# ---------------------------------------------------------------------------


def test_get_current_snapshot_returns_none_initially():
    """Cache must be None before first collection cycle."""
    assert get_current_snapshot() is None


def test_update_snapshot_cache_then_get():
    """update_snapshot_cache sets the cache; get_current_snapshot retrieves it."""
    snap = _make_snapshot(ts=5000)
    update_snapshot_cache(snap)
    result = get_current_snapshot()
    assert result is snap
    assert result.timestamp == 5000


def test_update_snapshot_cache_replaces_old():
    """Second update replaces the first."""
    snap1 = _make_snapshot(ts=1)
    snap2 = _make_snapshot(ts=2)
    update_snapshot_cache(snap1)
    update_snapshot_cache(snap2)
    assert get_current_snapshot().timestamp == 2


def test_cache_stores_reference_not_copy():
    """Cache stores the exact object, not a copy."""
    snap = _make_snapshot()
    update_snapshot_cache(snap)
    assert get_current_snapshot() is snap
