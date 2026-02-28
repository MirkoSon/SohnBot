"""Heartbeat report generation for daily status summaries."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import structlog

from .observe import get_current_snapshot
from ..persistence.db import get_db

logger = structlog.get_logger(__name__)


def _format_uptime(uptime_seconds: int) -> str:
    """Format process uptime as human-readable duration."""
    seconds = max(0, uptime_seconds)
    days, rem = divmod(seconds, 86_400)
    hours, rem = divmod(rem, 3_600)
    minutes, secs = divmod(rem, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    if not days:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _format_number(num: int) -> str:
    """Format number with thousands separator."""
    return f"{num:,}"


async def _get_operations_summary_24h() -> dict[str, int]:
    """Query execution_log for operations in last 24 hours grouped by status."""
    db = await get_db()
    cutoff_timestamp = int(time.time()) - 86_400

    try:
        cursor = await db.execute(
            """
            SELECT status, COUNT(*) as count
            FROM execution_log
            WHERE timestamp >= ?
            GROUP BY status
            """,
            (cutoff_timestamp,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
    except Exception as exc:  # noqa: BLE001
        logger.error("heartbeat_operations_query_failed", error=str(exc))
        return {}

    summary: dict[str, int] = {}
    for row in rows:
        status, count = row
        summary[str(status)] = int(count)
    return summary


async def _get_scheduler_jobs_count_24h() -> int:
    """Count scheduler job executions in last 24 hours."""
    db = await get_db()
    cutoff_timestamp = int(time.time()) - 86_400

    try:
        cursor = await db.execute(
            """
            SELECT COUNT(*) as count
            FROM execution_log
            WHERE timestamp >= ?
              AND capability = 'scheduler'
              AND status IN ('completed', 'failed')
            """,
            (cutoff_timestamp,),
        )
        row = await cursor.fetchone()
        await cursor.close()
    except Exception as exc:  # noqa: BLE001
        logger.error("heartbeat_scheduler_jobs_query_failed", error=str(exc))
        return 0

    if row is None:
        return 0
    return int(row[0])


def _health_overall(snapshot) -> tuple[str, str]:
    checks = snapshot.health or []
    if not checks:
        return "❔", "Unknown"

    fail_count = sum(1 for check in checks if check.status == "fail")
    warn_count = sum(1 for check in checks if check.status == "warn")
    if fail_count > 0:
        return "❌", "Unhealthy"
    if warn_count > 0:
        return "⚠️", "Degraded"
    return "✅", "Healthy"


async def generate_heartbeat_report() -> str:
    """Generate a heartbeat report with operations summary and system status."""
    logger.info("heartbeat_report_generation_started")
    report_timestamp = datetime.now(timezone.utc)

    operations_summary = await _get_operations_summary_24h()
    scheduler_jobs_count = await _get_scheduler_jobs_count_24h()
    snapshot = get_current_snapshot()

    total_operations = sum(operations_summary.values())
    completed = operations_summary.get("completed", 0)
    failed = operations_summary.get("failed", 0)
    postponed = operations_summary.get("postponed", 0)
    cancelled = operations_summary.get("cancelled", 0)
    success_rate = (completed / total_operations * 100) if total_operations > 0 else 0.0

    lines = [
        "📊 Daily Heartbeat Report",
        "",
        f"Timestamp: {report_timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "Operations (Last 24h):",
    ]

    if total_operations == 0:
        lines.append("- No operations recorded")
    else:
        lines.append(f"- Total: {_format_number(total_operations)}")
        lines.append(f"- ✅ Completed: {_format_number(completed)} ({success_rate:.1f}%)")
        if failed:
            lines.append(f"- ❌ Failed: {_format_number(failed)}")
        if postponed:
            lines.append(f"- ⏸️ Postponed: {_format_number(postponed)}")
        if cancelled:
            lines.append(f"- 🚫 Cancelled: {_format_number(cancelled)}")

    lines.extend(
        [
            "",
            "Scheduled Jobs (Last 24h):",
            (
                "- No jobs executed"
                if scheduler_jobs_count == 0
                else f"- Executed: {_format_number(scheduler_jobs_count)}"
            ),
            "",
            "System Status:",
        ]
    )

    if snapshot is None:
        lines.append("- Status snapshot: Not available")
        lines.append("- Uptime: Unknown")
        lines.append("- Health: Unknown")
    else:
        lines.append(f"- Uptime: {_format_uptime(int(snapshot.process.uptime_seconds))}")
        emoji, health_text = _health_overall(snapshot)
        lines.append(f"- Health: {emoji} {health_text}")
        lines.append(f"- Version: {snapshot.process.version}")
        lines.append("")
        lines.append("Resources:")
        lines.append(f"- CPU: {float(snapshot.resources.cpu_percent):.1f}%")
        lines.append(f"- RAM: {int(snapshot.resources.ram_mb)} MB")
        lines.append(f"- Database: {float(snapshot.resources.db_size_mb):.1f} MB")
        lines.append(f"- Logs: {float(snapshot.resources.log_size_mb):.1f} MB")

    logger.info(
        "heartbeat_report_generation_completed",
        total_operations=total_operations,
        scheduler_jobs=scheduler_jobs_count,
    )

    return "\n".join(lines)
