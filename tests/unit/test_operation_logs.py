"""Unit tests for operation log query and cleanup helpers."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.persistence.operation_logs import (
    cleanup_old_operation_logs,
    query_operation_logs,
)


@pytest.fixture
def logs_db(tmp_path):
    db_path = tmp_path / "logs-test.db"
    migrations_dir = Path(__file__).parent.parent.parent / "src" / "sohnbot" / "persistence" / "migrations"
    apply_migrations(db_path, migrations_dir)
    return db_path


@pytest.mark.asyncio
async def test_query_operation_logs_last_24_hours(logs_db):
    now = int(datetime.now(timezone.utc).timestamp())
    async with aiosqlite.connect(str(logs_db)) as db:
        await db.execute(
            """
            INSERT INTO execution_log (
                operation_id, timestamp, capability, action, chat_id, tier, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("op-1", now - 3600, "fs", "read", "chat-1", 0, "completed"),
        )
        await db.commit()

    rows = await query_operation_logs(str(logs_db), hours=24)
    assert len(rows) == 1
    assert rows[0]["operation_id"] == "op-1"
    assert rows[0]["timestamp_iso"]
    assert rows[0]["correlation_id"] is None


@pytest.mark.asyncio
async def test_query_operation_logs_with_filters(logs_db):
    now = int(datetime.now(timezone.utc).timestamp())
    async with aiosqlite.connect(str(logs_db)) as db:
        await db.execute(
            """
            INSERT INTO execution_log (
                operation_id, timestamp, capability, action, chat_id, tier, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "op-1", now - 3600, "fs", "read", "chat-a", 0, "completed",
                "op-2", now - 1200, "web", "search", "chat-b", 1, "failed",
            ),
        )
        await db.commit()

    rows = await query_operation_logs(
        str(logs_db),
        hours=24,
        capability="web",
        status="failed",
        chat_id="chat-b",
        tier=1,
    )
    assert len(rows) == 1
    assert rows[0]["operation_id"] == "op-2"
    assert rows[0]["capability"] == "web"


@pytest.mark.asyncio
async def test_query_operation_logs_decodes_json_fields(logs_db):
    now = int(datetime.now(timezone.utc).timestamp())
    async with aiosqlite.connect(str(logs_db)) as db:
        await db.execute(
            """
            INSERT INTO execution_log (
                operation_id, timestamp, capability, action, chat_id, tier, status, file_paths, error_details, correlation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "op-err",
                now - 120,
                "fs",
                "apply_patch",
                "chat-1",
                1,
                "failed",
                '["a.txt","b.txt"]',
                '{"message":"boom"}',
                "corr-12345",
            ),
        )
        await db.commit()

    rows = await query_operation_logs(str(logs_db), hours=24)
    assert rows[0]["file_paths"] == ["a.txt", "b.txt"]
    assert rows[0]["error_details"]["message"] == "boom"
    assert rows[0]["correlation_id"] == "corr-12345"


@pytest.mark.asyncio
async def test_query_operation_logs_hours_validation(logs_db):
    with pytest.raises(ValueError, match="hours must be between 1 and 720"):
        await query_operation_logs(str(logs_db), hours=0)


@pytest.mark.asyncio
async def test_cleanup_old_operation_logs(logs_db):
    now = datetime.now(timezone.utc)
    old_ts = int((now - timedelta(days=100)).timestamp())
    recent_ts = int((now - timedelta(days=10)).timestamp())
    async with aiosqlite.connect(str(logs_db)) as db:
        await db.execute(
            """
            INSERT INTO execution_log (
                operation_id, timestamp, capability, action, chat_id, tier, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "old", old_ts, "fs", "read", "chat-1", 0, "completed",
                "new", recent_ts, "fs", "read", "chat-1", 0, "completed",
            ),
        )
        await db.commit()

    deleted = await cleanup_old_operation_logs(str(logs_db), retention_days=90)
    assert deleted == 1

    remaining = await query_operation_logs(str(logs_db), hours=720)
    assert len(remaining) == 1
    assert remaining[0]["operation_id"] == "new"
