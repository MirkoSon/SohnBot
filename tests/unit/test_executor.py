"""Unit tests for scheduler executor logic."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.capabilities.scheduler.executor import (
    _calculate_current_slot,
    _execute_job_batch,
    _execute_single_job,
)
from src.sohnbot.capabilities.scheduler.job_manager import create_job
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager


@pytest.fixture
async def setup_database(tmp_path):
    db_path = tmp_path / "test.db"
    migrations_dir = Path(__file__).parent.parent.parent / "src" / "sohnbot" / "persistence" / "migrations"
    apply_migrations(db_path, migrations_dir)
    db_manager = DatabaseManager(db_path)
    set_db_manager(db_manager)
    yield db_manager
    await db_manager.close()


@pytest.mark.asyncio
async def test_calculate_current_slot():
    now = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)
    slot = _calculate_current_slot("0 9 * * *", now)
    assert slot == int(now.timestamp())


@pytest.mark.asyncio
async def test_idempotency_check_skips_completed(setup_database):
    fixed_now = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)
    slot = _calculate_current_slot("* * * * *", fixed_now)

    job = await create_job("skip-job", "* * * * *", "UTC", "heartbeat")

    db = await setup_database.get_connection()
    await db.execute("UPDATE jobs SET last_completed_slot = ? WHERE id = ?", (slot, job["id"]))
    await db.commit()

    loaded = {
        **job,
        "last_completed_slot": slot,
    }

    with (
        patch("src.sohnbot.capabilities.scheduler.executor._utc_now", return_value=fixed_now),
        patch("src.sohnbot.capabilities.scheduler.executor._dispatch_job_action", new=AsyncMock()) as mock_dispatch,
    ):
        await _execute_single_job(loaded)

    mock_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_idempotency_check_runs_new_slot(setup_database):
    fixed_now = datetime(2026, 3, 1, 9, 2, 0, tzinfo=timezone.utc)

    job = await create_job("run-job", "* * * * *", "UTC", "heartbeat")
    loaded = {**job, "last_completed_slot": None}

    with (
        patch("src.sohnbot.capabilities.scheduler.executor._utc_now", return_value=fixed_now),
        patch("src.sohnbot.capabilities.scheduler.executor._dispatch_job_action", new=AsyncMock()) as mock_dispatch,
    ):
        await _execute_single_job(loaded)

    mock_dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_catch_up_runs_most_recent_only(setup_database):
    now = datetime(2026, 3, 5, 10, 0, 0, tzinfo=timezone.utc)
    expected_slot = _calculate_current_slot("0 9 * * *", now)

    job = await create_job("catchup-job", "0 9 * * *", "UTC", "heartbeat")

    db = await setup_database.get_connection()
    old_slot = int(datetime(2026, 3, 2, 9, 0, 0, tzinfo=timezone.utc).timestamp())
    await db.execute("UPDATE jobs SET last_completed_slot = ? WHERE id = ?", (old_slot, job["id"]))
    await db.commit()

    with patch("src.sohnbot.capabilities.scheduler.executor._utc_now", return_value=now):
        await _execute_single_job({**job, "last_completed_slot": old_slot})

    cursor = await db.execute("SELECT last_completed_slot FROM jobs WHERE id = ?", (job["id"],))
    row = await cursor.fetchone()
    await cursor.close()

    assert row[0] == expected_slot


@pytest.mark.asyncio
async def test_concurrent_limit():
    jobs = [{"name": f"job-{idx}", "id": str(idx), "action": "heartbeat"} for idx in range(8)]

    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def fake_execute(_job):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        async with lock:
            active -= 1

    with patch("src.sohnbot.capabilities.scheduler.executor._execute_single_job", side_effect=fake_execute):
        await _execute_job_batch(jobs_to_run=jobs, max_concurrent_jobs=3)

    assert max_active <= 3


@pytest.mark.asyncio
async def test_job_execution_updates_last_completed_slot(setup_database):
    fixed_now = datetime(2026, 3, 1, 9, 5, 0, tzinfo=timezone.utc)
    expected_slot = _calculate_current_slot("* * * * *", fixed_now)

    job = await create_job("update-slot", "* * * * *", "UTC", "heartbeat")
    loaded = {**job, "last_completed_slot": None}

    with patch("src.sohnbot.capabilities.scheduler.executor._utc_now", return_value=fixed_now):
        await _execute_single_job(loaded)

    db = await setup_database.get_connection()
    cursor = await db.execute("SELECT last_completed_slot FROM jobs WHERE id = ?", (job["id"],))
    row = await cursor.fetchone()
    await cursor.close()

    assert row[0] == expected_slot


@pytest.mark.asyncio
async def test_job_execution_failure_does_not_update_slot(setup_database):
    fixed_now = datetime(2026, 3, 1, 9, 7, 0, tzinfo=timezone.utc)

    job = await create_job("fail-slot", "* * * * *", "UTC", "heartbeat")
    loaded = {**job, "last_completed_slot": None}

    with (
        patch("src.sohnbot.capabilities.scheduler.executor._utc_now", return_value=fixed_now),
        patch(
            "src.sohnbot.capabilities.scheduler.executor._dispatch_job_action",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
    ):
        await _execute_single_job(loaded)

    db = await setup_database.get_connection()
    cursor = await db.execute("SELECT last_completed_slot FROM jobs WHERE id = ?", (job["id"],))
    row = await cursor.fetchone()
    await cursor.close()

    assert row[0] is None


@pytest.mark.asyncio
async def test_calculate_current_slot_with_dst_spring_forward():
    now = datetime(2024, 3, 10, 3, 1, 0, tzinfo=ZoneInfo("America/New_York"))
    slot = _calculate_current_slot("0 2 * * *", now)
    expected = int(datetime(2024, 3, 10, 7, 0, 0, tzinfo=timezone.utc).timestamp())
    assert slot == expected


@pytest.mark.asyncio
async def test_calculate_current_slot_with_dst_fall_back():
    now = datetime(2024, 11, 3, 1, 30, 0, fold=1, tzinfo=ZoneInfo("America/New_York"))
    slot = _calculate_current_slot("0 1 * * *", now)
    expected = int(datetime(2024, 11, 3, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    assert slot == expected


@pytest.mark.asyncio
async def test_job_execution_during_dst_transition(setup_database):
    fixed_now_utc = datetime(2024, 3, 10, 7, 5, 0, tzinfo=timezone.utc)  # 03:05 local after spring-forward
    expected_slot = int(datetime(2024, 3, 10, 7, 0, 0, tzinfo=timezone.utc).timestamp())

    job = await create_job("dst-job", "0 2 * * *", "America/New_York", "heartbeat")

    with patch("src.sohnbot.capabilities.scheduler.executor._utc_now", return_value=fixed_now_utc):
        await _execute_single_job({**job, "last_completed_slot": None})

    db = await setup_database.get_connection()
    cursor = await db.execute("SELECT last_completed_slot FROM jobs WHERE id = ?", (job["id"],))
    row = await cursor.fetchone()
    await cursor.close()
    assert row[0] == expected_slot


@pytest.mark.asyncio
async def test_job_timeout_enforcement(setup_database):
    fixed_now = datetime(2026, 3, 1, 9, 10, 0, tzinfo=timezone.utc)
    job = await create_job("timeout-job", "* * * * *", "UTC", "heartbeat")

    config = MagicMock()
    config.get.side_effect = lambda key: 30 if key == "scheduler.job_timeout_seconds" else []

    async def timeout_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError

    with (
        patch("src.sohnbot.capabilities.scheduler.executor._utc_now", return_value=fixed_now),
        patch("src.sohnbot.capabilities.scheduler.executor.get_config_manager", return_value=config),
        patch("src.sohnbot.capabilities.scheduler.executor.asyncio.wait_for", side_effect=timeout_wait_for),
        patch("src.sohnbot.capabilities.scheduler.executor._send_timeout_notification"),
    ):
        await _execute_single_job({**job, "last_completed_slot": None})

    db = await setup_database.get_connection()
    cursor = await db.execute(
        "SELECT status, error_details, details FROM execution_log WHERE capability='scheduler' ORDER BY timestamp DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    await cursor.close()

    assert row[0] == "failed"
    assert '"timeout": true' in row[1].lower()
    assert '"timeout": true' in row[2].lower()


@pytest.mark.asyncio
async def test_timeout_updates_last_completed_slot(setup_database):
    fixed_now = datetime(2026, 3, 1, 9, 12, 0, tzinfo=timezone.utc)
    expected_slot = _calculate_current_slot("* * * * *", fixed_now)
    job = await create_job("timeout-slot", "* * * * *", "UTC", "heartbeat")

    config = MagicMock()
    config.get.side_effect = lambda key: 30 if key == "scheduler.job_timeout_seconds" else []

    async def timeout_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError

    with (
        patch("src.sohnbot.capabilities.scheduler.executor._utc_now", return_value=fixed_now),
        patch("src.sohnbot.capabilities.scheduler.executor.get_config_manager", return_value=config),
        patch("src.sohnbot.capabilities.scheduler.executor.asyncio.wait_for", side_effect=timeout_wait_for),
        patch("src.sohnbot.capabilities.scheduler.executor._send_timeout_notification"),
    ):
        await _execute_single_job({**job, "last_completed_slot": None})

    db = await setup_database.get_connection()
    cursor = await db.execute("SELECT last_completed_slot FROM jobs WHERE id = ?", (job["id"],))
    row = await cursor.fetchone()
    await cursor.close()
    assert row[0] == expected_slot


@pytest.mark.asyncio
async def test_timeout_less_than_one_second_clamped_to_one(setup_database):
    fixed_now = datetime(2026, 3, 1, 9, 14, 0, tzinfo=timezone.utc)
    job = await create_job("timeout-clamp", "* * * * *", "UTC", "heartbeat")

    config = MagicMock()
    config.get.side_effect = lambda key: 0 if key == "scheduler.job_timeout_seconds" else []

    async def fake_wait_for(coro, timeout):
        if timeout == 1:
            return await coro
        # Heartbeat action wraps report generation with an inner 10s wait_for.
        if timeout == 10:
            coro.close()
            return "heartbeat-report"
        raise AssertionError(f"Unexpected timeout: {timeout}")

    with (
        patch("src.sohnbot.capabilities.scheduler.executor._utc_now", return_value=fixed_now),
        patch("src.sohnbot.capabilities.scheduler.executor.get_config_manager", return_value=config),
        patch("src.sohnbot.capabilities.scheduler.executor.asyncio.wait_for", side_effect=fake_wait_for),
    ):
        await _execute_single_job({**job, "last_completed_slot": None})
