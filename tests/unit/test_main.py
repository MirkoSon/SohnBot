"""Unit tests for runtime startup orchestration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.sohnbot.main import initialize_heartbeat_job, run_main


@pytest.mark.asyncio
@patch("src.sohnbot.main.scheduler_executor_loop", new_callable=AsyncMock)
@patch("src.sohnbot.main.snapshot_collector_loop", new_callable=AsyncMock)
@patch("src.sohnbot.main._safe_http_server_loop", new_callable=AsyncMock)
@patch("src.sohnbot.main.initialize_heartbeat_job", new_callable=AsyncMock)
@patch("src.sohnbot.main.get_config_manager")
async def test_run_main_creates_scheduler_task_with_configured_tick(
    mock_get_config,
    mock_init_heartbeat,
    mock_http_loop,
    mock_snapshot_loop,
    mock_scheduler_loop,
):
    config = MagicMock()
    config.get.side_effect = lambda key: {
        "observability.collection_interval_seconds": 30,
        "scheduler.tick_seconds": 45,
        "observability.http_enabled": False,
    }[key]
    mock_get_config.return_value = config

    await run_main()

    mock_snapshot_loop.assert_awaited_once_with(interval_seconds=30)
    mock_scheduler_loop.assert_awaited_once_with(tick_seconds=45)
    mock_init_heartbeat.assert_awaited_once()
    mock_http_loop.assert_not_awaited()


@pytest.mark.asyncio
@patch("src.sohnbot.main.scheduler_executor_loop", new_callable=AsyncMock)
@patch("src.sohnbot.main.snapshot_collector_loop", new_callable=AsyncMock)
@patch("src.sohnbot.main._safe_http_server_loop", new_callable=AsyncMock)
@patch("src.sohnbot.main.initialize_heartbeat_job", new_callable=AsyncMock)
@patch("src.sohnbot.main.get_config_manager")
async def test_run_main_starts_http_when_enabled(
    mock_get_config,
    mock_init_heartbeat,
    mock_http_loop,
    mock_snapshot_loop,
    mock_scheduler_loop,
):
    config = MagicMock()
    config.get.side_effect = lambda key: {
        "observability.collection_interval_seconds": 30,
        "scheduler.tick_seconds": 60,
        "observability.http_enabled": True,
        "observability.http_host": "127.0.0.1",
        "observability.http_port": 8080,
    }[key]
    mock_get_config.return_value = config

    await run_main()

    mock_snapshot_loop.assert_awaited_once_with(interval_seconds=30)
    mock_scheduler_loop.assert_awaited_once_with(tick_seconds=60)
    mock_init_heartbeat.assert_awaited_once()
    mock_http_loop.assert_awaited_once_with(host="127.0.0.1", port=8080)


@pytest.mark.asyncio
@patch("src.sohnbot.main.create_job", new_callable=AsyncMock)
@patch("src.sohnbot.main.get_job_by_name", new_callable=AsyncMock)
@patch("src.sohnbot.main.get_config_manager")
async def test_initialize_heartbeat_job_creates_when_missing(
    mock_get_config,
    mock_get_job_by_name,
    mock_create_job,
):
    mock_get_job_by_name.return_value = None
    mock_create_job.return_value = {"id": "job-1"}
    config = MagicMock()
    config.get.side_effect = lambda key: {
        "heartbeat.cron": "0 18 * * *",
        "heartbeat.timezone": "UTC",
    }[key]
    mock_get_config.return_value = config

    await initialize_heartbeat_job()

    mock_create_job.assert_awaited_once()
    kwargs = mock_create_job.call_args.kwargs
    assert kwargs["name"] == "Daily Heartbeat"
    assert kwargs["cron_expr"] == "0 18 * * *"
    assert kwargs["timezone"] == "UTC"
    assert kwargs["action"] == "heartbeat"


@pytest.mark.asyncio
@patch("src.sohnbot.main.create_job", new_callable=AsyncMock)
@patch("src.sohnbot.main.get_job_by_name", new_callable=AsyncMock)
async def test_initialize_heartbeat_job_idempotent(
    mock_get_job_by_name,
    mock_create_job,
):
    mock_get_job_by_name.return_value = {"id": "existing"}

    await initialize_heartbeat_job()

    mock_create_job.assert_not_awaited()
