"""Local read-only HTTP observability server."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from html import escape
from pathlib import Path

import structlog
from aiohttp import web

from ..capabilities.observe import (
    get_current_snapshot,
    get_health_snapshot,
    get_resource_snapshot_data,
    get_status_snapshot_data,
)

logger = structlog.get_logger(__name__)

ALLOWED_HTTP_HOSTS = {"127.0.0.1", "::1"}
_TEMPLATE_PATH = Path(__file__).parent / "templates" / "status.html"


class ConfigError(ValueError):
    """Raised when HTTP observability configuration is invalid."""


def validate_http_host(host: str) -> None:
    """Validate localhost-only host binding."""
    if host not in ALLOWED_HTTP_HOSTS:
        raise ConfigError(f"HTTP server must bind to localhost only, got: {host}")


def _json_response(payload: dict, status: int = 200) -> web.Response:
    """Return JSON response with permissive localhost CORS header."""
    return web.json_response(
        payload,
        status=status,
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def handle_status(request: web.Request) -> web.Response:
    """Return status snapshot payload as JSON."""
    _ = request
    payload = get_status_snapshot_data()
    if payload is None:
        return _json_response({"error": "No snapshot available"}, status=503)
    return _json_response(payload)


async def handle_health(request: web.Request) -> web.Response:
    """Return health snapshot payload as JSON."""
    _ = request
    payload = get_health_snapshot()
    if payload is None:
        return _json_response({"error": "No snapshot available"}, status=503)
    return _json_response(payload)


async def handle_metrics(request: web.Request) -> web.Response:
    """Return resource metrics payload as JSON."""
    _ = request
    payload = get_resource_snapshot_data()
    if payload is None:
        return _json_response({"error": "No snapshot available"}, status=503)
    return _json_response(payload)


def _health_badge(checks: list[dict]) -> tuple[str, str]:
    statuses = {check.get("status") for check in checks}
    if "fail" in statuses:
        return "unhealthy", "❌ Unhealthy"
    if "warn" in statuses:
        return "degraded", "⚠️ Degraded"
    return "healthy", "✅ Healthy"


def _render_ops_rows(ops: list[dict]) -> str:
    if not ops:
        return "<tr><td colspan='4'>No active operations</td></tr>"
    rows = []
    for op in ops:
        rows.append(
            "<tr>"
            f"<td>{escape(str(op.get('operation_id', ''))[:8])}</td>"
            f"<td>{escape(str(op.get('tool', '-')))}</td>"
            f"<td>{escape(str(op.get('tier', '-')))}</td>"
            f"<td>{escape(str(op.get('elapsed_s', '-')))}s</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_scheduler_rows(jobs: list[dict]) -> str:
    if not jobs:
        return "<tr><td colspan='2'>No scheduled jobs</td></tr>"
    rows = []
    for job in jobs[:5]:
        rows.append(
            "<tr>"
            f"<td>{escape(str(job.get('job_name', '-')))}</td>"
            f"<td>{escape(str(job.get('next_run_local', '-')))}</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_error_rows(operations: list[dict]) -> str:
    errors = [op for op in operations if op.get("status") in {"error", "failed"}][:10]
    if not errors:
        return "<tr><td colspan='4'>No recent errors</td></tr>"

    rows = []
    for op in errors:
        error_message = (
            op.get("error_message")
            or op.get("error")
            or str(op.get("error_details", "-"))
        )
        rows.append(
            "<tr>"
            f"<td>{escape(str(op.get('operation_id', ''))[:8])}</td>"
            f"<td>{escape(str(op.get('tool', '-')))}</td>"
            f"<td>{escape(str(error_message)[:50])}</td>"
            f"<td>{escape(str(op.get('timestamp', '-')))}</td>"
            "</tr>"
        )
    return "".join(rows)


def _format_uptime(seconds: int) -> str:
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86_400)
    hours, rem = divmod(rem, 3_600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m {secs}s"
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


async def handle_ui(request: web.Request) -> web.Response:
    """Return HTML status dashboard for / and /ui."""
    _ = request
    snapshot = get_current_snapshot()
    if snapshot is None:
        html = (
            "<!DOCTYPE html><html><head><meta http-equiv='refresh' content='30'>"
            "<title>SohnBot Status</title></head><body>"
            "<h1>SohnBot Status</h1><p>No snapshot available</p>"
            "<p><em>Auto-refreshes every 30 seconds</em></p></body></html>"
        )
        return web.Response(text=html, content_type="text/html", status=503)

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    health_checks = [
        {"status": check.status}
        for check in snapshot.health
    ]
    health_class, health_badge = _health_badge(health_checks)

    html = template.format(
        health_class=health_class,
        health_badge=escape(health_badge),
        uptime=escape(_format_uptime(snapshot.process.uptime_seconds)),
        version=escape(snapshot.process.version),
        pid=escape(str(snapshot.process.pid)),
        supervisor=escape(str(snapshot.process.supervisor or "none")),
        active_operations_rows=_render_ops_rows(snapshot.broker.in_flight_operations),
        scheduler_rows=_render_scheduler_rows(snapshot.scheduler.next_jobs),
        cpu_percent=f"{snapshot.resources.cpu_percent:.1f}",
        ram_mb=escape(str(snapshot.resources.ram_mb)),
        db_size_mb=f"{snapshot.resources.db_size_mb:.1f}",
        log_size_mb=f"{snapshot.resources.log_size_mb:.1f}",
        snapshot_count=escape(str(snapshot.resources.snapshot_count)),
        event_loop_lag_ms=(
            "N/A"
            if snapshot.resources.event_loop_lag_ms is None
            else f"{snapshot.resources.event_loop_lag_ms:.1f}"
        ),
        error_rows=_render_error_rows(snapshot.recent_operations),
    )
    return web.Response(text=html, content_type="text/html")


def create_observability_app() -> web.Application:
    """Build aiohttp app with read-only observability endpoints."""
    app = web.Application()
    app.router.add_get("/", handle_ui)
    app.router.add_get("/ui", handle_ui)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/metrics", handle_metrics)
    return app


@dataclass
class HttpServerState:
    """Track the active aiohttp server resources."""

    app: web.Application
    runner: web.AppRunner
    site: web.BaseSite
    host: str
    port: int


_http_server_state: HttpServerState | None = None


async def start_http_server(host: str = "127.0.0.1", port: int = 8080) -> HttpServerState:
    """Start local observability server and return active state."""
    global _http_server_state

    validate_http_host(host)

    if _http_server_state is not None:
        logger.info(
            "http_server_already_running",
            host=_http_server_state.host,
            port=_http_server_state.port,
        )
        return _http_server_state

    app = create_observability_app()
    runner = web.AppRunner(app, handle_signals=False)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()

    _http_server_state = HttpServerState(
        app=app,
        runner=runner,
        site=site,
        host=host,
        port=port,
    )
    logger.info("http_server_started", host=host, port=port)
    return _http_server_state


async def stop_http_server() -> None:
    """Stop local observability server if active."""
    global _http_server_state

    if _http_server_state is None:
        return

    await _http_server_state.runner.cleanup()
    logger.info("http_server_stopped", host=_http_server_state.host, port=_http_server_state.port)
    _http_server_state = None


async def http_server_loop(host: str = "127.0.0.1", port: int = 8080) -> None:
    """Run HTTP server until cancelled."""
    await start_http_server(host=host, port=port)
    try:
        await asyncio.Event().wait()
    finally:
        await stop_http_server()
