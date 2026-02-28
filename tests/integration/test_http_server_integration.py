"""Integration tests for local HTTP observability server."""

from __future__ import annotations

import socket

import httpx
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
from src.sohnbot.observability.http_server import start_http_server, stop_http_server


@pytest.fixture(autouse=True)
def reset_server_and_snapshot():
    import src.sohnbot.capabilities.observe as observe_module
    import src.sohnbot.observability.http_server as http_module

    observe_module._snapshot_cache = None
    http_module._http_server_state = None
    yield
    observe_module._snapshot_cache = None
    http_module._http_server_state = None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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
async def test_http_server_endpoints_and_shutdown():
    update_snapshot_cache(_sample_snapshot())
    port = _free_port()
    await start_http_server(host="127.0.0.1", port=port)

    base_url = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient(timeout=5.0) as client:
        status_resp = await client.get(f"{base_url}/status")
        health_resp = await client.get(f"{base_url}/health")
        metrics_resp = await client.get(f"{base_url}/metrics")
        root_resp = await client.get(f"{base_url}/")
        ui_resp = await client.get(f"{base_url}/ui")
        post_resp = await client.post(f"{base_url}/status")

    assert status_resp.status_code == 200
    assert health_resp.status_code == 200
    assert metrics_resp.status_code == 200
    assert root_resp.status_code == 200
    assert ui_resp.status_code == 200
    assert post_resp.status_code == 405
    assert status_resp.headers["content-type"].startswith("application/json")
    assert root_resp.headers["content-type"].startswith("text/html")
    assert ui_resp.headers["content-type"].startswith("text/html")
    assert health_resp.json()["overall_status"] == "healthy"
    assert "resources" in metrics_resp.json()
    assert "SohnBot Status" in root_resp.text
    assert "Active Operations" in root_resp.text
    assert "Scheduler Next Runs" in ui_resp.text
    assert "Latest Errors" in ui_resp.text
    assert "✅ Healthy" in root_resp.text
    assert "class=\"health healthy\"" in root_resp.text

    await stop_http_server()

    async with httpx.AsyncClient(timeout=2.0) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get(f"{base_url}/status")
