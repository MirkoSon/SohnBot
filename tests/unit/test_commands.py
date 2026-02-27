"""Unit tests for gateway command handlers."""

from pathlib import Path

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.gateway.commands import handle_notify_command
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
async def test_notify_on_command(setup_database):
    response = await handle_notify_command("123", "/notify on")
    assert response == "Notifications enabled."


@pytest.mark.asyncio
async def test_notify_off_command(setup_database):
    response = await handle_notify_command("123", "/notify off")
    assert response == "Notifications disabled."


@pytest.mark.asyncio
async def test_notify_status_command(setup_database):
    await handle_notify_command("123", "/notify off")
    response = await handle_notify_command("123", "/notify status")
    assert response == "Notifications are OFF."
