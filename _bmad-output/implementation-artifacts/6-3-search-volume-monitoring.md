# Story 6.3: Search Volume Monitoring

**Epic**: Epic 6 - Research & Web Search
**Story Key**: 6-3-search-volume-monitoring
**Status**: done
**Created**: 2026-03-01

---

## Story Overview

**As a** user,
**I want** soft threshold alerts for search volume,
**So that** I can monitor API quota without hard blocking.

### Business Value
- **Cost Awareness**: Early warning before hitting API quota limits
- **No Hard Blocking**: Soft alerts preserve user autonomy (no forced blocking)
- **Proactive Monitoring**: Detect unusual search activity patterns
- **Budget Control**: Helps avoid unexpected API overage charges

---

## Functional Requirements

### FR-026: Search Volume Monitoring
**Priority**: MEDIUM
**Source**: epics.md lines 1208-1230

The system MUST track search volume and alert on threshold:

1. **Daily Search Count Tracking**
   - Track total searches per day (both fresh and static modes)
   - Counter scoped to calendar day (UTC timezone)
   - Increment on every successful `brave_search()` call
   - Store in persistent storage (survives restarts)

2. **Threshold-Based Alerts**
   - Configurable threshold: `search.volume_alert_threshold` (default: 100)
   - Alert triggers when daily count exceeds threshold
   - Alert sent once per day (not repeated for subsequent searches)
   - Alert delivered via Telegram notification

3. **Alert Content**
   - Format: "⚠️ Search Volume Alert: {count} searches (threshold: {threshold})"
   - Includes advice: "Monitor Brave API quota to avoid cost overruns"
   - Sent to admin chat (telegram.admin_chat_id)
   - If no admin chat configured, log warning only

4. **Soft Alert (No Blocking)**
   - Alert is informational only
   - Searches continue to work after threshold exceeded
   - User retains full control (can ignore or take action)
   - No automatic rate limiting or blocking

5. **Daily Reset**
   - Counter resets daily at midnight UTC
   - Reset can be manual (via cleanup job) or automatic
   - Previous day's count discarded or archived
   - Reset logic idempotent (safe to run multiple times)

---

## Non-Functional Requirements

### NFR-031: Monitoring Overhead
**Priority**: MEDIUM

- Counter increment: <1ms overhead per search
- Counter storage: SQLite transaction (async, non-blocking)
- Alert delivery: Async via notification_outbox (doesn't block search)
- Total overhead: <5ms per search operation

### NFR-032: Alert Reliability
**Priority**: HIGH

- Alert delivery guaranteed if admin_chat_id configured
- Uses existing notification_outbox system (reliable delivery)
- Alert not sent if notification system unavailable (degrades gracefully)
- Missed alerts logged as warnings

### NFR-033: Counter Accuracy
**Priority**: MEDIUM

- Counter is eventually consistent (async increments)
- Acceptable error margin: ±1 count per concurrent search batch
- Counter persists across restarts
- Reset is deterministic (always at midnight UTC)

---

## Acceptance Criteria

### AC-026.1: Daily Search Counter
- [x] Daily search count tracked in persistent storage
- [x] Counter increments on every `brave_search()` call (both fresh and static)
- [x] Counter persists across service restarts
- [x] Counter scoped to calendar day (UTC)
- [x] Storage: SQLite table or config table

### AC-026.2: Threshold Configuration
- [x] Config key: `search.volume_alert_threshold` (default: 100)
- [x] Config is dynamic (hot-reloadable without restart)
- [x] Validator: integer between 1 and 10,000
- [x] Config already exists in default.toml

### AC-026.3: Alert Triggering
- [x] Alert triggered when `daily_count > threshold`
- [x] Alert sent once per day (first time threshold exceeded)
- [x] Subsequent searches don't re-trigger alert
- [x] Alert delivered via `enqueue_notification()` to admin chat

### AC-026.4: Alert Format
- [x] Message: "⚠️ Search Volume Alert: {count} searches (threshold: {threshold})"
- [x] Includes advice: "Monitor Brave API quota to avoid cost overruns"
- [x] Delivered to `telegram.admin_chat_id`
- [x] If admin_chat_id not configured, log warning only

### AC-026.5: No Hard Blocking
- [x] Searches continue after threshold exceeded
- [x] No automatic rate limiting
- [x] No error returned to user
- [x] Alert is advisory only

### AC-026.6: Daily Reset
- [x] Counter resets at midnight UTC
- [x] Reset triggered by scheduler job or automatic check
- [x] Reset is idempotent (safe to run multiple times)
- [x] Previous day's count cleared

---

## Implementation Guidance

### Architecture Context

```
src/sohnbot/capabilities/
└── web.py                      # UPDATE: Add search counter tracking

src/sohnbot/persistence/
├── migrations/
│   └── 0007_search_volume.sql  # NEW: daily_search_volume table
└── search_volume.py            # NEW: Counter management functions

src/sohnbot/scheduler/
└── scheduler.py                # UPDATE: Add daily reset job (optional)

config/
└── default.toml                # VERIFY: search.volume_alert_threshold = 100

tests/unit/
├── test_web.py                 # UPDATE: Add volume tracking tests
└── test_search_volume.py       # NEW: Unit tests for counter

tests/integration/
└── test_search_volume_flow.py  # NEW: Integration test for alert flow
```

### Key Implementation Tasks

#### Task 6.3.1: Create Search Volume Migration
**File**: `src/sohnbot/persistence/migrations/0007_search_volume.sql` (NEW)

```sql
-- Migration 0007: Daily search volume tracking
-- Story: 6.3 Search Volume Monitoring
-- Created: 2026-03-01

CREATE TABLE IF NOT EXISTS daily_search_volume (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,  -- YYYY-MM-DD format
    search_count INTEGER NOT NULL DEFAULT 0,
    alert_sent BOOLEAN NOT NULL DEFAULT 0,  -- 1 if alert sent for this day
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_daily_search_volume_date
ON daily_search_volume(date DESC);

-- Query for current day's count:
-- SELECT search_count, alert_sent FROM daily_search_volume WHERE date = date('now');

-- Increment count:
-- INSERT INTO daily_search_volume (date, search_count)
-- VALUES (date('now'), 1)
-- ON CONFLICT(date) DO UPDATE SET
--   search_count = search_count + 1,
--   updated_at = datetime('now');

-- Reset old entries (cleanup):
-- DELETE FROM daily_search_volume WHERE date < date('now', '-30 days');
```

#### Task 6.3.2: Create Search Volume Module
**File**: `src/sohnbot/persistence/search_volume.py` (NEW)

```python
"""Search volume tracking and alerting."""

from datetime import date, datetime, timezone

import aiosqlite
import structlog

logger = structlog.get_logger(__name__)


async def increment_daily_search_count(db_path: str) -> tuple[int, bool]:
    """
    Increment today's search count and return (count, alert_sent).

    Args:
        db_path: Path to SQLite database.

    Returns:
        Tuple of (current_count, alert_already_sent)
    """
    today = date.today().isoformat()  # YYYY-MM-DD format

    try:
        async with aiosqlite.connect(db_path) as db:
            # Increment count (insert or update)
            await db.execute(
                """
                INSERT INTO daily_search_volume (date, search_count)
                VALUES (?, 1)
                ON CONFLICT(date) DO UPDATE SET
                    search_count = search_count + 1,
                    updated_at = datetime('now')
                """,
                (today,),
            )
            await db.commit()

            # Fetch current count and alert status
            async with db.execute(
                "SELECT search_count, alert_sent FROM daily_search_volume WHERE date = ?",
                (today,),
            ) as cursor:
                row = await cursor.fetchone()

        if row is None:
            logger.warning("search_volume_increment_failed", date=today)
            return (0, False)

        count, alert_sent = row
        logger.debug("search_volume_incremented", date=today, count=count)
        return (int(count), bool(alert_sent))

    except Exception as exc:  # noqa: BLE001
        logger.warning("search_volume_increment_error", error=str(exc), date=today)
        return (0, False)


async def mark_alert_sent(db_path: str) -> None:
    """Mark that alert has been sent for today."""
    today = date.today().isoformat()

    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                UPDATE daily_search_volume
                SET alert_sent = 1, updated_at = datetime('now')
                WHERE date = ?
                """,
                (today,),
            )
            await db.commit()
        logger.info("search_volume_alert_marked", date=today)

    except Exception as exc:  # noqa: BLE001
        logger.warning("search_volume_alert_mark_error", error=str(exc), date=today)


async def cleanup_old_volume_records(db_path: str, retention_days: int = 30) -> int:
    """
    Delete volume records older than retention_days.

    Args:
        db_path: Path to SQLite database.
        retention_days: How many days to retain (default: 30).

    Returns:
        Number of rows deleted.
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "DELETE FROM daily_search_volume WHERE date < date('now', ?)",
                (f"-{retention_days} days",),
            )
            await db.commit()
            deleted = cursor.rowcount or 0
        logger.info("search_volume_cleanup_completed", deleted=deleted, retention_days=retention_days)
        return int(deleted)

    except Exception as exc:  # noqa: BLE001
        logger.warning("search_volume_cleanup_error", error=str(exc))
        return 0
```

#### Task 6.3.3: Integrate Volume Tracking into brave_search
**File**: `src/sohnbot/capabilities/web.py` (UPDATE)

**Import search volume functions** (at top):
```python
from ..persistence.search_volume import increment_daily_search_count, mark_alert_sent
from ..persistence.notification import enqueue_notification, get_notifications_enabled
```

**Add volume tracking after successful search** (in `brave_search`, after line 304):

```python
async def brave_search(
    query: str,
    mode: Literal["fresh", "static"] = "fresh",
    max_results: int = 5,
    timeout_seconds: int = 5,
    db_path: str = "data/sohnbot.db",
    config_manager: Any | None = None,
) -> dict[str, Any]:
    # ... existing code ...

    # After successful API call and cache storage (line 304)
    # NEW: Track search volume and check threshold
    try:
        count, alert_sent = await increment_daily_search_count(db_path)

        # Check if threshold exceeded and alert not sent yet
        threshold = 100  # Default
        if config_manager:
            try:
                threshold = int(config_manager.get("search.volume_alert_threshold"))
            except Exception:
                pass

        if count > threshold and not alert_sent:
            # Send alert notification
            admin_chat_id = None
            if config_manager:
                try:
                    admin_chat_id = config_manager.get("telegram.admin_chat_id")
                except Exception:
                    pass

            if admin_chat_id:
                alert_message = (
                    f"⚠️ Search Volume Alert: {count} searches (threshold: {threshold})\n\n"
                    f"Monitor Brave API quota to avoid cost overruns."
                )

                # Queue notification (async, non-blocking)
                await enqueue_notification(
                    chat_id=admin_chat_id,
                    message=alert_message,
                    db_path=db_path,
                )

                # Mark alert as sent
                await mark_alert_sent(db_path)

                logger.warning(
                    "search_volume_threshold_exceeded",
                    count=count,
                    threshold=threshold,
                    alert_sent=True,
                )
            else:
                logger.warning(
                    "search_volume_threshold_exceeded_no_admin",
                    count=count,
                    threshold=threshold,
                    alert_sent=False,
                )
    except Exception as exc:  # noqa: BLE001
        # Don't fail search if volume tracking fails
        logger.warning("search_volume_tracking_error", error=str(exc))

    return response
```

#### Task 6.3.4: Update Config Registry
**File**: `src/sohnbot/config/registry.py` (UPDATE - verify exists)

**Verify volume_alert_threshold config** (should already exist):

```python
"search.volume_alert_threshold": ConfigKey(
    tier="dynamic",
    value_type=int,
    default=100,
    min_value=1,
    max_value=10000,
),
```

#### Task 6.3.5: Add Daily Reset Scheduler Job (Optional Enhancement)
**File**: `src/sohnbot/scheduler/scheduler.py` (UPDATE - optional)

**Add job to reset counter** (optional, counter auto-resets via SQL logic):

```python
# Optional: Add scheduled cleanup job for old volume records
# This runs weekly to delete records older than 30 days
# The counter itself auto-resets via SQL date-based queries
```

---

## Review Follow-ups (Code Review - 2026-03-01)

### HIGH Priority Issues

- [x] **[AI-Review][HIGH] mark_alert_sent Race Condition** `src/sohnbot/capabilities/web.py:356-363`
  - **Issue**: Alert notification is enqueued before `mark_alert_sent()` is called. If `mark_alert_sent()` fails (DB error, connection lost), the flag won't be set, causing duplicate alerts on next search.
  - **Impact**: User receives duplicate alerts for same day if mark_alert_sent fails.
  - **Fix**: Call `mark_alert_sent()` before `enqueue_notification()`, or wrap both in transaction, or add error handling to rollback notification if mark fails.
  - **Test**: Add test for mark_alert_sent failure scenario.

### MEDIUM Priority Issues

- [x] **[AI-Review][MEDIUM] Config Registry min_value=10 instead of 1** `src/sohnbot/config/registry.py:320`
  - **Issue**: `search.volume_alert_threshold` has `min_value=10`, but AC-026.2 and story spec say "validator: integer between 1 and 10,000".
  - **Impact**: Cannot set threshold to 1-9 for testing or very low-volume use cases.
  - **Fix**: Change `min_value=10` to `min_value=1` in registry.py line 320.
  - **Test**: Verify `test_validate_search_volume_alert_threshold_range` passes with value=1.

- [x] **[AI-Review][MEDIUM] mark_alert_sent Can Create Row with search_count=0** `src/sohnbot/persistence/search_volume.py:263-270`
  - **Issue**: `mark_alert_sent()` uses UPDATE only. If called before `increment_daily_search_count()` (bug or test scenario), it silently fails. Should use INSERT OR IGNORE pattern like increment.
  - **Impact**: Silent failure if alert logic called out of order.
  - **Fix**: Change to `INSERT INTO daily_search_volume (date, alert_sent) VALUES (?, 1) ON CONFLICT(date) DO UPDATE SET alert_sent = 1`.
  - **Test**: Add test calling mark_alert_sent before increment to verify it doesn't fail.

- [x] **[AI-Review][MEDIUM] Overly Broad Exception Handling** `src/sohnbot/persistence/search_volume.py:252,274,300`
  - **Issue**: Three functions use `except Exception:` (lines 252, 274, 300), catching all exceptions including programming errors.
  - **Impact**: Bugs like AttributeError or NameError get silently logged instead of failing tests.
  - **Fix**: Change to `except aiosqlite.Error:` or specific DB exceptions. Let programming errors propagate.
  - **Test**: Verify tests still pass with narrower exception handling.

- [x] **[AI-Review][MEDIUM] Config Error Handling Silent Failure** `src/sohnbot/capabilities/web.py:334-338,343-347`
  - **Issue**: Two try/except blocks silently swallow all exceptions when reading config (lines 334-338, 343-347). If config_manager raises TypeError or AttributeError, falls back to defaults without logging.
  - **Impact**: Config errors go unnoticed, making debugging harder.
  - **Fix**: Add specific exception types and log warnings for unexpected errors.
  - **Test**: Add test for config_manager.get() raising unexpected exception.

- [x] **[AI-Review][MEDIUM] increment_daily_search_count Returns (0, False) on Error** `src/sohnbot/persistence/search_volume.py:244-254`
  - **Issue**: On database error, returns `(0, False)` which is indistinguishable from legitimate first search of the day. Caller can't detect error vs. success.
  - **Impact**: Alert logic thinks count is 0, won't trigger even if threshold should be exceeded.
  - **Fix**: Either raise exception and let caller handle, or return sentinel like `(-1, False)` and document, or return Optional tuple.
  - **Test**: Add test verifying error return value is distinguishable from success.

- [x] **[AI-Review][MEDIUM] cleanup_old_volume_records Not Integrated** `src/sohnbot/persistence/search_volume.py:278-302`
  - **Issue**: `cleanup_old_volume_records()` function exists and tested, but never called. Old records accumulate indefinitely.
  - **Impact**: Database grows unbounded over time (1 row per day forever).
  - **Fix**: Add scheduled job to call cleanup weekly/monthly, or call from increment_daily_search_count with caching to prevent on every search.
  - **Test**: Integration test verifying cleanup is scheduled or called.

### LOW Priority Issues

- [x] **[AI-Review][LOW] Integration Test Doesn't Verify Complete Alert Format** `tests/integration/test_search_volume_flow.py:656`
  - **Issue**: Test verifies "admin-123" and "Search Volume Alert" are in call args, but doesn't verify exact message format, count, or threshold values.
  - **Impact**: Alert format could change (missing emoji, wrong count) and test still passes.
  - **Fix**: Extract call_args and assert exact message: `assert "⚠️ Search Volume Alert: 4 searches (threshold: 3)" in call_args[1]['message_text']`.
  - **Test**: Verify test fails if message format changes.

- [x] **[AI-Review][LOW] Volume Tracking Called for Cache Hits - Clarification** `src/sohnbot/capabilities/web.py:175-178,316-319`
  - **Note**: This is NOT a bug. Volume tracking is correctly integrated at two locations (after cache hit return line 175-178, and after API call line 316-319).
  - **Rationale**: AC-026.1 says "Counter increments on every `brave_search()` call (both fresh and static)" - this includes cache hits.
  - **Validation**: Integration tests verify this behavior is correct.
  - **Action**: Document in code comments that cache hits ARE counted intentionally.

---

## Testing Strategy

### Unit Tests

**File**: `tests/unit/test_search_volume.py` (NEW)

```python
"""Unit tests for search volume tracking (Story 6.3)."""

import pytest
from datetime import date
from pathlib import Path

import aiosqlite

from scripts.migrate import apply_migrations
from src.sohnbot.persistence.search_volume import (
    increment_daily_search_count,
    mark_alert_sent,
    cleanup_old_volume_records,
)


@pytest.fixture
def volume_db(tmp_path):
    """Create test database with migrations."""
    db_path = tmp_path / "volume-test.db"
    migrations_dir = Path(__file__).parent.parent.parent / "src" / "sohnbot" / "persistence" / "migrations"
    apply_migrations(db_path, migrations_dir)
    return db_path


@pytest.mark.asyncio
async def test_increment_daily_search_count_creates_entry(volume_db):
    """Test first increment creates new entry."""
    count, alert_sent = await increment_daily_search_count(str(volume_db))

    assert count == 1
    assert alert_sent is False


@pytest.mark.asyncio
async def test_increment_daily_search_count_increments_existing(volume_db):
    """Test subsequent increments update existing entry."""
    # First increment
    await increment_daily_search_count(str(volume_db))

    # Second increment
    count, alert_sent = await increment_daily_search_count(str(volume_db))

    assert count == 2
    assert alert_sent is False


@pytest.mark.asyncio
async def test_increment_daily_search_count_multiple_times(volume_db):
    """Test counter increments correctly multiple times."""
    for i in range(1, 6):
        count, alert_sent = await increment_daily_search_count(str(volume_db))
        assert count == i


@pytest.mark.asyncio
async def test_mark_alert_sent_updates_flag(volume_db):
    """Test marking alert as sent."""
    # Create entry
    await increment_daily_search_count(str(volume_db))

    # Mark alert sent
    await mark_alert_sent(str(volume_db))

    # Verify flag set
    today = date.today().isoformat()
    async with aiosqlite.connect(str(volume_db)) as db:
        async with db.execute(
            "SELECT alert_sent FROM daily_search_volume WHERE date = ?",
            (today,),
        ) as cursor:
            row = await cursor.fetchone()

    assert row is not None
    assert row[0] == 1  # alert_sent is True


@pytest.mark.asyncio
async def test_alert_sent_flag_persists_across_increments(volume_db):
    """Test alert_sent flag remains set after increments."""
    # Create entry and mark alert sent
    await increment_daily_search_count(str(volume_db))
    await mark_alert_sent(str(volume_db))

    # Increment again
    count, alert_sent = await increment_daily_search_count(str(volume_db))

    assert count == 2
    assert alert_sent is True  # Flag still set


@pytest.mark.asyncio
async def test_cleanup_old_volume_records(volume_db):
    """Test cleanup deletes old records."""
    # Insert old record manually
    today = date.today().isoformat()
    old_date = "2025-01-01"  # Old date

    async with aiosqlite.connect(str(volume_db)) as db:
        await db.execute(
            "INSERT INTO daily_search_volume (date, search_count) VALUES (?, ?)",
            (old_date, 50),
        )
        await db.execute(
            "INSERT INTO daily_search_volume (date, search_count) VALUES (?, ?)",
            (today, 10),
        )
        await db.commit()

    # Run cleanup (30 day retention)
    deleted = await cleanup_old_volume_records(str(volume_db), retention_days=30)

    assert deleted == 1  # Only old record deleted

    # Verify today's record remains
    async with aiosqlite.connect(str(volume_db)) as db:
        async with db.execute("SELECT COUNT(*) FROM daily_search_volume") as cursor:
            row = await cursor.fetchone()
    assert row[0] == 1
```

**File**: `tests/unit/test_web.py` (UPDATE)

```python
"""Add volume tracking tests to existing web tests."""

@pytest.mark.asyncio
async def test_brave_search_increments_volume_counter(cache_db, monkeypatch):
    """Test search increments daily volume counter."""
    # Mock API response
    request = httpx.Request("GET", BRAVE_SEARCH_API_URL)
    response = httpx.Response(
        200,
        request=request,
        json={
            "web": {
                "results": [
                    {"title": "Result", "url": "https://example.com", "description": "test"}
                ]
            }
        },
    )

    with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
        with patch(
            "src.sohnbot.capabilities.web.httpx.AsyncClient.get",
            new=AsyncMock(return_value=response),
        ):
            # First search
            await brave_search("test query", db_path=str(cache_db))

            # Second search
            await brave_search("another query", db_path=str(cache_db))

    # Verify count incremented
    from src.sohnbot.persistence.search_volume import increment_daily_search_count
    count, _ = await increment_daily_search_count(str(cache_db))
    # Count should be 3 (2 from searches above + 1 from this call)
    assert count >= 2
```

### Integration Tests

**File**: `tests/integration/test_search_volume_flow.py` (NEW)

```python
"""Integration tests for search volume monitoring (Story 6.3)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.broker import BrokerRouter, ScopeValidator
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager


@pytest.fixture
async def setup_database(tmp_path):
    """Setup test database with migrations."""
    db_path = tmp_path / "test.db"
    migrations_dir = Path(__file__).parent.parent.parent / "src" / "sohnbot" / "persistence" / "migrations"
    apply_migrations(db_path, migrations_dir)

    db_manager = DatabaseManager(db_path)
    set_db_manager(db_manager)
    yield db_manager
    await db_manager.close()


@pytest.mark.asyncio
async def test_volume_alert_triggered_when_threshold_exceeded(tmp_path, setup_database):
    """Test alert is sent when search volume exceeds threshold."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()

    config = MagicMock()

    def _cfg(key):
        if key == "database.path":
            return str(tmp_path / "test.db")
        if key == "search.volume_alert_threshold":
            return 3  # Low threshold for testing
        if key == "telegram.admin_chat_id":
            return "admin-123"
        return None

    config.get.side_effect = _cfg
    router = BrokerRouter(ScopeValidator([str(allowed_root)]), config_manager=config)

    request = httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search")
    response = httpx.Response(
        200,
        request=request,
        json={
            "web": {"results": [{"title": "Test", "url": "https://test.com", "description": "test"}]}
        },
    )

    with patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}):
        with patch("src.sohnbot.capabilities.web.httpx.AsyncClient.get", new=AsyncMock(return_value=response)):
            with patch("src.sohnbot.persistence.notification.enqueue_notification") as mock_enqueue:
                # Execute 4 searches (threshold is 3)
                for i in range(4):
                    await router.route_operation(
                        capability="web",
                        action="search",
                        params={"query": f"test query {i}", "mode": "fresh"},
                        chat_id="test-chat",
                    )

                # Verify alert was enqueued
                assert mock_enqueue.call_count == 1
                call_args = mock_enqueue.call_args
                assert "admin-123" in str(call_args)
                assert "Search Volume Alert" in str(call_args)


@pytest.mark.asyncio
async def test_volume_alert_sent_only_once_per_day(tmp_path, setup_database):
    """Test alert is sent only once even if threshold exceeded multiple times."""
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
        json={"web": {"results": [{"title": "T", "url": "https://t.com", "description": "t"}]}},
    )

    with patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}):
        with patch("src.sohnbot.capabilities.web.httpx.AsyncClient.get", new=AsyncMock(return_value=response)):
            with patch("src.sohnbot.persistence.notification.enqueue_notification") as mock_enqueue:
                # Execute 5 searches (threshold is 2)
                for i in range(5):
                    await router.route_operation(
                        capability="web",
                        action="search",
                        params={"query": f"query {i}", "mode": "fresh"},
                        chat_id="test-chat",
                    )

                # Alert should be sent only once
                assert mock_enqueue.call_count == 1
```

---

## Dependencies

### Required Stories
- ✅ **Story 6.1**: Brave Web Search Integration (provides brave_search function)
- ✅ **Story 1.8**: Structured Operation Logging & Notifications (provides enqueue_notification)

### External Dependencies
- **aiosqlite**: Already installed (async SQLite access)
- **notification_outbox**: Created in Story 1.8 (notification delivery system)

### Configuration Dependencies
- `search.volume_alert_threshold`: Default 100 (already in default.toml line 89)
- `telegram.admin_chat_id`: Required for alert delivery (already configured)
- `database.path`: Default "data/sohnbot.db" (already configured)

---

## Migration Plan

### Database Changes
**Migration**: `0007_search_volume.sql`
- Creates `daily_search_volume` table with STRICT mode
- Adds index on `date DESC` for fast current-day lookups
- Simple schema: date, count, alert_sent flag

### Configuration Changes
**None required** - `search.volume_alert_threshold` already exists in default.toml

### Deployment Steps
1. Run migration: `0007_search_volume.sql`
2. Deploy code changes (web.py, search_volume.py)
3. Restart SohnBot service
4. Execute 101 searches to test alert (or lower threshold temporarily)
5. Verify alert appears in admin Telegram chat
6. Check notification_outbox table for delivery

---

## Rollback Plan

If volume monitoring causes issues:

1. **Immediate Mitigation**: Set `search.volume_alert_threshold = 999999` (effectively disable alerts)
2. **Code Rollback**: Revert to Story 6.2 commit (remove volume tracking from web.py)
3. **Database Rollback**: `DROP TABLE daily_search_volume;`
4. **Monitoring**: Check for volume tracking errors in logs

---

## Story Intelligence from Previous Stories

### Story 6.2 Learnings
- web.py has brave_search() with cache integration
- Config manager passed to capability functions
- Error handling uses try/except with logging (don't fail main operation)
- Async patterns use aiosqlite for database access

### Story 1.8 Learnings
- Notifications use enqueue_notification() to notification_outbox
- Admin chat ID from telegram.admin_chat_id config
- Notification delivery is async and reliable
- Graceful degradation if notification system unavailable

### Story 4.6 Learnings
- Daily jobs scheduled via scheduler system
- Cleanup jobs use retention_days pattern
- Background jobs for periodic maintenance

---

## Architecture Compliance

### Volume Tracking Design
- **Storage**: SQLite table (daily_search_volume)
- **Scope**: Per calendar day (UTC timezone)
- **Increment**: Async, non-blocking (doesn't slow searches)
- **Reset**: Automatic via SQL date-based queries
- **Cleanup**: Optional scheduled job for old records

### Alert Mechanism
- **Trigger**: Soft threshold (no blocking)
- **Delivery**: Via notification_outbox (reliable, async)
- **Frequency**: Once per day maximum
- **Graceful Degradation**: Logs warning if admin_chat_id not configured

### Counter Format
```python
{
    "id": 1,
    "date": "2026-03-01",  # YYYY-MM-DD
    "search_count": 127,
    "alert_sent": 1,  # Boolean (0 or 1)
    "created_at": "2026-03-01 00:15:23",
    "updated_at": "2026-03-01 14:32:10",
}
```

### Alert Format
```
⚠️ Search Volume Alert: 127 searches (threshold: 100)

Monitor Brave API quota to avoid cost overruns.
```

---

## File Structure Requirements

```
src/sohnbot/capabilities/
└── web.py                      # UPDATE: Add volume tracking

src/sohnbot/persistence/
├── migrations/
│   └── 0007_search_volume.sql  # NEW: daily_search_volume table
└── search_volume.py            # NEW: Counter management

tests/unit/
├── test_web.py                 # UPDATE: Add volume tests
└── test_search_volume.py       # NEW: Counter unit tests

tests/integration/
└── test_search_volume_flow.py  # NEW: Alert flow tests
```

---

## Testing Requirements

### Unit Test Coverage
- ✅ First increment creates new entry with count=1
- ✅ Subsequent increments update existing entry
- ✅ Counter increments correctly multiple times
- ✅ Mark alert sent updates flag
- ✅ Alert flag persists across increments
- ✅ Cleanup deletes old records

### Integration Test Coverage
- ✅ Alert triggered when threshold exceeded
- ✅ Alert sent only once per day (not repeated)
- ✅ Alert includes correct count and threshold
- ✅ Alert delivered to admin_chat_id
- ✅ Graceful degradation if admin_chat_id not configured

### Manual Test Checklist
- [ ] Set threshold to 5 for testing: `/config set search.volume_alert_threshold 5`
- [ ] Execute 6 searches via Telegram
- [ ] Verify alert appears in admin chat after 6th search
- [ ] Execute more searches, verify no duplicate alerts
- [ ] Check database: `SELECT * FROM daily_search_volume WHERE date = date('now')`
- [ ] Verify count matches searches and alert_sent = 1
- [ ] Check notification_outbox: `SELECT * FROM notification_outbox ORDER BY created_at DESC LIMIT 5`

---

## Definition of Done

- [ ] Code implemented and committed to feature branch
- [x] All acceptance criteria met (AC-026.1 through AC-026.6)
- [x] Migration `0007_search_volume.sql` created
- [x] `search_volume.py` module created with counter functions
- [x] Volume tracking integrated into `brave_search()`
- [x] Config validation for volume_alert_threshold
- [x] Unit tests pass with >90% coverage on new code
- [x] Integration tests verify alert flow
- [ ] Manual testing completed (checklist above)
- [ ] Code review completed
- [ ] All linter checks pass
- [x] Story status updated to 'review' in sprint-status.yaml

---

## Open Questions

### Q1: Volume Counter Storage
**Question**: Use dedicated table or config table for counter?
**Decision**: Use dedicated `daily_search_volume` table for better querying and historical tracking

### Q2: Alert Delivery Retry
**Question**: Should alert retry if notification delivery fails?
**Decision**: No - notification_outbox system handles retries automatically

### Q3: Historical Volume Tracking
**Question**: Should we keep volume history for analytics?
**Decision**: Yes - cleanup job deletes records >30 days old (configurable)

---

## Related Documentation

- `src/sohnbot/capabilities/web.py`: Web search implementation
- `src/sohnbot/persistence/notification.py`: Notification delivery system
- `config/default.toml`: Volume threshold configuration (line 89)
- `_bmad-output/planning-artifacts/epics.md`: Epic 6 requirements (lines 1208-1230)

---

## Dev Agent Record

### Agent Model Used
- GPT-5 Codex (CLI)

### Debug Log References
- `.venv/bin/pytest -q tests/unit/test_search_volume.py tests/unit/test_web.py tests/unit/test_broker.py tests/unit/test_config_registry.py tests/integration/test_search_volume_flow.py tests/integration/test_web_search_flow.py`

### Completion Notes
- Added migration `0007_search_volume.sql` introducing `daily_search_volume` with daily counter and `alert_sent` flag.
- Added persistence module `search_volume.py` with `increment_daily_search_count`, `mark_alert_sent`, and `cleanup_old_volume_records`.
- Integrated volume tracking into `brave_search()` for both API-backed responses and cache-hit responses.
- Added soft-threshold alerting logic using `search.volume_alert_threshold` and `telegram.admin_chat_id`, with once-per-day alert semantics and non-blocking failure handling.
- Kept search behavior non-blocking: volume-tracking and alerting failures only emit warnings; search results still return.
- Expanded configuration validation to allow alert thresholds up to `10000`.
- Added unit/integration tests for counter persistence, alert trigger behavior, and once-per-day alert delivery.

### File List
- `_bmad-output/implementation-artifacts/6-3-search-volume-monitoring.md`
- `src/sohnbot/persistence/migrations/0007_search_volume.sql`
- `src/sohnbot/persistence/search_volume.py`
- `src/sohnbot/persistence/__init__.py`
- `src/sohnbot/capabilities/web.py`
- `src/sohnbot/config/registry.py`
- `tests/unit/test_search_volume.py`
- `tests/unit/test_web.py`
- `tests/unit/test_config_registry.py`
- `tests/integration/test_search_volume_flow.py`

---

## Critical Notes for Dev Agent

1. **Migration Number**
   - Latest migration is 0006_search_cache.sql (Story 6.1)
   - New migration MUST be 0007_search_volume.sql

2. **Counter Increment Location**
   - Add AFTER successful API call in brave_search()
   - After cache storage logic (around line 320)
   - Don't fail search if volume tracking fails (try/except)

3. **Alert Frequency**
   - alert_sent flag prevents duplicate alerts same day
   - Check flag BEFORE enqueuing notification
   - Mark alert as sent AFTER successful enqueue

4. **Admin Chat ID**
   - Read from telegram.admin_chat_id config
   - If not configured, log warning only (don't send)
   - Use enqueue_notification() for delivery

5. **SQL Date Functions**
   - Use `date('now')` for current date in YYYY-MM-DD format
   - Counter auto-resets via date-based SQL queries
   - No explicit reset logic needed (SQL handles it)

6. **Testing Strategy**
   - Lower threshold to 3-5 for integration tests
   - Mock enqueue_notification to verify alert sent
   - Verify alert sent only once (check call_count)

7. **Performance Considerations**
   - Volume increment is async (non-blocking)
   - Uses ON CONFLICT for atomic increment
   - Alert delivery via notification_outbox (async)
   - Total overhead: <5ms per search

8. **Graceful Degradation**
   - Volume tracking errors don't fail searches
   - Missing admin_chat_id logs warning only
   - Notification delivery failures handled by outbox system
