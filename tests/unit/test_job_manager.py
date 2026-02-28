"""Unit tests for scheduler job manager."""

from pathlib import Path

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.capabilities.scheduler.job_manager import (
    create_job,
    delete_job,
    disable_job,
    edit_job,
    enable_job,
    get_job_by_id,
    get_job_by_name,
    list_jobs,
)
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
async def test_create_job_success(setup_database):
    job = await create_job(
        name="morning-summary",
        cron_expr="0 9 * * *",
        timezone="America/New_York",
        action="agent_query",
        action_params={"prompt": "summarize"},
        enabled=True,
    )

    assert job["id"]
    assert job["name"] == "morning-summary"
    assert job["cron_expr"] == "0 9 * * *"
    assert job["timezone"] == "America/New_York"
    assert job["action"] == "agent_query"
    assert job["action_params"] == {"prompt": "summarize"}
    assert job["enabled"] is True
    assert isinstance(job["created_at"], int)


@pytest.mark.asyncio
async def test_create_job_invalid_cron(setup_database):
    with pytest.raises(ValueError, match="Invalid cron expression"):
        await create_job(
            name="bad-cron",
            cron_expr="not-a-cron",
            timezone="UTC",
            action="heartbeat",
        )


@pytest.mark.asyncio
async def test_create_job_invalid_timezone(setup_database):
    with pytest.raises(ValueError, match="Invalid timezone"):
        await create_job(
            name="bad-tz",
            cron_expr="0 9 * * *",
            timezone="Mars/Phobos",
            action="heartbeat",
        )


@pytest.mark.asyncio
async def test_create_job_invalid_action(setup_database):
    with pytest.raises(ValueError, match="Invalid action"):
        await create_job(
            name="bad-action",
            cron_expr="0 9 * * *",
            timezone="UTC",
            action="unknown_action",
        )


@pytest.mark.asyncio
async def test_list_jobs_all(setup_database):
    await create_job("job-a", "0 9 * * *", "UTC", "heartbeat", enabled=True)
    await create_job("job-b", "0 10 * * *", "UTC", "heartbeat", enabled=False)

    jobs = await list_jobs()
    names = {item["name"] for item in jobs}

    assert len(jobs) == 2
    assert names == {"job-a", "job-b"}


@pytest.mark.asyncio
async def test_list_jobs_enabled_only(setup_database):
    await create_job("enabled-job", "0 9 * * *", "UTC", "heartbeat", enabled=True)
    await create_job("disabled-job", "0 10 * * *", "UTC", "heartbeat", enabled=False)

    jobs = await list_jobs(enabled_only=True)

    assert len(jobs) == 1
    assert jobs[0]["name"] == "enabled-job"
    assert jobs[0]["enabled"] is True


@pytest.mark.asyncio
async def test_delete_job_success(setup_database):
    job = await create_job("delete-me", "0 9 * * *", "UTC", "heartbeat")

    deleted = await delete_job(job["id"])
    loaded = await get_job_by_name("delete-me")

    assert deleted is True
    assert loaded is None


@pytest.mark.asyncio
async def test_delete_job_not_found(setup_database):
    deleted = await delete_job("00000000-0000-4000-8000-000000000000")
    assert deleted is False


@pytest.mark.asyncio
async def test_disable_job_success(setup_database):
    job = await create_job("disable-me", "0 9 * * *", "UTC", "heartbeat", enabled=True)
    updated = await disable_job(job["id"])
    loaded = await get_job_by_id(job["id"])
    assert updated is True
    assert loaded is not None
    assert loaded["enabled"] is False


@pytest.mark.asyncio
async def test_enable_job_success(setup_database):
    job = await create_job("enable-me", "0 9 * * *", "UTC", "heartbeat", enabled=False)
    updated = await enable_job(job["id"])
    loaded = await get_job_by_id(job["id"])
    assert updated is True
    assert loaded is not None
    assert loaded["enabled"] is True


@pytest.mark.asyncio
async def test_edit_job_success(setup_database):
    job = await create_job("edit-me", "0 9 * * *", "UTC", "heartbeat")
    updated = await edit_job(job["id"], {"cron_expr": "30 10 * * *", "timezone": "America/New_York"})
    assert updated is not None
    assert updated["cron_expr"] == "30 10 * * *"
    assert updated["timezone"] == "America/New_York"


@pytest.mark.asyncio
async def test_edit_job_invalid_cron(setup_database):
    job = await create_job("edit-bad-cron", "0 9 * * *", "UTC", "heartbeat")
    with pytest.raises(ValueError, match="Invalid cron expression"):
        await edit_job(job["id"], {"cron_expr": "bad-cron"})
