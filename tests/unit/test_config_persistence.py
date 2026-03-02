"""Unit tests for dynamic config DB persistence (Task 4 of Story 7.1)."""

import json
from pathlib import Path

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.config.manager import ConfigManager
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager


@pytest.fixture
async def config_db(tmp_path):
    """Set up a DatabaseManager with migrated DB and return (manager, config_manager)."""
    db_path = tmp_path / "config-test.db"
    migrations_dir = (
        Path(__file__).parent.parent.parent
        / "src" / "sohnbot" / "persistence" / "migrations"
    )
    apply_migrations(db_path, migrations_dir)

    manager = DatabaseManager(db_path)
    await manager.get_connection()
    set_db_manager(manager)

    cfg = ConfigManager()
    cfg.load_static_config()
    cfg.load_dynamic_config_defaults()

    yield db_path, manager, cfg

    await manager.close()
    # Reset global manager so other tests aren't affected
    import src.sohnbot.persistence.db as db_mod
    db_mod._db_manager = None


@pytest.mark.asyncio
async def test_persist_stores_value_in_config_table(config_db):
    """_persist_to_database writes JSON-encoded value to config table."""
    db_path, manager, cfg = config_db
    await cfg._persist_to_database("logging.level", "DEBUG")

    conn = await manager.get_connection()
    cursor = await conn.execute(
        "SELECT value, tier FROM config WHERE key = ?", ("logging.level",)
    )
    row = await cursor.fetchone()
    await cursor.close()

    assert row is not None
    assert json.loads(row[0]) == "DEBUG"
    assert row[1] == "dynamic"


@pytest.mark.asyncio
async def test_load_dynamic_config_from_db_overlays_persisted_values(config_db):
    """load_dynamic_config_from_db overlays DB rows onto TOML defaults."""
    db_path, manager, cfg = config_db
    await cfg._persist_to_database("logging.level", "WARNING")

    loaded = await cfg.load_dynamic_config_from_db()

    assert loaded["logging.level"] == "WARNING"


@pytest.mark.asyncio
async def test_load_dynamic_config_ignores_invalid_values(config_db):
    """load_dynamic_config_from_db skips rows that fail validation."""
    db_path, manager, cfg = config_db
    conn = await manager.get_connection()
    # Insert a value that violates the logging.level validator
    await conn.execute(
        "INSERT OR REPLACE INTO config (key, value, updated_at, updated_by, tier) VALUES (?, ?, ?, ?, ?)",
        ("logging.level", '"INVALID_LEVEL"', 1700000000, "test", "dynamic"),
    )
    await conn.commit()

    original_default = cfg.dynamic_config.get("logging.level", "INFO")
    await cfg.load_dynamic_config_from_db()

    # Invalid value should not be applied; config stays at default
    assert cfg.dynamic_config.get("logging.level") == original_default


@pytest.mark.asyncio
async def test_reset_dynamic_config_deletes_from_db(config_db):
    """reset_dynamic_config deletes DB row and restores in-memory to registry default."""
    db_path, manager, cfg = config_db
    await cfg._persist_to_database("logging.level", "DEBUG")
    cfg.dynamic_config["logging.level"] = "DEBUG"

    await cfg.reset_dynamic_config("logging.level")

    conn = await manager.get_connection()
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM config WHERE key = ?", ("logging.level",)
    )
    count = (await cursor.fetchone())[0]
    await cursor.close()

    assert count == 0
    # In-memory value restored to registry default
    assert cfg.dynamic_config["logging.level"] == "INFO"


@pytest.mark.asyncio
async def test_update_dynamic_config_persists_to_db(config_db):
    """update_dynamic_config wires through to _persist_to_database."""
    db_path, manager, cfg = config_db
    await cfg.update_dynamic_config("logging.level", "ERROR")

    conn = await manager.get_connection()
    cursor = await conn.execute(
        "SELECT value FROM config WHERE key = ?", ("logging.level",)
    )
    row = await cursor.fetchone()
    await cursor.close()

    assert row is not None
    assert json.loads(row[0]) == "ERROR"
    assert cfg.dynamic_config["logging.level"] == "ERROR"


@pytest.mark.asyncio
async def test_persist_and_reload_round_trip(config_db):
    """Change a value, persist it, create a fresh ConfigManager, reload from DB → same value."""
    db_path, manager, cfg = config_db
    await cfg.update_dynamic_config("search.cache_retention_days", 14)

    # Simulate restart: fresh ConfigManager with same DB
    cfg2 = ConfigManager()
    cfg2.load_static_config()
    cfg2.load_dynamic_config_defaults()
    await cfg2.load_dynamic_config_from_db()

    assert cfg2.dynamic_config["search.cache_retention_days"] == 14
