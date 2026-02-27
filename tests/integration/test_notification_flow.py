"""Integration tests for structured logging + notification outbox flow."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.broker.router import BrokerRouter
from src.sohnbot.broker.scope_validator import ScopeValidator
from src.sohnbot.gateway.commands import handle_notify_command
from src.sohnbot.gateway.notification_worker import NotificationWorker
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager
from src.sohnbot.persistence.notification import get_pending_notifications


@pytest.fixture
async def setup_database(tmp_path):
    db_path = tmp_path / "test.db"
    migrations_dir = Path(__file__).parent.parent.parent / "src" / "sohnbot" / "persistence" / "migrations"
    apply_migrations(db_path, migrations_dir)
    db_manager = DatabaseManager(db_path)
    set_db_manager(db_manager)
    yield db_manager
    await db_manager.close()


@pytest.fixture
def allowed_root(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    return root


@pytest.mark.asyncio
async def test_operation_creates_execution_log_entry(setup_database, allowed_root):
    (allowed_root / "note.txt").write_text("hello")
    broker = BrokerRouter(ScopeValidator([str(allowed_root)]))
    result = await broker.route_operation("fs", "read", {"path": str(allowed_root / "note.txt")}, "chat1")
    assert result.allowed is True
    db = await setup_database.get_connection()
    cursor = await db.execute("SELECT COUNT(*) FROM execution_log WHERE operation_id = ?", (result.operation_id,))
    count = (await cursor.fetchone())[0]
    await cursor.close()
    assert count == 1


@pytest.mark.asyncio
async def test_operation_enqueues_notification(setup_database, allowed_root):
    (allowed_root / "note.txt").write_text("hello")
    broker = BrokerRouter(ScopeValidator([str(allowed_root)]))
    result = await broker.route_operation("fs", "read", {"path": str(allowed_root / "note.txt")}, "chat1")
    assert result.allowed is True
    pending = await get_pending_notifications()
    assert len(pending) >= 1
    assert any(p["operation_id"] == result.operation_id for p in pending)


@pytest.mark.asyncio
async def test_worker_polls_and_sends_notification(setup_database, allowed_root):
    (allowed_root / "note.txt").write_text("hello")
    broker = BrokerRouter(ScopeValidator([str(allowed_root)]))
    await broker.route_operation("fs", "read", {"path": str(allowed_root / "note.txt")}, "123")
    telegram_client = AsyncMock()
    telegram_client.send_message = AsyncMock(return_value=True)
    worker = NotificationWorker(telegram_client=telegram_client)
    await worker._process_batch()  # noqa: SLF001
    pending = await get_pending_notifications()
    assert pending == []


@pytest.mark.asyncio
async def test_notify_off_blocks_enqueue(setup_database, allowed_root):
    await handle_notify_command("chat1", "/notify off")
    (allowed_root / "note.txt").write_text("hello")
    broker = BrokerRouter(ScopeValidator([str(allowed_root)]))
    result = await broker.route_operation("fs", "read", {"path": str(allowed_root / "note.txt")}, "chat1")
    assert result.allowed is True
    pending = await get_pending_notifications()
    assert pending == []


@pytest.mark.asyncio
async def test_failed_notification_retries_with_backoff(setup_database, allowed_root):
    (allowed_root / "note.txt").write_text("hello")
    broker = BrokerRouter(ScopeValidator([str(allowed_root)]))
    await broker.route_operation("fs", "read", {"path": str(allowed_root / "note.txt")}, "123")
    telegram_client = AsyncMock()
    telegram_client.send_message = AsyncMock(return_value=False)
    worker = NotificationWorker(telegram_client=telegram_client, poll_interval_seconds=5, max_retries=3)
    pending = await get_pending_notifications()
    await worker._process_notification(pending[0])  # noqa: SLF001
    db = await setup_database.get_connection()
    cursor = await db.execute("SELECT status, retry_count FROM notification_outbox LIMIT 1")
    row = await cursor.fetchone()
    await cursor.close()
    assert row[1] >= 1
    # Either failed (exhausted) or pending (requeued) are acceptable retry states.
    assert row[0] in {"failed", "pending"}


@pytest.mark.asyncio
async def test_all_operations_logged(setup_database, allowed_root):
    (allowed_root / "a.txt").write_text("a")
    broker = BrokerRouter(ScopeValidator([str(allowed_root)]))
    await broker.route_operation("fs", "read", {"path": str(allowed_root / "a.txt")}, "chat1")
    await broker.route_operation("fs", "list", {"path": str(allowed_root)}, "chat1")
    await broker.route_operation("git", "status", {}, "chat1")
    db = await setup_database.get_connection()
    cursor = await db.execute("SELECT COUNT(*) FROM execution_log")
    count = (await cursor.fetchone())[0]
    await cursor.close()
    assert count == 3


@pytest.mark.asyncio
async def test_enqueue_failure_does_not_block_operation(setup_database, allowed_root):
    (allowed_root / "note.txt").write_text("hello")
    broker = BrokerRouter(ScopeValidator([str(allowed_root)]))
    with patch("src.sohnbot.broker.router.enqueue_notification", side_effect=RuntimeError("outbox down")):
        result = await broker.route_operation("fs", "read", {"path": str(allowed_root / "note.txt")}, "chat1")
    assert result.allowed is True


@pytest.mark.asyncio
async def test_notification_latency_under_ten_seconds(setup_database, allowed_root):
    (allowed_root / "note.txt").write_text("hello")
    broker = BrokerRouter(ScopeValidator([str(allowed_root)]))
    await broker.route_operation("fs", "read", {"path": str(allowed_root / "note.txt")}, "123")
    telegram_client = AsyncMock()
    telegram_client.send_message = AsyncMock(return_value=True)
    worker = NotificationWorker(telegram_client=telegram_client)
    await worker._process_batch()  # noqa: SLF001
    db = await setup_database.get_connection()
    cursor = await db.execute(
        "SELECT sent_at - created_at FROM notification_outbox ORDER BY id DESC LIMIT 1"
    )
    delta = (await cursor.fetchone())[0]
    await cursor.close()
    assert delta is not None
    assert delta <= 10
