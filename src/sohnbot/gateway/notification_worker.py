"""Background worker for notification outbox delivery."""

from __future__ import annotations

import asyncio

import structlog

from ..persistence.notification import (
    get_notification_lag_seconds,
    get_pending_notifications,
    mark_notification_failed,
    mark_notification_sent,
    schedule_notification_retry,
)

logger = structlog.get_logger(__name__)


class NotificationWorker:
    """Poll and deliver pending notifications via Telegram client."""

    def __init__(
        self,
        telegram_client,
        poll_interval_seconds: int = 5,
        batch_size: int = 10,
        max_retries: int = 3,
    ):
        self.telegram_client = telegram_client
        self.poll_interval_seconds = poll_interval_seconds
        self.batch_size = batch_size
        self.max_retries = max_retries
        self._running = False
        self._task: asyncio.Task | None = None
        self._restart_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start polling loop in background task."""
        if self._running and self._task and not self._task.done():
            return
        self._running = True
        self._spawn_worker_task()
        logger.info("notification_worker_started")

    async def stop(self) -> None:
        """Stop polling loop gracefully."""
        self._running = False
        if self._restart_task:
            self._restart_task.cancel()
            self._restart_task = None
        if self._task:
            try:
                await self._task
            except Exception:
                # Crash is already logged by done callback; stop should still complete.
                pass
            self._task = None
        logger.info("notification_worker_stopped")

    def _spawn_worker_task(self) -> None:
        self._task = asyncio.create_task(self._run(), name="notification-worker")
        self._task.add_done_callback(self._on_worker_done)

    def _on_worker_done(self, task: asyncio.Task) -> None:
        if not self._running:
            return
        if task.cancelled():
            logger.warning("notification_worker_cancelled_unexpectedly")
        else:
            exc = task.exception()
            if exc is not None:
                logger.error("notification_worker_crashed", error=str(exc))
            else:
                logger.warning("notification_worker_exited_unexpectedly")

        if self._restart_task and not self._restart_task.done():
            return
        self._restart_task = asyncio.create_task(self._restart_after_delay())

    async def _restart_after_delay(self) -> None:
        await asyncio.sleep(self.poll_interval_seconds)
        if self._running and (self._task is None or self._task.done()):
            self._spawn_worker_task()
            logger.info("notification_worker_restarted")

    async def _run(self) -> None:
        while self._running:
            await self._process_batch()
            await asyncio.sleep(self.poll_interval_seconds)

    async def _process_batch(self) -> None:
        pending = await get_pending_notifications(limit=self.batch_size)
        if not pending:
            return

        for notif in pending:
            await self._process_notification(notif)

        lag_seconds = await get_notification_lag_seconds()
        logger.info(
            "notification_worker_batch_complete",
            batch_size=len(pending),
            lag_seconds=lag_seconds,
        )

    async def _process_notification(self, notif: dict) -> None:
        chat_id_raw = notif["chat_id"]
        try:
            chat_id = int(chat_id_raw)
        except (TypeError, ValueError):
            await mark_notification_failed(notif["id"], "invalid chat_id")
            return

        success = await self.telegram_client.send_message(chat_id, notif["message_text"])
        if success:
            await mark_notification_sent(notif["id"])
            logger.info(
                "notification_sent_from_outbox",
                notification_id=notif["id"],
                chat_id=chat_id_raw,
            )
            return

        await mark_notification_failed(notif["id"], "telegram send failed")
        retry_count = int(notif.get("retry_count", 0)) + 1
        if retry_count < self.max_retries:
            backoff_seconds = self.poll_interval_seconds ** retry_count
            await schedule_notification_retry(notif["id"], backoff_seconds)
            logger.warning(
                "notification_retry_scheduled",
                notification_id=notif["id"],
                retry_count=retry_count,
                backoff_seconds=backoff_seconds,
            )
        else:
            logger.error(
                "notification_retry_exhausted",
                notification_id=notif["id"],
                retry_count=retry_count,
            )
