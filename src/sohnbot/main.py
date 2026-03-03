"""Runtime startup orchestration for SohnBot."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from uuid import uuid4

import structlog

from .broker.router import Broker
from .broker.scope_validator import ScopeValidator
from .capabilities.scheduler import create_job, get_job_by_name
from .config.manager import get_config_manager
from .capabilities.scheduler.executor import scheduler_executor_loop
from .gateway.message_router import MessageRouter
from .gateway.telegram_client import TelegramClient
from .observability.http_server import http_server_loop
from .observability.snapshot_collector import snapshot_collector_loop
from .persistence.notification import enqueue_notification
from .runtime.agent_session import AgentSession

logger = structlog.get_logger(__name__)


async def initialize_heartbeat_job() -> None:
    """Create default Daily Heartbeat job if it does not already exist."""
    logger.info("heartbeat_initialization_started")

    try:
        existing = await get_job_by_name("Daily Heartbeat")
        if existing is not None:
            logger.info("heartbeat_job_already_exists", job_id=existing.get("id"))
            return

        config = None
        try:
            config = get_config_manager()
        except Exception:  # noqa: BLE001
            config = None

        heartbeat_cron = "0 18 * * *"
        heartbeat_timezone = "UTC"
        timezone_from_config = False

        if config is not None:
            try:
                heartbeat_cron = str(config.get("heartbeat.cron"))
            except Exception:  # noqa: BLE001
                pass

            try:
                heartbeat_timezone = str(config.get("heartbeat.timezone"))
                timezone_from_config = True
            except Exception:  # noqa: BLE001
                pass

        if not timezone_from_config:
            # Best-effort local timezone fallback when config isn't present.
            local_tz_name = getattr(datetime.now().astimezone().tzinfo, "key", None)
            if isinstance(local_tz_name, str) and local_tz_name:
                heartbeat_timezone = local_tz_name

        job = await create_job(
            name="Daily Heartbeat",
            cron_expr=heartbeat_cron,
            timezone=heartbeat_timezone,
            action="heartbeat",
            action_params=None,
            enabled=True,
        )
        logger.info(
            "heartbeat_job_created",
            job_id=job.get("id"),
            cron=heartbeat_cron,
            timezone=heartbeat_timezone,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("heartbeat_initialization_failed", error=str(exc), exc_info=True)


async def initialize_operation_logs_cleanup_job() -> None:
    """Create default weekly operation logs cleanup job if missing."""
    logger.info("operation_logs_cleanup_initialization_started")
    try:
        existing = await get_job_by_name("Operation Logs Cleanup")
        if existing is not None:
            logger.info("operation_logs_cleanup_job_already_exists", job_id=existing.get("id"))
            return

        job = await create_job(
            name="Operation Logs Cleanup",
            cron_expr="0 3 * * 0",
            timezone="UTC",
            action="cleanup_operation_logs",
            action_params={"retention_days": 90},
            enabled=True,
        )
        logger.info("operation_logs_cleanup_job_created", job_id=job.get("id"))
    except Exception as exc:  # noqa: BLE001
        logger.error("operation_logs_cleanup_initialization_failed", error=str(exc), exc_info=True)


async def load_dynamic_config() -> None:
    """Load persisted dynamic config from DB, overlaying DB values onto TOML defaults."""
    try:
        config = get_config_manager()
        await config.load_dynamic_config_from_db()
        logger.info("dynamic_config_loaded")
    except Exception as exc:  # noqa: BLE001
        logger.warning("dynamic_config_load_failed", error=str(exc))


async def run_main() -> None:
    """Run SohnBot with Telegram gateway and background runtime tasks."""
    config = get_config_manager()
    await load_dynamic_config()

    # Load telegram configuration
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        logger.error("telegram_bot_token_missing", message="TELEGRAM_BOT_TOKEN environment variable not set")
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

    # Load allowed chat IDs from config
    try:
        allowed_chat_ids_str = str(config.get("telegram.allowed_chat_ids"))
        allowed_chat_ids = [int(cid.strip()) for cid in allowed_chat_ids_str.split(",") if cid.strip()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram_allowed_chat_ids_parse_failed", error=str(exc))
        allowed_chat_ids = []

    # Validate Claude authentication
    has_oauth = bool(os.getenv("CLAUDE_CODE_OAUTH_TOKEN"))
    has_api_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    if not (has_oauth or has_api_key):
        logger.error(
            "claude_authentication_missing",
            message="Neither CLAUDE_CODE_OAUTH_TOKEN nor ANTHROPIC_API_KEY found in environment"
        )
        raise ValueError(
            "Claude authentication required: set either CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY in .env file"
        )

    # Initialize core components
    scope_validator = ScopeValidator(config=config)
    broker = Broker(scope_validator=scope_validator, config=config)
    agent_session = AgentSession(broker=broker, config=config)

    # Initialize agent session (loads Claude SDK, MCP server, hooks)
    await agent_session.initialize()

    message_router = MessageRouter(agent_session=agent_session)
    telegram_client = TelegramClient(
        token=telegram_token,
        allowed_chat_ids=allowed_chat_ids,
        message_router=message_router,
    )

    # Load background task intervals
    interval = int(config.get("observability.collection_interval_seconds"))
    scheduler_tick = int(config.get("scheduler.tick_seconds"))

    logger.info(
        "sohnbot_starting",
        allowed_chat_count=len(allowed_chat_ids),
        snapshot_interval_seconds=interval,
        scheduler_tick_seconds=scheduler_tick,
        auth_method="oauth" if has_oauth else "api_key",
    )

    async with asyncio.TaskGroup() as tg:
        # Start Telegram gateway
        tg.create_task(
            _safe_telegram_gateway(telegram_client),
            name="telegram-gateway",
        )

        # Start background tasks
        tg.create_task(
            snapshot_collector_loop(interval_seconds=interval),
            name="snapshot-collector",
        )
        tg.create_task(
            scheduler_executor_loop(tick_seconds=scheduler_tick),
            name="scheduler-executor",
        )

        # Initialize default jobs
        await initialize_heartbeat_job()
        await initialize_operation_logs_cleanup_job()

        # Start HTTP observability server if enabled
        http_enabled = bool(config.get("observability.http_enabled"))
        if http_enabled:
            host = str(config.get("observability.http_host"))
            port = int(config.get("observability.http_port"))
            tg.create_task(
                _safe_http_server_loop(host=host, port=port),
                name="http-observability",
            )
            logger.info("http_observability_task_started", host=host, port=port)

        logger.info(
            "sohnbot_started",
            http_enabled=http_enabled,
        )


async def _safe_telegram_gateway(telegram_client: TelegramClient) -> None:
    """Run Telegram gateway with resilient restart behavior."""
    consecutive_failures = 0
    backoff = 2
    max_backoff = 60

    while True:
        try:
            await telegram_client.start()
            consecutive_failures = 0
            backoff = 2
        except asyncio.CancelledError:
            await telegram_client.stop()
            raise
        except Exception as exc:  # noqa: BLE001
            consecutive_failures += 1
            logger.error(
                "telegram_gateway_crash",
                error=str(exc),
                consecutive_failures=consecutive_failures,
                restart_delay_seconds=backoff,
                exc_info=True,
            )

            if consecutive_failures >= 5:
                try:
                    await enqueue_notification(
                        operation_id=f"telegram-gateway-restart-{uuid4()}",
                        chat_id="system",
                        message_text=(
                            "Telegram gateway crashed "
                            f"{consecutive_failures} times. Last error: {exc}"
                        ),
                    )
                except Exception as notify_exc:  # noqa: BLE001
                    logger.warning(
                        "telegram_gateway_crash_notification_failed",
                        error=str(notify_exc),
                        consecutive_failures=consecutive_failures,
                    )

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)


async def _safe_http_server_loop(host: str, port: int) -> None:
    """Run HTTP server loop with resilient restart behavior."""
    consecutive_failures = 0
    backoff = 2
    max_backoff = 60

    while True:
        try:
            await http_server_loop(host=host, port=port)
            consecutive_failures = 0
            backoff = 2
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            consecutive_failures += 1
            logger.error(
                "http_server_crash",
                host=host,
                port=port,
                error=str(exc),
                consecutive_failures=consecutive_failures,
                restart_delay_seconds=backoff,
                exc_info=True,
            )

            if consecutive_failures >= 5:
                try:
                    await enqueue_notification(
                        operation_id=f"http-server-restart-{uuid4()}",
                        chat_id="system",
                        message_text=(
                            "HTTP observability server crashed "
                            f"{consecutive_failures} times. Last error: {exc}"
                        ),
                    )
                except Exception as notify_exc:  # noqa: BLE001
                    logger.warning(
                        "http_server_crash_notification_failed",
                        error=str(notify_exc),
                        consecutive_failures=consecutive_failures,
                    )

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
