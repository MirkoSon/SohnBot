"""Manage ambiguous request clarification, postponement, and cancellation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

import structlog

from ..persistence.audit import log_operation_end
from ..persistence.notification import enqueue_notification
from ..persistence.postponement import (
    delete_operation,
    get_active_operation_by_chat,
    list_active_operations,
    mark_operation_cancelled,
    mark_operation_postponed,
    mark_operation_resolved,
    mark_retry_enqueued,
    save_pending_operation,
)

logger = structlog.get_logger(__name__)


@dataclass
class PendingClarification:
    """Track a pending clarification lifecycle for one operation."""

    operation_id: str
    chat_id: str
    original_prompt: str
    options: tuple[str, str]
    response_text: str | None = None
    response_event: asyncio.Event | None = None
    postponed: bool = False
    retry_message_sent: bool = False
    cancelled: bool = False
    retry_at: int | None = None
    cancel_at: int | None = None


class PostponementManager:
    """Coordinate clarification timeout, retry notification, and cancellation."""

    def __init__(
        self,
        clarification_timeout_seconds: int = 60,
        retry_delay_seconds: int = 1800,
        cancellation_delay_seconds: int = 1800,
    ):
        self.clarification_timeout_seconds = clarification_timeout_seconds
        self.retry_delay_seconds = retry_delay_seconds
        self.cancellation_delay_seconds = cancellation_delay_seconds
        self._pending_by_chat: dict[str, PendingClarification] = {}
        self._retry_tasks: dict[str, asyncio.Task] = {}
        self._cancel_tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _now_ts() -> int:
        return int(datetime.now().timestamp())

    async def add_pending(
        self,
        operation_id: str,
        chat_id: str,
        original_prompt: str,
        options: tuple[str, str],
    ) -> None:
        """Register a new ambiguous operation awaiting clarification."""
        async with self._lock:
            self._pending_by_chat[chat_id] = PendingClarification(
                operation_id=operation_id,
                chat_id=chat_id,
                original_prompt=original_prompt,
                options=options,
                response_event=asyncio.Event(),
            )
        await self._save_pending_safely(
            operation_id=operation_id,
            chat_id=chat_id,
            original_prompt=original_prompt,
            options=options,
        )

    async def has_pending(self, chat_id: str) -> bool:
        async with self._lock:
            if chat_id in self._pending_by_chat:
                return True
        return await self._has_pending_in_store(chat_id)

    async def resolve(self, chat_id: str, response_text: str) -> PendingClarification | None:
        """Resolve pending clarification with user response."""
        async with self._lock:
            pending = self._pending_by_chat.get(chat_id)

        if pending is None:
            return None

        pending.response_text = response_text.strip()
        if pending.response_event is not None:
            pending.response_event.set()
        await self._mark_resolved_safely(
            operation_id=pending.operation_id,
            clarification_response=pending.response_text,
        )

        logger.info(
            "clarification_resolved",
            operation_id=pending.operation_id,
            chat_id=chat_id,
            response_preview=response_text[:80],
        )
        return pending

    async def wait_for_clarification(self, chat_id: str, timeout_seconds: int) -> PendingClarification | None:
        """Wait for response on a pending clarification until timeout."""
        async with self._lock:
            pending = self._pending_by_chat.get(chat_id)
        if pending is None or pending.response_event is None:
            return None

        try:
            await asyncio.wait_for(pending.response_event.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return None

        return pending

    async def consume_resolved(self, chat_id: str) -> PendingClarification | None:
        """Remove and return a resolved clarification from pending state."""
        async with self._lock:
            pending = self._pending_by_chat.pop(chat_id, None)
        if pending is None:
            row = await self._get_active_by_chat_safely(chat_id)
            if row is None or row["status"] != "resolved":
                return None
            pending = PendingClarification(
                operation_id=row["operation_id"],
                chat_id=row["chat_id"],
                original_prompt=row["original_prompt"],
                options=(row["option_a"], row["option_b"]),
                response_text=row["clarification_response"],
                response_event=None,
                postponed=False,
                retry_message_sent=bool(row["retry_enqueued"]),
                cancelled=False,
                retry_at=row["retry_at"],
                cancel_at=row["cancel_at"],
            )

        self._cancel_task(pending.operation_id, self._retry_tasks)
        self._cancel_task(pending.operation_id, self._cancel_tasks)
        await self._delete_safely(pending.operation_id)
        return pending

    async def postpone_and_schedule(self, pending: PendingClarification) -> None:
        """Mark operation postponed and schedule retry/cancellation tasks."""
        pending.postponed = True
        pending.retry_at = self._now_ts() + self.retry_delay_seconds
        pending.cancel_at = pending.retry_at + self.cancellation_delay_seconds
        await log_operation_end(pending.operation_id, status="postponed")
        await self._mark_postponed_safely(
            operation_id=pending.operation_id,
            retry_at=pending.retry_at,
            cancel_at=pending.cancel_at,
        )

        retry_task = asyncio.create_task(
            self._send_retry_notification(pending, delay_seconds=self.retry_delay_seconds),
            name=f"postpone-retry-{pending.operation_id}",
        )
        self._retry_tasks[pending.operation_id] = retry_task

        cancel_task = asyncio.create_task(
            self._cancel_if_unresolved(
                pending,
                delay_seconds=self.retry_delay_seconds + self.cancellation_delay_seconds,
            ),
            name=f"postpone-cancel-{pending.operation_id}",
        )
        self._cancel_tasks[pending.operation_id] = cancel_task

    async def _send_retry_notification(self, pending: PendingClarification, delay_seconds: int) -> None:
        await asyncio.sleep(max(0, delay_seconds))
        if not await self.has_pending(pending.chat_id):
            return

        await enqueue_notification(
            operation_id=pending.operation_id,
            chat_id=pending.chat_id,
            message_text=(
                "Your earlier request is still waiting for clarification. "
                f"Reply with one option: '{pending.options[0]}' or '{pending.options[1]}'."
            ),
        )
        pending.retry_message_sent = True
        await self._mark_retry_enqueued_safely(pending.operation_id)
        logger.info(
            "clarification_retry_enqueued",
            operation_id=pending.operation_id,
            chat_id=pending.chat_id,
        )

    async def _cancel_if_unresolved(self, pending: PendingClarification, delay_seconds: int) -> None:
        await asyncio.sleep(max(0, delay_seconds))
        if not await self.has_pending(pending.chat_id):
            return

        async with self._lock:
            active = self._pending_by_chat.get(pending.chat_id)
            if active and active.operation_id == pending.operation_id:
                active.cancelled = True
                self._pending_by_chat.pop(pending.chat_id, None)
            else:
                active = None

        if active is not None:
            await log_operation_end(pending.operation_id, status="cancelled")
            await self._mark_cancelled_safely(pending.operation_id)
            logger.warning(
                "clarification_cancelled",
                operation_id=pending.operation_id,
                chat_id=pending.chat_id,
            )

    @staticmethod
    def build_clarified_prompt(original_prompt: str, clarification_response: str) -> str:
        """Compose a deterministic clarified prompt for runtime processing."""
        return (
            f"{original_prompt}\n\n"
            f"Clarification provided by user: {clarification_response.strip()}"
        )

    async def get_pending(self, chat_id: str) -> PendingClarification | None:
        async with self._lock:
            pending = self._pending_by_chat.get(chat_id)
        if pending is not None:
            return pending

        row = await self._get_active_by_chat_safely(chat_id)
        if row is None:
            return None
        if row["status"] not in {"waiting", "postponed"}:
            return None

        rebuilt = PendingClarification(
            operation_id=row["operation_id"],
            chat_id=row["chat_id"],
            original_prompt=row["original_prompt"],
            options=(row["option_a"], row["option_b"]),
            response_text=row["clarification_response"],
            response_event=asyncio.Event(),
            postponed=(row["status"] == "postponed"),
            retry_message_sent=bool(row["retry_enqueued"]),
            cancelled=False,
            retry_at=row["retry_at"],
            cancel_at=row["cancel_at"],
        )
        async with self._lock:
            self._pending_by_chat[chat_id] = rebuilt
        return rebuilt

    async def recover_pending(self) -> None:
        """Rebuild in-memory state and timers after process restart."""
        rows = await self._list_active_safely()
        if not rows:
            return

        now = self._now_ts()
        for row in rows:
            pending = PendingClarification(
                operation_id=row["operation_id"],
                chat_id=row["chat_id"],
                original_prompt=row["original_prompt"],
                options=(row["option_a"], row["option_b"]),
                response_text=row["clarification_response"],
                response_event=asyncio.Event(),
                postponed=(row["status"] == "postponed"),
                retry_message_sent=bool(row["retry_enqueued"]),
                cancelled=False,
                retry_at=row["retry_at"],
                cancel_at=row["cancel_at"],
            )
            async with self._lock:
                self._pending_by_chat[pending.chat_id] = pending

            # Recover "waiting" records as postponed after restart.
            if row["status"] == "waiting":
                pending.postponed = True
                pending.retry_at = now + self.retry_delay_seconds
                pending.cancel_at = pending.retry_at + self.cancellation_delay_seconds
                await self._mark_postponed_safely(
                    operation_id=pending.operation_id,
                    retry_at=pending.retry_at,
                    cancel_at=pending.cancel_at,
                )

            retry_delay = max(0, (pending.retry_at or (now + self.retry_delay_seconds)) - now)
            cancel_delay = max(
                0,
                (pending.cancel_at or (now + self.retry_delay_seconds + self.cancellation_delay_seconds)) - now,
            )
            if not pending.retry_message_sent:
                self._retry_tasks[pending.operation_id] = asyncio.create_task(
                    self._send_retry_notification(pending, delay_seconds=retry_delay),
                    name=f"postpone-retry-{pending.operation_id}",
                )
            self._cancel_tasks[pending.operation_id] = asyncio.create_task(
                self._cancel_if_unresolved(pending, delay_seconds=cancel_delay),
                name=f"postpone-cancel-{pending.operation_id}",
            )

    @staticmethod
    def _cancel_task(operation_id: str, tasks: dict[str, asyncio.Task]) -> None:
        task = tasks.pop(operation_id, None)
        if task and not task.done():
            task.cancel()

    async def _save_pending_safely(
        self,
        operation_id: str,
        chat_id: str,
        original_prompt: str,
        options: tuple[str, str],
    ) -> None:
        try:
            await save_pending_operation(
                operation_id=operation_id,
                chat_id=chat_id,
                original_prompt=original_prompt,
                option_a=options[0],
                option_b=options[1],
                clarification_deadline_at=self._now_ts() + self.clarification_timeout_seconds,
            )
        except RuntimeError:
            logger.warning("postponement_state_not_persisted_no_db")

    async def _mark_postponed_safely(self, operation_id: str, retry_at: int, cancel_at: int) -> None:
        try:
            await mark_operation_postponed(operation_id=operation_id, retry_at=retry_at, cancel_at=cancel_at)
        except RuntimeError:
            logger.warning("postponement_state_postpone_not_persisted_no_db")

    async def _mark_resolved_safely(self, operation_id: str, clarification_response: str) -> None:
        try:
            await mark_operation_resolved(
                operation_id=operation_id,
                clarification_response=clarification_response,
            )
        except RuntimeError:
            logger.warning("postponement_state_resolve_not_persisted_no_db")

    async def _mark_retry_enqueued_safely(self, operation_id: str) -> None:
        try:
            await mark_retry_enqueued(operation_id=operation_id)
        except RuntimeError:
            logger.warning("postponement_state_retry_not_persisted_no_db")

    async def _mark_cancelled_safely(self, operation_id: str) -> None:
        try:
            await mark_operation_cancelled(operation_id=operation_id)
        except RuntimeError:
            logger.warning("postponement_state_cancel_not_persisted_no_db")

    async def _delete_safely(self, operation_id: str) -> None:
        try:
            await delete_operation(operation_id=operation_id)
        except RuntimeError:
            logger.warning("postponement_state_delete_not_persisted_no_db")

    async def _get_active_by_chat_safely(self, chat_id: str) -> dict | None:
        try:
            return await get_active_operation_by_chat(chat_id=chat_id)
        except RuntimeError:
            return None

    async def _list_active_safely(self) -> list[dict]:
        try:
            return await list_active_operations()
        except RuntimeError:
            return []

    async def _has_pending_in_store(self, chat_id: str) -> bool:
        row = await self._get_active_by_chat_safely(chat_id)
        return row is not None and row["status"] in {"waiting", "postponed"}
