"""Integration tests for web search flow through broker."""

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import AsyncMock, patch

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
async def test_web_search_full_flow(tmp_path, setup_database):
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()
    router = BrokerRouter(ScopeValidator([str(allowed_root)]))

    request = httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search")
    response = httpx.Response(
        200,
        request=request,
        json={
            "web": {
                "results": [
                    {
                        "title": "Python AsyncIO",
                        "url": "https://docs.python.org/3/library/asyncio.html",
                        "description": "AsyncIO docs",
                    },
                    {
                        "title": "Real Python Async",
                        "url": "https://realpython.com/async-io-python/",
                        "description": "Async guide",
                    },
                ]
            }
        },
    )

    with patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
            new=AsyncMock(return_value=response),
        ):
            result = await router.route_operation(
                capability="web",
                action="search",
                params={"query": "python asyncio", "mode": "fresh"},
                chat_id="chat-web-int",
            )

    assert result.allowed is True
    assert result.tier == 0
    assert result.result is not None
    assert result.result["total_results"] == 2
    assert result.result["results"][0]["url"].startswith("https://")


@pytest.mark.asyncio
async def test_search_cache_table_exists_after_migrations(tmp_path, setup_database):
    db = await setup_database.get_connection()
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='search_cache'"
    )
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None

    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_search_cache_query_hash'"
    )
    index_row = await cursor.fetchone()
    await cursor.close()
    assert index_row is not None


@pytest.mark.asyncio
async def test_web_search_cache_flow_miss_then_hit(tmp_path, setup_database):
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    config = MagicMock()

    def _cfg(key):
        if key == "database.path":
            return str(tmp_path / "test.db")
        if key == "search.cache_retention_days":
            return 7
        return None

    config.get.side_effect = _cfg
    router = BrokerRouter(ScopeValidator([str(allowed_root)]), config_manager=config)

    request = httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search")
    response = httpx.Response(
        200,
        request=request,
        json={
            "web": {
                "results": [
                    {
                        "title": "Cached Candidate",
                        "url": "https://example.com/cached",
                        "description": "cache me",
                    }
                ]
            }
        },
    )

    with patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
            new=AsyncMock(return_value=response),
        ) as mock_get:
            first = await router.route_operation(
                capability="web",
                action="search",
                params={"query": "python asyncio tutorial", "mode": "static"},
                chat_id="chat-web-int",
            )
            second = await router.route_operation(
                capability="web",
                action="search",
                params={"query": "python asyncio tutorial", "mode": "static"},
                chat_id="chat-web-int",
            )

    assert first.allowed is True
    assert second.allowed is True
    assert first.result["cached"] is False
    assert second.result["cached"] is True
    assert mock_get.await_count == 1
