"""Unit tests for persistence layer (database, migrations, schemas)."""

import pytest
import aiosqlite
import hashlib
from pathlib import Path
from datetime import datetime

from src.sohnbot.persistence.db import DatabaseManager
from scripts.migrate import calculate_checksum, discover_migrations, apply_migrations


# Database Connection Tests

@pytest.mark.asyncio
async def test_get_connection_wal_mode(tmp_path):
    """Verify WAL mode is enabled on database connection."""
    db_path = tmp_path / "test.db"
    db_manager = DatabaseManager(db_path)

    conn = await db_manager.get_connection()

    # Check WAL mode
    cursor = await conn.execute("PRAGMA journal_mode")
    mode = await cursor.fetchone()
    await cursor.close()

    assert mode[0].lower() == "wal", "WAL mode should be enabled"

    await db_manager.close()


@pytest.mark.asyncio
async def test_get_connection_pragmas(tmp_path):
    """Verify all required pragmas are set."""
    db_path = tmp_path / "test.db"
    db_manager = DatabaseManager(db_path)

    conn = await db_manager.get_connection()

    # Check pragmas
    cursor = await conn.execute("PRAGMA foreign_keys")
    assert (await cursor.fetchone())[0] == 1
    await cursor.close()

    cursor = await conn.execute("PRAGMA synchronous")
    assert (await cursor.fetchone())[0] == 1  # NORMAL = 1
    await cursor.close()

    cursor = await conn.execute("PRAGMA busy_timeout")
    assert (await cursor.fetchone())[0] == 5000
    await cursor.close()

    await db_manager.close()


@pytest.mark.asyncio
async def test_connection_pooling(tmp_path):
    """Verify connection is reused (pooling)."""
    db_path = tmp_path / "test.db"
    db_manager = DatabaseManager(db_path)

    conn1 = await db_manager.get_connection()
    conn2 = await db_manager.get_connection()

    assert conn1 is conn2, "Connection should be reused"

    await db_manager.close()


# Migration Runner Tests

def test_calculate_checksum_sha256(tmp_path):
    """Verify SHA-256 checksum is calculated correctly."""
    test_file = tmp_path / "test.sql"
    test_content = "CREATE TABLE test (id INTEGER PRIMARY KEY);"
    test_file.write_text(test_content)

    checksum = calculate_checksum(test_file)

    # Verify it's SHA-256 (64 hex characters)
    assert len(checksum) == 64
    assert all(c in "0123456789abcdef" for c in checksum)

    # Verify deterministic
    checksum2 = calculate_checksum(test_file)
    assert checksum == checksum2


def test_discover_migrations_lexical_order(tmp_path):
    """Verify migrations are discovered in lexical order."""
    # Create migrations in non-lexical order
    (tmp_path / "0003_third.sql").write_text("-- Third")
    (tmp_path / "0001_first.sql").write_text("-- First")
    (tmp_path / "0002_second.sql").write_text("-- Second")

    migrations = discover_migrations(tmp_path)

    assert len(migrations) == 3
    assert migrations[0][0] == "0001_first.sql"
    assert migrations[1][0] == "0002_second.sql"
    assert migrations[2][0] == "0003_third.sql"


def test_apply_migrations_success(tmp_path):
    """Verify migrations are applied successfully."""
    db_path = tmp_path / "test.db"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    # Create test migration
    migration = migrations_dir / "0001_init.sql"
    migration.write_text("CREATE TABLE test (id INTEGER PRIMARY KEY) STRICT;")

    # Apply migrations
    apply_migrations(db_path, migrations_dir)

    # Verify table was created (use sync sqlite3)
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='test'")
    result = cursor.fetchone()
    conn.close()

    assert result is not None


def test_apply_migrations_skip_already_applied(tmp_path):
    """Verify already-applied migrations are skipped (idempotent)."""
    db_path = tmp_path / "test.db"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    migration = migrations_dir / "0001_init.sql"
    migration.write_text("CREATE TABLE test (id INTEGER PRIMARY KEY) STRICT;")

    # Apply migrations twice
    apply_migrations(db_path, migrations_dir)
    apply_migrations(db_path, migrations_dir)  # Should skip

    # Verify only one record in schema_migrations (use sync sqlite3)
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT COUNT(*) FROM schema_migrations")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 1


def test_apply_migrations_tamper_detection(tmp_path):
    """Verify tampering detection for modified migrations."""
    db_path = tmp_path / "test.db"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    migration = migrations_dir / "0001_init.sql"
    migration.write_text("CREATE TABLE test (id INTEGER PRIMARY KEY) STRICT;")

    # Apply migration
    apply_migrations(db_path, migrations_dir)

    # Modify migration (tamper)
    migration.write_text("CREATE TABLE test (id INTEGER, name TEXT);")

    # Attempt to reapply - should raise RuntimeError
    with pytest.raises(RuntimeError, match="tampered"):
        apply_migrations(db_path, migrations_dir)


def test_schema_migrations_table_created(tmp_path):
    """Verify schema_migrations table is created automatically."""
    db_path = tmp_path / "test.db"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    apply_migrations(db_path, migrations_dir)

    # Verify schema_migrations table exists (use sync sqlite3)
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    )
    result = cursor.fetchone()
    conn.close()

    assert result is not None


# Schema Validation Tests (require actual migration)

@pytest.mark.asyncio
async def test_execution_log_table_structure(tmp_path):
    """Verify execution_log table has correct STRICT schema."""
    db_path = tmp_path / "test.db"
    migrations_dir = Path("src/sohnbot/persistence/migrations")

    # Apply real migrations
    apply_migrations(db_path, migrations_dir)

    # Verify table structure
    conn = await aiosqlite.connect(str(db_path))
    cursor = await conn.execute("PRAGMA table_info(execution_log)")
    columns = await cursor.fetchall()
    await cursor.close()
    await conn.close()

    column_names = {col[1] for col in columns}
    expected = {
        "operation_id", "timestamp", "capability", "action", "chat_id",
        "tier", "status", "file_paths", "snapshot_ref", "duration_ms",
        "error_details", "details"
    }
    assert column_names == expected


@pytest.mark.asyncio
async def test_execution_log_check_constraints(tmp_path):
    """Verify CHECK constraints on tier and status."""
    db_path = tmp_path / "test.db"
    migrations_dir = Path("src/sohnbot/persistence/migrations")

    apply_migrations(db_path, migrations_dir)

    conn = await aiosqlite.connect(str(db_path))

    # Test invalid tier
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            "INSERT INTO execution_log (operation_id, timestamp, capability, action, chat_id, tier, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test", 123, "fs", "read", "chat1", 5, "completed")  # Invalid tier
        )

    # Test invalid status
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            "INSERT INTO execution_log (operation_id, timestamp, capability, action, chat_id, tier, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test", 123, "fs", "read", "chat1", 0, "invalid")  # Invalid status
        )

    await conn.close()


@pytest.mark.asyncio
async def test_config_table_structure(tmp_path):
    """Verify config table schema."""
    db_path = tmp_path / "test.db"
    migrations_dir = Path("src/sohnbot/persistence/migrations")

    apply_migrations(db_path, migrations_dir)

    conn = await aiosqlite.connect(str(db_path))
    cursor = await conn.execute("PRAGMA table_info(config)")
    columns = await cursor.fetchall()
    await cursor.close()
    await conn.close()

    column_names = {col[1] for col in columns}
    expected = {"key", "value", "updated_at", "updated_by", "tier"}
    assert column_names == expected


@pytest.mark.asyncio
async def test_strict_table_type_enforcement(tmp_path):
    """Verify STRICT mode enforces type checking."""
    db_path = tmp_path / "test.db"
    migrations_dir = Path("src/sohnbot/persistence/migrations")

    apply_migrations(db_path, migrations_dir)

    conn = await aiosqlite.connect(str(db_path))

    # Attempt to insert wrong type (string for INTEGER field)
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            "INSERT INTO execution_log (operation_id, timestamp, capability, action, chat_id, tier, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test", "not_an_integer", "fs", "read", "chat1", 0, "completed")
        )

    await conn.close()
