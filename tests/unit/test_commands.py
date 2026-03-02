"""Unit tests for gateway command handlers."""

from pathlib import Path

import pytest

from src.sohnbot.capabilities.observe import (
    BrokerActivity,
    HealthCheckResult,
    NotifierState,
    ProcessInfo,
    ResourceUsage,
    SchedulerState,
    StatusSnapshot,
    update_snapshot_cache,
)
from scripts.migrate import apply_migrations
from src.sohnbot.gateway.commands import (
    handle_heartbeat_command,
    handle_health_command,
    handle_logs_command,
    handle_notify_command,
    handle_schedule_command,
    handle_status_command,
    set_schedule_broker,
)
from src.sohnbot.capabilities.scheduler import create_job
from src.sohnbot.persistence.audit import log_operation_end, log_operation_start
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


@pytest.fixture(autouse=True)
def reset_snapshot_cache():
    import src.sohnbot.capabilities.observe as observe_module

    observe_module._snapshot_cache = None
    set_schedule_broker(None)
    yield
    observe_module._snapshot_cache = None
    set_schedule_broker(None)


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


@pytest.mark.asyncio
async def test_logs_command_invalid_hours_format(setup_database):
    response = await handle_logs_command("123", "/logs abc", str(setup_database.db_path))
    assert "Hours must be a number" in response


@pytest.mark.asyncio
async def test_logs_command_hours_out_of_range(setup_database):
    response = await handle_logs_command("123", "/logs 1000", str(setup_database.db_path))
    assert "between 1 and 720" in response


@pytest.mark.asyncio
async def test_logs_command_returns_empty_message(setup_database):
    response = await handle_logs_command("123", "/logs", str(setup_database.db_path))
    assert "No operations found in last 24 hours." == response


@pytest.mark.asyncio
async def test_logs_command_formats_entries(setup_database):
    operation_id = "logs-test-op"
    await log_operation_start(
        operation_id=operation_id,
        capability="fs",
        action="read",
        chat_id="chat-1",
        tier=0,
        file_paths=["README.md"],
        correlation_id="12345678-abcd-ef00-9999-aaaaaaaaaaaa",
    )
    await log_operation_end(
        operation_id=operation_id,
        status="completed",
        duration_ms=42,
    )

    response = await handle_logs_command("123", "/logs 24", str(setup_database.db_path))
    assert "Operation Logs (last 24h)" in response
    assert "fs__read" in response
    assert "Corr: 12345678" in response


def _sample_snapshot() -> StatusSnapshot:
    return StatusSnapshot(
        timestamp=1_700_000_100,
        process=ProcessInfo(
            pid=999,
            uptime_seconds=3661,
            version="0.1.0",
            supervisor="pm2",
            supervisor_status="online",
            restart_count=0,
        ),
        broker=BrokerActivity(
            last_operation_timestamp=1_700_000_090,
            in_flight_operations=[
                {
                    "operation_id": "op1",
                    "tool": "fs__read",
                    "tier": 0,
                    "elapsed_s": 3,
                }
            ],
            last_10_results={"completed": 8, "failed": 1},
        ),
        scheduler=SchedulerState(
            last_tick_timestamp=1_700_000_080,
            last_tick_local="2026-02-28T10:00:00",
            next_jobs=[],
            active_jobs_count=0,
        ),
        notifier=NotifierState(
            last_attempt_timestamp=1_700_000_070,
            pending_count=2,
            oldest_pending_age_seconds=11,
        ),
        resources=ResourceUsage(
            cpu_percent=7.5,
            cpu_1m_avg=None,
            ram_mb=123,
            db_size_mb=4.2,
            log_size_mb=8.4,
            snapshot_count=6,
            event_loop_lag_ms=2.5,
        ),
        health=[
            HealthCheckResult(
                name="sqlite_writable",
                status="pass",
                message="SQLite writable and WAL enabled",
                timestamp=1_700_000_090,
                details=None,
            ),
            HealthCheckResult(
                name="outbox_stuck",
                status="warn",
                message="Pending notifications detected",
                timestamp=1_700_000_090,
                details={"pending": 2},
            ),
            HealthCheckResult(
                name="scheduler_lag",
                status="fail",
                message="Scheduler lag exceeds threshold",
                timestamp=1_700_000_090,
                details={"lag_seconds": 301, "threshold": 300},
            ),
        ],
        recent_operations=[],
    )


@pytest.mark.asyncio
async def test_status_command_default_view():
    update_snapshot_cache(_sample_snapshot())
    response = await handle_status_command("123", "/status")
    assert "System Status" in response
    assert "Uptime:" in response
    assert "Version:" in response
    assert "Supervisor:" in response
    assert "Last scheduler tick:" in response
    assert "Last broker activity:" in response
    assert "In-flight operations:" in response
    assert "Notification outbox:" in response
    assert "DST transitions handled" in response
    assert "Last 10 operations:" in response


@pytest.mark.asyncio
async def test_status_command_resources_view():
    update_snapshot_cache(_sample_snapshot())
    response = await handle_status_command("123", "/status resources")
    assert "Resource Usage" in response
    assert "CPU:" in response
    assert "RAM:" in response
    assert "Database:" in response
    assert "Logs:" in response
    assert "Snapshots:" in response
    assert "Event Loop Lag:" in response


@pytest.mark.asyncio
async def test_status_command_invalid_args():
    response = await handle_status_command("123", "/status invalid")
    assert response == "Usage: /status [resources]"


@pytest.mark.asyncio
async def test_status_command_without_snapshot():
    response = await handle_status_command("123", "/status")
    assert response == "Status unavailable: snapshot not collected yet."


@pytest.mark.asyncio
async def test_health_command_returns_overall_status():
    update_snapshot_cache(_sample_snapshot())
    response = await handle_health_command("123")
    assert "System Health: UNHEALTHY" in response


@pytest.mark.asyncio
async def test_health_command_lists_all_checks():
    update_snapshot_cache(_sample_snapshot())
    response = await handle_health_command("123")
    assert "sqlite_writable" in response
    assert "outbox_stuck" in response
    assert "scheduler_lag" in response
    assert "✅" in response
    assert "⚠️" in response
    assert "❌" in response


@pytest.mark.asyncio
async def test_health_command_shows_failure_details():
    update_snapshot_cache(_sample_snapshot())
    response = await handle_health_command("123")
    assert "lag_seconds=301" in response
    assert "threshold=300" in response


@pytest.mark.asyncio
async def test_health_command_without_snapshot():
    response = await handle_health_command("123")
    assert response == "Health unavailable: snapshot not collected yet."


@pytest.mark.asyncio
async def test_schedule_command_create_success():
    class _Broker:
        async def route_operation(self, capability, action, params, chat_id):
            class _Result:
                allowed = True
                result = {
                    "name": params["name"],
                    "cron_expr": params["cron_expr"],
                    "timezone": params["timezone"],
                    "action": params["action"],
                }

            return _Result()

    set_schedule_broker(_Broker())
    response = await handle_schedule_command(
        "123",
        '/schedule create morning-summary "0 9 * * *" America/New_York heartbeat',
    )

    assert "Scheduled job created" in response
    assert "morning-summary" in response
    assert "0 9 * * *" in response


@pytest.mark.asyncio
async def test_schedule_command_invalid_usage():
    class _Broker:
        async def route_operation(self, capability, action, params, chat_id):
            raise AssertionError("Should not route for invalid usage")

    set_schedule_broker(_Broker())
    response = await handle_schedule_command("123", "/schedule create")
    assert "Usage: /schedule create" in response


@pytest.mark.asyncio
async def test_schedule_command_list_success():
    class _Broker:
        async def route_operation(self, capability, action, params, chat_id):
            class _Result:
                allowed = True
                result = {
                    "jobs": [
                        {
                            "name": "morning-summary",
                            "cron_expr": "0 9 * * *",
                            "timezone": "America/New_York",
                            "next_run_local": {
                                "local_datetime": "2024-03-10 09:00:00 America/New_York",
                            },
                        }
                    ]
                }

            return _Result()

    set_schedule_broker(_Broker())
    response = await handle_schedule_command("123", "/schedule list")
    assert "Scheduled Jobs:" in response
    assert "next=2024-03-10 09:00:00 America/New_York" in response


@pytest.mark.asyncio
async def test_schedule_command_disable_enable_delete_edit_success():
    class _Broker:
        async def route_operation(self, capability, action, params, chat_id):
            class _Result:
                allowed = True
                result = {}

            r = _Result()
            if action in {"disable", "enable"}:
                r.result = {"updated": True}
            elif action == "delete":
                r.result = {"deleted": True}
            elif action == "edit":
                r.result = {
                    "updated": True,
                    "job": {
                        "cron_expr": "30 10 * * *",
                        "timezone": "UTC",
                        "action": "heartbeat",
                        "next_run_local": {"local_datetime": "2024-03-10 10:30:00 UTC"},
                    },
                }
            return r

    set_schedule_broker(_Broker())
    disable_response = await handle_schedule_command("123", "/schedule disable morning-summary")
    enable_response = await handle_schedule_command("123", "/schedule enable morning-summary")
    delete_response = await handle_schedule_command("123", "/schedule delete morning-summary")
    edit_response = await handle_schedule_command("123", '/schedule edit morning-summary cron_expr "30 10 * * *"')

    assert disable_response == "✅ Job disabled: morning-summary"
    assert "✅ Job enabled: morning-summary" in enable_response
    assert delete_response == "✅ Job deleted: morning-summary"
    assert "✅ Job updated: morning-summary" in edit_response


@pytest.mark.asyncio
async def test_schedule_command_not_found_errors():
    class _Broker:
        async def route_operation(self, capability, action, params, chat_id):
            class _Result:
                allowed = True
                result = {}

            r = _Result()
            if action in {"disable", "enable"}:
                r.result = {"updated": False}
            elif action == "delete":
                r.result = {"deleted": False}
            elif action == "edit":
                r.result = {"updated": False, "job": None}
            return r

    set_schedule_broker(_Broker())
    assert "Job not found" in await handle_schedule_command("123", "/schedule disable missing")
    assert "Job not found" in await handle_schedule_command("123", "/schedule enable missing")
    assert "Job not found" in await handle_schedule_command("123", "/schedule delete missing")
    assert "Job not found" in await handle_schedule_command("123", '/schedule edit missing cron_expr "0 1 * * *"')


@pytest.mark.asyncio
async def test_heartbeat_status_command(setup_database):
    await create_job(
        name="Daily Heartbeat",
        cron_expr="0 18 * * *",
        timezone="UTC",
        action="heartbeat",
        enabled=True,
    )

    class _Broker:
        async def route_operation(self, capability, action, params, chat_id):
            class _Result:
                allowed = True
                result = {
                    "jobs": [
                        {
                            "name": "Daily Heartbeat",
                            "cron_expr": "0 18 * * *",
                            "timezone": "UTC",
                            "enabled": True,
                            "last_completed_slot": None,
                            "next_run_local": {"local_datetime": "2026-03-02 18:00:00 UTC"},
                        }
                    ]
                }

            return _Result()

    set_schedule_broker(_Broker())
    response = await handle_heartbeat_command("123", "/heartbeat status")
    assert "📊 Heartbeat Status" in response
    assert "✅ Enabled" in response
    assert "0 18 * * *" in response
    assert "UTC" in response


@pytest.mark.asyncio
async def test_heartbeat_configure_command(setup_database):
    await create_job(
        name="Daily Heartbeat",
        cron_expr="0 18 * * *",
        timezone="UTC",
        action="heartbeat",
        enabled=True,
    )

    response = await handle_heartbeat_command("123", "/heartbeat configure")
    assert "🔧 Heartbeat Configuration" in response
    assert "/schedule edit" in response
    assert "Daily Heartbeat" in response


@pytest.mark.asyncio
async def test_heartbeat_disable_enable_command(setup_database):
    await create_job(
        name="Daily Heartbeat",
        cron_expr="0 18 * * *",
        timezone="UTC",
        action="heartbeat",
        enabled=True,
    )

    class _Broker:
        async def route_operation(self, capability, action, params, chat_id):
            class _Result:
                allowed = True
                result = {}

            r = _Result()
            if action == "disable":
                r.result = {"updated": True}
            elif action == "enable":
                r.result = {
                    "updated": True,
                    "job": {"next_run_local": {"local_datetime": "2026-03-02 18:00:00 UTC"}},
                }
            return r

    set_schedule_broker(_Broker())
    disable_response = await handle_heartbeat_command("123", "/heartbeat disable")
    enable_response = await handle_heartbeat_command("123", "/heartbeat enable")
    assert "✅ Heartbeat disabled" in disable_response
    assert "✅ Heartbeat enabled" in enable_response
    assert "Next report:" in enable_response


@pytest.mark.asyncio
async def test_heartbeat_job_not_found(setup_database):
    response = await handle_heartbeat_command("123", "/heartbeat status")
    assert "❌ Heartbeat job not found" in response
    assert "Daily Heartbeat" in response
