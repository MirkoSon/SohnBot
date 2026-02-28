"""Unit tests for observability health checks (Story 3.2)."""

import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.capabilities.observe import NotifierState, ResourceUsage, SchedulerState
from src.sohnbot.config.manager import initialize_config
from src.sohnbot.observability.health_checks import (
    check_disk_usage,
    check_job_timeouts,
    check_notifier_alive,
    check_outbox_stuck,
    check_scheduler_lag,
    check_sqlite_writable,
    run_all_health_checks,
)
from src.sohnbot.observability.snapshot_collector import collect_snapshot
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager

MIGRATIONS_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "sohnbot"
    / "persistence"
    / "migrations"
)


@pytest.fixture
async def db_with_tables(tmp_path):
    db_path = tmp_path / "test.db"
    apply_migrations(db_path, MIGRATIONS_DIR)
    db_manager = DatabaseManager(db_path)
    set_db_manager(db_manager)
    db = await db_manager.get_connection()
    await db.execute("PRAGMA journal_mode=WAL")
    initialize_config()
    yield db_manager
    await db_manager.close()
    set_db_manager(None)  # type: ignore[arg-type]


def _scheduler(ts: int) -> SchedulerState:
    return SchedulerState(
        last_tick_timestamp=ts,
        last_tick_local="N/A (scheduler not yet implemented)" if ts == 0 else "ok",
        next_jobs=[],
        active_jobs_count=0,
    )


def _notifier(last_attempt: int = 0, oldest: int | None = None) -> NotifierState:
    return NotifierState(
        last_attempt_timestamp=last_attempt,
        pending_count=0,
        oldest_pending_age_seconds=oldest,
    )


def _resources(db_mb: float = 1.0, log_mb: float = 1.0) -> ResourceUsage:
    return ResourceUsage(
        cpu_percent=1.0,
        cpu_1m_avg=None,
        ram_mb=100,
        db_size_mb=db_mb,
        log_size_mb=log_mb,
        snapshot_count=0,
        event_loop_lag_ms=None,
    )


@pytest.mark.asyncio
async def test_check_sqlite_writable_pass(db_with_tables):
    db = await db_with_tables.get_connection()
    await db.execute("PRAGMA journal_mode=WAL")
    result = await check_sqlite_writable()
    assert result.name == "sqlite_writable"
    assert result.status == "pass"


@pytest.mark.asyncio
async def test_check_sqlite_writable_fail_on_db_error():
    with patch("src.sohnbot.observability.health_checks.get_db", AsyncMock(side_effect=RuntimeError("db down"))):
        result = await check_sqlite_writable()
    assert result.status == "fail"


@pytest.mark.asyncio
async def test_check_sqlite_writable_warns_if_not_wal(db_with_tables):
    db = await db_with_tables.get_connection()
    await db.execute("PRAGMA journal_mode=DELETE")
    result = await check_sqlite_writable()
    assert result.status == "warn"


def test_check_scheduler_lag_pass_when_not_implemented():
    result = check_scheduler_lag(_scheduler(0))
    assert result.status == "pass"


def test_check_scheduler_lag_pass():
    now = int(time.time())
    with patch("src.sohnbot.observability.health_checks._cfg_int", return_value=300):
        result = check_scheduler_lag(_scheduler(now - 30))
    assert result.status == "pass"


def test_check_scheduler_lag_warn():
    now = int(time.time())
    with patch("src.sohnbot.observability.health_checks._cfg_int", return_value=300):
        result = check_scheduler_lag(_scheduler(now - 200))
    assert result.status == "warn"


def test_check_scheduler_lag_fail():
    now = int(time.time())
    with patch("src.sohnbot.observability.health_checks._cfg_int", return_value=300):
        result = check_scheduler_lag(_scheduler(now - 301))
    assert result.status == "fail"


def test_check_job_timeouts_pass_when_not_implemented():
    result = check_job_timeouts()
    assert result.status == "pass"


def test_check_notifier_alive_pass_fresh_system():
    result = check_notifier_alive(_notifier(0))
    assert result.status == "pass"


def test_check_notifier_alive_pass():
    now = int(time.time())
    with patch("src.sohnbot.observability.health_checks._cfg_int", return_value=120):
        result = check_notifier_alive(_notifier(now - 30))
    assert result.status == "pass"


def test_check_notifier_alive_fail():
    now = int(time.time())
    with patch("src.sohnbot.observability.health_checks._cfg_int", return_value=120):
        result = check_notifier_alive(_notifier(now - 121))
    assert result.status == "fail"


def test_check_outbox_stuck_pass_empty_outbox():
    result = check_outbox_stuck(_notifier(0, None))
    assert result.status == "pass"


def test_check_outbox_stuck_pass_within_threshold():
    with patch("src.sohnbot.observability.health_checks._cfg_int", return_value=3600):
        result = check_outbox_stuck(_notifier(100, 120))
    assert result.status == "pass"


def test_check_outbox_stuck_warn_when_stuck():
    with patch("src.sohnbot.observability.health_checks._cfg_int", return_value=3600):
        result = check_outbox_stuck(_notifier(100, 3601))
    assert result.status == "warn"


def test_check_disk_usage_pass_when_disabled():
    with patch("src.sohnbot.observability.health_checks._cfg_bool", return_value=False):
        result = check_disk_usage(_resources(10, 10))
    assert result.status == "pass"


def test_check_disk_usage_pass_within_cap():
    with patch("src.sohnbot.observability.health_checks._cfg_bool", return_value=True), patch(
        "src.sohnbot.observability.health_checks._cfg_int",
        return_value=1000,
    ):
        result = check_disk_usage(_resources(100, 100))
    assert result.status == "pass"


def test_check_disk_usage_warn_exceeds_cap():
    with patch("src.sohnbot.observability.health_checks._cfg_bool", return_value=True), patch(
        "src.sohnbot.observability.health_checks._cfg_int",
        return_value=1000,
    ):
        result = check_disk_usage(_resources(900, 200))
    assert result.status == "warn"


@pytest.mark.asyncio
async def test_run_all_health_checks_returns_six_results(db_with_tables):
    results = await run_all_health_checks(_scheduler(0), _notifier(0, None), _resources())
    assert len(results) == 6


@pytest.mark.asyncio
async def test_run_all_health_checks_all_pass_fresh_system(db_with_tables):
    results = await run_all_health_checks(_scheduler(0), _notifier(0, None), _resources())
    assert all(r.status == "pass" for r in results)


@pytest.mark.asyncio
async def test_health_check_names_are_correct(db_with_tables):
    results = await run_all_health_checks(_scheduler(0), _notifier(0, None), _resources())
    assert [r.name for r in results] == [
        "sqlite_writable",
        "scheduler_lag",
        "job_timeouts",
        "notifier_alive",
        "outbox_stuck",
        "disk_usage",
    ]


@pytest.mark.asyncio
async def test_health_check_status_values_valid(db_with_tables):
    results = await run_all_health_checks(_scheduler(0), _notifier(0, None), _resources())
    assert all(r.status in {"pass", "fail", "warn"} for r in results)


@pytest.mark.asyncio
async def test_health_check_exception_in_one_does_not_affect_others(db_with_tables):
    with patch(
        "src.sohnbot.observability.health_checks.check_scheduler_lag",
        side_effect=RuntimeError("boom"),
    ):
        results = await run_all_health_checks(_scheduler(0), _notifier(0, None), _resources())
    assert len(results) == 6
    assert any(r.name == "scheduler_lag" and r.status == "fail" for r in results)


@pytest.mark.asyncio
async def test_collect_snapshot_health_not_empty(db_with_tables):
    snapshot = await collect_snapshot()
    assert snapshot.health
    assert len(snapshot.health) == 6
