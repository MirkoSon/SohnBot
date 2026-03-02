"""Unit tests for DatabaseManager write lock and execute_write methods."""

import asyncio
from pathlib import Path

import pytest

from src.sohnbot.persistence.db import DatabaseManager
from scripts.migrate import apply_migrations


@pytest.fixture
async def db_manager(tmp_path):
    """DatabaseManager connected to a fully-migrated temp DB."""
    db_path = tmp_path / "lock-test.db"
    migrations_dir = (
        Path(__file__).parent.parent.parent
        / "src" / "sohnbot" / "persistence" / "migrations"
    )
    apply_migrations(db_path, migrations_dir)
    manager = DatabaseManager(db_path)
    await manager.get_connection()
    yield manager
    await manager.close()


@pytest.mark.asyncio
async def test_db_manager_has_write_lock(tmp_path):
    """DatabaseManager.__init__ creates an asyncio.Lock."""
    manager = DatabaseManager(tmp_path / "test.db")
    assert hasattr(manager, "_write_lock")
    assert isinstance(manager._write_lock, asyncio.Lock)


@pytest.mark.asyncio
async def test_execute_write_inserts_row(db_manager):
    """execute_write inserts a row and returns a cursor with rowcount=1."""
    cursor = await db_manager.execute_write(
        "INSERT INTO config (key, value, updated_at, updated_by, tier) VALUES (?, ?, ?, ?, ?)",
        ("test.key", '"test_value"', 1700000000, "test", "dynamic"),
    )
    assert cursor.rowcount == 1

    conn = await db_manager.get_connection()
    c = await conn.execute("SELECT value FROM config WHERE key = ?", ("test.key",))
    row = await c.fetchone()
    await c.close()
    assert row is not None
    assert row[0] == '"test_value"'


@pytest.mark.asyncio
async def test_execute_write_many_inserts_multiple_rows(db_manager):
    """execute_write_many commits all operations in one atomic transaction."""
    await db_manager.execute_write_many([
        (
            "INSERT INTO config (key, value, updated_at, updated_by, tier) VALUES (?, ?, ?, ?, ?)",
            ("bulk.key1", '"v1"', 1700000001, "test", "dynamic"),
        ),
        (
            "INSERT INTO config (key, value, updated_at, updated_by, tier) VALUES (?, ?, ?, ?, ?)",
            ("bulk.key2", '"v2"', 1700000002, "test", "dynamic"),
        ),
    ])

    conn = await db_manager.get_connection()
    c = await conn.execute(
        "SELECT key FROM config WHERE key LIKE 'bulk.%' ORDER BY key"
    )
    rows = await c.fetchall()
    await c.close()
    assert len(rows) == 2
    assert rows[0][0] == "bulk.key1"
    assert rows[1][0] == "bulk.key2"


@pytest.mark.asyncio
async def test_concurrent_execute_write_no_lock_errors(db_manager):
    """Concurrent execute_write calls via asyncio.gather raise no OperationalError."""
    async def insert_row(idx: int) -> None:
        await db_manager.execute_write(
            "INSERT INTO config (key, value, updated_at, updated_by, tier) VALUES (?, ?, ?, ?, ?)",
            (f"concurrent.key{idx}", f'"{idx}"', 1700000000 + idx, "test", "dynamic"),
        )

    # Fire 10 concurrent writes — the lock must serialize them without errors
    await asyncio.gather(*[insert_row(i) for i in range(10)])

    conn = await db_manager.get_connection()
    c = await conn.execute(
        "SELECT COUNT(*) FROM config WHERE key LIKE 'concurrent.%'"
    )
    count = (await c.fetchone())[0]
    await c.close()
    assert count == 10


@pytest.mark.asyncio
async def test_execute_write_many_rolls_back_on_error(db_manager):
    """execute_write_many rolls back all operations when one fails."""
    with pytest.raises(Exception):
        await db_manager.execute_write_many([
            (
                "INSERT INTO config (key, value, updated_at, updated_by, tier) VALUES (?, ?, ?, ?, ?)",
                ("rollback.key", '"v"', 1700000000, "test", "dynamic"),
            ),
            # This will fail: duplicate primary key
            (
                "INSERT INTO config (key, value, updated_at, updated_by, tier) VALUES (?, ?, ?, ?, ?)",
                ("rollback.key", '"duplicate"', 1700000001, "test", "dynamic"),
            ),
        ])

    conn = await db_manager.get_connection()
    c = await conn.execute(
        "SELECT COUNT(*) FROM config WHERE key = 'rollback.key'"
    )
    count = (await c.fetchone())[0]
    await c.close()
    # Both inserts must be rolled back (atomicity)
    assert count == 0
