"""Unit tests for ambiguity postponement lifecycle."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.sohnbot.runtime.postponement_manager import PostponementManager


@pytest.mark.asyncio
async def test_add_pending_and_has_pending():
    manager = PostponementManager()
    await manager.add_pending("op-1", "123", "do it", ("list files", "search files"))
    assert await manager.has_pending("123") is True


@pytest.mark.asyncio
async def test_resolve_sets_response_text():
    manager = PostponementManager()
    await manager.add_pending("op-1", "123", "do it", ("list files", "search files"))

    pending = await manager.resolve("123", "list files")
    assert pending is not None
    assert pending.response_text == "list files"


@pytest.mark.asyncio
async def test_wait_for_clarification_timeout():
    manager = PostponementManager()
    await manager.add_pending("op-1", "123", "do it", ("list files", "search files"))

    resolved = await manager.wait_for_clarification("123", timeout_seconds=0.01)
    assert resolved is None


@pytest.mark.asyncio
async def test_postpone_and_schedule_logs_postponed_and_retry():
    manager = PostponementManager(retry_delay_seconds=0, cancellation_delay_seconds=3600)
    await manager.add_pending("op-1", "123", "do it", ("list files", "search files"))
    pending = await manager.get_pending("123")
    assert pending is not None

    with (
        patch("src.sohnbot.runtime.postponement_manager.log_operation_end", AsyncMock()) as mock_log_end,
        patch("src.sohnbot.runtime.postponement_manager.enqueue_notification", AsyncMock()) as mock_enqueue,
    ):
        await manager.postpone_and_schedule(pending)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    mock_log_end.assert_called_once_with("op-1", status="postponed")
    assert mock_enqueue.call_count >= 1


@pytest.mark.asyncio
async def test_consume_resolved_removes_pending():
    manager = PostponementManager()
    await manager.add_pending("op-1", "123", "do it", ("list files", "search files"))
    await manager.resolve("123", "list files")

    consumed = await manager.consume_resolved("123")
    assert consumed is not None
    assert consumed.operation_id == "op-1"
    assert await manager.has_pending("123") is False


@pytest.mark.asyncio
async def test_recover_pending_rebuilds_in_memory_and_schedules_tasks():
    manager = PostponementManager(retry_delay_seconds=10, cancellation_delay_seconds=20)
    row = {
        "operation_id": "op-1",
        "chat_id": "123",
        "original_prompt": "do it",
        "option_a": "list files",
        "option_b": "search files",
        "status": "postponed",
        "clarification_response": None,
        "retry_enqueued": 0,
        "created_at": 1,
        "updated_at": 1,
        "clarification_deadline_at": 2,
        "retry_at": manager._now_ts() + 1,
        "cancel_at": manager._now_ts() + 2,
    }
    with patch.object(manager, "_list_active_safely", AsyncMock(return_value=[row])):
        await manager.recover_pending()

    assert await manager.has_pending("123") is True
    assert "op-1" in manager._retry_tasks
    assert "op-1" in manager._cancel_tasks
