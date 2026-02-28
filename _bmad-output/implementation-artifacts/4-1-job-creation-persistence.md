# Story 4.1: Job Creation & Persistence

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to create scheduled jobs via natural language or explicit commands,
So that recurring tasks run automatically.

## Acceptance Criteria

**Given** I want to schedule a recurring task
**When** I request job creation (e.g., "Run morning summary daily at 9am")
**Then** job is created with: name, cron expression, timezone, action type, enabled status
**And** job is persisted to SQLite (survives system restarts)
**And** job schema includes: id, name, cron_expr, timezone, action, enabled, created_at, last_completed_slot
**And** jobs are stored in local timezone (converted to UTC internally)
**And** confirmation is sent via Telegram with job details

## Tasks / Subtasks

- [x] Task 1: Create jobs table migration (AC: job schema, SQLite persistence)
  - [x] Create `src/sohnbot/persistence/migrations/0005_scheduler.sql` (next sequential migration)
  - [x] Define jobs table with STRICT mode and CHECK constraints:
    - `id` TEXT PRIMARY KEY (UUID v4)
    - `name` TEXT NOT NULL UNIQUE (human-readable job name, e.g., "morning-summary")
    - `cron_expr` TEXT NOT NULL (cron expression, e.g., "0 9 * * *")
    - `timezone` TEXT NOT NULL (IANA timezone, e.g., "America/New_York")
    - `action` TEXT NOT NULL (action type: "agent_query", "profile_execute", "heartbeat")
    - `action_params` TEXT (JSON-encoded parameters for action, nullable)
    - `enabled` INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)) (boolean: 1=enabled, 0=disabled)
    - `created_at` INTEGER NOT NULL (Unix epoch timestamp)
    - `last_completed_slot` INTEGER (Unix epoch of last successfully completed slot, nullable, for idempotency)
  - [x] Add index: `idx_jobs_enabled_name` ON jobs(enabled, name)
  - [x] Document migration purpose and schema rationale in SQL comments
  - [x] Follow existing migration pattern (STRICT mode, CHECK constraints, indexes)

- [x] Task 2: Create job manager module (AC: create_job, list_jobs, delete_job)
  - [x] Create `src/sohnbot/capabilities/scheduler/job_manager.py`
  - [x] Implement `async def create_job(name: str, cron_expr: str, timezone: str, action: str, action_params: dict | None = None, enabled: bool = True) -> dict`:
    - Generate UUID v4 for job id
    - Validate cron expression using `croniter` library (validate syntax, raise ValueError if invalid)
    - Validate timezone using `zoneinfo.ZoneInfo(timezone)` (raise ValueError if invalid IANA timezone)
    - Validate action is in allowed set: ["agent_query", "profile_execute", "heartbeat"]
    - Serialize action_params to JSON if provided
    - Insert job into database with `created_at = int(time.time())`
    - Return job dict: {id, name, cron_expr, timezone, action, enabled, created_at}
  - [x] Implement `async def list_jobs(enabled_only: bool = False) -> list[dict]`:
    - Query jobs table (filter by enabled=1 if enabled_only=True)
    - Return list of job dicts with all fields
    - Order by created_at DESC
  - [x] Implement `async def delete_job(job_id: str) -> bool`:
    - Delete job from database by id
    - Return True if deleted, False if not found
  - [x] Add helper `async def get_job_by_name(name: str) -> dict | None` (used by other commands)
  - [x] Handle database exceptions gracefully (log error, return structured error)

- [x] Task 3: Add croniter dependency (AC: cron validation)
  - [x] Add `croniter = "^3.0.0"` to `[tool.poetry.dependencies]` in `pyproject.toml`
  - [x] Run `.venv/bin/pip install croniter` (or `poetry add croniter` if poetry available)
  - [x] Verify import works: `from croniter import croniter, CroniterBadCronError`

- [x] Task 4: Create MCP tools for job creation and listing (AC: MCP tools)
  - [x] Update `src/sohnbot/runtime/mcp_tools.py` to add scheduler tools:
    - `@tool("sched__create", "Create scheduled job", {"name": str, "cron_expr": str, "timezone": str, "action": str, "action_params": dict | None, "enabled": bool})`
    - `@tool("sched__list", "List scheduled jobs", {"enabled_only": bool})`
  - [x] Tool handlers call broker:
    - `await broker.route_operation(capability="scheduler", action="create", params=...)`
    - `await broker.route_operation(capability="scheduler", action="list", params=...)`
  - [x] Format tool responses for agent consumption (concise text with job details)
  - [x] Handle errors gracefully (return error message if operation denied or fails)

- [x] Task 5: Wire scheduler capability into broker (AC: broker routing)
  - [x] Update `src/sohnbot/broker/operation_classifier.py` to classify scheduler operations:
    - `scheduler.create` → Tier 1 (state-changing, creates DB record)
    - `scheduler.list` → Tier 0 (read-only query)
    - `scheduler.delete` → Tier 1 (state-changing, deletes DB record)
  - [x] Update `src/sohnbot/broker/router.py` to route scheduler operations:
    - Import job_manager functions
    - Route `scheduler.create` → `job_manager.create_job(...)`
    - Route `scheduler.list` → `job_manager.list_jobs(...)`
    - Route `scheduler.delete` → `job_manager.delete_job(...)`
  - [x] Ensure broker logs all scheduler operations to execution_log

- [x] Task 6: Add Telegram command for job creation (AC: Telegram confirmation)
  - [x] Update `src/sohnbot/gateway/commands.py` to add `handle_schedule_command(chat_id: str, command_text: str) -> str`
  - [x] Parse `/schedule create <name> <cron> <timezone> <action>` format
  - [x] Call broker to create job via agent query (let agent handle parameters)
  - [x] Format confirmation message with job details (name, cron, timezone, action, next run time)
  - [x] Return usage guidance for invalid arguments
  - [x] Update `telegram_client.py` to register `/schedule` command handler

- [x] Task 7: Testing (AC: all)
  - [x] Create `tests/unit/test_job_manager.py`:
    - [x] `test_create_job_success` - Valid job creation returns job dict
    - [x] `test_create_job_invalid_cron` - Raises ValueError for invalid cron
    - [x] `test_create_job_invalid_timezone` - Raises ValueError for invalid timezone
    - [x] `test_create_job_invalid_action` - Raises ValueError for invalid action
    - [x] `test_list_jobs_all` - Lists all jobs
    - [x] `test_list_jobs_enabled_only` - Lists only enabled jobs
    - [x] `test_delete_job_success` - Deletes existing job, returns True
    - [x] `test_delete_job_not_found` - Returns False for non-existent job
  - [x] Create `tests/integration/test_scheduler_integration.py`:
    - [x] `test_create_job_via_broker` - End-to-end job creation via broker
    - [x] `test_list_jobs_via_broker` - End-to-end job listing via broker
    - [x] `test_delete_job_via_broker` - End-to-end job deletion via broker
    - [x] `test_job_persistence_after_restart` - Create job, restart DB connection, verify job still exists
  - [x] Update `tests/unit/test_mcp_tools.py`:
    - [x] Verify `sched__create` and `sched__list` tools are registered
    - [x] Verify tool parameter schemas match expectations
  - [x] Run migration on test database and verify schema

## Dev Notes

### Epic 4 Context

**Epic Goal:** You can schedule recurring tasks (morning repo summaries, weekly notes digests, daily heartbeats) that run autonomously.

**Epic 4 Progress (at Story 4.1):**
- This story: Story 4.1 Job Creation & Persistence
- Next: Story 4.2 Idempotent Job Execution with Catch-Up
- Then: Story 4.3 Timezone-Aware Scheduling with DST Handling
- Then: Story 4.4 Job Timeout Enforcement
- Then: Story 4.5 Job Management Commands
- Then: Story 4.6 Daily Heartbeat System

This story establishes the foundation for the scheduler subsystem by creating the jobs table and basic CRUD operations.

### Previous Epic Intelligence (Epic 3)

**Epic 3 Patterns to Follow:**
- Story 3.1 created snapshot collection infrastructure with background asyncio tasks
- Story 3.2 added health checks as part of snapshot collection
- All observability data is read-only from in-memory cache
- Background tasks run in `asyncio.TaskGroup` with graceful shutdown
- Configuration uses `observability.*` config keys in `config/default.toml`

**Key Learnings:**
- Background tasks should be non-blocking and independent failure domains
- Database queries should use `await get_db()` pattern from `persistence/db.py`
- Structured logging with operation context (operation_id, chat_id)
- MCP tools follow naming pattern: `{capability}__{action}`

### Architecture and Safety Guardrails

1. **Job Persistence:**
   - Jobs table uses STRICT mode for type safety
   - CHECK constraints enforce valid values (enabled: 0 or 1)
   - UNIQUE constraint on job name prevents duplicates
   - last_completed_slot field is critical for idempotency (Story 4.2)

2. **Cron Validation:**
   - Use `croniter` library to validate cron expression syntax
   - Raise `ValueError` with clear message if invalid
   - Example valid: "0 9 * * *" (daily at 9am)
   - Example invalid: "invalid cron"

3. **Timezone Handling:**
   - Use Python's `zoneinfo` library (standard library in Python 3.9+)
   - Validate timezone with `zoneinfo.ZoneInfo(timezone)` (raises `ZoneInfoNotFoundError` if invalid)
   - Store timezone name (IANA format: "America/New_York", "Europe/London", "UTC")
   - UTC conversion happens in Story 4.3 (not this story)

4. **Action Types:**
   - `"agent_query"` - Run an agent query with prompt from action_params
   - `"profile_execute"` - Execute a command profile (lint, build, test)
   - `"heartbeat"` - Send heartbeat notification (Story 4.6)
   - Validate action is in this allowed set

5. **Broker Integration:**
   - Tier 0: `scheduler.list` (read-only, no snapshot)
   - Tier 1: `scheduler.create`, `scheduler.delete` (state-changing, no snapshot needed - DB only)
   - All operations logged to execution_log

### File-Level Guidance

**Primary files to create:**
- `src/sohnbot/persistence/migrations/0005_scheduler.sql` (new)
- `src/sohnbot/capabilities/scheduler/job_manager.py` (new)

**Primary files to modify:**
- `pyproject.toml` (add croniter dependency)
- `src/sohnbot/runtime/mcp_tools.py` (add sched__create, sched__list tools)
- `src/sohnbot/broker/operation_classifier.py` (add scheduler tier classification)
- `src/sohnbot/broker/router.py` (add scheduler routing)
- `src/sohnbot/gateway/commands.py` (add handle_schedule_command)
- `src/sohnbot/gateway/telegram_client.py` (register /schedule command)

**Files to reference (do not redesign):**
- `src/sohnbot/persistence/migrations/0001_init.sql` (migration pattern reference)
- `src/sohnbot/persistence/db.py` (database connection pattern)
- `src/sohnbot/broker/router.py` (routing pattern for other capabilities)
- `src/sohnbot/runtime/mcp_tools.py` (MCP tool registration pattern)

**Files to create for testing:**
- `tests/unit/test_job_manager.py` (new)
- `tests/integration/test_scheduler_integration.py` (new)

**Files to update for testing:**
- `tests/unit/test_mcp_tools.py` (verify new tools registered)

### Project Structure Notes

**Scheduler Directory Structure:**
- Architecture document shows both `capabilities/sched.py` and `capabilities/scheduler/` patterns
- Current project has `src/sohnbot/capabilities/scheduler/__init__.py` (empty placeholder)
- **Decision:** Use directory structure `capabilities/scheduler/` with:
  - `job_manager.py` (this story - CRUD operations)
  - `executor.py` (Story 4.2 - background execution loop)
  - `timezone_handler.py` (Story 4.3 - DST handling)

**Migration Numbering:**
- Existing migrations: 0001_init.sql, 0002_notifications.sql, 0003_execution_log_status_extension.sql, 0004_postponed_operation_state.sql
- **New migration:** 0005_scheduler.sql (not 0003 as stated in epics - that's outdated)

### Testing Standards

- Unit tests: Mock database, test job_manager functions in isolation
- Integration tests: Use real test database, test end-to-end via broker
- Test persistence: Create job, close DB connection, reopen, verify job exists
- Test validation: Invalid cron, invalid timezone, invalid action
- Preserve existing async testing patterns (`pytest.mark.asyncio`, lightweight fixtures)
- Follow existing test structure in `tests/unit/test_persistence.py` for database tests

### Database Schema Pattern

Follow existing migration patterns:

```sql
-- Migration header with description
-- Table creation with STRICT mode
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    cron_expr TEXT NOT NULL,
    timezone TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('agent_query', 'profile_execute', 'heartbeat')),
    action_params TEXT,  -- JSON-encoded dict
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    created_at INTEGER NOT NULL,
    last_completed_slot INTEGER
) STRICT;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_jobs_enabled_name ON jobs(enabled, name);
```

### MCP Tool Pattern

Follow existing MCP tool registration pattern:

```python
@tool("sched__create", "Create scheduled job", {
    "name": str,
    "cron_expr": str,
    "timezone": str,
    "action": str,
    "action_params": dict | None,
    "enabled": bool
})
async def sched_create(name: str, cron_expr: str, timezone: str, action: str, action_params: dict | None = None, enabled: bool = True):
    result = await broker.route_operation(
        capability="scheduler",
        action="create",
        params={
            "name": name,
            "cron_expr": cron_expr,
            "timezone": timezone,
            "action": action,
            "action_params": action_params,
            "enabled": enabled,
        },
        chat_id=get_chat_id_from_context(),
    )

    if not result.allowed:
        error_msg = (result.error or {}).get("message", "Operation denied")
        return _as_mcp_text(f"❌ Operation denied: {error_msg}")

    job = result.result or {}
    return _as_mcp_text(f"✅ Job created: {job['name']} ({job['cron_expr']}) in {job['timezone']}")
```

### Cron Expression Examples

Common cron patterns to support:
- `"0 9 * * *"` - Daily at 9:00 AM
- `"0 */6 * * *"` - Every 6 hours
- `"0 0 * * 0"` - Weekly on Sunday at midnight
- `"0 0 1 * *"` - Monthly on the 1st at midnight
- `"*/30 * * * *"` - Every 30 minutes

Validation using croniter:
```python
from croniter import croniter, CroniterBadCronError

try:
    croniter(cron_expr)  # Validates syntax
except (CroniterBadCronError, ValueError) as e:
    raise ValueError(f"Invalid cron expression: {e}")
```

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 4.1: Job Creation & Persistence]
- [Source: _bmad-output/planning-artifacts/architecture.md#Scheduler Architecture]
- [Source: src/sohnbot/persistence/migrations/0001_init.sql]
- [Source: src/sohnbot/broker/router.py]
- [Source: src/sohnbot/runtime/mcp_tools.py]
- [Source: src/sohnbot/capabilities/observe.py (observability patterns)]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex (CLI)

### Debug Log References

- Installed dependency: `.venv/bin/pip install croniter`
- Import verification: `.venv/bin/python -c "from croniter import croniter, CroniterBadCronError; print('ok')"`
- Validation tests:
  - `.venv/bin/pytest tests/unit/test_job_manager.py tests/unit/test_mcp_tools.py tests/unit/test_broker.py tests/unit/test_commands.py tests/unit/test_telegram_client.py tests/integration/test_scheduler_integration.py`
  - `.venv/bin/pytest tests/unit/test_agent_session.py`

### Completion Notes List

- Added migration `0005_scheduler.sql` with STRICT `jobs` table, CHECK constraints, and index `idx_jobs_enabled_name`.
- Implemented scheduler persistence module `job_manager.py` with async `create_job`, `list_jobs`, `delete_job`, and `get_job_by_name`.
- Added cron validation (`croniter`), timezone validation (`zoneinfo`), action allowlist validation, JSON action_params serialization, and structured DB error logging.
- Added broker routing and request validation for `scheduler.create`, `scheduler.list`, `scheduler.delete`.
- Updated tier classifier: `scheduler.list` Tier 0; `scheduler.create/delete` Tier 1.
- Prevented scheduler Tier 1 operations from attempting git snapshot creation.
- Added MCP tools `sched__create` and `sched__list` with broker integration and concise response formatting.
- Added Telegram `/schedule` command handling and command registration with usage guidance and next-run calculation.
- Added scheduler tools to runtime allowed tool list.
- Added unit/integration coverage for scheduler job manager, broker flow, MCP tool registration/schema, and Telegram/command handlers.

### File List

- `_bmad-output/implementation-artifacts/4-1-job-creation-persistence.md`
- `pyproject.toml`
- `src/sohnbot/persistence/migrations/0005_scheduler.sql`
- `src/sohnbot/capabilities/scheduler/__init__.py`
- `src/sohnbot/capabilities/scheduler/job_manager.py`
- `src/sohnbot/broker/operation_classifier.py`
- `src/sohnbot/broker/router.py`
- `src/sohnbot/runtime/mcp_tools.py`
- `src/sohnbot/runtime/agent_session.py`
- `src/sohnbot/gateway/commands.py`
- `src/sohnbot/gateway/telegram_client.py`
- `tests/unit/test_job_manager.py`
- `tests/integration/test_scheduler_integration.py`
- `tests/unit/test_mcp_tools.py`
- `tests/unit/test_broker.py`
- `tests/unit/test_commands.py`
- `tests/unit/test_telegram_client.py`

### Change Log

- 2026-02-28: Implemented Story 4.1 job creation + persistence foundation, broker/MCP/Telegram wiring, dependency install, and automated test coverage.
