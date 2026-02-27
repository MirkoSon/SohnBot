# Story 3.1: Runtime Status Snapshot Collection

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a developer,
I want background status snapshot collection every 30 seconds,
So that current system state is always available for queries.

## Acceptance Criteria

**Given** SohnBot is running
**When** the snapshot collector runs every 30 seconds (configurable via `observability.collection_interval_seconds`)
**Then** snapshot includes: process info, broker activity, scheduler state, notifier state, resources, health checks
**And** snapshot collection is non-blocking (independent failure domain — errors are caught and logged, never crash the collector)
**And** snapshot collection completes in <100ms (NFR-024)
**And** snapshot collection consumes <2% CPU (NFR-024)
**And** in-memory cache is updated each cycle (module-level singleton, accessible globally)
**And** optional persistence to SQLite is disabled by default

## Tasks / Subtasks

- [ ] Task 1: Add psutil dependency (AC: all — required for CPU/RAM collection)
  - [ ] Add `psutil = "^6.0.0"` to `[tool.poetry.dependencies]` in `pyproject.toml`
  - [ ] Run `poetry lock --no-update` to update lock file (or `poetry add psutil`)
  - [ ] Verify import works: `import psutil`

- [ ] Task 2: Add observability config keys to registry and default.toml (AC: 1)
  - [ ] Add `observability.collection_interval_seconds` (dynamic, int, default: 30, min: 5, max: 300) to `src/sohnbot/config/registry.py`
  - [ ] Add `observability.persist_snapshots` (dynamic, bool, default: False) to `src/sohnbot/config/registry.py`
  - [ ] Add `[observability]` section entries to `config/default.toml` (extend existing section — it already has `http_enabled`, `http_port`, `http_host`, `refresh_seconds`)
  - [ ] Note: `observability.http_enabled`, `http_port`, `http_host` are already in default.toml — DO NOT duplicate

- [ ] Task 3: Create StatusSnapshot dataclasses in `src/sohnbot/capabilities/observe.py` (AC: 1)
  - [ ] Create `src/sohnbot/capabilities/observe.py` with all dataclasses exactly as defined in architecture:
    - `ProcessInfo` (pid, uptime_seconds, version, supervisor, supervisor_status, restart_count)
    - `BrokerActivity` (last_operation_timestamp, in_flight_operations, last_10_results)
    - `SchedulerState` (last_tick_timestamp, last_tick_local, next_jobs, active_jobs_count)
    - `NotifierState` (last_attempt_timestamp, pending_count, oldest_pending_age_seconds)
    - `ResourceUsage` (cpu_percent, cpu_1m_avg, ram_mb, db_size_mb, log_size_mb, snapshot_count, event_loop_lag_ms)
    - `HealthCheckResult` (name, status, message, timestamp, details)
    - `StatusSnapshot` (timestamp, process, broker, scheduler, notifier, resources, health, recent_operations)
  - [ ] Add module-level snapshot cache: `_snapshot_cache: StatusSnapshot | None = None`
  - [ ] Add `get_current_snapshot() -> StatusSnapshot | None` — returns `_snapshot_cache`
  - [ ] Add `update_snapshot_cache(snapshot: StatusSnapshot) -> None` — sets `_snapshot_cache`

- [ ] Task 4: Create `src/sohnbot/observability/` module (AC: all)
  - [ ] Create `src/sohnbot/observability/__init__.py` (empty or with minimal exports)
  - [ ] Create `src/sohnbot/observability/snapshot_collector.py` with:
    - `snapshot_collector_loop(interval_seconds: int = 30)` — the async background loop
    - `collect_snapshot() -> StatusSnapshot` — assembles full snapshot from subsystems
    - `collect_process_info() -> ProcessInfo` — uses psutil + detect_supervisor()
    - `collect_broker_activity() -> BrokerActivity` — queries execution_log via aiosqlite
    - `collect_scheduler_state() -> SchedulerState` — graceful fallback (jobs table not yet created until Epic 4)
    - `collect_notifier_state() -> NotifierState` — queries notification_outbox via aiosqlite
    - `collect_resource_usage() -> ResourceUsage` — psutil for CPU/RAM + file sizes
    - `query_recent_operations(limit: int = 100) -> list[dict]` — queries execution_log

- [ ] Task 5: Implement collect_process_info() (AC: 1, 3, 4)
  - [ ] Use `psutil.Process(os.getpid())` to get process handle
  - [ ] Calculate `uptime_seconds = int(time.time() - process.create_time())`
  - [ ] Get version from `pyproject.toml` or fallback to git hash (use importlib.metadata or read file directly)
  - [ ] Implement `detect_supervisor()` → try `shutil.which("pm2")` + subprocess to get pm2 info, fallback to "none"
  - [ ] Return `ProcessInfo(pid=..., uptime_seconds=..., version=..., supervisor=..., ...)`

- [ ] Task 6: Implement collect_broker_activity() (AC: 1)
  - [ ] Use `await get_db()` from `src/sohnbot/persistence/db.py`
  - [ ] Query `execution_log` for in-flight operations (status='in_progress')
  - [ ] Query `execution_log` for last 10 completed operation results grouped by status
  - [ ] Query `execution_log` for MAX(timestamp) as last_operation_timestamp
  - [ ] Handle empty table gracefully (return zeros/empty lists)

- [ ] Task 7: Implement collect_scheduler_state() (AC: 1)
  - [ ] CRITICAL: Epic 4 (Scheduler) is NOT yet implemented — `jobs` table does NOT exist
  - [ ] Return a stub/placeholder `SchedulerState` with safe defaults:
    ```python
    return SchedulerState(
        last_tick_timestamp=0,
        last_tick_local="N/A (scheduler not yet implemented)",
        next_jobs=[],
        active_jobs_count=0,
    )
    ```
  - [ ] Add TODO comment: `# Epic 4 will implement the scheduler; this returns placeholder until then`
  - [ ] Do NOT attempt to query the non-existent `jobs` table — it will cause a runtime error

- [ ] Task 8: Implement collect_notifier_state() (AC: 1)
  - [ ] Use `await get_db()` from `src/sohnbot/persistence/db.py`
  - [ ] Query `notification_outbox` for pending count: `SELECT COUNT(*) WHERE status = 'pending'`
  - [ ] Query `notification_outbox` for oldest pending: `SELECT MIN(created_at) WHERE status = 'pending'`
  - [ ] Query `notification_outbox` for last_attempt: `SELECT MAX(created_at)`
  - [ ] Calculate `oldest_pending_age_seconds = int(time.time()) - oldest_pending` (if exists)
  - [ ] Handle empty table gracefully

- [ ] Task 9: Implement collect_resource_usage() (AC: 3, 4)
  - [ ] CRITICAL: Use `await asyncio.to_thread(process.cpu_percent, 0.1)` — psutil.cpu_percent(interval=0.1) blocks for 100ms and MUST NOT block the event loop
  - [ ] Use `process.memory_info().rss // (1024 * 1024)` for RAM MB
  - [ ] Get DB size via `os.path.getsize(db_path) / (1024 * 1024)` if exists, else 0.0
  - [ ] Get log size by summing files in log directory if exists
  - [ ] Get snapshot count: query `SnapshotManager.list_snapshots()` or count git branches matching `snapshot/*` pattern — use the FIRST configured scope root as repo_path (or skip if not a git repo)
  - [ ] Measure event loop lag: use a simple asyncio scheduling trick (see Dev Notes below)
  - [ ] Return `ResourceUsage(cpu_percent=..., cpu_1m_avg=None, ram_mb=..., ...)`

- [ ] Task 10: Implement snapshot_collector_loop() (AC: 2, 3, 4, 5)
  - [ ] Implement `async def snapshot_collector_loop(interval_seconds: int = 30):`
  - [ ] Loop: `while True:` → collect snapshot → update cache → optional persist → sleep
  - [ ] ALL errors MUST be caught with `except Exception as e:` — log and continue (independent failure domain)
  - [ ] Use `await asyncio.sleep(interval_seconds)` between collections
  - [ ] Log at DEBUG level on success, ERROR level on failure (do not use WARNING — not a transient issue)
  - [ ] Add timing: measure `collect_snapshot()` duration, log if >100ms (performance guardrail for NFR-024)

- [ ] Task 11: Testing (AC: all)
  - [ ] Add `tests/unit/test_snapshot_collector.py`:
    - `test_collect_process_info_returns_valid_data` — pid > 0, uptime > 0
    - `test_collect_resource_usage_non_blocking` — verify function returns without hanging
    - `test_collect_scheduler_state_returns_placeholder` — confirm stub values until Epic 4
    - `test_collect_broker_activity_empty_db` — handle missing/empty execution_log
    - `test_collect_notifier_state_empty_db` — handle missing/empty notification_outbox
    - `test_snapshot_cache_update_and_get` — `update_snapshot_cache` → `get_current_snapshot`
    - `test_snapshot_collector_loop_catches_errors` — errors don't propagate out of loop
    - `test_collect_snapshot_completes_fast` — collect_snapshot() finishes within reasonable time
  - [ ] Add `tests/unit/test_observe_dataclasses.py`:
    - Test `StatusSnapshot` can be constructed with all fields
    - Test `get_current_snapshot()` returns None before first collection
    - Test `update_snapshot_cache()` → `get_current_snapshot()` returns the snapshot

## Dev Notes

### Epic 3 Context

**Epic Goal:** Monitor SohnBot's health, resource usage, and operation history.

**Epic Progress (at Story 3.1):**
- 🔄 Story 3.1: Runtime Status Snapshot Collection (THIS STORY — Foundation for all observability)
- 📋 Story 3.2: Health Checks Implementation (depends on this story)
- 📋 Story 3.3: System Status via Telegram (depends on 3.1 + 3.2)
- 📋 Story 3.4: Health Checks via Telegram (depends on 3.1 + 3.2)
- 📋 Story 3.5: Local HTTP Observability Server (depends on 3.1 + 3.2)
- 📋 Story 3.6: HTML Status Page (depends on 3.5)

**Why Story 3.1 first:** The snapshot collector is the data backbone. All other Epic 3 stories consume the in-memory cache that this story creates. Without the `StatusSnapshot` dataclasses and collector loop, nothing else can be built.

### Critical Architecture Decisions

**1. psutil is NOT in pyproject.toml — must be added first**

The current `pyproject.toml` does NOT list psutil. The architecture explicitly states:
> "Requires `psutil` (process resource monitoring)"

Add to `[tool.poetry.dependencies]`:
```toml
psutil = "^6.0.0"
```

Latest stable as of 2026: psutil 6.x (Python 3.13 compatible).

**2. `psutil.cpu_percent(interval=0.1)` BLOCKS THE EVENT LOOP**

This is the most critical gotcha. `cpu_percent(interval=0.1)` sleeps for 100ms before returning. In an async context this blocks the entire event loop — a major performance violation.

Use `asyncio.to_thread` to offload it:
```python
cpu_pct = await asyncio.to_thread(psutil.Process(os.getpid()).cpu_percent, 0.1)
# Or use interval=None for zero-sleep (uses last measurement):
cpu_pct = psutil.Process(os.getpid()).cpu_percent(interval=None)
```

Prefer `interval=None` (non-blocking, returns 0.0 on first call) for snapshot_collector, since it runs every 30 seconds anyway — the measurement between cycles provides the average naturally.

**3. Scheduler (Epic 4) is NOT implemented — jobs table does NOT exist**

Story 3.1 is created BEFORE Epic 4. The `jobs` table referenced in the architecture's `collect_scheduler_state()` **does not exist in the database yet**. Querying it will raise `aiosqlite.OperationalError: no such table: jobs`.

**MANDATORY:** Return a placeholder `SchedulerState` until Epic 4 is implemented:
```python
def collect_scheduler_state() -> SchedulerState:
    # TODO: Epic 4 will implement the scheduler. This returns a placeholder.
    return SchedulerState(
        last_tick_timestamp=0,
        last_tick_local="N/A (scheduler not yet implemented)",
        next_jobs=[],
        active_jobs_count=0,
    )
```

**4. aiohttp is NOT needed for Story 3.1**

`aiohttp` is required for Stories 3.5/3.6 (HTTP server). Do NOT add it in this story — it's out of scope.

**5. Health checks are Story 3.2 — minimal stub for Story 3.1**

The `health` field in `StatusSnapshot` requires health check results. Story 3.2 implements health checks. For Story 3.1, the `collect_snapshot()` should pass an empty list `[]` for the health field (health checks will be integrated in Story 3.2):
```python
health=[],  # Populated in Story 3.2
```

### Module Structure

**New files to create:**
```
src/sohnbot/capabilities/observe.py          # StatusSnapshot dataclasses + cache
src/sohnbot/observability/__init__.py         # New module init
src/sohnbot/observability/snapshot_collector.py  # Background task + collect functions
tests/unit/test_snapshot_collector.py
tests/unit/test_observe_dataclasses.py
```

**Files to modify:**
```
pyproject.toml                               # Add psutil dependency
src/sohnbot/config/registry.py               # Add observability config keys
config/default.toml                          # Add collection_interval_seconds, persist_snapshots
```

**Files to reference (DO NOT MODIFY unless needed):**
```
src/sohnbot/persistence/db.py               # get_db() — aiosqlite connection
src/sohnbot/persistence/audit.py            # execution_log table schema reference
src/sohnbot/persistence/notification.py     # notification_outbox table schema reference
src/sohnbot/config/manager.py               # get() config access pattern
src/sohnbot/capabilities/git/snapshot_manager.py  # list_snapshots() for snapshot count
```

### Complete Dataclass Specification

From architecture (follow EXACTLY — other stories build on this interface):

```python
# src/sohnbot/capabilities/observe.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class ProcessInfo:
    pid: int
    uptime_seconds: int
    version: str                        # From pyproject.toml or git hash
    supervisor: Optional[str]           # "pm2" | "systemd" | "none"
    supervisor_status: Optional[str]    # pm2 status if available
    restart_count: Optional[int]

@dataclass
class BrokerActivity:
    last_operation_timestamp: int       # Unix epoch
    in_flight_operations: list[dict]    # [{operation_id, tool, tier, elapsed_s}]
    last_10_results: dict               # {"ok": 8, "error": 1, "timeout": 1}

@dataclass
class SchedulerState:
    last_tick_timestamp: int            # Unix epoch
    last_tick_local: str                # ISO format in local TZ
    next_jobs: list[dict]               # [{job_name, next_run_utc, next_run_local}]
    active_jobs_count: int

@dataclass
class NotifierState:
    last_attempt_timestamp: int         # Unix epoch
    pending_count: int
    oldest_pending_age_seconds: Optional[int]

@dataclass
class ResourceUsage:
    cpu_percent: float                  # Instant CPU %
    cpu_1m_avg: Optional[float]         # 1-min average if available
    ram_mb: int                         # RSS in MB
    db_size_mb: float
    log_size_mb: float
    snapshot_count: int                 # Total git snapshot branches
    event_loop_lag_ms: Optional[float]  # Event loop lag estimate

@dataclass
class HealthCheckResult:
    name: str                           # "sqlite_writable", "scheduler_lag", etc.
    status: str                         # "pass" | "fail" | "warn"
    message: str
    timestamp: int                      # Unix epoch
    details: Optional[dict]             # Additional context

@dataclass
class StatusSnapshot:
    timestamp: int                      # Snapshot creation time (UTC epoch)
    process: ProcessInfo
    broker: BrokerActivity
    scheduler: SchedulerState
    notifier: NotifierState
    resources: ResourceUsage
    health: list[HealthCheckResult]
    recent_operations: list[dict]       # Last 100 operations (trimmed)


# Module-level singleton cache
_snapshot_cache: Optional[StatusSnapshot] = None


def get_current_snapshot() -> Optional[StatusSnapshot]:
    """Return the latest cached snapshot, or None if not yet collected."""
    return _snapshot_cache


def update_snapshot_cache(snapshot: StatusSnapshot) -> None:
    """Update the global in-memory snapshot cache."""
    global _snapshot_cache
    _snapshot_cache = snapshot
```

### snapshot_collector.py Implementation Pattern

```python
# src/sohnbot/observability/snapshot_collector.py
import asyncio
import os
import time
from datetime import datetime, timezone

import psutil
import structlog

from ..capabilities.observe import (
    BrokerActivity, NotifierState, ProcessInfo, ResourceUsage,
    SchedulerState, StatusSnapshot, update_snapshot_cache,
)
from ..config.manager import get_config_manager
from ..persistence.db import get_db

logger = structlog.get_logger(__name__)


async def snapshot_collector_loop(interval_seconds: int = 30) -> None:
    """
    Background task that collects runtime status snapshots every N seconds.
    Non-blocking, independent failure domain — errors are caught and logged, never propagated.
    """
    logger.info("snapshot_collector_started", interval_seconds=interval_seconds)
    while True:
        try:
            start_ns = time.perf_counter_ns()
            snapshot = await collect_snapshot()
            update_snapshot_cache(snapshot)

            duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            if duration_ms > 100:
                logger.warning(
                    "snapshot_collection_slow",
                    duration_ms=round(duration_ms, 1),
                    threshold_ms=100,
                )
            else:
                logger.debug("snapshot_collected", duration_ms=round(duration_ms, 1))

            # Optional: persist to SQLite (disabled by default)
            try:
                config = get_config_manager()
                if config.get("observability.persist_snapshots"):
                    await _persist_snapshot(snapshot)
            except Exception:
                pass  # Config not initialized in tests — ignore

        except Exception as exc:
            logger.error(
                "snapshot_collection_failed",
                error=str(exc),
                exc_info=True,
            )

        await asyncio.sleep(interval_seconds)


async def collect_snapshot() -> StatusSnapshot:
    """Collect current runtime status from all subsystems. Read-only, non-blocking."""
    timestamp = int(datetime.now(timezone.utc).timestamp())

    process_info = collect_process_info()
    broker_activity = await collect_broker_activity()
    scheduler_state = collect_scheduler_state()
    notifier_state = await collect_notifier_state()
    resources = await collect_resource_usage()
    recent_ops = await query_recent_operations(limit=100)

    return StatusSnapshot(
        timestamp=timestamp,
        process=process_info,
        broker=broker_activity,
        scheduler=scheduler_state,
        notifier=notifier_state,
        resources=resources,
        health=[],  # Health checks integrated in Story 3.2
        recent_operations=recent_ops,
    )
```

### Measuring Event Loop Lag

Event loop lag is estimated by scheduling a callback and measuring how long it takes to actually run:

```python
async def _measure_event_loop_lag() -> Optional[float]:
    """
    Estimate event loop lag by measuring callback scheduling delay.
    Returns lag in milliseconds, or None if measurement fails.
    """
    try:
        start = time.perf_counter()
        await asyncio.sleep(0)  # Yield control and measure round-trip
        elapsed_ms = (time.perf_counter() - start) * 1000
        # asyncio.sleep(0) ideally takes ~0ms; anything over 1ms indicates lag
        return round(elapsed_ms, 2)
    except Exception:
        return None
```

### Config Registry Keys to Add

```python
# In src/sohnbot/config/registry.py REGISTRY dict:
"observability.collection_interval_seconds": ConfigKey(
    tier="dynamic",
    value_type=int,
    default=30,
    min_value=5,
    max_value=300,
),
"observability.persist_snapshots": ConfigKey(
    tier="dynamic",
    value_type=bool,
    default=False,
),
```

The `observability.http_enabled`, `observability.http_port`, `observability.http_host` keys are NOT yet in the registry — they are needed for Stories 3.5/3.6. Do NOT add them in this story unless you find they're missing from the registry.

### Collector Integration Point (Context for Future)

Story 3.1 creates the collector function but does NOT wire it into the main application lifecycle — that's in scope for the story that activates observability (likely the Telegram integration story or a main.py update). The function signature must be:

```python
async def snapshot_collector_loop(interval_seconds: int = 30) -> None:
```

This will be launched with `asyncio.TaskGroup` or `asyncio.create_task()` in main.py in a future story. The collector is designed as a standalone coroutine — it does NOT need the broker or any injected dependency (it reads from the global DB manager and config).

### Database Schema Reference

`execution_log` table (from Story 1.2 migration):
```sql
CREATE TABLE execution_log (
    operation_id TEXT PRIMARY KEY,
    timestamp INTEGER NOT NULL,    -- Unix epoch
    capability TEXT NOT NULL,
    action TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    tier INTEGER NOT NULL,
    status TEXT NOT NULL,          -- 'in_progress' | 'completed' | 'failed' | 'postponed'
    file_paths TEXT,               -- JSON array
    snapshot_ref TEXT,
    duration_ms INTEGER,
    error_details TEXT             -- JSON
) STRICT
```

`notification_outbox` table (from Story 1.8):
```sql
CREATE TABLE notification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    message_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'sent' | 'failed'
    created_at INTEGER NOT NULL,             -- Unix epoch
    sent_at INTEGER,
    retry_count INTEGER NOT NULL DEFAULT 0
) STRICT
```

### Project Structure Notes

**Alignment with Unified Project Structure:**
```
src/sohnbot/
├── capabilities/
│   ├── observe.py              # NEW: Dataclasses + in-memory cache (Story 3.1)
│   └── ...
├── observability/              # NEW: Observability subsystem module
│   ├── __init__.py             # Empty init
│   ├── snapshot_collector.py   # Background task + collection functions
│   ├── health_checks.py        # Story 3.2 (DO NOT create in this story)
│   ├── http_server.py          # Story 3.5 (DO NOT create in this story)
│   └── templates/              # Story 3.6 (DO NOT create in this story)
```

**Do NOT create** `health_checks.py`, `http_server.py`, or `templates/` — those are for Stories 3.2, 3.5, 3.6. Only create what is needed for Story 3.1.

### Previous Story Intelligence

**From Story 2.4 (Enhanced Snapshot Branch Management — JUST COMPLETED):**

Key review findings resolved in Story 2.4:
1. **[MEDIUM] Async consistency**: `prune_snapshots` was refactored from sync subprocess to `asyncio.create_subprocess_exec` for consistency — follow the same pattern in Story 3.1 (use async operations; only use `asyncio.to_thread` for CPU-bound/blocking calls)
2. **[LOW] Config duplication**: Consolidate config keys under a single name — do not create duplicate keys in registry

Apply to Story 3.1:
- All database queries must use `await get_db()` (async)
- CPU measurement must use `asyncio.to_thread` or non-blocking `interval=None` variant
- Single config key per setting (no duplicates)

**From Story 1.8 (Structured Operation Logging):**
- `notification_outbox` table schema is well-established — query `status = 'pending'` and `created_at` fields
- `execution_log` table uses `timestamp` (integer epoch) and `status` fields

**From Story 1.1 (Configuration System):**
- Add new config keys to `REGISTRY` dict in `registry.py` with `ConfigKey(tier="dynamic", ...)`
- Add corresponding entries to `config/default.toml` under `[observability]` section
- Use `config_manager.get("observability.collection_interval_seconds")` to retrieve

**From Epic 2 Retrospective:**
- Security and adversarial thinking: test edge cases (empty DB, missing binary, etc.)
- Monitor mobile/cloud execution behavior — snapshot collector must work gracefully in non-standard environments (Docker, WSL, pm2)

### Git Intelligence

Recent commit history shows:
- `ceefb66 Epic 2 completed and reviewed` — all git operations implemented and reviewed
- `c3e7b04 Story 2.1 implemented and reviewed` — clean history of story-by-story implementation
- `51fd25f Epic 1 complete and reviewed` — full test coverage established

**Pattern to follow:** Implement → test → commit (referencing story key `3-1`)

### Latest Tech Information

**psutil 6.x (2026):**
- Python 3.13 fully supported in psutil 6.0+
- `psutil.Process.cpu_percent(interval=None)` returns last cached value (non-blocking, returns 0.0 on first call)
- `psutil.Process.memory_info().rss` — Resident Set Size in bytes (reliable across platforms)
- `psutil.Process.create_time()` — float, seconds since epoch (for uptime calculation)
- No `interval` argument needed for memory_info (non-blocking)

**asyncio background tasks (Python 3.13):**
- Use `asyncio.TaskGroup` for structured concurrency (available since Python 3.11)
- `asyncio.sleep(0)` yields control to event loop without waiting
- `asyncio.to_thread(func, *args)` — run blocking function in thread pool (Python 3.9+)

**structlog (24.x):**
- Use `logger.debug`, `logger.info`, `logger.warning`, `logger.error` — consistent with existing codebase
- Pass `exc_info=True` for errors to capture stack traces
- Bind context with `bind_contextvars` for request-scoped logging (not needed for background task)

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.1: Runtime Status Snapshot Collection]
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 3: System Observability & Monitoring]
- [Source: _bmad-output/planning-artifacts/architecture.md#Observability Capability] (lines 1100–1406)
- [Source: _bmad-output/planning-artifacts/architecture.md#Implementation Specification] — exact dataclass definitions
- [Source: src/sohnbot/persistence/db.py] — DatabaseManager and get_db() pattern
- [Source: src/sohnbot/persistence/audit.py] — execution_log schema and aiosqlite query pattern
- [Source: src/sohnbot/persistence/notification.py] — notification_outbox schema reference
- [Source: src/sohnbot/config/registry.py] — ConfigKey pattern for new config keys
- [Source: config/default.toml] — existing observability section (http_enabled, http_port, http_host)
- [Source: src/sohnbot/capabilities/git/snapshot_manager.py] — list_snapshots() for snapshot count
- [Source: _bmad-output/implementation-artifacts/2-4-enhanced-snapshot-branch-management.md] — async patterns, review findings
- [Source: _bmad-output/implementation-artifacts/epic-2-retro-2026-02-27.md] — Epic 2 lessons

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
