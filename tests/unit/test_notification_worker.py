"""Unit tests for NotificationWorker."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.gateway.notification_worker import NotificationWorker
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager
from src.sohnbot.persistence.notification import (
    enqueue_notification,
    get_pending_notifications,
)


async def _seed_operation(db_manager: DatabaseManager, operation_id: str, chat_id: str = "123") -> None:
    db = await db_manager.get_connection()
    await db.execute(
        """
        INSERT INTO execution_log (
            operation_id, timestamp, capability, action, chat_id, tier, status
        ) VALUES (?, strftime('%s','now'), 'fs', 'read', ?, 0, 'completed')
        """,
        (operation_id, chat_id),
    )
    await db.commit()


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
async def test_worker_process_notification_success(setup_database):
    await _seed_operation(setup_database, "op1")
    await enqueue_notification("op1", "123", "hello")
    telegram_client = AsyncMock()
    telegram_client.send_message = AsyncMock(return_value=True)
    worker = NotificationWorker(telegram_client=telegram_client)
    pending = await get_pending_notifications()
    await worker._process_notification(pending[0])  # noqa: SLF001
    pending_after = await get_pending_notifications()
    assert pending_after == []


@pytest.mark.asyncio
async def test_worker_process_notification_failure_schedules_retry(setup_database):
    await _seed_operation(setup_database, "op1")
    await enqueue_notification("op1", "123", "hello")
    telegram_client = AsyncMock()
    telegram_client.send_message = AsyncMock(return_value=False)
    worker = NotificationWorker(telegram_client=telegram_client, poll_interval_seconds=5, max_retries=3)
    pending = await get_pending_notifications()
    await worker._process_notification(pending[0])  # noqa: SLF001
    # Retry is scheduled in the future, so no pending immediately.
    pending_after = await get_pending_notifications()
    assert pending_after == []


@pytest.mark.asyncio
async def test_worker_process_notification_failure_exhausted(setup_database):
    await _seed_operation(setup_database, "op1")
    notification_id = await enqueue_notification("op1", "123", "hello")
    db = await setup_database.get_connection()
    await db.execute("UPDATE notification_outbox SET retry_count = 2 WHERE id = ?", (notification_id,))
    await db.commit()

    telegram_client = AsyncMock()
    telegram_client.send_message = AsyncMock(return_value=False)
    worker = NotificationWorker(telegram_client=telegram_client, poll_interval_seconds=5, max_retries=3)
    pending = await get_pending_notifications()
    await worker._process_notification(pending[0])  # noqa: SLF001
    cursor = await db.execute("SELECT status, retry_count FROM notification_outbox WHERE id = ?", (notification_id,))
    row = await cursor.fetchone()
    await cursor.close()
    assert row[0] == "failed"
    assert row[1] == 3


@pytest.mark.asyncio
async def test_worker_invalid_chat_id_marks_failed(setup_database):
    await _seed_operation(setup_database, "op1", chat_id="not-an-int")
    notification_id = await enqueue_notification("op1", "not-an-int", "hello")
    telegram_client = AsyncMock()
    telegram_client.send_message = AsyncMock(return_value=True)
    worker = NotificationWorker(telegram_client=telegram_client)
    pending = await get_pending_notifications()
    await worker._process_notification(pending[0])  # noqa: SLF001
    db = await setup_database.get_connection()
    cursor = await db.execute("SELECT status FROM notification_outbox WHERE id = ?", (notification_id,))
    row = await cursor.fetchone()
    await cursor.close()
    assert row[0] == "failed"


@pytest.mark.asyncio
async def test_worker_start_stop_lifecycle():
    telegram_client = AsyncMock()
    telegram_client.send_message = AsyncMock(return_value=True)
    worker = NotificationWorker(telegram_client=telegram_client, poll_interval_seconds=0)
    await worker.start()
    assert worker._task is not None  # noqa: SLF001
    await worker.stop()
    assert worker._task is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_worker_restarts_after_crash():
    telegram_client = AsyncMock()
    worker = NotificationWorker(telegram_client=telegram_client, poll_interval_seconds=0)
    worker._running = True  # noqa: SLF001
    worker._spawn_worker_task = MagicMock()  # noqa: SLF001

    async def _boom():
        raise RuntimeError("boom")

    crashed = asyncio.create_task(_boom())
    with pytest.raises(RuntimeError):
        await crashed

    worker._on_worker_done(crashed)  # noqa: SLF001
    assert worker._restart_task is not None  # noqa: SLF001
    await worker._restart_task  # noqa: SLF001
    worker._spawn_worker_task.assert_called_once()  # noqa: SLF001
