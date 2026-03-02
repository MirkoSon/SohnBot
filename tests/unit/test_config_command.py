"""Unit tests for /config Telegram command handling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.config.manager import get_config_manager, initialize_config
from src.sohnbot.gateway.commands import handle_config_command
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager


@pytest.fixture
async def setup_config_runtime(tmp_path):
    """Provision migrated test DB and initialized global config manager."""
    db_path = tmp_path / "config-command-test.db"
    migrations_dir = (
        Path(__file__).parent.parent.parent
        / "src"
        / "sohnbot"
        / "persistence"
        / "migrations"
    )
    apply_migrations(db_path, migrations_dir)

    manager = DatabaseManager(db_path)
    await manager.get_connection()
    set_db_manager(manager)
    initialize_config()

    yield db_path, manager

    await manager.close()

    import src.sohnbot.persistence.db as db_mod
    import src.sohnbot.config.manager as cfg_mod

    db_mod._db_manager = None
    cfg_mod._config_manager = None


@pytest.mark.asyncio
async def test_config_show_returns_grouped_output_with_keys(setup_config_runtime):
    response = await handle_config_command("123", "/config show")

    assert "Dynamic Keys:" in response
    assert "Static Keys:" in response
    assert "scheduler.tick_seconds" in response
    assert "database.path" in response
    assert "[dynamic]" in response
    assert "[static, restart required]" in response


@pytest.mark.asyncio
async def test_config_set_updates_dynamic_config_and_persists(setup_config_runtime):
    _, manager = setup_config_runtime
    response = await handle_config_command("123", "/config set scheduler.tick_seconds=120")

    assert response == "Updated scheduler.tick_seconds = 120"
    assert get_config_manager().get("scheduler.tick_seconds") == 120

    conn = await manager.get_connection()
    cursor = await conn.execute(
        "SELECT value FROM config WHERE key = ?", ("scheduler.tick_seconds",)
    )
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    assert json.loads(row[0]) == 120


@pytest.mark.asyncio
async def test_config_set_static_key_returns_restart_required(setup_config_runtime):
    response = await handle_config_command("123", "/config set database.path=data/new.db")

    assert (
        response
        == "Key database.path is static — update config/default.toml and restart"
    )


@pytest.mark.asyncio
async def test_config_set_invalid_key_returns_error(setup_config_runtime):
    response = await handle_config_command("123", "/config set unknown.key=123")

    assert "not found in registry" in response


@pytest.mark.asyncio
async def test_config_set_out_of_bounds_returns_validation_error(setup_config_runtime):
    response = await handle_config_command("123", "/config set scheduler.tick_seconds=5")

    assert "below minimum" in response


@pytest.mark.asyncio
async def test_config_reset_restores_default_and_removes_persisted_value(setup_config_runtime):
    _, manager = setup_config_runtime
    await handle_config_command("123", "/config set scheduler.tick_seconds=120")

    response = await handle_config_command("123", "/config reset scheduler.tick_seconds")

    assert response == "Reset scheduler.tick_seconds to default: 60"
    assert get_config_manager().get("scheduler.tick_seconds") == 60

    conn = await manager.get_connection()
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM config WHERE key = ?", ("scheduler.tick_seconds",)
    )
    count = (await cursor.fetchone())[0]
    await cursor.close()
    assert count == 0


@pytest.mark.asyncio
async def test_config_command_without_args_returns_usage(setup_config_runtime):
    response = await handle_config_command("123", "/config")

    assert response == "Usage: /config show | set <key>=<value> | reset <key>"
