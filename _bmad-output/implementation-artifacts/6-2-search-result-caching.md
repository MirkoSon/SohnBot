# Story 6.2: Search Result Caching

**Epic**: Epic 6 - Research & Web Search
**Story Key**: 6-2-search-result-caching
**Status**: done
**Created**: 2026-03-01

---

## Story Overview

**As a** user,
**I want** static search results cached for 7 days,
**So that** repeated searches don't consume API quota.

### Business Value
- **Cost Savings**: Reduce Brave API quota consumption for repeated queries
- **Performance**: Instant results for cached queries (<10ms vs 3s API call)
- **Reliability**: Cached results available even during API outages
- **User Experience**: Faster response times for common research queries

---

## Functional Requirements

### FR-025: Search Result Caching
**Priority**: HIGH
**Source**: epics.md lines 1184-1204

The system MUST cache static search results:

1. **Cache Strategy**
   - Cache only `mode="static"` queries
   - `mode="fresh"` always bypasses cache (direct API call)
   - Cache key: SHA256 hash of `query.lower() + mode`
   - Cache duration: 7 days (configurable via `search.cache_retention_days`)

2. **Cache Lookup**
   - Before calling Brave API, check `search_cache` table
   - Match on `query_hash` + `expires_at > now()`
   - If cache hit: return cached results, set `cached=True`
   - If cache miss: call API, store results, return with `cached=False`

3. **Time-Sensitive Query Detection**
   - Keywords that bypass cache (even in static mode):
     - Date references: "today", "yesterday", "2026", "march", "this week"
     - Temporal qualifiers: "latest", "recent", "current", "now"
     - Breaking news: "breaking", "live", "just announced"
   - Case-insensitive keyword detection
   - Bypass cache if any keyword found in query

4. **Cache Storage**
   - Store in `search_cache` table (created in Story 6.1)
   - Fields: `query_hash`, `query`, `mode`, `results_json`, `created_at`, `expires_at`
   - `results_json`: JSON-serialized results array
   - `expires_at`: `created_at` + `cache_retention_days`
   - Insert new entry after successful API call (static mode only)

5. **Cache Expiration**
   - Automatic expiration: queries with `expires_at < now()` ignored
   - Manual cleanup: periodic job to delete expired entries (Story 6.3 or background task)
   - Config: `search.cache_retention_days` (default: 7, range: 1-90)

---

## Non-Functional Requirements

### NFR-021: Automated Cleanup
**Priority**: MEDIUM
**Source**: epics.md line 108

- Expired cache entries deleted automatically (background job or manual cleanup)
- Retention period: 7 days default (configurable)
- Cleanup job runs daily (or on-demand via /cleanup command)
- Database size monitored (cache table shouldn't exceed reasonable size)

### NFR-029: Cache Performance
**Priority**: HIGH

- Cache lookup: <10ms (SQLite indexed query)
- Cache hit rate target: >50% for common queries
- Cache storage overhead: <1MB per 100 cached queries
- No memory caching (SQLite only, reduces memory footprint)

### NFR-030: Cache Accuracy
**Priority**: MEDIUM

- Cached results match fresh API results (within 7 days)
- Time-sensitive queries always return fresh data
- Cache invalidation is deterministic (no stale data beyond retention period)
- No cache poisoning (query_hash uniquely identifies query+mode)

---

## Acceptance Criteria

### AC-025.1: Cache Lookup for Static Mode
- [x] `brave_search()` checks cache before API call (static mode only)
- [x] Cache lookup: `SELECT * FROM search_cache WHERE query_hash = ? AND expires_at > datetime('now')`
- [x] Cache hit: return cached results with `cached=True`
- [x] Cache miss: proceed to API call

### AC-025.2: Cache Storage After API Call
- [x] After successful API call (static mode only), insert into `search_cache`
- [x] Fields populated: `query_hash`, `query`, `mode`, `results_json`, `created_at`, `expires_at`
- [x] `results_json`: JSON string of results array
- [x] `expires_at`: calculated as `created_at + cache_retention_days`
- [x] Duplicate inserts handled gracefully (IGNORE or REPLACE)

### AC-025.3: Fresh Mode Bypasses Cache
- [x] `mode="fresh"` queries skip cache lookup
- [x] Fresh mode queries do NOT insert into cache
- [x] Fresh mode always returns `cached=False`

### AC-025.4: Time-Sensitive Query Detection
- [x] Keywords detected: "today", "yesterday", "latest", "recent", "current", "now", "2026" (current year), month names, "this week", "breaking", "live"
- [x] Case-insensitive detection
- [x] If keyword found, skip cache lookup (even in static mode)
- [x] Log: `cache_bypassed_time_sensitive` event

### AC-025.5: Cache Expiration
- [x] Expired entries (`expires_at < now()`) not returned
- [x] Cleanup function: `DELETE FROM search_cache WHERE expires_at < datetime('now')`
- [x] Cleanup can be triggered manually or via background job
- [x] Config: `search.cache_retention_days` (default: 7, validator: 1-90)

### AC-025.6: Cache Metrics
- [x] Log cache hit/miss events with structured data
- [x] Track cache hit rate (hits / total queries)
- [x] Expose cache stats in observability (optional enhancement)

---

## Implementation Guidance

### Architecture Context

```
src/sohnbot/capabilities/
└── web.py                      # UPDATE: Add cache lookup/storage logic

src/sohnbot/persistence/
└── db.py                       # UPDATE: Add cache query functions (optional helper)

config/
└── default.toml                # VERIFY: search.cache_retention_days = 7

tests/unit/
└── test_web.py                 # UPDATE: Add cache tests

tests/integration/
└── test_web_search_flow.py     # UPDATE: Add cache integration tests
```

### Key Implementation Tasks

#### Task 6.2.1: Add Time-Sensitive Keyword Detection
**File**: `src/sohnbot/capabilities/web.py` (UPDATE)

**Add keyword detection function** (before `brave_search`):

```python
# Time-sensitive keywords that bypass cache
TIME_SENSITIVE_KEYWORDS = {
    "today", "yesterday", "tomorrow",
    "latest", "recent", "current", "now",
    "breaking", "live", "just announced",
    "this week", "this month", "this year",
    # Month names
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
}


def is_time_sensitive(query: str) -> bool:
    """
    Check if query contains time-sensitive keywords that should bypass cache.

    Args:
        query: Search query string.

    Returns:
        True if query contains time-sensitive keywords, False otherwise.
    """
    query_lower = query.lower()

    # Check for time-sensitive keywords
    if any(keyword in query_lower for keyword in TIME_SENSITIVE_KEYWORDS):
        return True

    # Check for current year (e.g., "2026")
    import datetime
    current_year = str(datetime.datetime.now(datetime.timezone.utc).year)
    if current_year in query:
        return True

    return False
```

#### Task 6.2.2: Add Cache Lookup Logic
**File**: `src/sohnbot/capabilities/web.py` (UPDATE)

**Import aiosqlite and add cache lookup** (update `brave_search` function):

```python
import aiosqlite
import json
from datetime import datetime, timedelta, timezone

# Add to imports at top

async def brave_search(
    query: str,
    mode: Literal["fresh", "static"] = "fresh",
    max_results: int = 5,
    timeout_seconds: int = 5,
    db_path: str = "data/sohnbot.db",  # NEW parameter
) -> dict[str, Any]:
    """Query Brave Search and return normalized top results."""
    normalized_query = (query or "").strip()

    # ... existing validation code ...

    # NEW: Check if query is time-sensitive
    if is_time_sensitive(normalized_query):
        logger.info(
            "cache_bypassed_time_sensitive",
            query_length=len(normalized_query),
            mode=mode,
        )
        # Force fresh mode for time-sensitive queries
        mode = "fresh"

    # NEW: Cache lookup for static mode
    if mode == "static":
        query_hash = get_query_hash(normalized_query, mode)
        cached_result = await _get_cached_search(db_path, query_hash)

        if cached_result is not None:
            logger.info(
                "cache_hit",
                query_length=len(normalized_query),
                mode=mode,
                query_hash=query_hash,
            )
            return cached_result

        logger.debug(
            "cache_miss",
            query_length=len(normalized_query),
            mode=mode,
            query_hash=query_hash,
        )

    # ... existing API call code ...

    # After successful API call (before return)
    result = {
        "results": results,
        "total_results": len(results),
        "query": normalized_query,
        "mode": mode,
        "cached": False,
    }

    # NEW: Store in cache if static mode
    if mode == "static":
        query_hash = get_query_hash(normalized_query, mode)
        await _store_search_cache(db_path, query_hash, normalized_query, mode, result)

    logger.info(
        "brave_search_completed",
        query_length=len(normalized_query),
        mode=mode,
        total_results=len(results),
        cached=False,
    )

    return result
```

#### Task 6.2.3: Add Cache Database Functions
**File**: `src/sohnbot/capabilities/web.py` (UPDATE)

**Add cache helper functions** (after `get_query_hash`):

```python
async def _get_cached_search(db_path: str, query_hash: str) -> dict[str, Any] | None:
    """
    Retrieve cached search results if not expired.

    Args:
        db_path: Path to SQLite database.
        query_hash: SHA256 hash of query+mode.

    Returns:
        Cached result dict with cached=True, or None if not found/expired.
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                """
                SELECT query, mode, results_json, created_at
                FROM search_cache
                WHERE query_hash = ? AND expires_at > datetime('now')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (query_hash,),
            ) as cursor:
                row = await cursor.fetchone()

        if row is None:
            return None

        query, mode, results_json, created_at = row

        # Deserialize results
        try:
            results = json.loads(results_json)
        except json.JSONDecodeError:
            logger.warning("cache_invalid_json", query_hash=query_hash)
            return None

        return {
            "results": results,
            "total_results": len(results),
            "query": query,
            "mode": mode,
            "cached": True,
            "cached_at": created_at,
        }

    except Exception as exc:
        logger.warning("cache_lookup_error", error=str(exc), query_hash=query_hash)
        return None


async def _store_search_cache(
    db_path: str,
    query_hash: str,
    query: str,
    mode: str,
    result: dict[str, Any],
) -> None:
    """
    Store search results in cache.

    Args:
        db_path: Path to SQLite database.
        query_hash: SHA256 hash of query+mode.
        query: Original query string.
        mode: Search mode ("static" only).
        result: Search result dict with results list.
    """
    try:
        # Read cache retention config (default: 7 days)
        cache_retention_days = 7

        created_at = datetime.now(timezone.utc).isoformat()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=cache_retention_days)
        ).isoformat()

        results_json = json.dumps(result["results"])

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO search_cache
                (query_hash, query, mode, results_json, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (query_hash, query, mode, results_json, created_at, expires_at),
            )
            await db.commit()

        logger.debug(
            "cache_stored",
            query_hash=query_hash,
            query_length=len(query),
            results_count=len(result["results"]),
            expires_at=expires_at,
        )

    except Exception as exc:
        logger.warning("cache_storage_error", error=str(exc), query_hash=query_hash)
        # Don't raise - cache storage failure shouldn't fail the search


async def cleanup_expired_cache(db_path: str) -> int:
    """
    Delete expired cache entries.

    Args:
        db_path: Path to SQLite database.

    Returns:
        Number of entries deleted.
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "DELETE FROM search_cache WHERE expires_at < datetime('now')"
            )
            await db.commit()
            deleted = cursor.rowcount

        logger.info("cache_cleanup_completed", deleted_count=deleted)
        return deleted

    except Exception as exc:
        logger.error("cache_cleanup_error", error=str(exc))
        return 0
```

#### Task 6.2.4: Update Config Validation (Optional)
**File**: `src/sohnbot/config/registry.py` (UPDATE)

**Verify cache_retention_days config** (should already exist from Story 6.1):

```python
ConfigKey(
    "search.cache_retention_days",
    ConfigTier.DYNAMIC,
    int,
    default=7,
    validator=lambda v: 1 <= int(v) <= 90,  # Between 1 and 90 days
),
```

#### Task 6.2.5: Integrate Config with Cache Storage
**File**: `src/sohnbot/capabilities/web.py` (UPDATE)

**Update `_store_search_cache` to read config**:

```python
async def _store_search_cache(
    db_path: str,
    query_hash: str,
    query: str,
    mode: str,
    result: dict[str, Any],
    config_manager: ConfigManager | None = None,  # NEW parameter
) -> None:
    """Store search results in cache."""
    try:
        # Read cache retention config
        cache_retention_days = 7  # Default
        if config_manager:
            try:
                cache_retention_days = int(
                    config_manager.get("search.cache_retention_days")
                )
            except Exception:
                pass  # Use default on error

        # ... rest of function ...
```

**Update `brave_search` signature**:

```python
async def brave_search(
    query: str,
    mode: Literal["fresh", "static"] = "fresh",
    max_results: int = 5,
    timeout_seconds: int = 5,
    db_path: str = "data/sohnbot.db",
    config_manager: ConfigManager | None = None,  # NEW parameter
) -> dict[str, Any]:
    # ...

    # Pass config_manager to cache storage
    await _store_search_cache(
        db_path, query_hash, normalized_query, mode, result, config_manager
    )
```

#### Task 6.2.6: Update Broker to Pass DB Path and Config
**File**: `src/sohnbot/broker/router.py` (UPDATE)

**Update web operation routing** (in `_execute_capability` method):

```python
if capability == "web":
    from ..capabilities.web import brave_search

    if action == "search":
        # Get db_path from config or use default
        db_path = "data/sohnbot.db"
        if self.config_manager:
            try:
                db_path = self.config_manager.get("database.path")
            except Exception:
                pass

        result = await brave_search(
            query=params["query"],
            mode=params.get("mode", "fresh"),
            db_path=db_path,
            config_manager=self.config_manager,  # NEW
        )
        return result
```

---

## Review Follow-ups (Code Review - 2026-03-01)

### HIGH Priority Issues

- [x] [AI-Review][HIGH] **File List Incomplete** - Add missing files to Dev Agent Record → File List: `agent_session.py`, `mcp_tools.py`, `test_mcp_tools.py` OR remove these from git (they appear to be Story 6.1 files) [story:1056-1064]
- [x] [AI-Review][HIGH] **Global Cache Metrics Not Thread-Safe** - Replace global `_cache_total_queries` and `_cache_hits` with thread-safe mechanism (asyncio.Lock) OR remove global tracking and rely on log aggregation [web.py:52-53, 90-96]

### MEDIUM Priority Issues

- [x] [AI-Review][MEDIUM] **Type Hints Use Any** - Change `config_manager: Any | None` to `config_manager: ConfigManager | None` and add proper import [web.py:105, 364]
- [x] [AI-Review][MEDIUM] **Overly Broad Exception Handling** - Replace `except Exception:` with specific exceptions like `(aiosqlite.Error, json.JSONDecodeError, ValueError)` [web.py:330, 371, 397, 413]
- [x] [AI-Review][MEDIUM] **Cache Metrics Edge Case Bug** - Fix metrics recording when cache lookup throws exception - only record miss if cache was actually checked [web.py:166, 175]
- [x] [AI-Review][MEDIUM] **Missing Error Handling Tests** - Add tests for: cache storage error graceful degradation, cache lookup error fallback to API [test_web.py]
- [x] [AI-Review][MEDIUM] **Time-Sensitive Bypass Doesn't Preserve Original Mode** - Add `effective_mode` and `cache_bypassed` fields to response so users know when mode was overridden [web.py:134, 290]

### LOW Priority Issues

- [x] [AI-Review][LOW] **Migration File Incorrectly Claimed as New** - Remove `0006_search_cache.sql` from Story 6.2 File List (it was created in Story 6.1) [story:1061]
- [x] [AI-Review][LOW] **Story Code Examples Outdated** - Update story line 358 TODO comment - config reading is already implemented (no TODO needed) [story:358 vs web.py:371]

---

## Testing Strategy

### Unit Tests

**File**: `tests/unit/test_web.py` (UPDATE)

```python
"""Add cache tests to existing unit test file."""

import pytest
from datetime import datetime, timedelta, timezone

from sohnbot.capabilities.web import (
    brave_search,
    is_time_sensitive,
    cleanup_expired_cache,
)


def test_is_time_sensitive():
    """Test time-sensitive keyword detection."""
    assert is_time_sensitive("latest Python tutorial") is True
    assert is_time_sensitive("Python tutorial today") is True
    assert is_time_sensitive("breaking news AI") is True
    assert is_time_sensitive("Python 2026 features") is True
    assert is_time_sensitive("march updates") is True
    assert is_time_sensitive("Python tutorial") is False
    assert is_time_sensitive("async programming guide") is False


@pytest.mark.asyncio
async def test_cache_hit(tmp_path):
    """Test cache hit returns cached results."""
    test_db = tmp_path / "test.db"

    # Initialize DB and insert cache entry
    from sohnbot.persistence.db import init_db
    await init_db(str(test_db))

    import aiosqlite
    import json
    from sohnbot.capabilities.web import get_query_hash

    query = "Python tutorial"
    mode = "static"
    query_hash = get_query_hash(query, mode)
    results = [{"title": "Test", "url": "https://test.com", "snippet": "Test snippet"}]
    created_at = datetime.now(timezone.utc).isoformat()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    async with aiosqlite.connect(str(test_db)) as db:
        await db.execute(
            """
            INSERT INTO search_cache
            (query_hash, query, mode, results_json, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (query_hash, query, mode, json.dumps(results), created_at, expires_at),
        )
        await db.commit()

    # Mock API call (should not be called)
    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch("httpx.AsyncClient.get") as mock_get:
            result = await brave_search(
                query=query,
                mode=mode,
                db_path=str(test_db),
            )

            # Verify cache hit
            assert result["cached"] is True
            assert result["total_results"] == 1
            assert result["results"][0]["title"] == "Test"

            # Verify API was NOT called
            mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_stores_result(tmp_path):
    """Test cache miss calls API and stores result."""
    test_db = tmp_path / "test.db"
    await init_db(str(test_db))

    query = "Python async"
    mode = "static"

    # Mock API response
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "web": {
            "results": [
                {
                    "title": "Python Async Guide",
                    "url": "https://docs.python.org",
                    "description": "Async programming guide",
                },
            ]
        }
    }

    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await brave_search(
                query=query,
                mode=mode,
                db_path=str(test_db),
            )

            # Verify API was called
            assert result["cached"] is False
            assert result["total_results"] == 1

            # Verify result was stored in cache
            import aiosqlite
            from sohnbot.capabilities.web import get_query_hash

            query_hash = get_query_hash(query, mode)
            async with aiosqlite.connect(str(test_db)) as db:
                async with db.execute(
                    "SELECT query, mode FROM search_cache WHERE query_hash = ?",
                    (query_hash,),
                ) as cursor:
                    row = await cursor.fetchone()

            assert row is not None
            assert row[0] == query
            assert row[1] == mode


@pytest.mark.asyncio
async def test_fresh_mode_bypasses_cache(tmp_path):
    """Test fresh mode always bypasses cache."""
    test_db = tmp_path / "test.db"
    await init_db(str(test_db))

    # Pre-populate cache
    import aiosqlite
    import json
    from sohnbot.capabilities.web import get_query_hash

    query = "Python tutorial"
    mode = "fresh"  # Fresh mode
    query_hash = get_query_hash(query, "static")  # Cache entry for static mode
    results = [{"title": "Cached", "url": "https://cached.com", "snippet": "Cached"}]
    created_at = datetime.now(timezone.utc).isoformat()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    async with aiosqlite.connect(str(test_db)) as db:
        await db.execute(
            """
            INSERT INTO search_cache
            (query_hash, query, mode, results_json, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (query_hash, query, "static", json.dumps(results), created_at, expires_at),
        )
        await db.commit()

    # Mock API response
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "web": {
            "results": [
                {
                    "title": "Fresh Result",
                    "url": "https://fresh.com",
                    "description": "Fresh result",
                },
            ]
        }
    }

    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await brave_search(
                query=query,
                mode=mode,
                db_path=str(test_db),
            )

            # Verify API was called (not cached)
            assert result["cached"] is False
            assert result["results"][0]["title"] == "Fresh Result"


@pytest.mark.asyncio
async def test_time_sensitive_bypasses_cache(tmp_path):
    """Test time-sensitive queries bypass cache even in static mode."""
    test_db = tmp_path / "test.db"
    await init_db(str(test_db))

    query = "latest Python news"  # Time-sensitive
    mode = "static"

    # Mock API response
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "web": {"results": [{"title": "News", "url": "https://news.com", "description": "Latest news"}]}
    }

    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await brave_search(
                query=query,
                mode=mode,
                db_path=str(test_db),
            )

            # Verify cache was bypassed
            assert result["cached"] is False


@pytest.mark.asyncio
async def test_cleanup_expired_cache(tmp_path):
    """Test expired cache entries are deleted."""
    test_db = tmp_path / "test.db"
    await init_db(str(test_db))

    import aiosqlite
    import json
    from sohnbot.capabilities.web import get_query_hash

    # Insert expired entry
    query = "old query"
    mode = "static"
    query_hash = get_query_hash(query, mode)
    results = [{"title": "Old", "url": "https://old.com", "snippet": "Old"}]
    created_at = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    expires_at = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()  # Expired

    async with aiosqlite.connect(str(test_db)) as db:
        await db.execute(
            """
            INSERT INTO search_cache
            (query_hash, query, mode, results_json, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (query_hash, query, mode, json.dumps(results), created_at, expires_at),
        )
        await db.commit()

    # Run cleanup
    deleted = await cleanup_expired_cache(str(test_db))

    assert deleted == 1

    # Verify entry was deleted
    async with aiosqlite.connect(str(test_db)) as db:
        async with db.execute("SELECT COUNT(*) FROM search_cache") as cursor:
            row = await cursor.fetchone()
            assert row[0] == 0
```

### Integration Tests

**File**: `tests/integration/test_web_search_flow.py` (UPDATE)

```python
"""Add cache integration tests."""

@pytest.mark.asyncio
async def test_cache_integration_full_flow(tmp_path):
    """Test complete cache flow: miss -> store -> hit."""
    test_db = tmp_path / "test.db"
    await init_db(str(test_db))

    config = ConfigManager()
    scope_validator = ScopeValidator(config)
    broker = BrokerRouter(scope_validator, config)

    query = "Python asyncio tutorial"
    mode = "static"

    # Mock API response
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "web": {
            "results": [
                {
                    "title": "Asyncio Tutorial",
                    "url": "https://docs.python.org/asyncio",
                    "description": "Complete asyncio tutorial",
                },
            ]
        }
    }

    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch("httpx.AsyncClient.get", return_value=mock_response) as mock_get:
            # First call: cache miss, API called
            result1 = await broker.route_operation(
                capability="web",
                action="search",
                params={"query": query, "mode": mode},
                chat_id="test-chat",
            )

            assert result1.allowed is True
            assert result1.result["cached"] is False
            assert mock_get.call_count == 1

            # Second call: cache hit, API NOT called
            result2 = await broker.route_operation(
                capability="web",
                action="search",
                params={"query": query, "mode": mode},
                chat_id="test-chat",
            )

            assert result2.allowed is True
            assert result2.result["cached"] is True
            assert mock_get.call_count == 1  # Still 1 (not called again)

            # Verify results match
            assert result1.result["total_results"] == result2.result["total_results"]
            assert result1.result["results"][0]["title"] == result2.result["results"][0]["title"]
```

---

## Dependencies

### Required Stories
- ✅ **Story 6.1**: Brave Web Search Integration (provides foundation, table, hash function)

### External Dependencies
- **aiosqlite**: Already installed (async SQLite access)
- **search_cache table**: Created in Story 6.1 migration

### Configuration Dependencies
- `search.cache_retention_days`: Default 7 (already in default.toml from Story 6.1)
- `database.path`: Default "data/sohnbot.db" (already configured)

---

## Migration Plan

### Database Changes
**None required** - `search_cache` table already created in Story 6.1

### Configuration Changes
**None required** - `search.cache_retention_days` already exists

### Deployment Steps
1. Deploy code changes to `web.py` (cache logic)
2. Restart SohnBot service
3. Test cache: Send same search twice in static mode
4. Verify second search returns cached results
5. Monitor cache hit rate in logs

---

## Rollback Plan

If caching causes issues:

1. **Immediate Mitigation**: Set `search.cache_retention_days = 0` (effectively disables caching)
2. **Code Rollback**: Revert to Story 6.1 commit (remove cache lookup/storage)
3. **Cache Clear**: `DELETE FROM search_cache;` (clear all cache)
4. **Monitoring**: Check for cache errors: `SELECT * FROM execution_log WHERE capability='web' AND error_details LIKE '%cache%'`

---

## Story Intelligence from Previous Stories

### Story 6.1 Learnings
- `web.py` has `brave_search()` function with structured error handling
- `get_query_hash()` generates SHA256 cache keys
- `search_cache` table ready for use
- Broker routes web operations with Tier 0 classification
- MCP tool `web__search` integrates with broker
- API key security enforced (NFR-013)

### Story 5.5 Learnings
- Config values read with fallback defaults
- Dynamic config reloads without restart
- Async patterns use `async with` for resource management

### Story 4.6 Learnings
- Background jobs for periodic cleanup
- Structured logging for observability
- Database operations wrapped in try/except (no exceptions bubble up)

---

## Architecture Compliance

### Cache Design
- **Storage**: SQLite only (no in-memory cache)
- **Lookup**: Indexed query on `query_hash` + `expires_at`
- **Expiration**: Automatic (queries ignore expired entries)
- **Cleanup**: Manual via `cleanup_expired_cache()` or background job
- **Performance**: <10ms lookup time (indexed query)

### Mode Behavior
- **fresh**: Always bypasses cache, never stores
- **static**: Checks cache first, stores on miss (unless time-sensitive)
- **Time-sensitive**: Forced to fresh mode (bypasses cache)

### Cache Key Format
```python
# Deterministic hash of query + mode
query_hash = SHA256(f"{query.strip().lower()}:{mode}")
```

### Cache Entry Format
```python
{
    "id": 1,
    "query_hash": "abc123...",
    "query": "Python tutorial",
    "mode": "static",
    "results_json": '[{"title": "...", "url": "...", "snippet": "..."}]',
    "created_at": "2026-03-01T12:00:00Z",
    "expires_at": "2026-03-08T12:00:00Z",
}
```

### Cached Result Format
```python
{
    "results": [...],
    "total_results": 5,
    "query": "Python tutorial",
    "mode": "static",
    "cached": True,
    "cached_at": "2026-03-01T12:00:00Z",
}
```

---

## File Structure Requirements

```
src/sohnbot/capabilities/
└── web.py                      # UPDATE: Add cache lookup/storage

src/sohnbot/broker/
└── router.py                   # UPDATE: Pass db_path and config to brave_search

tests/unit/
└── test_web.py                 # UPDATE: Add cache tests

tests/integration/
└── test_web_search_flow.py     # UPDATE: Add cache integration tests
```

---

## Testing Requirements

### Unit Test Coverage
- ✅ Time-sensitive keyword detection (today, latest, breaking, etc.)
- ✅ Cache hit returns cached results (no API call)
- ✅ Cache miss calls API and stores result
- ✅ Fresh mode bypasses cache
- ✅ Time-sensitive queries bypass cache (even in static mode)
- ✅ Expired cache entries not returned
- ✅ Cleanup function deletes expired entries
- ✅ Cache storage errors don't fail searches

### Integration Test Coverage
- ✅ Full cache flow: miss → store → hit
- ✅ Fresh mode never uses cache
- ✅ Config integration: cache_retention_days affects expiration

### Manual Test Checklist
- [ ] Send static search: "Python tutorial"
- [ ] Send same search again: verify cached=true, instant response
- [ ] Send fresh search: "Python tutorial" (mode=fresh)
- [ ] Verify API called (not cached)
- [ ] Send time-sensitive search: "latest Python news" (mode=static)
- [ ] Verify API called (cache bypassed)
- [ ] Check database: `SELECT * FROM search_cache LIMIT 10`
- [ ] Run cleanup: Call `cleanup_expired_cache()`
- [ ] Verify old entries deleted

---

## Definition of Done

- [ ] Code implemented and committed to feature branch
- [x] All acceptance criteria met (AC-025.1 through AC-025.6)
- [x] Cache lookup logic added to `brave_search()`
- [x] Cache storage logic added after API calls
- [x] Time-sensitive keyword detection implemented
- [x] Fresh mode bypasses cache
- [x] Cleanup function implemented
- [x] Unit tests pass with >90% coverage on new code
- [x] Integration tests verify cache flow
- [ ] Manual testing completed (checklist above)
- [ ] Code review completed
- [ ] All linter checks pass
- [x] Story status updated to 'review' in sprint-status.yaml

---

## Open Questions

### Q1: Cache Hit Rate Target
**Question**: What cache hit rate should we target?
**Decision**: >50% for common queries (monitor in Story 6.3)

### Q2: Cache Size Limits
**Question**: Should we limit cache table size (e.g., max 10,000 entries)?
**Decision**: No hard limit for now, rely on 7-day expiration (monitor disk usage)

### Q3: Background Cleanup Job
**Question**: Should cleanup run automatically via scheduler?
**Decision**: Manual cleanup for Story 6.2, automated in future story or Story 6.3

---

## Related Documentation

- `src/sohnbot/capabilities/web.py`: Web capability implementation
- `src/sohnbot/persistence/migrations/0006_search_cache.sql`: Cache table schema
- `config/default.toml`: Cache configuration (line 88)
- `_bmad-output/planning-artifacts/epics.md`: Epic 6 requirements (lines 1184-1204)

---

## Dev Agent Record

### Agent Model Used
- GPT-5 Codex (CLI)

### Debug Log References
- `.venv/bin/pytest -q tests/unit/test_web.py tests/unit/test_broker.py tests/unit/test_mcp_tools.py tests/unit/test_config_registry.py tests/integration/test_web_search_flow.py`

### Completion Notes
- Extended `brave_search()` with SQLite-backed static-mode caching using `query_hash`, expiration checks, and `cached=True/False` response behavior.
- Implemented time-sensitive query detection (`is_time_sensitive`) with keyword and current-year checks; static mode automatically bypasses cache for these queries.
- Added cache lifecycle helpers: `_get_cached_search`, `_store_search_cache`, and `cleanup_expired_cache`.
- Added cache hit/miss logging and removed shared in-process cache counters to avoid thread-safety issues.
- Wired broker web routing to pass `database.path` and `config_manager` into `brave_search` so cache storage uses dynamic `search.cache_retention_days`.
- Updated configuration bounds for `search.cache_retention_days` to `1..90`.
- Added focused tests for cache miss/store/hit flow, fresh-mode bypass, time-sensitive bypass, retention config behavior, cleanup behavior, and broker integration.

### File List
- `_bmad-output/implementation-artifacts/6-2-search-result-caching.md`
- `src/sohnbot/capabilities/web.py`
- `src/sohnbot/broker/router.py`
- `src/sohnbot/config/registry.py`
- `src/sohnbot/runtime/agent_session.py`
- `src/sohnbot/runtime/mcp_tools.py`
- `tests/unit/test_web.py`
- `tests/unit/test_broker.py`
- `tests/unit/test_mcp_tools.py`
- `tests/unit/test_config_registry.py`
- `tests/integration/test_web_search_flow.py`

---

## Critical Notes for Dev Agent

1. **search_cache Table Already Exists**
   - Created in Story 6.1 migration (0006_search_cache.sql)
   - No new migration needed
   - Verify table exists before implementing cache logic

2. **Cache Only Static Mode**
   - `mode="fresh"` ALWAYS bypasses cache
   - `mode="static"` checks cache, stores results
   - Time-sensitive queries forced to fresh mode

3. **Time-Sensitive Keywords**
   - Comprehensive list: today, latest, breaking, current year, month names
   - Case-insensitive detection
   - Bypass cache even if mode="static"

4. **Config Integration**
   - `search.cache_retention_days` already exists (default: 7)
   - Pass `config_manager` to `brave_search()` function
   - Read config in `_store_search_cache()` function

5. **Error Handling**
   - Cache lookup errors: return None (proceed to API call)
   - Cache storage errors: log warning (don't fail search)
   - Expired entries: filtered in SQL query (`expires_at > now()`)

6. **Performance Targets**
   - Cache lookup: <10ms (indexed query)
   - Cache hit rate: >50% target
   - No memory caching (SQLite only)

7. **Testing Strategy**
   - Mock API calls in unit tests
   - Verify cache hit/miss behavior
   - Test time-sensitive bypass
   - Integration test: miss → store → hit flow

8. **Cleanup Function**
   - `cleanup_expired_cache(db_path)` deletes expired entries
   - Can be called manually or via background job
   - Returns count of deleted entries
   - Logs completion event
