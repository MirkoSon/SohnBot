# Story 7.1: Database & Persistence Hardening

Status: in-progress

## Story

As a developer,
I want all database access to be transactionally safe, schema-correct, and persistent,
So that SohnBot cannot corrupt data under concurrency, fail on valid job types, or lose configuration on restart.

## Acceptance Criteria

**Given** a fresh database with no prior jobs
**When** `initialize_operation_logs_cleanup_job()` runs at startup
**Then** the `cleanup_operation_logs` job is inserted without `IntegrityError`
**And** the `action` CHECK constraint permits `'agent_query'`, `'profile_execute'`, `'heartbeat'`, `'cleanup_operation_logs'`

**Given** two concurrent coroutines (scheduler tick + Telegram handler) both writing to SQLite
**When** both attempt INSERT/UPDATE simultaneously
**Then** writes are serialized via `asyncio.Lock` on the DatabaseManager
**And** each write uses an explicit `BEGIN IMMEDIATE` transaction
**And** no `OperationalError: database is locked` is raised under normal load

**Given** `capabilities/web.py` needs to read/write search cache
**When** it performs any database operation
**Then** it uses `await get_db()` from `DatabaseManager`, not ad-hoc `aiosqlite.connect()`
**And** all WAL, busy_timeout, and foreign_keys pragmas are applied consistently

**Given** a user changes a dynamic config value at runtime
**When** the process restarts
**Then** the changed value persists in the SQLite `config` table
**And** `load_dynamic_config_from_db()` loads persisted values at startup
**And** persisted values override TOML defaults

**Given** the project is installed
**When** a user runs `python -m sohnbot`
**Then** the `__main__.py` entry point invokes `main.run_main()`

## Tasks / Subtasks

- [ ] Task 1: Create migration 0008 to widen jobs CHECK constraint (AC: 1)
  - [ ] Create `src/sohnbot/persistence/migrations/0008_widen_jobs_action_check.sql`
  - [ ] SQLite requires table recreation for CHECK changes — use `CREATE TABLE jobs_new ... ; INSERT INTO jobs_new SELECT * FROM jobs; DROP TABLE jobs; ALTER TABLE jobs_new RENAME TO jobs;`
  - [ ] Include `'cleanup_operation_logs'` in the CHECK set
  - [ ] Recreate index `idx_jobs_enabled_name` after rename

- [ ] Task 2: Add asyncio.Lock to DatabaseManager (AC: 2)
  - [ ] Add `self._write_lock = asyncio.Lock()` to `DatabaseManager.__init__`
  - [ ] Create `async def execute_write(self, sql, params=None)` method that acquires lock, executes `BEGIN IMMEDIATE`, runs SQL, commits
  - [ ] Create `async def execute_write_many(self, operations: list)` for multi-statement writes in one transaction
  - [ ] Existing `get_connection()` remains unchanged (reads don't need locking in WAL mode)

- [ ] Task 3: Route web.py through DatabaseManager (AC: 3)
  - [ ] Replace `aiosqlite.connect(db_path)` at `web.py:339` (`_get_cached_search`) with `await get_db()`
  - [ ] Replace `aiosqlite.connect(db_path)` at `web.py:405` (`_store_search_cache`) with `await get_db()`
  - [ ] Replace `aiosqlite.connect(db_path)` at `web.py:429` (`cleanup_expired_cache`) with `await get_db()`
  - [ ] Remove `db_path` parameter from these functions; use global `get_db()` instead
  - [ ] Update callers: `brave_search()` and `_track_search_volume_and_alert()` no longer pass db_path to cache functions
  - [ ] Update `search_volume.py` if it also uses ad-hoc connections (verify)

- [ ] Task 4: Implement dynamic config DB persistence (AC: 4)
  - [ ] Implement `ConfigManager._persist_to_database(key, value)` — INSERT OR REPLACE into `config` table with `updated_at` timestamp and `tier='dynamic'`
  - [ ] Implement `ConfigManager.load_dynamic_config_from_db(db_path)` — SELECT all rows from `config` WHERE `tier='dynamic'`; overlay onto in-memory config; validate each value via registry
  - [ ] Implement `ConfigManager.reset_dynamic_config(key)` — DELETE from `config` WHERE `key=?`; restore in-memory to registry default
  - [ ] Call `load_dynamic_config_from_db()` during `main.py` initialization after database is ready
  - [ ] Wire `_persist_to_database()` into `update_dynamic_config()` replacing the TODO comment at line 268-272

- [ ] Task 5: Create `__main__.py` entry point (AC: 5)
  - [ ] Create `src/sohnbot/__main__.py` with: `import asyncio; from sohnbot.main import run_main; asyncio.run(run_main())`

- [ ] Task 6: Testing (AC: all)
  - [ ] Test: migration 0008 applies cleanly on fresh DB and on DB with existing jobs
  - [ ] Test: INSERT with action='cleanup_operation_logs' succeeds
  - [ ] Test: concurrent write simulation using `asyncio.gather` — no lock errors
  - [ ] Test: web.py cache functions use shared connection (mock `get_db`)
  - [ ] Test: config persist → restart → load round-trip preserves values
  - [ ] Test: `python -m sohnbot` resolves to `__main__.py`

## Dev Notes

### Epic 7 Context

**Epic Goal:** Address all security and spec-compliance findings from the adversarial audit.

**This story:** Foundation — fixes 3 CRITICALs (A-01, F-02, F-04) and 1 HIGH (A-10), plus `__main__.py` from A-06.

**Next:** Story 7.2 (Subprocess Safety), Story 7.3 (Scope TOCTOU) — both independent.

### Architecture and Safety Guardrails

1. **Migration Safety:**
   - SQLite does not support `ALTER TABLE ... ALTER CHECK`. Table must be recreated.
   - Use `INSERT INTO jobs_new SELECT * FROM jobs` to preserve existing data.
   - Wrap entire migration in a transaction.

2. **Connection Locking Pattern:**
   - WAL mode allows concurrent reads. Only writes need serialization.
   - `BEGIN IMMEDIATE` acquires a RESERVED lock immediately, preventing deadlocks.
   - Lock is per-DatabaseManager instance (single connection, single lock).
   - Pattern: `async with self._write_lock: await conn.execute("BEGIN IMMEDIATE"); ...; await conn.commit()`

3. **Config Persistence:**
   - The `config` table already exists (migration 0001).
   - Schema: `key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL, updated_by TEXT, tier TEXT`.
   - Store values as JSON-encoded strings (handles int, float, str, bool).
   - Load at startup AFTER migrations run, BEFORE any capability initialization.

### File-Level Guidance

**Primary files to create:**
- `src/sohnbot/persistence/migrations/0008_widen_jobs_action_check.sql`
- `src/sohnbot/__main__.py`

**Primary files to modify:**
- `src/sohnbot/persistence/db.py` — add `_write_lock`, `execute_write()`, `execute_write_many()`
- `src/sohnbot/capabilities/web.py` — replace 3 ad-hoc `aiosqlite.connect()` calls with `get_db()`
- `src/sohnbot/config/manager.py` — implement `_persist_to_database()`, `load_dynamic_config_from_db()`, `reset_dynamic_config()`
- `src/sohnbot/main.py` — call `load_dynamic_config_from_db()` during init

**Files to reference (do not redesign):**
- `src/sohnbot/persistence/audit.py` — pattern for using `get_db()` + explicit commits
- `src/sohnbot/persistence/migrations/0005_scheduler.sql` — the original jobs table schema
- `src/sohnbot/config/registry.py` — registry keys and validation functions

**Files to create for testing:**
- `tests/unit/test_db_write_lock.py` (new)
- `tests/unit/test_config_persistence.py` (new)

**Files to update for testing:**
- `tests/unit/test_web.py` — update cache function tests to mock `get_db` instead of `aiosqlite.connect`

### Migration SQL

```sql
-- 0008_widen_jobs_action_check.sql
-- Widen jobs.action CHECK to include 'cleanup_operation_logs'.
-- SQLite requires table recreation for CHECK constraint changes.

CREATE TABLE jobs_new (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    cron_expr TEXT NOT NULL,
    timezone TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN (
        'agent_query', 'profile_execute', 'heartbeat', 'cleanup_operation_logs'
    )),
    action_params TEXT,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    created_at INTEGER NOT NULL,
    last_completed_slot INTEGER
) STRICT;

INSERT INTO jobs_new SELECT * FROM jobs;
DROP TABLE jobs;
ALTER TABLE jobs_new RENAME TO jobs;
CREATE INDEX IF NOT EXISTS idx_jobs_enabled_name ON jobs(enabled, name);
```

### References

- [Source: _bmad-output/implementation-artifacts/security-audit-findings-v1.md#F-02]
- [Source: _bmad-output/implementation-artifacts/security-audit-findings-v1.md#F-04]
- [Source: _bmad-output/implementation-artifacts/prd-architecture-adherence-audit-v1.md#A-01]
- [Source: _bmad-output/implementation-artifacts/prd-architecture-adherence-audit-v1.md#A-10]
