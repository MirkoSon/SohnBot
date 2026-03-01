"""Unit tests for Brave web search capability."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import httpx
import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.capabilities.web import (
    BRAVE_SEARCH_API_URL,
    WebCapabilityError,
    brave_search,
    cleanup_expired_cache,
    get_query_hash,
    is_time_sensitive,
)


@pytest.mark.asyncio
async def test_brave_search_success():
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(
        200,
        request=request,
        json={
            "web": {
                "results": [
                    {
                        "title": "<b>Python Docs</b>",
                        "url": "https://docs.python.org/3/",
                        "description": "<p>Official docs</p>",
                    }
                ]
            }
        },
    )

    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
            new=AsyncMock(return_value=response),
        ):
            result = await brave_search("python asyncio", mode="fresh")

    assert result["total_results"] == 1
    assert result["mode"] == "fresh"
    assert result["effective_mode"] == "fresh"
    assert result["cache_bypassed"] is False
    assert result["cached"] is False
    assert result["results"][0]["title"] == "Python Docs"
    assert result["results"][0]["snippet"] == "Official docs"


@pytest.mark.asyncio
async def test_brave_search_requires_api_key():
    with patch.dict(os.environ, {"BRAVE_API_KEY": ""}):
        with pytest.raises(WebCapabilityError, match="not configured"):
            await brave_search("python asyncio")


@pytest.mark.asyncio
async def test_brave_search_http_401_maps_to_invalid_api_key():
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(401, request=request, json={})

    with patch.dict(os.environ, {"BRAVE_API_KEY": "bad-key"}):
        with patch(
            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
            new=AsyncMock(return_value=response),
        ):
            with pytest.raises(WebCapabilityError, match="Invalid API key"):
                await brave_search("python asyncio")


@pytest.mark.asyncio
async def test_brave_search_http_429_maps_to_quota_error():
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(429, request=request, json={})

    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
            new=AsyncMock(return_value=response),
        ):
            with pytest.raises(WebCapabilityError, match="API quota exceeded"):
                await brave_search("python asyncio")


@pytest.mark.asyncio
async def test_brave_search_timeout_maps_to_search_timeout():
    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
            new=AsyncMock(side_effect=httpx.TimeoutException("timeout")),
        ):
            with pytest.raises(WebCapabilityError, match="Search timeout exceeded"):
                await brave_search("python asyncio", timeout_seconds=5)


@pytest.mark.asyncio
async def test_brave_search_limits_to_five_results():
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    payload = {
        "web": {
            "results": [
                {
                    "title": f"Result {idx}",
                    "url": f"https://example.com/{idx}",
                    "description": "x" * 500,
                }
                for idx in range(8)
            ]
        }
    }
    response = httpx.Response(200, request=request, json=payload)

    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
            new=AsyncMock(return_value=response),
        ):
            result = await brave_search("python asyncio", mode="static", max_results=10)

    assert result["total_results"] == 5
    assert len(result["results"]) == 5
    assert len(result["results"][0]["snippet"]) == 300


def test_get_query_hash_deterministic_and_case_insensitive():
    hash1 = get_query_hash("Python Asyncio", "fresh")
    hash2 = get_query_hash("python asyncio", "fresh")
    hash3 = get_query_hash("python asyncio", "static")

    assert hash1 == hash2
    assert hash1 != hash3
    assert len(hash1) == 64


def test_is_time_sensitive_detection():
    assert is_time_sensitive("latest python news") is True
    assert is_time_sensitive("Python release march notes") is True
    assert is_time_sensitive("today in ai") is True
    assert is_time_sensitive("this week python updates") is True
    current_year = str(datetime.now(timezone.utc).year)
    assert is_time_sensitive(f"python changes {current_year}") is True
    assert is_time_sensitive("python async tutorial") is False


@pytest.fixture
def cache_db(tmp_path):
    db_path = tmp_path / "web-cache.db"
    migrations_dir = Path(__file__).parent.parent.parent / "src" / "sohnbot" / "persistence" / "migrations"
    apply_migrations(db_path, migrations_dir)
    return db_path


@pytest.mark.asyncio
async def test_static_mode_cache_miss_stores_result(cache_db):
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(
        200,
        request=request,
        json={
            "web": {
                "results": [
                    {"title": "Result", "url": "https://example.com", "description": "snippet"}
                ]
            }
        },
    )
    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
            new=AsyncMock(return_value=response),
        ):
            result = await brave_search("python asyncio", mode="static", db_path=str(cache_db))

    assert result["cached"] is False
    assert result["effective_mode"] == "static"
    assert result["cache_bypassed"] is False
    query_hash = get_query_hash("python asyncio", "static")
    async with aiosqlite.connect(str(cache_db)) as db:
        cursor = await db.execute(
            "SELECT query, mode FROM search_cache WHERE query_hash = ?",
            (query_hash,),
        )
        row = await cursor.fetchone()
        await cursor.close()
    assert row is not None
    assert row[0] == "python asyncio"
    assert row[1] == "static"


@pytest.mark.asyncio
async def test_static_mode_cache_hit_skips_api_call(cache_db):
    query = "python asyncio"
    query_hash = get_query_hash(query, "static")
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(str(cache_db)) as db:
        await db.execute(
            """
            INSERT INTO search_cache (query_hash, query, mode, results_json, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                query_hash,
                query,
                "static",
                '[{"title":"Cached","url":"https://cached.example","snippet":"cached"}]',
                created_at,
                expires_at,
            ),
        )
        await db.commit()

    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
            new=AsyncMock(),
        ) as mock_get:
            result = await brave_search(query, mode="static", db_path=str(cache_db))

    assert result["cached"] is True
    assert result["mode"] == "static"
    assert result["effective_mode"] == "static"
    assert result["cache_bypassed"] is False
    assert result["results"][0]["title"] == "Cached"
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_fresh_mode_bypasses_cache(cache_db):
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(
        200,
        request=request,
        json={
            "web": {"results": [{"title": "Fresh", "url": "https://fresh.example", "description": "fresh"}]}
        },
    )
    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
            new=AsyncMock(return_value=response),
        ) as mock_get:
            result = await brave_search("python asyncio", mode="fresh", db_path=str(cache_db))

    assert result["cached"] is False
    assert result["mode"] == "fresh"
    assert result["effective_mode"] == "fresh"
    assert result["cache_bypassed"] is False
    mock_get.assert_awaited_once()


@pytest.mark.asyncio
async def test_time_sensitive_static_query_bypasses_cache(cache_db):
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(
        200,
        request=request,
        json={"web": {"results": [{"title": "Live", "url": "https://live.example", "description": "live"}]}},
    )
    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
            new=AsyncMock(return_value=response),
        ):
            result = await brave_search("latest python news", mode="static", db_path=str(cache_db))

    assert result["cached"] is False
    assert result["mode"] == "static"
    assert result["effective_mode"] == "fresh"
    assert result["cache_bypassed"] is True


@pytest.mark.asyncio
async def test_cleanup_expired_cache_removes_old_rows(cache_db):
    query_hash = get_query_hash("old query", "static")
    created_at = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    expires_at = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(str(cache_db)) as db:
        await db.execute(
            """
            INSERT INTO search_cache (query_hash, query, mode, results_json, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (query_hash, "old query", "static", "[]", created_at, expires_at),
        )
        await db.commit()

    deleted = await cleanup_expired_cache(str(cache_db))
    assert deleted == 1


@pytest.mark.asyncio
async def test_cache_retention_days_from_config(cache_db):
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(
        200,
        request=request,
        json={
            "web": {"results": [{"title": "Result", "url": "https://example.com", "description": "snippet"}]}
        },
    )
    config = AsyncMock()
    config.get = lambda key: 2 if key == "search.cache_retention_days" else None
    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
            new=AsyncMock(return_value=response),
        ):
            await brave_search(
                "retention test",
                mode="static",
                db_path=str(cache_db),
                config_manager=config,
            )

    query_hash = get_query_hash("retention test", "static")
    async with aiosqlite.connect(str(cache_db)) as db:
        cursor = await db.execute(
            "SELECT created_at, expires_at FROM search_cache WHERE query_hash = ?",
            (query_hash,),
        )
        row = await cursor.fetchone()
        await cursor.close()
    assert row is not None
    created_at = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    expires_at = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
    assert (expires_at - created_at).days == 2


@pytest.mark.asyncio
async def test_cache_lookup_error_falls_back_to_api(cache_db):
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(
        200,
        request=request,
        json={"web": {"results": [{"title": "Fallback", "url": "https://example.com", "description": "ok"}]}},
    )
    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web._get_cached_search",
            new=AsyncMock(side_effect=aiosqlite.Error("lookup failed")),
        ):
            with patch(
                "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
                new=AsyncMock(return_value=response),
            ) as mock_get:
                result = await brave_search("python asyncio", mode="static", db_path=str(cache_db))

    assert result["cached"] is False
    mock_get.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_storage_error_does_not_fail_search(cache_db):
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(
        200,
        request=request,
        json={"web": {"results": [{"title": "Stored", "url": "https://example.com", "description": "ok"}]}},
    )
    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web._get_cached_search",
            new=AsyncMock(return_value=None),
        ):
            with patch(
                "src.sohnbot.capabilities.web._store_search_cache",
                new=AsyncMock(side_effect=ValueError("storage failed")),
            ):
                with patch(
                    "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
                    new=AsyncMock(return_value=response),
                ):
                    result = await brave_search("python asyncio", mode="static", db_path=str(cache_db))

    assert result["cached"] is False
    assert result["total_results"] == 1


@pytest.mark.asyncio
async def test_time_sensitive_bypass_preserves_requested_mode(cache_db):
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(
        200,
        request=request,
        json={"web": {"results": [{"title": "Live", "url": "https://example.com", "description": "news"}]}},
    )
    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
            new=AsyncMock(return_value=response),
        ):
            result = await brave_search("latest python news", mode="static", db_path=str(cache_db))

    assert result["cached"] is False
    assert result["mode"] == "static"
    assert result["effective_mode"] == "fresh"
    assert result["cache_bypassed"] is True


@pytest.mark.asyncio
async def test_brave_search_increments_daily_volume_counter(cache_db):
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(
        200,
        request=request,
        json={"web": {"results": [{"title": "R", "url": "https://example.com", "description": "d"}]}},
    )
    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.increment_daily_search_count",
            new=AsyncMock(return_value=(1, False)),
        ) as mock_increment:
            with patch(
                "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
                new=AsyncMock(return_value=response),
            ):
                await brave_search("volume check", mode="fresh", db_path=str(cache_db))
    mock_increment.assert_awaited_once()


@pytest.mark.asyncio
async def test_brave_search_sends_volume_alert_when_threshold_exceeded(cache_db):
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(
        200,
        request=request,
        json={"web": {"results": [{"title": "R", "url": "https://example.com", "description": "d"}]}},
    )
    config = AsyncMock()
    config.get = lambda key: (
        3 if key == "search.volume_alert_threshold"
        else ("admin-1" if key == "telegram.admin_chat_id" else None)
    )

    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.increment_daily_search_count",
            new=AsyncMock(return_value=(4, False)),
        ):
            with patch(
                "src.sohnbot.capabilities.web.claim_alert_slot",
                new=AsyncMock(return_value=4),
            ) as mock_claim:
                with patch(
                    "src.sohnbot.capabilities.web.enqueue_notification",
                    new=AsyncMock(),
                ) as mock_enqueue:
                    with patch(
                        "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
                        new=AsyncMock(return_value=response),
                    ):
                        await brave_search(
                            "volume alert",
                            mode="fresh",
                            db_path=str(cache_db),
                            config_manager=config,
                        )
    mock_claim.assert_awaited_once_with(db_path=str(cache_db), threshold=3)
    mock_enqueue.assert_awaited_once()
    kwargs = mock_enqueue.await_args.kwargs
    assert kwargs["chat_id"] == "admin-1"
    assert kwargs["message_text"].startswith("⚠️ Search Volume Alert: 4 searches (threshold: 3)")
    assert "Monitor Brave API quota to avoid cost overruns." in kwargs["message_text"]


@pytest.mark.asyncio
async def test_brave_search_volume_alert_fallback_on_threshold_config_exception(cache_db):
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(
        200,
        request=request,
        json={"web": {"results": [{"title": "R", "url": "https://example.com", "description": "d"}]}},
    )
    config = AsyncMock()

    def _cfg(key):
        if key == "search.volume_alert_threshold":
            raise RuntimeError("config backend unavailable")
        if key == "telegram.admin_chat_id":
            return "admin-1"
        return None

    config.get = _cfg
    bound_logger = MagicMock()

    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch("src.sohnbot.capabilities.web.logger", bound_logger):
            with patch(
                "src.sohnbot.capabilities.web.increment_daily_search_count",
                new=AsyncMock(return_value=(101, False)),
            ):
                with patch(
                    "src.sohnbot.capabilities.web.claim_alert_slot",
                    new=AsyncMock(return_value=101),
                ) as mock_claim:
                    with patch(
                        "src.sohnbot.capabilities.web.enqueue_notification",
                        new=AsyncMock(),
                    ) as mock_enqueue:
                        with patch(
                            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
                            new=AsyncMock(return_value=response),
                        ):
                            await brave_search(
                                "volume alert",
                                mode="fresh",
                                db_path=str(cache_db),
                                config_manager=config,
                            )
    bound_logger.warning.assert_any_call(
        "search_volume_threshold_config_error",
        error="config backend unavailable",
    )
    mock_claim.assert_awaited_once_with(db_path=str(cache_db), threshold=100)
    mock_enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_brave_search_volume_alert_skip_when_claim_not_acquired(cache_db):
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(
        200,
        request=request,
        json={"web": {"results": [{"title": "R", "url": "https://example.com", "description": "d"}]}},
    )
    config = AsyncMock()
    config.get = lambda key: (
        3 if key == "search.volume_alert_threshold"
        else ("admin-1" if key == "telegram.admin_chat_id" else None)
    )

    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.increment_daily_search_count",
            new=AsyncMock(return_value=(4, False)),
        ):
            with patch(
                "src.sohnbot.capabilities.web.claim_alert_slot",
                new=AsyncMock(return_value=None),
            ) as mock_claim:
                with patch(
                    "src.sohnbot.capabilities.web.enqueue_notification",
                    new=AsyncMock(),
                ) as mock_enqueue:
                    with patch(
                        "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
                        new=AsyncMock(return_value=response),
                    ):
                        await brave_search(
                            "volume no-claim",
                            mode="fresh",
                            db_path=str(cache_db),
                            config_manager=config,
                        )
    mock_claim.assert_awaited_once_with(db_path=str(cache_db), threshold=3)
    mock_enqueue.assert_not_awaited()
