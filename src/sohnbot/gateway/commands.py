"""Gateway command handlers."""

from __future__ import annotations

from datetime import datetime
import shlex
import time
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter

from ..capabilities.scheduler.timezone_handler import get_dst_transition_count
from ..capabilities.scheduler import get_job_by_name
from ..config.manager import get_config_manager
from ..config.registry import REGISTRY, get_config_key, get_dynamic_keys, get_static_keys
from ..capabilities.observe import (
    get_health_snapshot,
    get_resource_snapshot_data,
    get_status_snapshot_data,
)
from ..persistence.notification import (
    get_notifications_enabled,
    set_notifications_enabled,
)
from ..persistence.operation_logs import query_operation_logs
from ..runtime.agent_selector import get_agent_status

_schedule_broker: Any = None


def set_schedule_broker(broker: Any) -> None:
    """Set broker used by /schedule command handlers."""
    global _schedule_broker
    _schedule_broker = broker


async def handle_web_research_command(chat_id: str, command_text: str) -> str:
    """Handle /web_research <query> [--depth=quick|deep] [--mode=fresh|static]."""
    if _schedule_broker is None:
        return "Web research unavailable: broker not initialized."

    usage = (
        "Usage: /web_research <query> [--depth=quick|deep] [--mode=fresh|static]\n"
        "Example: /web_research \"best React patterns 2026\" --depth=deep --mode=fresh"
    )

    try:
        parts = shlex.split(command_text.strip())
    except ValueError:
        return usage

    if len(parts) < 2:
        return usage

    depth = "quick"
    mode = "fresh"
    query_parts: list[str] = []
    i = 1
    while i < len(parts):
        token = parts[i]
        if token.startswith("--depth="):
            depth = token.split("=", 1)[1].strip().lower()
        elif token == "--depth" and i + 1 < len(parts):
            depth = parts[i + 1].strip().lower()
            i += 1
        elif token.startswith("--mode="):
            mode = token.split("=", 1)[1].strip().lower()
        elif token == "--mode" and i + 1 < len(parts):
            mode = parts[i + 1].strip().lower()
            i += 1
        else:
            query_parts.append(token)
        i += 1

    query = " ".join(query_parts).strip()
    if not query:
        return usage
    if depth not in {"quick", "deep"}:
        return "Invalid depth. Use --depth=quick or --depth=deep"
    if mode not in {"fresh", "static"}:
        return "Invalid mode. Use --mode=fresh or --mode=static"

    result = await _schedule_broker.route_operation(
        capability="web",
        action="research",
        params={"query": query, "depth": depth, "mode": mode},
        chat_id=chat_id,
    )
    if not result.allowed:
        message = (result.error or {}).get("message", "Operation denied")
        return f"❌ Web research failed: {message}"

    data = result.result or {}
    search_data = data.get("search", {})
    search_items = search_data.get("results", [])
    fetched_items = data.get("fetched", [])
    lines = [
        f"🔎 Web Research: {data.get('query', query)}",
        f"Mode: {data.get('mode', mode)} | Depth: {data.get('depth', depth)}",
        f"Search results: {len(search_items)} | Fetched pages: {len(fetched_items)}",
    ]
    summary = str(data.get("summary", "")).strip()
    if summary:
        lines.extend(["", "Summary:", summary])

    if fetched_items:
        lines.extend(["", "Sources:"])
        for idx, item in enumerate(fetched_items[:3], start=1):
            title = item.get("title") or item.get("url") or f"Source {idx}"
            lines.append(f"{idx}. {title}")
            lines.append(str(item.get("url", "")))
            if item.get("success"):
                excerpt = str(item.get("excerpt", "")).strip()
                if excerpt:
                    lines.append(excerpt[:240])
            else:
                lines.append(f"Fetch failed: {item.get('error', 'unknown')}")
            lines.append("")
    return "\n".join(lines).strip()


async def handle_notify_command(chat_id: str, command_text: str) -> str:
    """Handle /notify on|off|status command."""
    parts = command_text.strip().split()
    if len(parts) < 2:
        return "Usage: /notify on|off|status"

    action = parts[1].lower()
    if action == "on":
        await set_notifications_enabled(chat_id, True)
        return "Notifications enabled."
    if action == "off":
        await set_notifications_enabled(chat_id, False)
        return "Notifications disabled."
    if action == "status":
        enabled = await get_notifications_enabled(chat_id)
        return "Notifications are ON." if enabled else "Notifications are OFF."
    return "Usage: /notify on|off|status"


def _format_config_value(value: Any) -> str:
    """Render config values for compact Telegram display."""
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_config_value(key: str, raw_value: str) -> Any:
    """Coerce raw `/config set` value to the registry-declared type for key."""
    config_key = get_config_key(key)
    expected = config_key.value_type
    value = raw_value.strip()

    if expected is bool:
        lowered = value.lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
        raise ValueError(
            f"Type mismatch for '{key}': expected bool "
            "(true/false/yes/no/1/0/on/off)"
        )

    if expected is int:
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"Type mismatch for '{key}': expected int") from exc

    if expected is float:
        try:
            return float(value)
        except ValueError as exc:
            raise ValueError(f"Type mismatch for '{key}': expected float") from exc

    if expected is str:
        return value

    raise ValueError(
        f"Unsupported config value type for '{key}': {expected.__name__}"
    )


async def handle_config_command(chat_id: str, command_text: str) -> str:
    """Handle /config show|set|reset command family."""
    _ = chat_id  # Reserved for future auditing/formatting customization.
    usage = "Usage: /config show | set <key>=<value> | reset <key>"
    parts = command_text.strip().split(maxsplit=2)
    if len(parts) < 2:
        return usage

    subcommand = parts[1].lower()

    try:
        config_manager = get_config_manager()
    except RuntimeError as exc:
        return f"Configuration unavailable: {exc}"

    if subcommand == "show":
        lines = ["Configuration", "", "Dynamic Keys:"]
        for key in sorted(get_dynamic_keys()):
            key_def = REGISTRY[key]
            current = _format_config_value(config_manager.get(key))
            default = _format_config_value(key_def.default)
            lines.append(f"`{key} = {current} (default: {default}) [dynamic]`")

        lines.extend(["", "Static Keys:"])
        for key in sorted(get_static_keys()):
            current = _format_config_value(config_manager.get(key))
            lines.append(f"`{key} = {current} [static, restart required]`")

        response = "\n".join(lines)
        if len(response) > 4000:
            return f"{response[:3997]}..."
        return response

    if subcommand == "set":
        if len(parts) < 3 or "=" not in parts[2]:
            return usage

        key, raw_value = parts[2].split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            return usage

        try:
            key_def = get_config_key(key)
            if key_def.tier != "dynamic":
                return f"Key {key} is static — update config/default.toml and restart"

            value = _coerce_config_value(key, raw_value)
            await config_manager.update_dynamic_config(key, value)
            return f"Updated {key} = {_format_config_value(value)}"
        except (KeyError, ValueError) as exc:
            return str(exc)

    if subcommand == "reset":
        if len(parts) < 3:
            return usage

        key = parts[2].strip()
        if not key:
            return usage

        try:
            restored_default = await config_manager.reset_dynamic_config(key)
            return f"Reset {key} to default: {_format_config_value(restored_default)}"
        except (KeyError, ValueError) as exc:
            return str(exc)

    return usage


def _format_elapsed(reference_ts: int) -> str:
    """Format human-readable elapsed time from a Unix timestamp."""
    if reference_ts <= 0:
        return "N/A"

    delta = max(0, int(time.time()) - reference_ts)
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    return f"{delta // 3600}h ago"


def _format_uptime(uptime_seconds: int) -> str:
    """Format process uptime as d/h/m/s."""
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
    parts.append(f"{secs}s")
    return " ".join(parts)


async def handle_status_command(chat_id: str, command_text: str) -> str:
    """Handle /status [resources] command using in-memory observability snapshots."""
    parts = command_text.strip().split()
    mode = parts[1].lower() if len(parts) > 1 else ""

    if mode not in {"", "resources"}:
        return "Usage: /status [resources]"

    if mode == "resources":
        payload = get_resource_snapshot_data()
        if payload is None:
            return "Status unavailable: snapshot not collected yet."

        resources = payload["resources"]
        lag = resources["event_loop_lag_ms"]
        lag_text = "N/A" if lag is None else f"{float(lag):.1f} ms"
        return (
            "Resource Usage\n\n"
            f"CPU: {float(resources['cpu_percent']):.1f}%\n"
            f"RAM: {int(resources['ram_mb'])} MB\n"
            f"Database: {float(resources['db_size_mb']):.1f} MB\n"
            f"Logs: {float(resources['log_size_mb']):.1f} MB\n"
            f"Snapshots: {int(resources['snapshot_count'])}\n"
            f"Event Loop Lag: {lag_text}"
        )

    payload = get_status_snapshot_data()
    if payload is None:
        return "Status unavailable: snapshot not collected yet."

    process = payload["process"]
    scheduler = payload["scheduler"]
    broker = payload["broker"]
    notifier = payload["notifier"]
    in_flight = broker["in_flight_operations"][:5]
    in_flight_count = len(broker["in_flight_operations"])

    if in_flight:
        in_flight_lines = "\n".join(
            f"- {item.get('tool', '?')} (Tier {item.get('tier', '?')}, {item.get('elapsed_s', '?')}s)"
            for item in in_flight
        )
    else:
        in_flight_lines = "- none"

    results = broker["last_10_results"]
    if results:
        result_text = ", ".join(
            f"{status}: {count}" for status, count in sorted(results.items())
        )
    else:
        result_text = "none"

    supervisor = process["supervisor"] or "none"
    supervisor_status = process["supervisor_status"] or "unknown"
    last_tick_ts = int(scheduler["last_tick_timestamp"])
    last_tick = (
        scheduler["last_tick_local"]
        if last_tick_ts <= 0
        else _format_elapsed(last_tick_ts)
    )

    return (
        "System Status\n\n"
        f"Uptime: {_format_uptime(int(process['uptime_seconds']))}\n"
        f"Version: {process['version']}\n"
        f"Supervisor: {supervisor} ({supervisor_status})\n"
        f"Last scheduler tick: {last_tick}\n"
        f"Last broker activity: {_format_elapsed(int(broker['last_operation_timestamp']))}\n"
        f"In-flight operations: {in_flight_count}\n"
        f"{in_flight_lines}\n"
        f"Notification outbox: {int(notifier['pending_count'])} pending\n"
        f"DST transitions handled (today UTC): {get_dst_transition_count()}\n"
        f"Last 10 operations: {result_text}"
    )


async def handle_health_command(chat_id: str) -> str:
    """Handle /health command using in-memory observability snapshots."""
    _ = chat_id  # Reserved for future chat-specific formatting.

    payload = get_health_snapshot()
    if payload is None:
        return "Health unavailable: snapshot not collected yet."

    overall = payload["overall_status"]
    checks = payload["checks"]

    overall_emoji = {
        "healthy": "✅",
        "degraded": "⚠️",
        "unhealthy": "❌",
        "unknown": "❔",
    }.get(overall, "❔")

    if not checks:
        return f"{overall_emoji} System Health: {overall.upper()}\n\nNo health checks available yet."

    lines = [f"{overall_emoji} System Health: {overall.upper()}", "", "Health Checks:"]
    for check in checks:
        status = check["status"]
        status_icon = "✅" if status == "pass" else ("⚠️" if status == "warn" else "❌")
        line = f"{status_icon} {check['name']}: {status} - {check['message']}"
        details = check.get("details") or {}
        if status in {"warn", "fail"} and details:
            detail_text = ", ".join(f"{k}={v}" for k, v in details.items())
            line = f"{line} ({detail_text})"
        lines.append(line)

    return "\n".join(lines)


async def handle_logs_command(chat_id: str, command_text: str, db_path: str) -> str:
    """Handle /logs [hours] command."""
    _ = chat_id  # Reserved for future chat-specific filtering options.
    parts = command_text.strip().split()
    hours = 24

    if len(parts) > 1:
        try:
            hours = int(parts[1])
        except ValueError:
            return "Usage: /logs [hours]\nHours must be a number."

    if hours < 1 or hours > 720:
        return "Usage: /logs [hours]\nHours must be between 1 and 720 (30 days)."

    try:
        logs = await query_operation_logs(db_path=db_path, hours=hours, limit=1000)
    except (RuntimeError, ValueError) as exc:
        return f"Error querying logs: {exc}"

    if not logs:
        return f"No operations found in last {hours} hours."

    max_rows = 50
    lines = [f"📋 Operation Logs (last {hours}h) — {len(logs)} operations", ""]
    status_emoji = {
        "completed": "✅",
        "failed": "❌",
        "in_progress": "⏳",
        "postponed": "⏸️",
        "cancelled": "🚫",
    }

    for entry in logs[:max_rows]:
        op_type = f"{entry.get('capability', '?')}__{entry.get('action', '?')}"
        status = str(entry.get("status", "unknown"))
        timestamp_iso = str(entry.get("timestamp_iso", "unknown-time"))
        duration = entry.get("duration_ms")
        duration_text = f"{int(duration)}ms" if isinstance(duration, int) else "N/A"
        prefix = status_emoji.get(status, "❔")

        line = f"{prefix} {timestamp_iso} | {op_type} | {status} | {duration_text}"

        correlation_id = entry.get("correlation_id")
        if correlation_id:
            corr_preview = str(correlation_id)[:8]
            line = f"{line}\n  Corr: {corr_preview}"

        file_paths = entry.get("file_paths") or []
        if file_paths:
            preview = ", ".join(str(path) for path in file_paths[:3])
            more = len(file_paths) - 3
            if more > 0:
                preview = f"{preview} (+{more} more)"
            line = f"{line}\n  Files: {preview}"

        if status == "failed":
            error_details = entry.get("error_details") or {}
            if isinstance(error_details, dict) and error_details:
                error_message = str(error_details.get("message", "Unknown error"))
                line = f"{line}\n  Error: {error_message[:120]}"

        lines.append(line)

    if len(logs) > max_rows:
        lines.append("")
        lines.append(f"... and {len(logs) - max_rows} more operations")

    return "\n".join(lines)


async def handle_schedule_command(chat_id: str, command_text: str) -> str:
    """Handle /schedule create/list/disable/enable/delete/edit commands."""
    if _schedule_broker is None:
        return "Scheduler unavailable: broker not initialized."

    usage = (
        'Usage: /schedule create <name> "<cron_expr>" <timezone> <action> | '
        "/schedule list | /schedule disable <name> | /schedule enable <name> | "
        '/schedule delete <name> | /schedule edit <name> <cron_expr|timezone|action> "<value>"'
    )

    try:
        parts = shlex.split(command_text.strip())
    except ValueError:
        return usage

    if len(parts) < 2:
        return usage

    subcommand = parts[1].lower()
    if subcommand == "list":
        result = await _schedule_broker.route_operation(
            capability="scheduler",
            action="list",
            params={"enabled_only": False},
            chat_id=chat_id,
        )
        if not result.allowed:
            message = (result.error or {}).get("message", "Operation denied")
            return f"❌ Failed to list schedules: {message}"
        jobs = (result.result or {}).get("jobs", [])
        if not jobs:
            return "No scheduled jobs found."
        lines = ["Scheduled Jobs:"]
        for job in jobs:
            next_run = (job.get("next_run_local") or {}).get("local_datetime") or "unknown"
            enabled = bool(job.get("enabled", False))
            status = "✓ enabled" if enabled else "✗ disabled"
            last_run = job.get("last_completed_slot")
            last_run_text = "never" if not last_run else str(last_run)
            lines.append(
                f"- {job.get('name')} | {status} | cron={job.get('cron_expr')} | tz={job.get('timezone')} | last={last_run_text} | next={next_run}"
            )
        return "\n".join(lines)

    if subcommand == "disable":
        if len(parts) != 3:
            return usage
        name = parts[2]
        result = await _schedule_broker.route_operation(
            capability="scheduler",
            action="disable",
            params={"name": name},
            chat_id=chat_id,
        )
        if not result.allowed:
            message = (result.error or {}).get("message", "Operation denied")
            return f"❌ Failed to disable schedule: {message}"
        if not (result.result or {}).get("updated"):
            return f"❌ Job not found: {name}"
        return f"✅ Job disabled: {name}"

    if subcommand == "enable":
        if len(parts) != 3:
            return usage
        name = parts[2]
        result = await _schedule_broker.route_operation(
            capability="scheduler",
            action="enable",
            params={"name": name},
            chat_id=chat_id,
        )
        if not result.allowed:
            message = (result.error or {}).get("message", "Operation denied")
            return f"❌ Failed to enable schedule: {message}"
        if not (result.result or {}).get("updated"):
            return f"❌ Job not found: {name}"
        list_result = await _schedule_broker.route_operation(
            capability="scheduler",
            action="list",
            params={"enabled_only": False},
            chat_id=chat_id,
        )
        next_run = "unknown"
        if list_result.allowed:
            for job in (list_result.result or {}).get("jobs", []):
                if job.get("name") == name:
                    next_run = (job.get("next_run_local") or {}).get("local_datetime") or "unknown"
                    break
        return f"✅ Job enabled: {name} | Next run: {next_run}"

    if subcommand == "delete":
        if len(parts) != 3:
            return usage
        name = parts[2]
        result = await _schedule_broker.route_operation(
            capability="scheduler",
            action="delete",
            params={"name": name},
            chat_id=chat_id,
        )
        if not result.allowed:
            message = (result.error or {}).get("message", "Operation denied")
            return f"❌ Failed to delete schedule: {message}"
        if not (result.result or {}).get("deleted"):
            return f"❌ Job not found: {name}"
        return f"✅ Job deleted: {name}"

    if subcommand == "edit":
        if len(parts) != 5:
            return usage
        name = parts[2]
        param = parts[3]
        value = parts[4]
        if param not in {"cron_expr", "timezone", "action"}:
            return "❌ Invalid parameter for edit. Allowed: cron_expr, timezone, action"
        result = await _schedule_broker.route_operation(
            capability="scheduler",
            action="edit",
            params={"name": name, "updates": {param: value}},
            chat_id=chat_id,
        )
        if not result.allowed:
            message = (result.error or {}).get("message", "Operation denied")
            return f"❌ Failed to edit schedule: {message}"
        if not (result.result or {}).get("updated"):
            return f"❌ Job not found: {name}"
        job = (result.result or {}).get("job") or {}
        next_run = (job.get("next_run_local") or {}).get("local_datetime") or "unknown"
        return (
            f"✅ Job updated: {name}\n"
            f"Cron: {job.get('cron_expr')}\n"
            f"Timezone: {job.get('timezone')}\n"
            f"Action: {job.get('action')}\n"
            f"Next run: {next_run}"
        )

    if subcommand != "create":
        return usage

    if len(parts) != 6:
        return usage

    _, _, name, cron_expr, timezone, action = parts
    result = await _schedule_broker.route_operation(
        capability="scheduler",
        action="create",
        params={
            "name": name,
            "cron_expr": cron_expr,
            "timezone": timezone,
            "action": action,
            "enabled": True,
        },
        chat_id=chat_id,
    )
    if not result.allowed:
        message = (result.error or {}).get("message", "Operation denied")
        return f"❌ Failed to create schedule: {message}"

    job = result.result or {}
    next_run_text = "unknown"
    try:
        next_run = croniter(job["cron_expr"], datetime.now(ZoneInfo(job["timezone"]))).get_next(datetime)
        next_run_text = next_run.isoformat()
    except Exception:
        pass

    return (
        "✅ Scheduled job created\n\n"
        f"Name: {job.get('name')}\n"
        f"Cron: {job.get('cron_expr')}\n"
        f"Timezone: {job.get('timezone')}\n"
        f"Action: {job.get('action')}\n"
        f"Next run: {next_run_text}"
    )


async def handle_heartbeat_command(chat_id: str, command_text: str) -> str:
    """Handle /heartbeat status|configure|disable|enable command."""
    parts = command_text.strip().split()
    if len(parts) < 2:
        return (
            "Usage: /heartbeat status | configure | disable | enable\n\n"
            "The heartbeat is a daily status report sent automatically."
        )

    subcommand = parts[1].lower()

    try:
        job = await get_job_by_name("Daily Heartbeat")
    except Exception as exc:  # noqa: BLE001
        return f"❌ Failed to query heartbeat job: {exc}"

    if job is None:
        return (
            "❌ Heartbeat job not found.\n\n"
            "The 'Daily Heartbeat' job should be created automatically on startup. "
            "Try restarting SohnBot or create it manually:\n"
            '/schedule create "Daily Heartbeat" "0 18 * * *" UTC heartbeat'
        )

    if subcommand == "status":
        status = "✅ Enabled" if job.get("enabled") else "❌ Disabled"
        next_run = "unknown"
        if _schedule_broker is not None:
            listed = await _schedule_broker.route_operation(
                capability="scheduler",
                action="list",
                params={"enabled_only": False},
                chat_id=chat_id,
            )
            if listed.allowed:
                for listed_job in (listed.result or {}).get("jobs", []):
                    if listed_job.get("name") == "Daily Heartbeat":
                        next_run = (listed_job.get("next_run_local") or {}).get("local_datetime") or "unknown"
                        job = listed_job
                        break
        last_run = job.get("last_completed_slot")
        last_run_text = str(last_run) if last_run else "never"
        return (
            "📊 Heartbeat Status\n\n"
            f"Status: {status}\n"
            f"Schedule: {job.get('cron_expr')}\n"
            f"Timezone: {job.get('timezone')}\n"
            f"Next run: {next_run}\n"
            f"Last run: {last_run_text}"
        )

    if subcommand == "configure":
        return (
            "🔧 Heartbeat Configuration\n\n"
            "To modify the heartbeat schedule, use:\n"
            '/schedule edit "Daily Heartbeat" cron_expr "YOUR_CRON"\n'
            '/schedule edit "Daily Heartbeat" timezone YOUR_TIMEZONE\n\n'
            "Examples:\n"
            '- Daily at 6pm: "0 18 * * *"\n'
            '- Daily at 9am: "0 9 * * *"\n'
            '- Twice daily (9am, 6pm): "0 9,18 * * *"\n\n'
            "Check current status: /heartbeat status"
        )

    if subcommand in {"disable", "enable"}:
        if _schedule_broker is None:
            return "Scheduler unavailable: broker not initialized."
        action = "disable" if subcommand == "disable" else "enable"
        result = await _schedule_broker.route_operation(
            capability="scheduler",
            action=action,
            params={"name": "Daily Heartbeat"},
            chat_id=chat_id,
        )
        if not result.allowed:
            message = (result.error or {}).get("message", "Operation denied")
            return f"❌ Failed to {action} heartbeat: {message}"

        if not (result.result or {}).get("updated"):
            return f"❌ Failed to {action} heartbeat job"

        if action == "disable":
            return "✅ Heartbeat disabled. Re-enable with: /heartbeat enable"

        next_run = "unknown"
        enabled_job = (result.result or {}).get("job")
        if enabled_job:
            next_run = (enabled_job.get("next_run_local") or {}).get("local_datetime") or "unknown"
        return f"✅ Heartbeat enabled. Next report: {next_run}"

    return "Unknown subcommand. Usage:\n/heartbeat status | configure | disable | enable"


async def handle_agent_command() -> str:
    """Handle /agent command - show current agent mode and status."""
    status = get_agent_status()
    return status.get_status_message()


async def handle_help_command() -> str:
    """Handle /help command - show all available commands."""
    return """
🤖 **SohnBot Commands**

**System Information:**
• `/help` - Show this help message
• `/agent` - Check current agent mode (Claude or Gemini fallback)
• `/status` - View system status and active operations
• `/health` - Check system health and component status
• `/logs [filters]` - Query operation logs
  Examples: `/logs status=failed` `/logs capability=fs limit=10`

**Configuration:**
• `/config list` - List all configuration keys
• `/config get <key>` - Get a configuration value
• `/config set <key> <value>` - Update a dynamic setting
  Example: `/config set logging.level DEBUG`

**Notifications:**
• `/notify on` - Enable operation notifications
• `/notify off` - Disable notifications
• `/notify status` - Check notification status

**Scheduled Jobs:**
• `/schedule list` - List all scheduled jobs
• `/schedule create --name <name> --cron <expr> --action <action> --timezone <tz>`
  Example: `/schedule create --name backup --cron "0 2 * * *" --action snapshot_health --timezone UTC`
• `/schedule enable <name>` - Enable a job
• `/schedule disable <name>` - Disable a job
• `/schedule delete <name>` - Delete a job
• `/schedule info <name>` - View job details

**Daily Heartbeat:**
• `/heartbeat enable` - Enable daily health report
• `/heartbeat disable` - Disable daily report
• `/heartbeat status` - Check heartbeat status

**Web Research:**
• `/web_research <query> [--depth=quick|deep] [--mode=fresh|static]`
  Example: `/web_research "weather in Helsinki" --depth=quick`

**Natural Language:**
You can also ask me to do things naturally:
• "Search for 'def main' in src/"
• "Read the README.md file"
• "List Python files in tests/"
• "Show git status"
• "Search the web for Python async patterns"

📖 **Full documentation:** See `docs/USER_GUIDE.md`
    """.strip()
