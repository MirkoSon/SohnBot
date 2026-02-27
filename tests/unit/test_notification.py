"""Unit tests for notification outbox persistence operations."""

from pathlib import Path

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager
from src.sohnbot.persistence.notification import (
    enqueue_notification,
    get_notifications_enabled,
    get_pending_notifications,
    mark_notification_failed,
    mark_notification_sent,
    schedule_notification_retry,
    set_notifications_enabled,
)


async def _seed_operation(db_manager: DatabaseManager, operation_id: str, chat_id: str = "chat1") -> None:
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
async def test_enqueue_notification_creates_pending(setup_database):
    await _seed_operation(setup_database, "op1")
    notification_id = await enqueue_notification("op1", "chat1", "hello")
    assert notification_id > 0
    pending = await get_pending_notifications()
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"
    assert pending[0]["message_text"] == "hello"


@pytest.mark.asyncio
async def test_get_pending_notifications_orders_oldest_first(setup_database):
    await _seed_operation(setup_database, "op1")
    await _seed_operation(setup_database, "op2")
    first = await enqueue_notification("op1", "chat1", "first")
    second = await enqueue_notification("op2", "chat1", "second")
    pending = await get_pending_notifications(limit=10)
    assert [p["id"] for p in pending] == [first, second]


@pytest.mark.asyncio
async def test_mark_notification_sent_updates_status(setup_database):
    await _seed_operation(setup_database, "op1")
    notification_id = await enqueue_notification("op1", "chat1", "hello")
    await mark_notification_sent(notification_id)
    pending = await get_pending_notifications()
    assert pending == []


@pytest.mark.asyncio
async def test_mark_notification_failed_increments_retry_count(setup_database):
    await _seed_operation(setup_database, "op1")
    notification_id = await enqueue_notification("op1", "chat1", "hello")
    await mark_notification_failed(notification_id, "fail")
    db = await setup_database.get_connection()
    cursor = await db.execute("SELECT status, retry_count FROM notification_outbox WHERE id = ?", (notification_id,))
    row = await cursor.fetchone()
    await cursor.close()
    assert row[0] == "failed"
    assert row[1] == 1


@pytest.mark.asyncio
async def test_schedule_notification_retry_hides_until_due(setup_database):
    await _seed_operation(setup_database, "op1")
    notification_id = await enqueue_notification("op1", "chat1", "hello")
    await schedule_notification_retry(notification_id, 999)
    pending = await get_pending_notifications()
    assert pending == []


@pytest.mark.asyncio
async def test_notifications_enabled_default_true(setup_database):
    assert await get_notifications_enabled("chat1") is True


@pytest.mark.asyncio
async def test_set_notifications_enabled_false(setup_database):
    await set_notifications_enabled("chat1", False)
    assert await get_notifications_enabled("chat1") is False


@pytest.mark.asyncio
async def test_set_notifications_enabled_true(setup_database):
    await set_notifications_enabled("chat1", False)
    await set_notifications_enabled("chat1", True)
    assert await get_notifications_enabled("chat1") is True


@pytest.mark.asyncio
async def test_get_pending_notifications_limit(setup_database):
    await _seed_operation(setup_database, "op1")
    await _seed_operation(setup_database, "op2")
    await _seed_operation(setup_database, "op3")
    await enqueue_notification("op1", "chat1", "one")
    await enqueue_notification("op2", "chat1", "two")
    await enqueue_notification("op3", "chat1", "three")
    pending = await get_pending_notifications(limit=2)
    assert len(pending) == 2
