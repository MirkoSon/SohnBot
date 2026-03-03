"""Web capability operations backed by Brave Search API."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from urllib.parse import urlparse
from uuid import uuid4
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, TYPE_CHECKING

import aiosqlite
import httpx
import structlog

if TYPE_CHECKING:
    from ..config.manager import ConfigManager
from ..persistence.db import get_db
from ..persistence.notification import enqueue_notification
from ..persistence.search_volume import (
    claim_alert_slot,
    cleanup_old_volume_records,
    increment_daily_search_count,
)

logger = structlog.get_logger(__name__)

BRAVE_SEARCH_API_URL = "https://api.search.brave.com/res/v1/web/search"
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_VALID_MODES = {"fresh", "static"}
_VALID_RESEARCH_DEPTHS = {"quick", "deep"}
_SQLITE_TIME_FMT = "%Y-%m-%d %H:%M:%S"
TIME_SENSITIVE_KEYWORDS = {
    "today",
    "yesterday",
    "tomorrow",
    "latest",
    "recent",
    "current",
    "now",
    "breaking",
    "live",
    "just announced",
    "this week",
    "this month",
    "this year",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}
_LAST_VOLUME_CLEANUP_DATE: str | None = None
_TRUSTED_DOMAIN_HINTS = (
    "docs.",
    ".gov",
    ".edu",
    "wikipedia.org",
    "github.com",
    "developer.",
)

@dataclass
class WebCapabilityError(Exception):
    """Structured error for web capability operations."""

    code: str
    message: str
    details: dict[str, Any] | None = None
    retryable: bool = False

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details or {},
            "retryable": self.retryable,
        }


def _strip_html(value: str) -> str:
    return _HTML_TAG_RE.sub("", value)


def is_time_sensitive(query: str) -> bool:
    """Return True when query likely requires fresh data."""
    text = (query or "").lower()
    if any(keyword in text for keyword in TIME_SENSITIVE_KEYWORDS):
        return True
    current_year = str(datetime.now(timezone.utc).year)
    return current_year in text


async def brave_search(
    query: str,
    mode: Literal["fresh", "static"] = "fresh",
    max_results: int = 5,
    timeout_seconds: int = 5,
    config_manager: "ConfigManager | None" = None,
) -> dict[str, Any]:
    """Query Brave Search and return normalized top results."""
    normalized_query = (query or "").strip()
    if not normalized_query:
        raise WebCapabilityError(
            code="invalid_query",
            message="Search query cannot be empty",
            details={"query": query},
            retryable=False,
        )
    if len(normalized_query) > 500:
        raise WebCapabilityError(
            code="invalid_query",
            message="Search query exceeds 500 characters",
            details={"query_length": len(normalized_query)},
            retryable=False,
        )
    if mode not in _VALID_MODES:
        raise WebCapabilityError(
            code="invalid_mode",
            message="mode must be 'fresh' or 'static'",
            details={"mode": mode},
            retryable=False,
        )

    effective_mode = mode
    bypass_reason = None
    cache_bypassed = False
    if mode == "static" and is_time_sensitive(normalized_query):
        effective_mode = "fresh"
        bypass_reason = "time_sensitive"
        cache_bypassed = True
        logger.info(
            "cache_bypassed_time_sensitive",
            query_length=len(normalized_query),
            mode=mode,
        )

    api_key = os.environ.get("BRAVE_API_KEY", "").strip()
    if not api_key:
        raise WebCapabilityError(
            code="api_key_missing",
            message="Brave API key not configured",
            details={"env_var": "BRAVE_API_KEY"},
            retryable=False,
        )

    capped_results = max(1, min(int(max_results), 5))
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {
        "q": normalized_query,
        "count": capped_results,
    }

    if effective_mode == "static":
        query_hash = get_query_hash(normalized_query, "static")
        try:
            cached = await _get_cached_search(query_hash=query_hash)
        except (aiosqlite.Error, RuntimeError, TypeError, ValueError) as exc:
            logger.warning(
                "cache_lookup_error_fallback",
                query_hash=query_hash,
                error=str(exc),
            )
            cached = None
        if cached is not None:
            logger.info(
                "cache_hit",
                query_hash=query_hash,
                query_length=len(normalized_query),
                mode="static",
            )
            # Volume tracking intentionally counts cache hits too (all successful searches).
            await _track_search_volume_and_alert(
                config_manager=config_manager,
            )
            return cached
        logger.info(
            "cache_miss",
            query_hash=query_hash,
            query_length=len(normalized_query),
            mode="static",
        )

    logger.info(
        "brave_search_started",
        query_length=len(normalized_query),
        mode=effective_mode,
        cache_bypass_reason=bypass_reason,
        max_results=capped_results,
        timeout_seconds=timeout_seconds,
    )

    try:
        async with httpx.AsyncClient() as client:
            async with asyncio.timeout(timeout_seconds):
                response = await client.get(
                    BRAVE_SEARCH_API_URL,
                    headers=headers,
                    params=params,
                )
    except TimeoutError as exc:
        raise WebCapabilityError(
            code="search_timeout",
            message=f"Search timeout exceeded ({timeout_seconds}s)",
            details={"timeout_seconds": timeout_seconds},
            retryable=True,
        ) from exc
    except httpx.TimeoutException as exc:
        raise WebCapabilityError(
            code="search_timeout",
            message=f"Search timeout exceeded ({timeout_seconds}s)",
            details={"timeout_seconds": timeout_seconds},
            retryable=True,
        ) from exc
    except httpx.RequestError as exc:
        raise WebCapabilityError(
            code="network_error",
            message="Network error while contacting Brave Search API",
            details={"reason": str(exc)},
            retryable=True,
        ) from exc

    if response.status_code in (401, 403):
        raise WebCapabilityError(
            code="invalid_api_key",
            message="Invalid API key",
            details={"status_code": response.status_code},
            retryable=False,
        )
    if response.status_code == 429:
        raise WebCapabilityError(
            code="api_quota_exceeded",
            message="API quota exceeded",
            details={"status_code": response.status_code},
            retryable=True,
        )
    if response.status_code >= 500:
        raise WebCapabilityError(
            code="brave_api_error",
            message=f"Brave API error (HTTP {response.status_code})",
            details={"status_code": response.status_code},
            retryable=True,
        )
    if response.status_code >= 400:
        raise WebCapabilityError(
            code="brave_api_error",
            message=f"Brave API error (HTTP {response.status_code})",
            details={"status_code": response.status_code},
            retryable=False,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise WebCapabilityError(
            code="invalid_response",
            message="Brave API returned invalid JSON response",
            retryable=True,
        ) from exc

    raw_results = payload.get("web", {}).get("results", [])
    results: list[dict[str, str]] = []
    for item in raw_results[:capped_results]:
        title = _strip_html(str(item.get("title", "")).strip())
        url = str(item.get("url", "")).strip()
        snippet = _strip_html(str(item.get("description", "")).strip())
        snippet = snippet[:300]
        if not url.startswith(("http://", "https://")):
            continue
        if not title:
            title = url
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
            }
        )

    logger.info(
        "brave_search_completed",
        query_length=len(normalized_query),
        mode=effective_mode,
        total_results=len(results),
    )
    response = {
        "results": results,
        "total_results": len(results),
        "query": normalized_query,
        "mode": mode,
        "effective_mode": effective_mode,
        "cache_bypassed": cache_bypassed,
        "cached": False,
    }

    if effective_mode == "static":
        query_hash = get_query_hash(normalized_query, "static")
        try:
            await _store_search_cache(
                query_hash=query_hash,
                query=normalized_query,
                mode="static",
                result=response,
                config_manager=config_manager,
            )
        except (aiosqlite.Error, RuntimeError, TypeError, ValueError) as exc:
            logger.warning(
                "cache_storage_error_fallback",
                query_hash=query_hash,
                error=str(exc),
            )
    # Volume tracking intentionally counts API-backed responses and cache hits.
    await _track_search_volume_and_alert(
        config_manager=config_manager,
    )
    return response


def _extract_domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def _score_result(item: dict[str, str], query_tokens: set[str]) -> int:
    title = (item.get("title") or "").lower()
    url = (item.get("url") or "").lower()
    domain = _extract_domain(url)
    score = 0
    if any(hint in domain for hint in _TRUSTED_DOMAIN_HINTS):
        score += 3
    if url.startswith("https://"):
        score += 1
    if query_tokens and any(token in title for token in query_tokens):
        score += 1
    return score


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


async def _fetch_page_excerpt(
    url: str,
    timeout_seconds: int = 8,
    max_chars: int = 2500,
) -> dict[str, Any]:
    headers = {
        "User-Agent": "SohnBot/0.1 (+https://github.com/)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            async with asyncio.timeout(timeout_seconds):
                response = await client.get(url, headers=headers)
    except (TimeoutError, httpx.TimeoutException) as exc:
        return {
            "url": url,
            "success": False,
            "error": f"timeout after {timeout_seconds}s",
            "retryable": True,
            "details": str(exc),
        }
    except httpx.RequestError as exc:
        return {
            "url": url,
            "success": False,
            "error": "network error during fetch",
            "retryable": True,
            "details": str(exc),
        }

    if response.status_code >= 400:
        return {
            "url": url,
            "success": False,
            "error": f"http {response.status_code}",
            "retryable": response.status_code >= 500,
            "status_code": response.status_code,
        }

    html = response.text or ""
    # Keep sanitization simple and deterministic: strip script/style blocks and tags.
    stripped = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    stripped = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", stripped)
    stripped = _strip_html(stripped)
    excerpt = _normalize_whitespace(stripped)[:max_chars]
    return {
        "url": url,
        "final_url": str(response.url),
        "status_code": response.status_code,
        "success": True,
        "excerpt": excerpt,
        "char_count": len(excerpt),
    }


async def hybrid_web_research(
    query: str,
    depth: Literal["quick", "deep"] = "quick",
    mode: Literal["fresh", "static"] = "fresh",
    config_manager: "ConfigManager | None" = None,
) -> dict[str, Any]:
    """Run discovery-first web research with selective page fetches."""
    normalized_depth = (depth or "quick").strip().lower()
    if normalized_depth not in _VALID_RESEARCH_DEPTHS:
        raise WebCapabilityError(
            code="invalid_depth",
            message="depth must be 'quick' or 'deep'",
            details={"depth": depth},
            retryable=False,
        )

    search_result = await brave_search(
        query=query,
        mode=mode,
        max_results=5,
        config_manager=config_manager,
    )
    search_items = list(search_result.get("results", []))
    if not search_items:
        return {
            "query": search_result.get("query", query),
            "mode": search_result.get("mode", mode),
            "effective_mode": search_result.get("effective_mode", mode),
            "depth": normalized_depth,
            "search": search_result,
            "fetched": [],
            "summary": "No results found.",
        }

    max_fetches = 2 if normalized_depth == "quick" else 3
    query_tokens = {token for token in re.findall(r"[a-z0-9]{3,}", query.lower())}
    ranked = sorted(
        search_items,
        key=lambda item: _score_result(item, query_tokens),
        reverse=True,
    )

    selected: list[dict[str, str]] = []
    seen_domains: set[str] = set()
    for item in ranked:
        url = item.get("url", "")
        domain = _extract_domain(url)
        if domain and domain in seen_domains:
            continue
        if domain:
            seen_domains.add(domain)
        selected.append(item)
        if len(selected) >= max_fetches:
            break

    fetched_raw = await asyncio.gather(
        *[_fetch_page_excerpt(item.get("url", "")) for item in selected],
    )

    fetched: list[dict[str, Any]] = []
    summary_lines: list[str] = []
    for source, fetched_item in zip(selected, fetched_raw, strict=False):
        combined = {
            "title": source.get("title", ""),
            "source_snippet": source.get("snippet", ""),
            **fetched_item,
        }
        fetched.append(combined)
        if fetched_item.get("success"):
            excerpt = str(fetched_item.get("excerpt", "")).strip()
            if excerpt:
                summary_lines.append(f"- {source.get('title', source.get('url', 'Source'))}: {excerpt[:260]}")
        else:
            summary_lines.append(
                f"- {source.get('title', source.get('url', 'Source'))}: fetch failed ({fetched_item.get('error')})"
            )

    summary = "\n".join(summary_lines[:max_fetches]) if summary_lines else "No fetched content available."
    return {
        "query": search_result.get("query", query),
        "mode": search_result.get("mode", mode),
        "effective_mode": search_result.get("effective_mode", mode),
        "depth": normalized_depth,
        "search": search_result,
        "fetched": fetched,
        "summary": summary,
    }


def get_query_hash(query: str, mode: str) -> str:
    """Generate deterministic cache key for query/mode combination."""
    key = f"{query.strip().lower()}:{mode}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def _get_cached_search(query_hash: str) -> dict[str, Any] | None:
    """Return cached search result when present and not expired."""
    try:
        db = await get_db()
        cursor = await db.execute(
            """
            SELECT query, mode, results_json, created_at
            FROM search_cache
            WHERE query_hash = ?
              AND expires_at > datetime('now')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (query_hash,),
        )
        row = await cursor.fetchone()
        await cursor.close()
    except aiosqlite.Error as exc:
        logger.warning("cache_lookup_error", query_hash=query_hash, error=str(exc))
        return None

    if row is None:
        return None

    query, mode, results_json, created_at = row
    try:
        results = json.loads(results_json)
    except json.JSONDecodeError:
        logger.warning("cache_invalid_json", query_hash=query_hash)
        return None

    if not isinstance(results, list):
        logger.warning("cache_invalid_payload", query_hash=query_hash)
        return None

    return {
        "results": results,
        "total_results": len(results),
        "query": query,
        "mode": mode,
        "effective_mode": mode,
        "cache_bypassed": False,
        "cached": True,
        "cached_at": created_at,
    }


async def _store_search_cache(
    query_hash: str,
    query: str,
    mode: str,
    result: dict[str, Any],
    config_manager: "ConfigManager | None" = None,
) -> None:
    """Persist static-mode search result in SQLite cache."""
    retention_days = 7
    if config_manager is not None:
        try:
            retention_days = int(config_manager.get("search.cache_retention_days"))
        except (TypeError, ValueError, KeyError):
            retention_days = 7

    now = datetime.now(timezone.utc)
    created_at = now.strftime(_SQLITE_TIME_FMT)
    expires_at = (now + timedelta(days=retention_days)).strftime(_SQLITE_TIME_FMT)
    results_json = json.dumps(result.get("results", []))

    try:
        db = await get_db()
        await db.execute(
            """
            INSERT OR REPLACE INTO search_cache
            (query_hash, query, mode, results_json, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (query_hash, query, mode, results_json, created_at, expires_at),
        )
        await db.commit()
        logger.info(
            "cache_stored",
            query_hash=query_hash,
            query_length=len(query),
            result_count=len(result.get("results", [])),
            retention_days=retention_days,
        )
    except (aiosqlite.Error, TypeError, ValueError) as exc:
        logger.warning("cache_storage_error", query_hash=query_hash, error=str(exc))


async def cleanup_expired_cache() -> int:
    """Delete expired cache rows and return deleted row count."""
    try:
        db = await get_db()
        cursor = await db.execute(
            "DELETE FROM search_cache WHERE expires_at < datetime('now')"
        )
        await db.commit()
        deleted_count = int(cursor.rowcount or 0)
        await cursor.close()
        logger.info("cache_cleanup_completed", deleted_count=deleted_count)
        return deleted_count
    except aiosqlite.Error as exc:
        logger.warning("cache_cleanup_error", error=str(exc))
        return 0


async def _track_search_volume_and_alert(
    config_manager: "ConfigManager | None",
) -> None:
    """Increment daily search count and send soft threshold alert once/day."""
    try:
        increment_result = await increment_daily_search_count()
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_volume_tracking_error", reason="increment_failed", error=str(exc))
        return
    if increment_result is None:
        logger.warning("search_volume_tracking_error", reason="increment_failed")
        return
    count, alert_sent = increment_result

    threshold = 100
    if config_manager is not None:
        try:
            threshold = int(config_manager.get("search.volume_alert_threshold"))
        except (TypeError, ValueError, KeyError) as exc:
            logger.warning(
                "search_volume_threshold_config_invalid",
                error=str(exc),
            )
            threshold = 100
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "search_volume_threshold_config_error",
                error=str(exc),
            )
            threshold = 100

    await _maybe_cleanup_volume_records()

    if count <= threshold or alert_sent:
        return

    admin_chat_id = ""
    if config_manager is not None:
        try:
            admin_chat_id = str(config_manager.get("telegram.admin_chat_id") or "").strip()
        except (TypeError, ValueError, KeyError) as exc:
            logger.warning(
                "search_volume_admin_chat_config_invalid",
                error=str(exc),
            )
            admin_chat_id = ""
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "search_volume_admin_chat_config_error",
                error=str(exc),
            )
            admin_chat_id = ""

    if not admin_chat_id:
        logger.warning(
            "search_volume_threshold_exceeded_no_admin",
            count=count,
            threshold=threshold,
        )
        return

    claimed_count = await claim_alert_slot(threshold=threshold)
    if claimed_count is None:
        return

    alert_message = (
        f"⚠️ Search Volume Alert: {claimed_count} searches (threshold: {threshold})\n\n"
        "Monitor Brave API quota to avoid cost overruns."
    )
    operation_id = f"search-volume-alert-{datetime.now(timezone.utc).date().isoformat()}-{uuid4().hex[:8]}"
    try:
        await enqueue_notification(
            operation_id=operation_id,
            chat_id=admin_chat_id,
            message_text=alert_message,
        )
        logger.warning(
            "search_volume_threshold_exceeded",
            count=claimed_count,
            threshold=threshold,
            chat_id=admin_chat_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_volume_alert_enqueue_failed", error=str(exc))


async def _maybe_cleanup_volume_records() -> None:
    """Run volume cleanup at most once per UTC day."""
    global _LAST_VOLUME_CLEANUP_DATE
    today = datetime.now(timezone.utc).date().isoformat()
    if _LAST_VOLUME_CLEANUP_DATE == today:
        return
    try:
        deleted = await cleanup_old_volume_records(retention_days=30)
        _LAST_VOLUME_CLEANUP_DATE = today
        logger.info("search_volume_cleanup_tick", deleted=deleted, date=today)
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_volume_cleanup_failed", error=str(exc))
