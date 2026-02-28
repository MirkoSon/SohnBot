"""Unit tests for observability snapshot collector."""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.capabilities.observe import (
    BrokerActivity,
    NotifierState,
    ProcessInfo,
    ResourceUsage,
    SchedulerState,
    StatusSnapshot,
    get_current_snapshot,
    update_snapshot_cache,
)
from src.sohnbot.observability.snapshot_collector import (
    collect_broker_activity,
    collect_notifier_state,
    collect_process_info,
    collect_resource_usage,
    collect_scheduler_state,
    collect_snapshot,
    query_recent_operations,
    snapshot_collector_loop,
)
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MIGRATIONS_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "sohnbot"
    / "persistence"
    / "migrations"
)


@pytest.fixture(autouse=True)
def reset_snapshot_cache():
    """Reset module-level snapshot cache between tests."""
    import src.sohnbot.capabilities.observe as obs_module
    import src.sohnbot.observability.snapshot_collector as sc_module

    obs_module._snapshot_cache = None
    sc_module._process = None  # Reset cached psutil handle
    sc_module._persist_warning_logged = False  # Reset warning flag
    yield
    obs_module._snapshot_cache = None
    sc_module._persist_warning_logged = False


@pytest.fixture
async def db_with_tables(tmp_path):
    """Fixture: real SQLite DB with all migrations applied, set as global.

    Resets the global DB manager to None on teardown to prevent cross-test
    interference (other tests rely on RuntimeError when no DB is configured).
    """
    db_path = tmp_path / "test.db"
    apply_migrations(db_path, MIGRATIONS_DIR)
    db_manager = DatabaseManager(db_path)
    set_db_manager(db_manager)
    yield db_manager
    await db_manager.close()
    set_db_manager(None)  # type: ignore[arg-type]  # Reset global to prevent test pollution


async def _seed_operation(db_manager: DatabaseManager, op_id: str, status: str = "completed") -> None:
    """Seed a row in execution_log for testing."""
    db = await db_manager.get_connection()
    await db.execute(
        """
        INSERT INTO execution_log (
            operation_id, timestamp, capability, action, chat_id, tier, status
        ) VALUES (?, strftime('%s','now'), 'fs', 'read', 'chat1', 0, ?)
        """,
        (op_id, status),
    )
    await db.commit()


async def _seed_notification(
    db_manager: DatabaseManager,
    op_id: str,
    status: str = "pending",
    sent_at: int | None = None,
) -> None:
    """Seed a row in notification_outbox for testing.

    Args:
        db_manager: DatabaseManager for the test DB.
        op_id: Unique operation ID for the seeded rows.
        status: Notification status ('pending', 'sent', 'failed').
        sent_at: Optional Unix epoch for sent_at column (simulates attempted send).
    """
    db = await db_manager.get_connection()
    await db.execute(
        """
        INSERT INTO execution_log (
            operation_id, timestamp, capability, action, chat_id, tier, status
        ) VALUES (?, strftime('%s','now'), 'fs', 'read', 'chat1', 0, 'completed')
        """,
        (op_id,),
    )
    await db.execute(
        """
        INSERT INTO notification_outbox (
            operation_id, chat_id, status, message_text, created_at, sent_at
        ) VALUES (?, 'chat1', ?, 'test msg', strftime('%s','now'), ?)
        """,
        (op_id, status, sent_at),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# collect_process_info tests
# ---------------------------------------------------------------------------


def test_collect_process_info_returns_valid_data():
    """ProcessInfo must have a positive PID and non-negative uptime."""
    info = collect_process_info()
    assert isinstance(info, ProcessInfo)
    assert info.pid > 0
    assert info.uptime_seconds >= 0
    assert isinstance(info.version, str)
    assert len(info.version) > 0


def test_collect_process_info_version_not_empty():
    """Version must be non-empty string (may be 'unknown' but never blank)."""
    info = collect_process_info()
    assert info.version.strip() != ""


def test_collect_process_info_supervisor_type():
    """Supervisor field must be a string or None."""
    info = collect_process_info()
    assert info.supervisor is None or isinstance(info.supervisor, str)


# ---------------------------------------------------------------------------
# collect_scheduler_state tests
# ---------------------------------------------------------------------------


def test_collect_scheduler_state_returns_placeholder():
    """Before Epic 4, scheduler must return safe placeholder values."""
    state = collect_scheduler_state()
    assert isinstance(state, SchedulerState)
    assert state.last_tick_timestamp == 0
    assert "not yet implemented" in state.last_tick_local
    assert state.next_jobs == []
    assert state.active_jobs_count == 0


def test_collect_scheduler_state_never_raises():
    """Scheduler state collection must never raise an exception."""
    try:
        collect_scheduler_state()
    except Exception as exc:
        pytest.fail(f"collect_scheduler_state() raised: {exc}")


# ---------------------------------------------------------------------------
# collect_broker_activity tests (with empty DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_broker_activity_empty_db(db_with_tables):
    """Empty execution_log must return zero-valued BrokerActivity."""
    activity = await collect_broker_activity()
    assert isinstance(activity, BrokerActivity)
    assert activity.last_operation_timestamp == 0
    assert activity.in_flight_operations == []
    assert activity.last_10_results == {}


@pytest.mark.asyncio
async def test_collect_broker_activity_with_completed_operations(db_with_tables):
    """Completed operations show up in last_10_results."""
    await _seed_operation(db_with_tables, "op1", "completed")
    await _seed_operation(db_with_tables, "op2", "completed")
    activity = await collect_broker_activity()
    assert activity.last_operation_timestamp > 0
    assert activity.last_10_results.get("completed", 0) == 2


@pytest.mark.asyncio
async def test_collect_broker_activity_in_flight(db_with_tables):
    """In-progress operations appear in in_flight_operations."""
    await _seed_operation(db_with_tables, "op_running", "in_progress")
    activity = await collect_broker_activity()
    assert len(activity.in_flight_operations) == 1
    assert activity.in_flight_operations[0]["tool"] == "fs__read"


@pytest.mark.asyncio
async def test_collect_broker_activity_no_db_returns_defaults():
    """When no DB is configured, returns safe zero-valued defaults."""
    with patch("src.sohnbot.observability.snapshot_collector.get_db", side_effect=RuntimeError("no db")):
        activity = await collect_broker_activity()
    assert isinstance(activity, BrokerActivity)
    assert activity.last_operation_timestamp == 0


# ---------------------------------------------------------------------------
# collect_notifier_state tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_notifier_state_empty_db(db_with_tables):
    """Empty notification_outbox must return zero-valued NotifierState."""
    state = await collect_notifier_state()
    assert isinstance(state, NotifierState)
    assert state.pending_count == 0
    assert state.oldest_pending_age_seconds is None
    assert state.last_attempt_timestamp == 0


@pytest.mark.asyncio
async def test_collect_notifier_state_with_pending(db_with_tables):
    """Pending notification shows up in pending_count."""
    await _seed_notification(db_with_tables, "notif1", "pending")
    state = await collect_notifier_state()
    assert state.pending_count == 1
    assert state.last_attempt_timestamp > 0


@pytest.mark.asyncio
async def test_collect_notifier_state_oldest_age_is_non_negative(db_with_tables):
    """oldest_pending_age_seconds must be >= 0 when there are pending items."""
    await _seed_notification(db_with_tables, "notif2", "pending")
    state = await collect_notifier_state()
    if state.oldest_pending_age_seconds is not None:
        assert state.oldest_pending_age_seconds >= 0


@pytest.mark.asyncio
async def test_collect_notifier_state_last_attempt_uses_sent_at(db_with_tables):
    """last_attempt_timestamp reflects sent_at, not created_at, when available."""
    # Seed a sent notification with a known sent_at in the past
    known_sent_at = 1_700_000_000  # 2023-11-14 — clearly distinct from now
    await _seed_notification(db_with_tables, "notif_sent", status="sent", sent_at=known_sent_at)
    state = await collect_notifier_state()
    # last_attempt_timestamp must reflect the actual send time, not now
    assert state.last_attempt_timestamp == known_sent_at


@pytest.mark.asyncio
async def test_collect_notifier_state_no_db_returns_defaults():
    """When no DB is configured, returns safe zero-valued defaults."""
    with patch("src.sohnbot.observability.snapshot_collector.get_db", side_effect=RuntimeError("no db")):
        state = await collect_notifier_state()
    assert isinstance(state, NotifierState)
    assert state.pending_count == 0


# ---------------------------------------------------------------------------
# collect_resource_usage tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_resource_usage_non_blocking():
    """collect_resource_usage() must complete quickly (non-blocking design)."""
    start = time.perf_counter()
    usage = await collect_resource_usage()
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, f"collect_resource_usage took {elapsed:.2f}s — too slow"
    assert isinstance(usage, ResourceUsage)


@pytest.mark.asyncio
async def test_collect_resource_usage_ram_positive():
    """Process RAM usage must be > 0."""
    usage = await collect_resource_usage()
    assert usage.ram_mb > 0


@pytest.mark.asyncio
async def test_collect_resource_usage_cpu_percent_non_negative():
    """CPU percent must be non-negative."""
    usage = await collect_resource_usage()
    assert usage.cpu_percent >= 0.0


@pytest.mark.asyncio
async def test_collect_resource_usage_db_size_non_negative():
    """DB size must be >= 0 (may be 0 if file not found)."""
    usage = await collect_resource_usage()
    assert usage.db_size_mb >= 0.0


@pytest.mark.asyncio
async def test_collect_resource_usage_snapshot_count_non_negative():
    """Snapshot count must be non-negative."""
    usage = await collect_resource_usage()
    assert usage.snapshot_count >= 0


# ---------------------------------------------------------------------------
# query_recent_operations tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_recent_operations_empty_db(db_with_tables):
    """Empty execution_log must return an empty list."""
    ops = await query_recent_operations(limit=10)
    assert ops == []


@pytest.mark.asyncio
async def test_query_recent_operations_returns_operations(db_with_tables):
    """Seeded operations are returned with expected keys."""
    await _seed_operation(db_with_tables, "op_a", "completed")
    ops = await query_recent_operations(limit=10)
    assert len(ops) == 1
    assert ops[0]["operation_id"] == "op_a"
    assert "status" in ops[0]
    assert "capability" in ops[0]


@pytest.mark.asyncio
async def test_query_recent_operations_respects_limit(db_with_tables):
    """Only up to `limit` operations are returned."""
    for i in range(5):
        await _seed_operation(db_with_tables, f"op_{i}", "completed")
    ops = await query_recent_operations(limit=3)
    assert len(ops) <= 3


# ---------------------------------------------------------------------------
# collect_snapshot integration test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_snapshot_completes_fast(db_with_tables):
    """collect_snapshot() must complete in a reasonable time."""
    start = time.perf_counter()
    snap = await collect_snapshot()
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert isinstance(snap, StatusSnapshot)
    assert snap.timestamp > 0
    # Allow generous margin in CI — strict <100ms is a prod target
    assert elapsed_ms < 5000, f"collect_snapshot took {elapsed_ms:.0f}ms"


@pytest.mark.asyncio
async def test_collect_snapshot_health_populated(db_with_tables):
    """Story 3.2: health checks must be populated in snapshots."""
    snap = await collect_snapshot()
    assert len(snap.health) > 0


@pytest.mark.asyncio
async def test_collect_snapshot_all_fields_present(db_with_tables):
    """All StatusSnapshot fields must be populated."""
    snap = await collect_snapshot()
    assert snap.process is not None
    assert snap.broker is not None
    assert snap.scheduler is not None
    assert snap.notifier is not None
    assert snap.resources is not None
    assert isinstance(snap.recent_operations, list)


# ---------------------------------------------------------------------------
# snapshot cache tests
# ---------------------------------------------------------------------------


def test_snapshot_cache_update_and_get():
    """update_snapshot_cache → get_current_snapshot round-trip."""
    from src.sohnbot.capabilities.observe import (
        BrokerActivity,
        NotifierState,
        ProcessInfo,
        ResourceUsage,
        SchedulerState,
        StatusSnapshot,
    )

    snap = StatusSnapshot(
        timestamp=9999,
        process=ProcessInfo(1, 0, "t", None, None, None),
        broker=BrokerActivity(0, [], {}),
        scheduler=SchedulerState(0, "N/A", [], 0),
        notifier=NotifierState(0, 0, None),
        resources=ResourceUsage(0.0, None, 1, 0.0, 0.0, 0, None),
        health=[],
        recent_operations=[],
    )
    update_snapshot_cache(snap)
    result = get_current_snapshot()
    assert result is snap
    assert result.timestamp == 9999


# ---------------------------------------------------------------------------
# snapshot_collector_loop error isolation test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_collector_loop_catches_errors():
    """Loop must survive errors without propagating exceptions."""
    call_count = 0

    async def failing_collect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("simulated collection failure")
        # Cancel the task on the 3rd call to end the test
        raise asyncio.CancelledError

    with patch(
        "src.sohnbot.observability.snapshot_collector.collect_snapshot",
        side_effect=failing_collect,
    ), patch(
        "src.sohnbot.observability.snapshot_collector.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        with pytest.raises(asyncio.CancelledError):
            await snapshot_collector_loop(interval_seconds=0)

    # Must have been called at least twice (errors don't stop the loop)
    assert call_count >= 2


@pytest.mark.asyncio
async def test_snapshot_collector_loop_updates_cache(db_with_tables):
    """After one successful loop iteration, the cache is populated."""
    # Launch the loop as a real background task with a long sleep interval
    # so it runs exactly once before we cancel it.
    task = asyncio.create_task(snapshot_collector_loop(interval_seconds=999))

    # Poll the cache until populated (up to 10s for slow CI environments)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if get_current_snapshot() is not None:
            break
        await asyncio.sleep(0.05)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    result = get_current_snapshot()
    assert result is not None
    assert isinstance(result, StatusSnapshot)
