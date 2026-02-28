"""Integration tests for heartbeat system."""

from pathlib import Path

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.capabilities.heartbeat import generate_heartbeat_report
from src.sohnbot.capabilities.scheduler import get_job_by_name
from src.sohnbot.main import initialize_heartbeat_job
from src.sohnbot.persistence.audit import log_operation_end, log_operation_start
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
async def test_heartbeat_initialization_idempotent(setup_database):
    await initialize_heartbeat_job()
    job1 = await get_job_by_name("Daily Heartbeat")
    assert job1 is not None
    first_id = job1["id"]

    await initialize_heartbeat_job()
    job2 = await get_job_by_name("Daily Heartbeat")
    assert job2 is not None
    assert job2["id"] == first_id


@pytest.mark.asyncio
async def test_heartbeat_full_flow(setup_database):
    await initialize_heartbeat_job()
    job = await get_job_by_name("Daily Heartbeat")
    assert job is not None
    assert job["action"] == "heartbeat"
    assert job["enabled"] is True

    for i in range(5):
        operation_id = f"op-{i}"
        await log_operation_start(
            operation_id=operation_id,
            capability="fs",
            action="read",
            chat_id="test-chat",
            tier=0,
        )
        await log_operation_end(
            operation_id=operation_id,
            status="completed",
            duration_ms=100,
        )

    report = await generate_heartbeat_report()
    assert "📊 Daily Heartbeat Report" in report
    assert "Total: 5" in report
    assert "Completed: 5" in report
