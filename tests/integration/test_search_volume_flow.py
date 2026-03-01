"""Integration tests for search volume monitoring and alerting."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.broker import BrokerRouter, ScopeValidator
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager


@pytest.fixture
async def setup_database(tmp_path):
    db_path = tmp_path / "test.db"
    migrations_dir = Path(__file__).parent.parent.parent / "src" / "sohnbot" / "persistence" / "migrations"
    apply_migrations(db_path, migrations_dir)
    db_manager = DatabaseManager(db_path)
    set_db_manager(db_manager)
    yield db_manager
    await db_manager.close()


@pytest.mark.asyncio
async def test_volume_alert_triggered_when_threshold_exceeded(tmp_path, setup_database):
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    config = MagicMock()

    def _cfg(key):
        if key == "database.path":
            return str(tmp_path / "test.db")
        if key == "search.volume_alert_threshold":
            return 3
        if key == "telegram.admin_chat_id":
            return "admin-123"
        return None

    config.get.side_effect = _cfg
    router = BrokerRouter(ScopeValidator([str(allowed_root)]), config_manager=config)

    request = httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search")
    response = httpx.Response(
        200,
        request=request,
        json={"web": {"results": [{"title": "T", "url": "https://t.com", "description": "d"}]}},
    )

    with patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}):
        with patch("src.sohnbot.capabilities.web.httpx.AsyncClient.get", new=AsyncMock(return_value=response)):
            with patch("src.sohnbot.capabilities.web.enqueue_notification", new=AsyncMock()) as mock_enqueue:
                for idx in range(4):
                    result = await router.route_operation(
                        capability="web",
                        action="search",
                        params={"query": f"query {idx}", "mode": "fresh"},
                        chat_id="chat-1",
                    )
                    assert result.allowed is True

    assert mock_enqueue.await_count == 1
    kwargs = mock_enqueue.await_args.kwargs
    assert kwargs["chat_id"] == "admin-123"
    assert (
        kwargs["message_text"]
        == "⚠️ Search Volume Alert: 4 searches (threshold: 3)\n\n"
        "Monitor Brave API quota to avoid cost overruns."
    )


@pytest.mark.asyncio
async def test_volume_alert_sent_once_per_day(tmp_path, setup_database):
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    config = MagicMock()

    def _cfg(key):
        if key == "database.path":
            return str(tmp_path / "test.db")
        if key == "search.volume_alert_threshold":
            return 2
        if key == "telegram.admin_chat_id":
            return "admin-123"
        return None

    config.get.side_effect = _cfg
    router = BrokerRouter(ScopeValidator([str(allowed_root)]), config_manager=config)

    request = httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search")
    response = httpx.Response(
        200,
        request=request,
        json={"web": {"results": [{"title": "T", "url": "https://t.com", "description": "d"}]}},
    )

    with patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}):
        with patch("src.sohnbot.capabilities.web.httpx.AsyncClient.get", new=AsyncMock(return_value=response)):
            with patch("src.sohnbot.capabilities.web.enqueue_notification", new=AsyncMock()) as mock_enqueue:
                for idx in range(5):
                    result = await router.route_operation(
                        capability="web",
                        action="search",
                        params={"query": f"query {idx}", "mode": "fresh"},
                        chat_id="chat-1",
                    )
                    assert result.allowed is True

    assert mock_enqueue.await_count == 1
