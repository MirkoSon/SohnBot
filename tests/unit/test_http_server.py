"""Unit tests for local HTTP observability server."""

from __future__ import annotations

import json

import pytest
from aiohttp.test_utils import make_mocked_request

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
from src.sohnbot.observability.http_server import (
    ConfigError,
    handle_health,
    handle_metrics,
    handle_status,
    handle_ui,
    validate_http_host,
)


@pytest.fixture(autouse=True)
def reset_snapshot_cache():
    import src.sohnbot.capabilities.observe as observe_module

    observe_module._snapshot_cache = None
    yield
    observe_module._snapshot_cache = None


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
                    "operation_id": "abcdef1234",
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
            next_jobs=[{"job_name": "daily-heartbeat", "next_run_local": "2026-03-01T08:00:00"}],
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
            )
        ],
        recent_operations=[
            {
                "operation_id": "zzzz11112222",
                "tool": "git__status",
                "status": "error",
                "error_message": "git status failed",
                "timestamp": 1_700_000_095,
            }
        ],
    )


@pytest.mark.asyncio
async def test_status_route_returns_snapshot_json():
    update_snapshot_cache(_sample_snapshot())
    request = make_mocked_request("GET", "/status")
    response = await handle_status(request)
    assert response.status == 200
    assert response.content_type == "application/json"
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    payload = json.loads(response.text)
    assert payload["process"]["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_health_route_returns_snapshot_json():
    update_snapshot_cache(_sample_snapshot())
    request = make_mocked_request("GET", "/health")
    response = await handle_health(request)
    assert response.status == 200
    assert response.content_type == "application/json"
    payload = json.loads(response.text)
    assert payload["overall_status"] == "healthy"
    assert len(payload["checks"]) == 1


@pytest.mark.asyncio
async def test_metrics_route_returns_snapshot_json():
    update_snapshot_cache(_sample_snapshot())
    request = make_mocked_request("GET", "/metrics")
    response = await handle_metrics(request)
    assert response.status == 200
    assert response.content_type == "application/json"
    payload = json.loads(response.text)
    assert payload["resources"]["cpu_percent"] == 7.5


@pytest.mark.asyncio
async def test_all_routes_return_503_without_snapshot():
    status_request = make_mocked_request("GET", "/status")
    health_request = make_mocked_request("GET", "/health")
    metrics_request = make_mocked_request("GET", "/metrics")

    status_response = await handle_status(status_request)
    health_response = await handle_health(health_request)
    metrics_response = await handle_metrics(metrics_request)

    assert status_response.status == 503
    assert health_response.status == 503
    assert metrics_response.status == 503

    assert json.loads(status_response.text)["error"] == "No snapshot available"
    assert json.loads(health_response.text)["error"] == "No snapshot available"
    assert json.loads(metrics_response.text)["error"] == "No snapshot available"


def test_validate_http_host_accepts_localhost():
    validate_http_host("127.0.0.1")
    validate_http_host("::1")


def test_validate_http_host_rejects_non_localhost():
    with pytest.raises(ConfigError, match="localhost only"):
        validate_http_host("0.0.0.0")
    with pytest.raises(ConfigError, match="localhost only"):
        validate_http_host("192.168.1.1")


@pytest.mark.asyncio
async def test_ui_route_returns_html_with_sections():
    update_snapshot_cache(_sample_snapshot())
    request = make_mocked_request("GET", "/ui")
    response = await handle_ui(request)
    assert response.status == 200
    assert response.content_type == "text/html"
    assert "<h1>SohnBot Status</h1>" in response.text
    assert "Active Operations" in response.text
    assert "Scheduler Next Runs" in response.text
    assert "Resources" in response.text
    assert "Latest Errors" in response.text


@pytest.mark.asyncio
async def test_ui_route_contains_health_badge_and_meta_refresh():
    update_snapshot_cache(_sample_snapshot())
    request = make_mocked_request("GET", "/")
    response = await handle_ui(request)
    assert "✅ Healthy" in response.text
    assert "meta http-equiv=\"refresh\" content=\"30\"" in response.text


@pytest.mark.asyncio
async def test_ui_route_handles_no_snapshot():
    request = make_mocked_request("GET", "/ui")
    response = await handle_ui(request)
    assert response.status == 503
    assert response.content_type == "text/html"
    assert "No snapshot available" in response.text


@pytest.mark.asyncio
async def test_ui_route_handles_empty_lists_gracefully():
    snapshot = _sample_snapshot()
    snapshot.broker.in_flight_operations = []
    snapshot.scheduler.next_jobs = []
    snapshot.recent_operations = []
    update_snapshot_cache(snapshot)
    request = make_mocked_request("GET", "/ui")
    response = await handle_ui(request)
    assert "No active operations" in response.text
    assert "No scheduled jobs" in response.text
    assert "No recent errors" in response.text
