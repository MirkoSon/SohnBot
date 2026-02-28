"""Integration tests for scheduler operations routed through broker."""

from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.broker import BrokerRouter, ScopeValidator
from src.sohnbot.capabilities.scheduler.timezone_handler import get_next_run_time
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager


@pytest.fixture
async def setup_database(tmp_path):
    db_path = tmp_path / "test.db"
    migrations_dir = Path(__file__).parent.parent.parent / "src" / "sohnbot" / "persistence" / "migrations"
    apply_migrations(db_path, migrations_dir)

    db_manager = DatabaseManager(db_path)
    set_db_manager(db_manager)
    yield db_manager, db_path
    await db_manager.close()


@pytest.fixture
def broker(tmp_path):
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()
    validator = ScopeValidator([str(allowed_root)])
    return BrokerRouter(validator)


@pytest.mark.asyncio
async def test_create_job_via_broker(broker, setup_database):
    result = await broker.route_operation(
        capability="scheduler",
        action="create",
        params={
            "name": "daily-heartbeat",
            "cron_expr": "0 9 * * *",
            "timezone": "UTC",
            "action": "heartbeat",
            "enabled": True,
        },
        chat_id="chat1",
    )

    assert result.allowed is True
    assert result.tier == 1
    assert result.result["name"] == "daily-heartbeat"
    assert result.snapshot_ref is None


@pytest.mark.asyncio
async def test_list_jobs_via_broker(broker, setup_database):
    await broker.route_operation(
        capability="scheduler",
        action="create",
        params={
            "name": "job-1",
            "cron_expr": "0 9 * * *",
            "timezone": "UTC",
            "action": "heartbeat",
            "enabled": True,
        },
        chat_id="chat1",
    )

    result = await broker.route_operation(
        capability="scheduler",
        action="list",
        params={"enabled_only": False},
        chat_id="chat1",
    )

    assert result.allowed is True
    assert result.tier == 0
    assert len(result.result["jobs"]) >= 1
    assert any(job["name"] == "job-1" for job in result.result["jobs"])


@pytest.mark.asyncio
async def test_delete_job_via_broker(broker, setup_database):
    created = await broker.route_operation(
        capability="scheduler",
        action="create",
        params={
            "name": "job-delete",
            "cron_expr": "0 9 * * *",
            "timezone": "UTC",
            "action": "heartbeat",
            "enabled": True,
        },
        chat_id="chat1",
    )

    result = await broker.route_operation(
        capability="scheduler",
        action="delete",
        params={"job_id": created.result["id"]},
        chat_id="chat1",
    )

    assert result.allowed is True
    assert result.tier == 1
    assert result.result["deleted"] is True


@pytest.mark.asyncio
async def test_job_persistence_after_restart(broker, setup_database):
    db_manager, db_path = setup_database

    create_result = await broker.route_operation(
        capability="scheduler",
        action="create",
        params={
            "name": "persisted-job",
            "cron_expr": "0 9 * * *",
            "timezone": "UTC",
            "action": "heartbeat",
            "enabled": True,
        },
        chat_id="chat1",
    )
    assert create_result.allowed is True

    await db_manager.close()

    restarted = DatabaseManager(db_path)
    set_db_manager(restarted)

    list_result = await broker.route_operation(
        capability="scheduler",
        action="list",
        params={"enabled_only": False},
        chat_id="chat1",
    )

    assert list_result.allowed is True
    assert any(job["name"] == "persisted-job" for job in list_result.result["jobs"])

    await restarted.close()


@pytest.mark.asyncio
async def test_scheduler_handles_spring_forward_correctly(broker, setup_database):
    _ = broker
    _ = setup_database

    # Last run before DST jump (Mar 9 2024 02:00 America/New_York -> 07:00 UTC)
    last_completed = 1709967600
    with patch(
        "src.sohnbot.capabilities.scheduler.timezone_handler._now_utc",
        return_value=datetime(2024, 3, 9, 12, 0, 0, tzinfo=timezone.utc),
    ):
        next_run = get_next_run_time("0 2 * * *", "America/New_York", last_completed_slot=last_completed)

    # Mar 10 2024 02:00 local does not exist; should execute at 03:00 local (07:00 UTC)
    assert next_run["utc_timestamp"] == 1710054000
    assert next_run["local_datetime"] == "2024-03-10 03:00:00 America/New_York"


@pytest.mark.asyncio
async def test_scheduler_handles_fall_back_correctly(broker, setup_database):
    _ = broker
    _ = setup_database

    # Last run before fall-back day (Nov 2 2024 01:00 America/New_York -> 05:00 UTC)
    last_completed = 1730523600
    with patch(
        "src.sohnbot.capabilities.scheduler.timezone_handler._now_utc",
        return_value=datetime(2024, 11, 2, 12, 0, 0, tzinfo=timezone.utc),
    ):
        next_run = get_next_run_time("0 1 * * *", "America/New_York", last_completed_slot=last_completed)

    # Nov 3 2024 01:00 local occurs twice; scheduler must use first occurrence (fold=0, 05:00 UTC).
    assert next_run["utc_timestamp"] == 1730610000
    assert next_run["local_datetime"] == "2024-11-03 01:00:00 America/New_York"


@pytest.mark.asyncio
async def test_disable_enable_delete_edit_job_by_name_via_broker(broker, setup_database):
    created = await broker.route_operation(
        capability="scheduler",
        action="create",
        params={
            "name": "manage-me",
            "cron_expr": "0 9 * * *",
            "timezone": "UTC",
            "action": "heartbeat",
            "enabled": True,
        },
        chat_id="chat1",
    )
    assert created.allowed is True

    disabled = await broker.route_operation(
        capability="scheduler",
        action="disable",
        params={"name": "manage-me"},
        chat_id="chat1",
    )
    assert disabled.allowed is True
    assert disabled.result["updated"] is True

    edited = await broker.route_operation(
        capability="scheduler",
        action="edit",
        params={"name": "manage-me", "updates": {"cron_expr": "30 10 * * *"}},
        chat_id="chat1",
    )
    assert edited.allowed is True
    assert edited.result["updated"] is True
    assert edited.result["job"]["cron_expr"] == "30 10 * * *"

    enabled = await broker.route_operation(
        capability="scheduler",
        action="enable",
        params={"name": "manage-me"},
        chat_id="chat1",
    )
    assert enabled.allowed is True
    assert enabled.result["updated"] is True

    deleted = await broker.route_operation(
        capability="scheduler",
        action="delete",
        params={"name": "manage-me"},
        chat_id="chat1",
    )
    assert deleted.allowed is True
    assert deleted.result["deleted"] is True
