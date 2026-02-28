# Story 4.3: Timezone-Aware Scheduling with DST Handling

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want jobs scheduled in my local timezone with correct DST handling,
So that jobs run at the expected local time.

## Acceptance Criteria

**Given** jobs are created with local timezone
**When** the job is stored
**Then** job time is converted to UTC internally (storage)
**And** user-facing times are displayed in local timezone (queries)
**And** DST transitions are handled correctly (non-existent hours run at next valid time)
**And** jobs during spring-forward (2am → 3am) run at 3am
**And** jobs during fall-back (2am → 1am) run once at first occurrence
**And** validates: FR-029

## Tasks / Subtasks

- [x] Task 1: Create timezone handler module (AC: DST handling, timezone conversion)
  - [x] Create `src/sohnbot/capabilities/scheduler/timezone_handler.py`
  - [x] Implement `def format_local_time(utc_timestamp: int, timezone_name: str) -> str`:
    - Convert Unix epoch to local timezone datetime
    - Format as human-readable string: "2024-03-10 09:00:00 America/New_York"
    - Handle invalid timezone gracefully (fall back to UTC)
  - [x] Implement `def get_next_run_time(cron_expr: str, timezone_name: str, last_completed_slot: int | None = None) -> dict`:
    - Calculate next scheduled run time for a job
    - Return dict: {"utc_timestamp": int, "local_datetime": str, "timezone": str}
    - Use croniter with timezone-aware datetime
    - Account for last_completed_slot to determine next future slot
  - [x] Implement `def handle_dst_transition(job_tz_dt: datetime, timezone_name: str) -> datetime`:
    - Detect if datetime falls in DST transition
    - Spring-forward (non-existent hour like 2:30am → 3:00am): Move to next valid time (3:00am)
    - Fall-back (ambiguous hour like 1:30am appears twice): Use first occurrence
    - Return adjusted datetime with proper timezone info

- [x] Task 2: Enhance executor slot calculation for DST edge cases (AC: DST transitions handled correctly)
  - [x] Update `_calculate_current_slot()` in `executor.py`:
    - Add DST transition detection using timezone_handler
    - For spring-forward: If calculated slot is in non-existent hour, move to next valid time
    - For fall-back: If calculated slot is ambiguous, use first occurrence (fold=0)
    - Log DST transitions for debugging: "DST transition detected: 2am → 3am spring-forward"
  - [x] Use Python zoneinfo's `fold` parameter for ambiguous times:
    - `datetime.replace(fold=0)` → First occurrence during fall-back
    - `datetime.replace(fold=1)` → Second occurrence during fall-back
  - [x] Ensure croniter uses timezone-aware datetime when calculating slots

- [x] Task 3: Update job listing to display local times (AC: user-facing times in local timezone)
  - [x] Update `list_jobs()` in `job_manager.py`:
    - Add computed field `next_run_local` to job dict
    - Call `timezone_handler.get_next_run_time(...)` for each job
    - Include in returned dict: `job["next_run_local"] = {"utc": ..., "local": ..., "timezone": ...}`
  - [x] Update MCP tool `sched__list`:
    - Format response to include next run time in local timezone
    - Example: "Job: morning-summary | Next run: 2024-03-10 09:00:00 America/New_York"
  - [x] Update Telegram `/schedule list` command:
    - Display next run time in local timezone for each job
    - Show both local time and timezone name

- [x] Task 4: Add DST transition logging and monitoring (AC: DST transitions logged)
  - [x] Add structured logging in `timezone_handler.py`:
    - Log spring-forward transitions: "dst_spring_forward" with original and adjusted times
    - Log fall-back transitions: "dst_fall_back" with fold information
  - [x] Add DST transition counter to observability metrics:
    - Track number of DST transitions handled per day
    - Include in health checks or status endpoint
  - [x] Document DST handling behavior in code comments with examples

- [x] Task 5: Handle timezone edge cases (AC: robust timezone handling)
  - [x] Add validation in `create_job()`:
    - Verify timezone exists using `zoneinfo.available_timezones()` (optional, zoneinfo.ZoneInfo already validates)
    - Provide clear error message for invalid timezones
  - [x] Handle timezone database updates:
    - Document that system should use latest tzdata (timezone database)
    - Add comment about `zoneinfo` using system tzdata or `tzdata` package
  - [x] Add UTC fallback for timezone errors:
    - If timezone cannot be loaded, log error and fall back to UTC
    - Never crash on timezone errors (graceful degradation)

- [x] Task 6: Testing (AC: all DST scenarios)
  - [x] Create `tests/unit/test_timezone_handler.py`:
    - [x] `test_format_local_time_converts_utc_to_local` - UTC timestamp → local datetime string
    - [x] `test_get_next_run_time_calculates_next_slot` - Next run time for job
    - [x] `test_handle_dst_spring_forward` - Non-existent 2:30am → 3:00am
    - [x] `test_handle_dst_fall_back` - Ambiguous 1:30am uses first occurrence (fold=0)
    - [x] `test_dst_transition_logging` - DST events logged correctly
    - [x] `test_invalid_timezone_fallback` - Invalid timezone falls back to UTC
  - [x] Update `tests/unit/test_executor.py`:
    - [x] `test_calculate_current_slot_with_dst_spring_forward` - Slot calculation during spring-forward
    - [x] `test_calculate_current_slot_with_dst_fall_back` - Slot calculation during fall-back
    - [x] `test_job_execution_during_dst_transition` - Jobs execute correctly during DST
  - [x] Update `tests/integration/test_scheduler_integration.py`:
    - [x] `test_scheduler_handles_spring_forward_correctly` - End-to-end spring-forward test
    - [x] `test_scheduler_handles_fall_back_correctly` - End-to-end fall-back test
  - [x] Create DST test fixtures:
    - [x] Mock datetime for DST transition dates (March 10, November 3 for US)
    - [x] Create jobs scheduled during DST transition hours (2:00am)

## Dev Notes

### Epic 4 Context

**Epic Goal:** You can schedule recurring tasks (morning repo summaries, weekly notes digests, daily heartbeats) that run autonomously.

**Epic 4 Progress (at Story 4.3):**
- Done: Story 4.1 Job Creation & Persistence
- Done: Story 4.2 Idempotent Job Execution with Catch-Up
- This story: Story 4.3 Timezone-Aware Scheduling with DST Handling
- Next: Story 4.4 Job Timeout Enforcement
- Then: Story 4.5 Job Management Commands
- Then: Story 4.6 Daily Heartbeat System

This story enhances Story 4.2 executor with robust DST handling and timezone conversion.

### Previous Story Intelligence (4.2)

**Story 4.2 Implementation Details:**
- Created `executor.py` with tick loop and idempotent execution
- Slot calculation already uses timezone conversion: `job_tz_now = current.astimezone(ZoneInfo(job_tz_name))`
- `_calculate_current_slot()` function exists at line 42-54
- croniter used for slot calculation: `croniter(cron_expr, now).get_prev(datetime)`

**Existing Timezone Handling (Partial):**
```python
# From executor.py lines 82-84
job_tz_name = str(job.get("timezone") or "UTC")
job_tz_now = current.astimezone(ZoneInfo(job_tz_name))
current_slot = _calculate_current_slot(str(job["cron_expr"]), job_tz_now)
```

**Key Gaps to Address:**
- No explicit DST transition handling (spring-forward, fall-back)
- No user-facing local time formatting (next run times shown in UTC)
- No DST transition logging or monitoring

### Architecture and Safety Guardrails

1. **DST Transition Handling:**
   - **Spring-Forward (Non-Existent Hours):**
     - In US, March: 2:00am → 3:00am (2:00am-2:59am don't exist)
     - If job scheduled at 2:30am, run at 3:00am (next valid time)
     - Use zoneinfo to detect non-existent times
   - **Fall-Back (Ambiguous Hours):**
     - In US, November: 2:00am → 1:00am (1:00am-1:59am happen twice)
     - If job scheduled at 1:30am, run at FIRST occurrence (fold=0)
     - Use `datetime.replace(fold=0)` to specify first occurrence

2. **Timezone Storage vs Display:**
   - **Storage (Database):** Unix epoch timestamps (UTC) + timezone name string
   - **Display (User-Facing):** Local timezone datetime strings
   - **Calculation:** Convert to local timezone, calculate slot, store UTC epoch

3. **croniter with Timezone Awareness:**
   - croniter works with timezone-aware datetime objects
   - Pass timezone-aware datetime: `datetime.now(ZoneInfo("America/New_York"))`
   - croniter respects timezone when calculating next/prev occurrences

4. **FR-029 Compliance:**
   - FR-029: Timezone-aware scheduling with DST handling
   - Jobs run at expected local time across DST transitions
   - No missed or duplicate executions during DST changes

### File-Level Guidance

**Primary files to create:**
- `src/sohnbot/capabilities/scheduler/timezone_handler.py` (new - DST logic)

**Primary files to modify:**
- `src/sohnbot/capabilities/scheduler/executor.py` (enhance _calculate_current_slot for DST)
- `src/sohnbot/capabilities/scheduler/job_manager.py` (add next_run_local to list_jobs)
- `src/sohnbot/runtime/mcp_tools.py` (format sched__list with local times)
- `src/sohnbot/gateway/commands.py` (display local times in /schedule list)

**Files to reference (do not redesign):**
- `src/sohnbot/capabilities/scheduler/executor.py` (existing timezone conversion at lines 82-84)
- `src/sohnbot/capabilities/scheduler/job_manager.py` (existing create_job timezone validation)

**Files to create for testing:**
- `tests/unit/test_timezone_handler.py` (new)

**Files to update for testing:**
- `tests/unit/test_executor.py` (add DST tests)
- `tests/integration/test_scheduler_integration.py` (add DST end-to-end tests)

### Project Structure Notes

**Scheduler Directory Structure:**
- `capabilities/scheduler/job_manager.py` (Story 4.1 - CRUD operations)
- `capabilities/scheduler/executor.py` (Story 4.2 - execution loop)
- `capabilities/scheduler/timezone_handler.py` (This story - DST handling)

**Timezone Data Source:**
- Python 3.9+ includes `zoneinfo` in standard library
- Uses system tzdata (timezone database) on Linux/macOS
- On Windows, may need `tzdata` package (already available via system or pip)

### Testing Standards

- Unit tests: Mock datetime to DST transition dates
- Test spring-forward: March 10, 2024 at 2:00am → 3:00am (US)
- Test fall-back: November 3, 2024 at 2:00am → 1:00am (US)
- Use `freezegun` or similar library to mock specific datetimes
- Test multiple timezones: America/New_York, Europe/London, Asia/Tokyo, UTC

### DST Transition Examples

**Spring-Forward Example (US):**
```
Date: March 10, 2024 (Second Sunday in March)
Before: 1:59:59 AM EST
After:  3:00:00 AM EDT (2:00:00-2:59:59 don't exist)

Job scheduled at "0 2 * * *" (2:00am daily):
- On March 10: Should run at 3:00am EDT (next valid time)
- croniter may return 2:00am, but zoneinfo will adjust to 3:00am
```

**Fall-Back Example (US):**
```
Date: November 3, 2024 (First Sunday in November)
At 2:00am EDT: Clocks fall back to 1:00am EST
1:00am-1:59am happen twice (fold=0 for first, fold=1 for second)

Job scheduled at "0 1 * * *" (1:00am daily):
- On November 3: Should run at 1:00am fold=0 (first occurrence)
- Last completed slot prevents second occurrence (idempotency)
```

### Python zoneinfo DST Handling

```python
from datetime import datetime
from zoneinfo import ZoneInfo

# Spring-Forward: Non-existent time
# 2:30am doesn't exist on March 10, 2024 in America/New_York
try:
    dt = datetime(2024, 3, 10, 2, 30, tzinfo=ZoneInfo("America/New_York"))
except Exception:
    # zoneinfo may raise exception or adjust automatically
    # Need to handle and move to 3:00am
    pass

# Fall-Back: Ambiguous time
# 1:30am exists twice on November 3, 2024 in America/New_York
dt_first = datetime(2024, 11, 3, 1, 30, fold=0, tzinfo=ZoneInfo("America/New_York"))  # First occurrence (EDT)
dt_second = datetime(2024, 11, 3, 1, 30, fold=1, tzinfo=ZoneInfo("America/New_York"))  # Second occurrence (EST)
```

### Timezone Handler Pattern

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import structlog

logger = structlog.get_logger(__name__)

def format_local_time(utc_timestamp: int, timezone_name: str) -> str:
    """Convert UTC timestamp to local timezone string."""
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        logger.warning("invalid_timezone_fallback", timezone=timezone_name)
        tz = timezone.utc

    dt = datetime.fromtimestamp(utc_timestamp, tz=tz)
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S %Z')}"

def handle_dst_transition(job_tz_dt: datetime, timezone_name: str) -> datetime:
    """Adjust datetime for DST transitions."""
    # Check if datetime is in a DST transition
    # For spring-forward: non-existent times → move forward
    # For fall-back: ambiguous times → use first occurrence (fold=0)

    try:
        # Attempt to create timezone-aware datetime
        tz = ZoneInfo(timezone_name)
        adjusted = job_tz_dt.replace(tzinfo=tz)

        # Check for non-existent time (spring-forward)
        # This is tricky - zoneinfo may auto-adjust or we need to check manually

        return adjusted

    except Exception as exc:
        logger.error("dst_transition_handling_failed", error=str(exc))
        return job_tz_dt
```

### Next Run Time Calculation

```python
from croniter import croniter
from datetime import datetime
from zoneinfo import ZoneInfo

def get_next_run_time(cron_expr: str, timezone_name: str, last_completed_slot: int | None = None) -> dict:
    """Calculate next scheduled run time for a job."""
    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)

    # Create croniter with timezone-aware datetime
    iter = croniter(cron_expr, now)

    # Get next occurrence
    next_dt = iter.get_next(datetime)

    # Ensure timezone info
    if next_dt.tzinfo is None:
        next_dt = next_dt.replace(tzinfo=tz)

    # Convert to UTC for storage
    utc_timestamp = int(next_dt.astimezone(timezone.utc).timestamp())

    # Format local time for display
    local_str = next_dt.strftime("%Y-%m-%d %H:%M:%S %Z")

    return {
        "utc_timestamp": utc_timestamp,
        "local_datetime": local_str,
        "timezone": timezone_name,
    }
```

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 4.3: Timezone-Aware Scheduling with DST Handling]
- [Source: _bmad-output/planning-artifacts/architecture.md#Timezone & Scheduling Correctness]
- [Source: _bmad-output/implementation-artifacts/4-2-idempotent-job-execution-with-catch-up.md]
- [Source: src/sohnbot/capabilities/scheduler/executor.py (existing timezone handling)]
- [Source: src/sohnbot/capabilities/scheduler/job_manager.py]
- [Python zoneinfo documentation: https://docs.python.org/3/library/zoneinfo.html]
- [croniter documentation: https://github.com/kiorky/croniter]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex (CLI)

### Debug Log References

- Validation tests:
  - `.venv/bin/pytest tests/unit/test_timezone_handler.py tests/unit/test_executor.py tests/integration/test_scheduler_integration.py tests/unit/test_commands.py tests/unit/test_mcp_tools.py tests/integration/test_executor_integration.py`

### Completion Notes List

- Added `src/sohnbot/capabilities/scheduler/timezone_handler.py` with:
  - `format_local_time(utc_timestamp, timezone_name)` with UTC fallback on timezone errors
  - `get_next_run_time(cron_expr, timezone_name, last_completed_slot)` returning UTC+local metadata
  - `handle_dst_transition(job_tz_dt, timezone_name)` for spring-forward/fall-back handling
  - DST transition counters via `get_dst_transition_count()`
- Enhanced scheduler slot calculation in `executor.py`:
  - applies DST transition handling in `_calculate_current_slot`
  - logs DST transition adjustments
  - keeps timezone-aware cron evaluation and adds UTC fallback when job timezone cannot be loaded
- Updated `job_manager.list_jobs()` to include per-job `next_run_local` computed via timezone handler.
- Updated MCP `sched__list` output to include next local run time.
- Extended Telegram `/schedule` command to support `/schedule list` and display local next-run times.
- Added DST transition metric visibility to status outputs:
  - Telegram `/status`
  - MCP `observe__status`
- Strengthened timezone validation message and added tzdata behavior comment in job creation path.
- Added DST-focused unit and integration tests covering spring-forward, fall-back, slot calculations, transition execution behavior, logging counter behavior, and fallback handling.

### File List

- `_bmad-output/implementation-artifacts/4-3-timezone-aware-scheduling-with-dst-handling.md`
- `src/sohnbot/capabilities/scheduler/timezone_handler.py`
- `src/sohnbot/capabilities/scheduler/executor.py`
- `src/sohnbot/capabilities/scheduler/job_manager.py`
- `src/sohnbot/capabilities/scheduler/__init__.py`
- `src/sohnbot/runtime/mcp_tools.py`
- `src/sohnbot/gateway/commands.py`
- `tests/unit/test_timezone_handler.py`
- `tests/unit/test_executor.py`
- `tests/integration/test_scheduler_integration.py`
- `tests/unit/test_commands.py`

### Change Log

- 2026-02-28: Implemented Story 4.3 timezone-aware scheduling with DST handling, local-time presentation, DST metrics, and test coverage.
