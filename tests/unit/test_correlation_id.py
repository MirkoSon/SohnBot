"""Unit tests for correlation ID generation, context propagation, and persistence."""

from pathlib import Path
from uuid import UUID
from unittest.mock import AsyncMock

import aiosqlite
import pytest
from structlog.contextvars import get_contextvars

from scripts.migrate import apply_migrations
from src.sohnbot.gateway.telegram_client import TelegramClient
from src.sohnbot.persistence.audit import log_operation_start
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager


def _build_update(chat_id: int = 123456789, text: str = "hello"):
    update = AsyncMock()
    update.effective_chat.id = chat_id
    update.message.text = text
    ack_msg = AsyncMock()
    update.message.reply_text = AsyncMock(return_value=ack_msg)
    return update


@pytest.mark.asyncio
async def test_telegram_message_generates_unique_correlation_id_per_request():
    seen: list[str] = []
    router = AsyncMock()

    async def route_side_effect(*_args, **kwargs):
        seen.append(kwargs["correlation_id"])
        return "ok"

    router.route_to_runtime.side_effect = route_side_effect
    client = TelegramClient(token="test", allowed_chat_ids=[123456789], message_router=router)

    await client.handle_message(_build_update(), None)
    await client.handle_message(_build_update(), None)

    assert len(seen) == 2
    assert seen[0] != seen[1]
    UUID(seen[0])
    UUID(seen[1])


@pytest.mark.asyncio
async def test_correlation_id_bound_in_structlog_context_during_request():
    seen_context: list[str] = []
    router = AsyncMock()

    async def route_side_effect(*_args, **_kwargs):
        seen_context.append(str(get_contextvars().get("correlation_id")))
        return "ok"

    router.route_to_runtime.side_effect = route_side_effect
    client = TelegramClient(token="test", allowed_chat_ids=[123456789], message_router=router)

    await client.handle_message(_build_update(), None)

    assert len(seen_context) == 1
    assert seen_context[0] and seen_context[0] != "None"
    assert get_contextvars().get("correlation_id") is None


@pytest.mark.asyncio
async def test_log_operation_start_persists_correlation_id(tmp_path):
    db_path = tmp_path / "test.db"
    migrations_dir = Path(__file__).parent.parent.parent / "src" / "sohnbot" / "persistence" / "migrations"
    apply_migrations(db_path, migrations_dir)

    db_manager = DatabaseManager(db_path)
    set_db_manager(db_manager)
    try:
        await log_operation_start(
            operation_id="corr-op-1",
            capability="runtime",
            action="clarification",
            chat_id="chat-1",
            tier=0,
            correlation_id="corr-xyz-123",
        )

        async with aiosqlite.connect(str(db_path)) as db:
            cursor = await db.execute(
                "SELECT correlation_id FROM execution_log WHERE operation_id = ?",
                ("corr-op-1",),
            )
            row = await cursor.fetchone()
            await cursor.close()

        assert row is not None
        assert row[0] == "corr-xyz-123"
    finally:
        await db_manager.close()
        set_db_manager(None)  # type: ignore[arg-type]
