"""Integration tests for scheduler executor tick behavior."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.capabilities.scheduler.executor import _calculate_current_slot, _execute_single_job, _scheduler_tick
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
async def test_scheduler_tick_executes_due_jobs(setup_database):
    now = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)
    expected_slot = _calculate_current_slot("* * * * *", now)

    job = await create_job("due-job", "* * * * *", "UTC", "heartbeat")

    await _scheduler_tick(now=now, max_concurrent_jobs=3)

    db = await setup_database.get_connection()
    cursor = await db.execute("SELECT last_completed_slot FROM jobs WHERE id = ?", (job["id"],))
    row = await cursor.fetchone()
    await cursor.close()

    assert row[0] == expected_slot


@pytest.mark.asyncio
async def test_scheduler_catch_up_after_downtime(setup_database):
    now = datetime(2026, 3, 5, 10, 0, 0, tzinfo=timezone.utc)
    expected_slot = _calculate_current_slot("0 9 * * *", now)

    job = await create_job("catchup", "0 9 * * *", "UTC", "heartbeat")

    db = await setup_database.get_connection()
    old_slot = int(datetime(2026, 3, 2, 9, 0, 0, tzinfo=timezone.utc).timestamp())
    await db.execute("UPDATE jobs SET last_completed_slot = ? WHERE id = ?", (old_slot, job["id"]))
    await db.commit()

    await _scheduler_tick(now=now, max_concurrent_jobs=3)

    cursor = await db.execute("SELECT last_completed_slot FROM jobs WHERE id = ?", (job["id"],))
    row = await cursor.fetchone()
    await cursor.close()

    assert row[0] == expected_slot


@pytest.mark.asyncio
async def test_scheduler_respects_concurrency_limit(setup_database):
    now = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)

    for idx in range(5):
        await create_job(f"concurrency-{idx}", "* * * * *", "UTC", "heartbeat")

    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def fake_dispatch(_job):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        async with lock:
            active -= 1

    with patch("src.sohnbot.capabilities.scheduler.executor._dispatch_job_action", side_effect=fake_dispatch):
        await _scheduler_tick(now=now, max_concurrent_jobs=3)

    assert max_active <= 3


@pytest.mark.asyncio
async def test_scheduler_logs_execution_to_audit(setup_database):
    now = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)

    await create_job("audit-job", "* * * * *", "UTC", "heartbeat")
    await _scheduler_tick(now=now, max_concurrent_jobs=3)

    db = await setup_database.get_connection()
    cursor = await db.execute(
        """
        SELECT capability, action, chat_id, status
        FROM execution_log
        WHERE capability = 'scheduler' AND action = 'heartbeat'
        ORDER BY timestamp DESC
        LIMIT 1
        """
    )
    row = await cursor.fetchone()
    await cursor.close()

    assert row is not None
    assert row[0] == "scheduler"
    assert row[1] == "heartbeat"
    assert row[2] == "scheduler"
    assert row[3] == "completed"


@pytest.mark.asyncio
async def test_timeout_notification_delivery(setup_database):
    now = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)
    job = await create_job("timeout-notify", "* * * * *", "UTC", "heartbeat")

    class _Config:
        def get(self, key):
            if key == "scheduler.job_timeout_seconds":
                return 5
            if key == "telegram.allowed_chat_ids":
                return [123456]
            return None

    async def timeout_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError

    with (
        patch("src.sohnbot.capabilities.scheduler.executor._utc_now", return_value=now),
        patch("src.sohnbot.capabilities.scheduler.executor.get_config_manager", return_value=_Config()),
        patch("src.sohnbot.capabilities.scheduler.executor.asyncio.wait_for", side_effect=timeout_wait_for),
    ):
        await _execute_single_job({**job, "last_completed_slot": None})
        await asyncio.sleep(0)  # allow fire-and-forget notification task to enqueue

    db = await setup_database.get_connection()
    cursor = await db.execute(
        "SELECT chat_id, message_text FROM notification_outbox ORDER BY created_at DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    await cursor.close()

    assert row is not None
    assert row[0] == "123456"
    assert "Scheduled job timeout" in row[1]
