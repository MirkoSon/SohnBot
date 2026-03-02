"""Unit tests for search volume tracking persistence."""

from datetime import date
from pathlib import Path
from unittest.mock import patch, AsyncMock

import aiosqlite
import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager
from src.sohnbot.persistence.search_volume import (
    claim_alert_slot,
    cleanup_old_volume_records,
    increment_daily_search_count,
    mark_alert_sent,
)


@pytest.fixture
async def volume_db(tmp_path):
    """Set up a DatabaseManager with migrated DB; install as global manager."""
    db_path = tmp_path / "volume-test.db"
    migrations_dir = (
        Path(__file__).parent.parent.parent
        / "src" / "sohnbot" / "persistence" / "migrations"
    )
    apply_migrations(db_path, migrations_dir)
    manager = DatabaseManager(db_path)
    await manager.get_connection()
    set_db_manager(manager)
    yield db_path
    await manager.close()
    import src.sohnbot.persistence.db as db_mod
    db_mod._db_manager = None


@pytest.mark.asyncio
async def test_increment_daily_search_count_creates_entry(volume_db):
    count, alert_sent = await increment_daily_search_count()
    assert count == 1
    assert alert_sent is False


@pytest.mark.asyncio
async def test_increment_daily_search_count_updates_existing(volume_db):
    await increment_daily_search_count()
    count, alert_sent = await increment_daily_search_count()
    assert count == 2
    assert alert_sent is False


@pytest.mark.asyncio
async def test_mark_alert_sent_sets_flag(volume_db):
    await increment_daily_search_count()
    updated = await mark_alert_sent()

    today = date.today().isoformat()
    async with aiosqlite.connect(str(volume_db)) as db:
        cursor = await db.execute(
            "SELECT alert_sent FROM daily_search_volume WHERE date = ?",
            (today,),
        )
        row = await cursor.fetchone()
        await cursor.close()

    assert updated is True
    assert row is not None
    assert int(row[0]) == 1


@pytest.mark.asyncio
async def test_alert_flag_persists_after_increment(volume_db):
    await increment_daily_search_count()
    updated = await mark_alert_sent()
    count, alert_sent = await increment_daily_search_count()

    assert updated is True
    assert count == 2
    assert alert_sent is True


@pytest.mark.asyncio
async def test_mark_alert_sent_before_increment_does_not_create_row(volume_db):
    updated = await mark_alert_sent()

    today = date.today().isoformat()
    async with aiosqlite.connect(str(volume_db)) as db:
        cursor = await db.execute(
            "SELECT search_count, alert_sent FROM daily_search_volume WHERE date = ?",
            (today,),
        )
        row = await cursor.fetchone()
        await cursor.close()

    assert updated is False
    assert row is None


@pytest.mark.asyncio
async def test_increment_daily_search_count_returns_none_on_db_error(volume_db):
    with patch(
        "src.sohnbot.persistence.search_volume.get_db",
        new=AsyncMock(side_effect=aiosqlite.Error("db offline")),
    ):
        result = await increment_daily_search_count()

    assert result is None


@pytest.mark.asyncio
async def test_claim_alert_slot_claims_once_when_threshold_exceeded(volume_db):
    for _ in range(4):
        await increment_daily_search_count()

    first_claim = await claim_alert_slot(threshold=3)
    second_claim = await claim_alert_slot(threshold=3)

    assert first_claim == 4
    assert second_claim is None


@pytest.mark.asyncio
async def test_claim_alert_slot_returns_none_when_threshold_not_exceeded(volume_db):
    for _ in range(3):
        await increment_daily_search_count()

    claim = await claim_alert_slot(threshold=3)

    assert claim is None


@pytest.mark.asyncio
async def test_cleanup_old_volume_records(volume_db):
    today = date.today().isoformat()
    old_date = "2020-01-01"
    async with aiosqlite.connect(str(volume_db)) as db:
        await db.execute(
            "INSERT INTO daily_search_volume (date, search_count) VALUES (?, ?)",
            (old_date, 10),
        )
        await db.execute(
            "INSERT OR REPLACE INTO daily_search_volume (date, search_count) VALUES (?, ?)",
            (today, 2),
        )
        await db.commit()

    deleted = await cleanup_old_volume_records(retention_days=30)
    assert deleted == 1
