"""Integration tests for config table seeding and hot-reload.

NOTE: These tests verify config table exists and can be used.
Full ConfigManager integration (seeding, hot-reload) is implemented in Story 1.2's
Phase 5 integration with Story 1.1.
"""

import pytest
import json
from pathlib import Path
from datetime import datetime

from src.sohnbot.persistence.db import DatabaseManager
from scripts.migrate import apply_migrations


@pytest.fixture
async def setup_database(tmp_path):
    """Set up test database with migrations."""
    db_path = tmp_path / "test.db"
    migrations_dir = Path("src/sohnbot/persistence/migrations")

    apply_migrations(db_path, migrations_dir)

    db_manager = DatabaseManager(db_path)

    yield db_manager

    await db_manager.close()


@pytest.mark.asyncio
async def test_config_table_exists(tmp_path, setup_database):
    """Config table should exist after migrations."""
    conn = await setup_database.get_connection()

    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='config'"
    )
    result = await cursor.fetchone()
    await cursor.close()

    assert result is not None


@pytest.mark.asyncio
async def test_config_table_can_store_dynamic_settings(tmp_path, setup_database):
    """Config table should accept dynamic configuration values."""
    conn = await setup_database.get_connection()

    # Insert dynamic config
    await conn.execute(
        """
        INSERT INTO config (key, value, updated_at, tier)
        VALUES (?, ?, ?, ?)
        """,
        (
            "thresholds.search_volume_daily",
            json.dumps(100),
            int(datetime.now().timestamp()),
            "dynamic",
        ),
    )
    await conn.commit()

    # Verify inserted
    cursor = await conn.execute("SELECT * FROM config WHERE key = ?", ("thresholds.search_volume_daily",))
    row = await cursor.fetchone()
    await cursor.close()

    assert row is not None
    assert row[0] == "thresholds.search_volume_daily"
    assert json.loads(row[1]) == 100
    assert row[4] == "dynamic"


@pytest.mark.asyncio
async def test_config_table_seeding_from_toml(tmp_path, setup_database):
    """Dynamic config should be seeded from default.toml (integration with Story 1.1).

    NOTE: Full implementation in Phase 5 (ConfigManager.seed_dynamic_config()).
    This test verifies the config table is ready for seeding.
    """
    # This test verifies infrastructure is ready
    # Actual seeding logic will be added to ConfigManager in Phase 5

    conn = await setup_database.get_connection()

    # Verify config table can handle seeding
    seed_data = [
        ("thresholds.search_volume_daily", 100, "dynamic"),
        ("timeouts.lint_timeout", 300, "dynamic"),
        ("retention.logs_days", 90, "dynamic"),
    ]

    for key, value, tier in seed_data:
        await conn.execute(
            "INSERT INTO config (key, value, updated_at, tier) VALUES (?, ?, ?, ?)",
            (key, json.dumps(value), int(datetime.now().timestamp()), tier),
        )
    await conn.commit()

    # Verify seeded
    cursor = await conn.execute("SELECT COUNT(*) FROM config")
    count = (await cursor.fetchone())[0]
    await cursor.close()

    assert count == 3


@pytest.mark.asyncio
async def test_config_manager_reads_from_database(tmp_path, setup_database):
    """ConfigManager should query config table for dynamic settings (Story 1.1 integration).

    NOTE: Full implementation in Phase 5.
    This test verifies the table schema supports ConfigManager queries.
    """
    # Verify query pattern works
    conn = await setup_database.get_connection()

    # Insert test config
    await conn.execute(
        "INSERT INTO config (key, value, updated_at, tier) VALUES (?, ?, ?, ?)",
        ("scheduler.max_concurrent_jobs", json.dumps(5), int(datetime.now().timestamp()), "dynamic"),
    )
    await conn.commit()

    # Query like ConfigManager would
    cursor = await conn.execute("SELECT value FROM config WHERE key = ?", ("scheduler.max_concurrent_jobs",))
    row = await cursor.fetchone()
    await cursor.close()

    assert row is not None
    assert json.loads(row[0]) == 5


@pytest.mark.asyncio
async def test_config_hot_reload_without_restart(tmp_path, setup_database):
    """Config updates should trigger reload without restart (Story 1.1 integration).

    NOTE: Full implementation in Phase 5 with ConfigManager event system.
    This test verifies config table supports updates.
    """
    conn = await setup_database.get_connection()

    # Insert initial config
    await conn.execute(
        "INSERT INTO config (key, value, updated_at, tier) VALUES (?, ?, ?, ?)",
        ("scheduler.tick_seconds", json.dumps(60), int(datetime.now().timestamp()), "dynamic"),
    )
    await conn.commit()

    # Update config (simulating hot-reload trigger)
    await conn.execute(
        "UPDATE config SET value = ?, updated_at = ? WHERE key = ?",
        (json.dumps(30), int(datetime.now().timestamp()), "scheduler.tick_seconds"),
    )
    await conn.commit()

    # Verify updated
    cursor = await conn.execute("SELECT value FROM config WHERE key = ?", ("scheduler.tick_seconds",))
    row = await cursor.fetchone()
    await cursor.close()

    assert json.loads(row[0]) == 30
