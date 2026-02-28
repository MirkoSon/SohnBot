"""Unit tests for heartbeat report generation."""

from pathlib import Path

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.capabilities.heartbeat import _format_number, _format_uptime, generate_heartbeat_report
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


@pytest.fixture(autouse=True)
def reset_snapshot_cache():
    import src.sohnbot.capabilities.observe as observe_module

    observe_module._snapshot_cache = None
    yield
    observe_module._snapshot_cache = None


def test_format_uptime():
    assert _format_uptime(0) == "0s"
    assert _format_uptime(45) == "45s"
    assert _format_uptime(90) == "1m 30s"
    assert _format_uptime(3661) == "1h 1m 1s"
    assert _format_uptime(86400) == "1d 0h 0m"
    assert _format_uptime(90061) == "1d 1h 1m"


def test_format_number():
    assert _format_number(0) == "0"
    assert _format_number(123) == "123"
    assert _format_number(1234) == "1,234"
    assert _format_number(1234567) == "1,234,567"


@pytest.mark.asyncio
async def test_generate_heartbeat_report_no_operations(setup_database):
    report = await generate_heartbeat_report()
    assert "📊 Daily Heartbeat Report" in report
    assert "No operations recorded" in report
    assert "No jobs executed" in report
    assert "Timestamp:" in report


@pytest.mark.asyncio
async def test_generate_heartbeat_report_with_operations(setup_database):
    for i in range(10):
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
            status="completed" if i < 8 else "failed",
            duration_ms=100,
        )

    for i in range(3):
        operation_id = f"sched-{i}"
        await log_operation_start(
            operation_id=operation_id,
            capability="scheduler",
            action="heartbeat",
            chat_id="scheduler",
            tier=1,
        )
        await log_operation_end(
            operation_id=operation_id,
            status="completed",
            duration_ms=200,
        )

    report = await generate_heartbeat_report()
    assert "Total: 13" in report
    assert "Completed: 11" in report
    assert "Failed: 2" in report
    assert "Executed: 3" in report


@pytest.mark.asyncio
async def test_generate_heartbeat_report_no_snapshot(setup_database):
    report = await generate_heartbeat_report()
    assert "Status snapshot: Not available" in report
    assert "Uptime: Unknown" in report
    assert "Health: Unknown" in report
