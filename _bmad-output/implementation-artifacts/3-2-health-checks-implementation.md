# Story 3.2: Health Checks Implementation

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want automated health checks for critical subsystems,
So that I can detect issues before they cause failures.

## Acceptance Criteria

**Given** the system is running
**When** health checks execute (integrated into snapshot collection every 30 seconds)
**Then** SQLite writable check verifies database write capability (pass/fail/warn)
**And** scheduler lag check detects if scheduler is behind (threshold: 5 minutes configurable) — returns "pass" when scheduler not yet implemented (Epic 4 stub)
**And** job timeout check identifies jobs exceeding timeout — returns "pass" gracefully when jobs table does not exist (Epic 4 stub)
**And** notifier alive check verifies notification worker is active (uses NotifierState.last_attempt_timestamp)
**And** outbox stuck check identifies pending notifications older than 1 hour (configurable threshold)
**And** disk usage check (optional, disabled by default) monitors DB + log size against configured cap
**And** health checks complete within 500ms total (NFR-026)
**And** false positive rate < 1% over 30 days (NFR-026)
**And** `StatusSnapshot.health` field is populated (no longer empty `[]` as in Story 3.1)

## Tasks / Subtasks

- [ ] Task 1: Add health check config keys to registry and default.toml (AC: all)
  - [ ] Add `observability.scheduler_lag_threshold` (dynamic, int, default: 300, min: 60, max: 3600) to `src/sohnbot/config/registry.py` under the OBSERVABILITY section
  - [ ] Add `observability.notifier_lag_threshold` (dynamic, int, default: 120, min: 30, max: 600) to `src/sohnbot/config/registry.py`
  - [ ] Add `observability.outbox_stuck_threshold` (dynamic, int, default: 3600, min: 300, max: 86400) to `src/sohnbot/config/registry.py`
  - [ ] Add `observability.disk_cap_enabled` (dynamic, bool, default: False) to `src/sohnbot/config/registry.py`
  - [ ] Add `observability.disk_cap_mb` (dynamic, int, default: 1000, min: 100, max: 100000) to `src/sohnbot/config/registry.py`
  - [ ] Add the 5 new keys to `config/default.toml` under `[observability]` section
  - [ ] CRITICAL: Do NOT add `http_enabled`, `http_port`, `http_host` — already in registry and default.toml

- [ ] Task 2: Create `src/sohnbot/observability/health_checks.py` (AC: all)
  - [ ] Create the module with `async def run_all_health_checks(scheduler_state, notifier_state, resources) -> list[HealthCheckResult]:`
  - [ ] Import `HealthCheckResult` from `..capabilities.observe`
  - [ ] Import `get_db` from `..persistence.db`
  - [ ] Import `get_config_manager` from `..config.manager`
  - [ ] Implement `async def check_sqlite_writable() -> HealthCheckResult`
  - [ ] Implement `def check_scheduler_lag(scheduler_state: SchedulerState) -> HealthCheckResult`
  - [ ] Implement `def check_job_timeouts() -> HealthCheckResult` (sync, handles missing table)
  - [ ] Implement `def check_notifier_alive(notifier_state: NotifierState) -> HealthCheckResult`
  - [ ] Implement `def check_outbox_stuck(notifier_state: NotifierState) -> HealthCheckResult`
  - [ ] Implement `def check_disk_usage(resources: ResourceUsage) -> HealthCheckResult`
  - [ ] All individual check functions must catch exceptions and return `fail` HealthCheckResult — never raise

- [ ] Task 3: Integrate health checks into `snapshot_collector.py` (AC: health field populated)
  - [ ] Import `run_all_health_checks` from `.health_checks`
  - [ ] Import `SchedulerState`, `NotifierState`, `ResourceUsage` are already imported from `..capabilities.observe`
  - [ ] In `collect_snapshot()`, replace `health=[]` with:
    ```python
    health = await run_all_health_checks(
        scheduler_state=scheduler_state,
        notifier_state=notifier_state,
        resources=resources,
    )
    ```
  - [ ] Place the `health` call AFTER `scheduler_state`, `notifier_state`, and `resources` are collected
  - [ ] CRITICAL: Update `StatusSnapshot.health` docstring in `observe.py` from "Empty until Story 3.2" to "Health check results from health_checks.py"
  - [ ] CRITICAL: Ensure `health` call is wrapped in the overall `collect_snapshot()` timing — all errors in `run_all_health_checks` are caught internally, never propagate to `collect_snapshot()`

- [ ] Task 4: Testing (AC: all)
  - [ ] Create `tests/unit/test_health_checks.py` with all required tests (see Dev Notes below for exact test list)
  - [ ] Run the full test suite to verify no regressions

## Dev Notes

### Epic 3 Context

**Epic Goal:** Monitor SohnBot's health, resource usage, and operation history through Telegram commands and a local HTTP dashboard.

**Epic 3 Progress (at Story 3.2):**
- ✅ Story 3.1: Runtime Status Snapshot Collection (DONE — psutil, snapshot dataclasses, background collector, `health=[]` placeholder)
- 🔄 Story 3.2: Health Checks Implementation (THIS STORY — fill `health=[]` with real results)
- 📋 Story 3.3: System Status via Telegram (depends on 3.1 + 3.2)
- 📋 Story 3.4: Health Checks via Telegram (depends on 3.1 + 3.2)
- 📋 Story 3.5: Local HTTP Observability Server (depends on 3.1 + 3.2)
- 📋 Story 3.6: HTML Status Page (depends on 3.5)

**Why Story 3.2 now:** The `StatusSnapshot.health` field has been `[]` since Story 3.1. Stories 3.3 and 3.4 will expose health status over Telegram — they depend on real health check results being in the snapshot. This story creates the health check engine and wires it in.

### Critical Architecture Decisions

**1. Health checks are integrated into snapshot collection (NOT a separate polling loop)**

Health checks run as part of `collect_snapshot()` in `snapshot_collector.py`. They are NOT a separate background task. The 30-second collection interval (configurable) drives health check frequency. This keeps the system simple and ensures health data is always in sync with the rest of the snapshot.

**2. Scheduler (Epic 4) and jobs table do NOT exist — MANDATORY graceful handling**

The `check_scheduler_lag()` and `check_job_timeouts()` functions MUST handle the absence of the scheduler gracefully:

- `collect_scheduler_state()` (already implemented in Story 3.1) returns `last_tick_timestamp=0` and `last_tick_local="N/A (scheduler not yet implemented)"`
- `check_scheduler_lag(scheduler_state)`:
  - Check `if scheduler_state.last_tick_local == "N/A (scheduler not yet implemented)"` → return `HealthCheckResult(name="scheduler_lag", status="pass", message="Scheduler not yet implemented (Epic 4 pending)", ...)`
  - Do NOT compute lag from `last_tick_timestamp=0` — that would give a massive lag and trigger false positives
- `check_job_timeouts()`:
  - This function queries `execution_log` for in-progress operations that look like scheduled jobs (capability = 'sched'), NOT the non-existent `jobs` table
  - Or alternatively, simply return "pass" with message "Scheduler not yet implemented (Epic 4 pending)" — matching the same graceful pattern
  - Do NOT query a `jobs` table — it does not exist

**3. Health check functions accept pre-collected state (avoid duplicate DB queries)**

`run_all_health_checks(scheduler_state, notifier_state, resources)` accepts already-collected state from `collect_snapshot()`. This avoids:
- Re-querying the DB for notifier state (already collected by `collect_notifier_state()`)
- Re-computing resource usage (already collected by `collect_resource_usage()`)
- Extra DB connections in the already-performance-sensitive 100ms window

Only `check_sqlite_writable()` performs its own DB access (it specifically needs to test write capability).

**4. `check_sqlite_writable()` must be async — uses `await get_db()`**

Pattern from Story 3.1:
```python
async def check_sqlite_writable() -> HealthCheckResult:
    try:
        db = await get_db()
        # Test write via temporary table in transaction that is rolled back
        await db.execute("CREATE TEMP TABLE IF NOT EXISTS _health_check_test (id INTEGER)")
        await db.execute("INSERT INTO _health_check_test VALUES (1)")
        await db.execute("DELETE FROM _health_check_test WHERE 1=1")
        # Check WAL mode
        cursor = await db.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        await cursor.close()
        journal_mode = row[0] if row else "unknown"
        if journal_mode.upper() != "WAL":
            return HealthCheckResult(
                name="sqlite_writable",
                status="warn",
                message=f"SQLite writable but not in WAL mode (current: {journal_mode})",
                timestamp=int(time.time()),
                details={"journal_mode": journal_mode},
            )
        return HealthCheckResult(
            name="sqlite_writable",
            status="pass",
            message="SQLite writable and WAL enabled",
            timestamp=int(time.time()),
            details=None,
        )
    except Exception as exc:
        return HealthCheckResult(
            name="sqlite_writable",
            status="fail",
            message=f"SQLite write test failed: {str(exc)}",
            timestamp=int(time.time()),
            details={"error": str(exc)},
        )
```

Note: `CREATE TEMP TABLE IF NOT EXISTS` avoids table-already-exists errors in repeated calls. TEMP tables are session-scoped and auto-cleaned.

**5. `run_all_health_checks()` must be async**

Because `check_sqlite_writable()` is async, `run_all_health_checks()` must also be async:
```python
async def run_all_health_checks(
    scheduler_state: SchedulerState,
    notifier_state: NotifierState,
    resources: ResourceUsage,
) -> list[HealthCheckResult]:
    checks = [
        await check_sqlite_writable(),
        check_scheduler_lag(scheduler_state),
        check_job_timeouts(),
        check_notifier_alive(notifier_state),
        check_outbox_stuck(notifier_state),
        check_disk_usage(resources),
    ]
    return checks
```

All non-async checks are synchronous functions that catch their own exceptions internally.

**6. `check_notifier_alive()` uses `NotifierState.last_attempt_timestamp`**

`last_attempt_timestamp` was fixed in Story 3.1 code review (MEDIUM-2): it now correctly reflects the most recent `sent_at` (actual delivery attempt), falling back to `MAX(created_at)`. This is the correct field to use for "is notifier making progress".

Special case: if `last_attempt_timestamp == 0` (no notifications ever attempted AND outbox is empty), return "pass" — system is fresh, not broken.

**7. Config access pattern**

Use `get_config_manager()` from `..config.manager`. Pattern from existing code:
```python
from ..config.manager import get_config_manager

config = get_config_manager()
threshold = config.get("observability.scheduler_lag_threshold")
```

Wrap config access in try/except — config manager may not be initialized in test environments.

### Module Structure

**New file to create:**
```
src/sohnbot/observability/health_checks.py   # Health check implementations (Story 3.2)
```

**Files to modify:**
```
src/sohnbot/config/registry.py              # Add 5 new observability health check config keys
config/default.toml                         # Add 5 new keys under [observability]
src/sohnbot/observability/snapshot_collector.py  # Wire health checks into collect_snapshot()
src/sohnbot/capabilities/observe.py         # Update StatusSnapshot.health docstring comment
```

**Files to reference (DO NOT MODIFY unless needed):**
```
src/sohnbot/capabilities/observe.py         # HealthCheckResult, SchedulerState, NotifierState, ResourceUsage dataclasses
src/sohnbot/persistence/db.py               # get_db() — aiosqlite async connection
src/sohnbot/config/manager.py               # get_config_manager() — config access pattern
tests/unit/test_snapshot_collector.py       # Reference for testing patterns (aiosqlite mocking)
```

### Complete Health Checks Specification

#### check_sqlite_writable() — async

```python
async def check_sqlite_writable() -> HealthCheckResult:
    """Verify SQLite is writable and in WAL mode."""
    # See full implementation in Critical Architecture Decision #4 above
    # Key: Use CREATE TEMP TABLE IF NOT EXISTS for idempotent write test
    # Check PRAGMA journal_mode for WAL
    # Return: pass (WAL), warn (writable but not WAL), fail (any exception)
```

#### check_scheduler_lag(scheduler_state: SchedulerState) — sync

```python
def check_scheduler_lag(scheduler_state: SchedulerState) -> HealthCheckResult:
    """Check if scheduler is running and not lagging behind."""
    now = int(time.time())

    # Graceful handling for Epic 4 not-yet-implemented
    if scheduler_state.last_tick_timestamp == 0:
        return HealthCheckResult(
            name="scheduler_lag",
            status="pass",
            message="Scheduler not yet implemented (Epic 4 pending)",
            timestamp=now,
            details=None,
        )

    lag_seconds = now - scheduler_state.last_tick_timestamp
    try:
        config = get_config_manager()
        threshold = config.get("observability.scheduler_lag_threshold")
    except Exception:
        threshold = 300  # Default: 5 minutes

    if lag_seconds > threshold:
        return HealthCheckResult(
            name="scheduler_lag",
            status="fail",
            message=f"Scheduler lag {lag_seconds}s exceeds threshold {threshold}s",
            timestamp=now,
            details={"lag_seconds": lag_seconds, "threshold": threshold},
        )
    elif lag_seconds > threshold * 0.5:
        return HealthCheckResult(
            name="scheduler_lag",
            status="warn",
            message=f"Scheduler lag {lag_seconds}s approaching threshold {threshold}s",
            timestamp=now,
            details={"lag_seconds": lag_seconds, "threshold": threshold},
        )
    return HealthCheckResult(
        name="scheduler_lag",
        status="pass",
        message=f"Scheduler healthy (lag: {lag_seconds}s)",
        timestamp=now,
        details=None,
    )
```

#### check_job_timeouts() — sync

```python
def check_job_timeouts() -> HealthCheckResult:
    """Check if scheduler jobs are exceeding timeout (stub until Epic 4)."""
    # Epic 4 (scheduler) not yet implemented — no jobs table exists
    # Return pass until scheduler is built
    return HealthCheckResult(
        name="job_timeouts",
        status="pass",
        message="Scheduler not yet implemented (Epic 4 pending)",
        timestamp=int(time.time()),
        details=None,
    )
    # TODO: Epic 4 — query execution_log WHERE capability='sched' AND status='in_progress'
    # AND (unixepoch() - timestamp) > scheduler.job_timeout_seconds
```

#### check_notifier_alive(notifier_state: NotifierState) — sync

```python
def check_notifier_alive(notifier_state: NotifierState) -> HealthCheckResult:
    """Check if notification worker is making progress."""
    now = int(time.time())

    # Fresh system: no notifications ever — outbox empty, no attempt made
    if notifier_state.last_attempt_timestamp == 0:
        return HealthCheckResult(
            name="notifier_alive",
            status="pass",
            message="Notifier ready (no notifications sent yet)",
            timestamp=now,
            details=None,
        )

    lag = now - notifier_state.last_attempt_timestamp
    try:
        config = get_config_manager()
        threshold = config.get("observability.notifier_lag_threshold")
    except Exception:
        threshold = 120  # Default: 2 minutes

    if lag > threshold:
        return HealthCheckResult(
            name="notifier_alive",
            status="fail",
            message=f"Notifier last attempt {lag}s ago (threshold: {threshold}s)",
            timestamp=now,
            details={"lag_seconds": lag, "threshold": threshold},
        )
    return HealthCheckResult(
        name="notifier_alive",
        status="pass",
        message=f"Notifier active (last attempt {lag}s ago)",
        timestamp=now,
        details=None,
    )
```

#### check_outbox_stuck(notifier_state: NotifierState) — sync

```python
def check_outbox_stuck(notifier_state: NotifierState) -> HealthCheckResult:
    """Check if notification outbox has stuck pending messages."""
    now = int(time.time())

    if notifier_state.oldest_pending_age_seconds is None:
        return HealthCheckResult(
            name="outbox_stuck",
            status="pass",
            message="Outbox empty",
            timestamp=now,
            details=None,
        )

    try:
        config = get_config_manager()
        threshold = config.get("observability.outbox_stuck_threshold")
    except Exception:
        threshold = 3600  # Default: 1 hour

    age = notifier_state.oldest_pending_age_seconds
    if age > threshold:
        return HealthCheckResult(
            name="outbox_stuck",
            status="warn",
            message=f"Oldest pending notification {age}s old (threshold: {threshold}s)",
            timestamp=now,
            details={"oldest_age_seconds": age, "threshold": threshold},
        )
    return HealthCheckResult(
        name="outbox_stuck",
        status="pass",
        message=f"Outbox healthy (oldest pending: {age}s)",
        timestamp=now,
        details=None,
    )
```

#### check_disk_usage(resources: ResourceUsage) — sync

```python
def check_disk_usage(resources: ResourceUsage) -> HealthCheckResult:
    """Optional disk usage check against configured cap (disabled by default)."""
    now = int(time.time())

    try:
        config = get_config_manager()
        disk_cap_enabled = config.get("observability.disk_cap_enabled")
    except Exception:
        disk_cap_enabled = False

    if not disk_cap_enabled:
        return HealthCheckResult(
            name="disk_usage",
            status="pass",
            message="Disk usage check disabled (set observability.disk_cap_enabled=true to enable)",
            timestamp=now,
            details=None,
        )

    total_mb = resources.db_size_mb + resources.log_size_mb
    try:
        cap_mb = config.get("observability.disk_cap_mb")
    except Exception:
        cap_mb = 1000

    if total_mb > cap_mb:
        return HealthCheckResult(
            name="disk_usage",
            status="warn",
            message=f"Disk usage {total_mb:.1f}MB exceeds cap {cap_mb}MB",
            timestamp=now,
            details={"total_mb": round(total_mb, 2), "cap_mb": cap_mb},
        )
    return HealthCheckResult(
        name="disk_usage",
        status="pass",
        message=f"Disk usage {total_mb:.1f}MB within cap {cap_mb}MB",
        timestamp=now,
        details=None,
    )
```

### Config Keys to Add

Add these 5 keys to `src/sohnbot/config/registry.py` in the `# ===== OBSERVABILITY =====` section, after the existing `observability.persist_snapshots` key:

```python
"observability.scheduler_lag_threshold": ConfigKey(
    tier="dynamic",
    value_type=int,
    default=300,   # 5 minutes
    min_value=60,
    max_value=3600,
),
"observability.notifier_lag_threshold": ConfigKey(
    tier="dynamic",
    value_type=int,
    default=120,   # 2 minutes
    min_value=30,
    max_value=600,
),
"observability.outbox_stuck_threshold": ConfigKey(
    tier="dynamic",
    value_type=int,
    default=3600,  # 1 hour
    min_value=300,
    max_value=86400,
),
"observability.disk_cap_enabled": ConfigKey(
    tier="dynamic",
    value_type=bool,
    default=False,
),
"observability.disk_cap_mb": ConfigKey(
    tier="dynamic",
    value_type=int,
    default=1000,  # 1 GB
    min_value=100,
    max_value=100000,
),
```

Add these 5 entries to `config/default.toml` in the `[observability]` section (after `persist_snapshots`):

```toml
# Health check thresholds (DYNAMIC - hot-reloadable)
scheduler_lag_threshold = 300   # Seconds before scheduler is considered lagging (default: 5 min)
notifier_lag_threshold = 120    # Seconds before notifier is considered stalled (default: 2 min)
outbox_stuck_threshold = 3600   # Seconds before pending notification is considered stuck (default: 1 hr)
disk_cap_enabled = false        # Enable disk usage cap check (DYNAMIC, disabled by default)
disk_cap_mb = 1000              # Disk cap in MB for DB + logs combined (default: 1 GB)
```

### Snapshot Collector Update

In `src/sohnbot/observability/snapshot_collector.py`, make these changes:

**Import addition** (at top with other imports from health_checks):
```python
from .health_checks import run_all_health_checks
```

**`collect_snapshot()` update** — replace `health=[]` line:
```python
async def collect_snapshot() -> StatusSnapshot:
    timestamp = int(datetime.now(timezone.utc).timestamp())

    process_info = await asyncio.to_thread(collect_process_info)
    broker_activity = await collect_broker_activity()
    scheduler_state = collect_scheduler_state()
    notifier_state = await collect_notifier_state()
    resources = await collect_resource_usage()
    recent_ops = await query_recent_operations(limit=100)

    # Story 3.2: Run health checks using already-collected subsystem state
    health = await run_all_health_checks(
        scheduler_state=scheduler_state,
        notifier_state=notifier_state,
        resources=resources,
    )

    return StatusSnapshot(
        timestamp=timestamp,
        process=process_info,
        broker=broker_activity,
        scheduler=scheduler_state,
        notifier=notifier_state,
        resources=resources,
        health=health,          # Populated by Story 3.2 (was [] in 3.1)
        recent_operations=recent_ops,
    )
```

### observe.py Docstring Update

In `src/sohnbot/capabilities/observe.py`, update line 87 in `StatusSnapshot`:

```python
# Change this:
health: list[HealthCheckResult]  # Empty until Story 3.2

# To this:
health: list[HealthCheckResult]  # Health check results from health_checks.py (Story 3.2)
```

### Required Tests

Create `tests/unit/test_health_checks.py` with the following tests:

```
test_check_sqlite_writable_pass                    — real async DB, pass result
test_check_sqlite_writable_fail_on_db_error        — mock get_db() to raise, expect fail status
test_check_sqlite_writable_warns_if_not_wal        — mock PRAGMA journal_mode to return "delete"
test_check_scheduler_lag_pass_when_not_implemented — scheduler_state with last_tick_timestamp=0, expect pass
test_check_scheduler_lag_pass                      — lag within threshold, expect pass
test_check_scheduler_lag_warn                      — lag > 50% of threshold, expect warn
test_check_scheduler_lag_fail                      — lag > threshold, expect fail
test_check_job_timeouts_pass_when_not_implemented  — expect pass (Epic 4 stub)
test_check_notifier_alive_pass_fresh_system        — last_attempt_timestamp=0, expect pass
test_check_notifier_alive_pass                     — lag within threshold, expect pass
test_check_notifier_alive_fail                     — lag > threshold, expect fail
test_check_outbox_stuck_pass_empty_outbox          — oldest_pending_age_seconds=None, expect pass
test_check_outbox_stuck_pass_within_threshold      — age < threshold, expect pass
test_check_outbox_stuck_warn_when_stuck            — age > threshold, expect warn
test_check_disk_usage_pass_when_disabled           — disk_cap_enabled=False, expect pass with disabled message
test_check_disk_usage_pass_within_cap              — disk_cap_enabled=True, total_mb < cap, expect pass
test_check_disk_usage_warn_exceeds_cap             — disk_cap_enabled=True, total_mb > cap, expect warn
test_run_all_health_checks_returns_six_results     — returns list of 6 HealthCheckResult
test_run_all_health_checks_all_pass_fresh_system   — fresh system → all pass (no lag, empty outbox, etc.)
test_health_check_names_are_correct                — verify names: sqlite_writable, scheduler_lag, job_timeouts, notifier_alive, outbox_stuck, disk_usage
test_health_check_status_values_valid              — all statuses are "pass" | "fail" | "warn"
test_health_check_exception_in_one_does_not_affect_others — one check fails internally, others still run
test_collect_snapshot_health_not_empty             — integration: collect_snapshot() returns snapshot with non-empty health list (uses DB fixture)
```

**Testing patterns from Story 3.1** (apply same conventions):
- Use `pytest.mark.asyncio` for async tests
- Use `unittest.mock.AsyncMock` and `unittest.mock.patch` for mocking async functions
- Mock `get_config_manager()` to avoid needing full config initialization
- Use the existing `db_with_tables` fixture for DB-dependent tests (see `tests/unit/test_snapshot_collector.py` for reference)
- Health check tests that don't need DB can use simple `SchedulerState`, `NotifierState`, `ResourceUsage` constructor calls

### Project Structure Notes

**Current observability module state after Story 3.1:**
```
src/sohnbot/
├── capabilities/
│   ├── observe.py              ✅ DONE: 7 dataclasses + module-level cache
│   └── ...
├── observability/
│   ├── __init__.py             ✅ DONE: Module init with story roadmap
│   ├── snapshot_collector.py   ✅ DONE: Background collector + collect functions
│   ├── health_checks.py        📋 CREATE IN THIS STORY
│   ├── http_server.py          DO NOT CREATE (Story 3.5)
│   └── templates/              DO NOT CREATE (Story 3.6)
```

**Alignment with unified project structure:**
- All new code in `src/sohnbot/observability/health_checks.py`
- Follow existing `src/sohnbot/observability/snapshot_collector.py` pattern for async + error handling
- Tests in `tests/unit/test_health_checks.py` (matching existing unit test naming)

### Previous Story Intelligence

**From Story 3.1 (Runtime Status Snapshot Collection — DONE):**

Key patterns established:
1. **Async DB access**: Always `db = await get_db()` then `cursor = await db.execute(...)` then `await cursor.close()`
2. **Error isolation**: Wrap each function body in `try/except Exception as exc: logger.debug(...); return fallback`
3. **Config access pattern**: `from ..config.manager import get_config_manager` inside function body (or at top of file) — wrap in try/except for test compatibility
4. **Non-blocking CPU**: `cpu_percent(interval=None)` — not needed in health checks but demonstrates asyncio.to_thread pattern
5. **Structlog usage**: `logger = structlog.get_logger(__name__)` at module level

**From Story 3.1 Code Review Fixes (MEDIUM issues — apply same thinking):**
- **MEDIUM-1 (pm2 false positive)**: Lesson — a check returning "healthy" when the underlying system is not actually managing us is a false positive. Apply same thinking: `check_notifier_alive` should return pass on `last_attempt_timestamp=0` (fresh system, not broken)
- **MEDIUM-2 (sent_at vs created_at)**: `last_attempt_timestamp` is now `COALESCE(MAX(sent_at), MAX(created_at))` — reflects actual delivery attempt timing
- **MEDIUM-3 (persist warning)**: Lesson — use rate-limited logging to avoid log spam

**Test isolation note from Story 3.1:**
- `db_with_tables` fixture calls `set_db_manager(None)` on teardown — check if `test_health_checks.py` needs the same teardown
- Pre-existing test suite issues (3 collection errors, async cleanup timeout) are unrelated to Story 3.2 — do not investigate

### Git Intelligence

**Recent commit history:**
```
02c1600 Merge pull request #4 from MirkoSon/claude/create-story-3-1-rcbeY
7c80816 fix(observability): resolve 3 MEDIUM code review findings in story 3.1
8fcfff0 Implement story 3-1: Runtime Status Snapshot Collection
182e1e9 Create story 3.1: Runtime Status Snapshot Collection
ceefb66 Epic 2 completed and reviewed
```

**Pattern to follow:** Implement → test → commit (referencing story key `3-2`)
**Branch pattern**: `claude/...` branches from PRs indicate story-per-branch workflow

### Latest Tech Information

**Python 3.13 async patterns:**
- `pytest-asyncio`: Use `@pytest.mark.asyncio` for async test functions
- `unittest.mock.AsyncMock`: For mocking async functions (replaces `MagicMock` for coroutines)
- `asyncio.to_thread()`: For blocking calls; not needed in health_checks.py (all checks are either async with aiosqlite or purely in-memory/synchronous non-blocking)

**aiosqlite patterns (current version in project):**
- `db = await get_db()` — returns the `aiosqlite.Connection` (DatabaseManager's connection)
- `cursor = await db.execute(sql)` — returns cursor
- `rows = await cursor.fetchall()` / `row = await cursor.fetchone()`
- `await cursor.close()` — always close cursors to avoid resource leaks
- TEMP tables in aiosqlite: `CREATE TEMP TABLE IF NOT EXISTS` works on the same connection — idempotent

**structlog (24.x):**
- Same pattern as `snapshot_collector.py`: `logger = structlog.get_logger(__name__)`
- Use `logger.debug(...)` for check details, `logger.warning(...)` for unexpected failures in check logic

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.2: Health Checks Implementation]
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 3: System Observability & Monitoring]
- [Source: _bmad-output/planning-artifacts/architecture.md#Observability Capability — Health Checks Module]
- [Source: _bmad-output/planning-artifacts/architecture.md#Configuration Keys — observability.*]
- [Source: src/sohnbot/capabilities/observe.py] — HealthCheckResult, StatusSnapshot, SchedulerState, NotifierState, ResourceUsage dataclasses
- [Source: src/sohnbot/observability/snapshot_collector.py] — collect_snapshot() function to update (line 123-132), async DB patterns
- [Source: src/sohnbot/observability/__init__.py] — Story 3.2 referenced in module roadmap
- [Source: src/sohnbot/config/registry.py] — ConfigKey pattern; existing observability keys (lines 218-255)
- [Source: config/default.toml#observability] — existing section (lines 76-83); add health check thresholds
- [Source: src/sohnbot/persistence/db.py] — get_db() async pattern
- [Source: src/sohnbot/config/manager.py] — get_config_manager() access
- [Source: _bmad-output/implementation-artifacts/3-1-runtime-status-snapshot-collection.md] — Story 3.1 dev notes, test patterns, review findings

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
