# Story 4.4: Job Timeout Enforcement

**Epic**: Epic 4 - Scheduler System with Heartbeat
**Story Key**: 4-4-job-timeout-enforcement
**Status**: done
**Created**: 2026-02-28

---

## Story Overview

**As a** system operator
**I want** scheduled jobs to be forcibly terminated if they exceed their configured timeout duration
**So that** one misbehaving job cannot block the entire scheduler or exhaust system resources

### Business Value
- **Risk Mitigation**: Prevents runaway jobs from monopolizing executor resources
- **Reliability**: Ensures scheduler tick loop remains responsive even if individual jobs hang
- **Observability**: Provides clear timeout signals in execution logs and Telegram notifications
- **Predictability**: Guarantees maximum execution time bounds for all scheduled operations

---

## Functional Requirements

### FR-030: Job Timeout Enforcement
**Priority**: HIGH
**Source**: epics.md lines 956-976

The scheduler executor MUST enforce timeout limits on all job executions:

1. **Timeout Configuration**
   - Read timeout value from `config.scheduler.job_timeout_seconds` (default: 600)
   - Apply timeout uniformly to all job action types (agent_query, profile_execute, heartbeat)
   - Timeout boundary wraps the `_dispatch_job_action()` call only (not idempotency checks or logging)

2. **Timeout Mechanism**
   - Use `asyncio.wait_for()` to wrap job action execution
   - Catch `asyncio.TimeoutError` exception when timeout expires
   - Log timeout as operation failure with clear error details
   - Update `execution_log` with timeout-specific status and metadata

3. **Telegram Notification**
   - Send notification to configured admin chat when job timeout occurs
   - Message format: `⚠️ Scheduled job timeout: [{job_name}] exceeded {timeout}s limit`
   - Include job metadata: name, action type, scheduled slot, actual duration
   - Use existing notification infrastructure from Story 1.8

4. **Execution Log Recording**
   - Mark timed-out jobs with `status='failed'`
   - Include `error_details.timeout=True` flag for filtering timeout failures
   - Record actual elapsed time before timeout triggered
   - Preserve job slot timestamp for idempotency tracking

---

## Non-Functional Requirements

### NFR-009: Timeout Precision
- Timeout enforcement MUST trigger within ±5 seconds of configured limit
- Use asyncio event loop timing (not wall-clock comparison)
- Timeout countdown begins when `_dispatch_job_action()` starts

### NFR-026: Graceful Timeout Handling
- Timeout MUST NOT crash the scheduler executor loop
- Timeout MUST NOT prevent other concurrent jobs from executing
- Timed-out jobs MUST still update `last_completed_slot` to prevent infinite retries

### NFR-027: Notification Reliability
- Telegram timeout notifications MUST be fire-and-forget (non-blocking)
- Failed notification delivery MUST NOT affect job status recording
- Notification failures MUST be logged but not propagated

---

## Acceptance Criteria

### AC-030.1: Timeout Wrapper Integration
- [x] `_execute_single_job()` wraps `_dispatch_job_action()` with `asyncio.wait_for()`
- [x] Timeout duration read from `get_config_manager().get("scheduler.job_timeout_seconds")`
- [x] Default timeout of 600 seconds applied if config read fails
- [x] Idempotency check and slot update occur outside timeout boundary

### AC-030.2: TimeoutError Exception Handling
- [x] `asyncio.TimeoutError` caught in dedicated except block
- [x] Timeout logged with structured logging: `scheduler_job_timeout` event
- [x] `execution_log` updated with `status='failed'` and `error_details.timeout=True`
- [x] `last_completed_slot` updated even for timed-out jobs

### AC-030.3: Telegram Timeout Notification
- [x] Notification message includes job name, timeout duration, scheduled slot
- [x] Notification sent to admin chat (chat_id from config or environment)
- [x] Notification dispatch does not block executor loop
- [x] Notification failures logged with `notification_delivery_failed` event

### AC-030.4: Timeout Observability
- [x] Execution log query can filter timeout failures: `WHERE details->>'timeout' = 'true'`
- [x] Timeout count exposed in `/metrics` endpoint (if implemented)
- [x] Structured logs include timeout duration and job metadata

### AC-030.5: Timeout Testing
- [x] Unit test: `test_job_timeout_enforcement()` with mock slow action
- [x] Unit test: `test_timeout_updates_last_completed_slot()` verifies idempotency
- [x] Integration test: `test_timeout_notification_delivery()` with test chat
- [x] Edge case: Timeout < 1 second handled gracefully (clamp to 1)

---

## Implementation Guidance

### Architecture Context

```
src/sohnbot/capabilities/scheduler/
├── executor.py          # ADD timeout wrapper in _execute_single_job
└── job_manager.py       # No changes (config read only)

src/sohnbot/gateway/
├── telegram_client.py   # REUSE existing send_message for notification
└── notification_worker.py  # OPTIONAL: Could use notification queue

src/sohnbot/persistence/
└── audit.py            # No changes (existing log_operation_end handles error_details)

config/
└── default.toml        # ALREADY HAS job_timeout_seconds = 600
```

### Key Implementation Tasks

#### Task 4.4.1: Add Timeout Wrapper to _execute_single_job
**File**: `src/sohnbot/capabilities/scheduler/executor.py`
**Lines**: 165-253 (current _execute_single_job function)

**Current Structure** (Story 4.3):
```python
async def _execute_single_job(job: dict[str, Any]) -> None:
    operation_id = str(uuid.uuid4())
    started = time.perf_counter()

    # ... timezone setup, slot calculation ...
    await log_operation_start(...)

    try:
        # Idempotency check
        latest_last_completed = await _get_last_completed_slot(str(job["id"]))
        if latest_last_completed is not None and slot_timestamp <= int(latest_last_completed):
            # Skip duplicate, return early
            return

        await _dispatch_job_action(job)  # ← WRAP THIS WITH TIMEOUT
        await _update_last_completed_slot(str(job["id"]), slot_timestamp)

        await log_operation_end(operation_id=operation_id, status="completed", ...)

    except Exception as exc:
        await log_operation_end(operation_id=operation_id, status="failed", ...)
```

**New Structure** (Story 4.4):
```python
async def _execute_single_job(job: dict[str, Any]) -> None:
    operation_id = str(uuid.uuid4())
    started = time.perf_counter()

    # Read timeout from config
    try:
        timeout_seconds = int(get_config_manager().get("scheduler.job_timeout_seconds"))
    except Exception:
        timeout_seconds = 600  # Default 10 minutes

    # Ensure minimum timeout of 1 second
    timeout_seconds = max(1, timeout_seconds)

    # ... timezone setup, slot calculation ...
    await log_operation_start(...)

    try:
        # Idempotency check (outside timeout boundary)
        latest_last_completed = await _get_last_completed_slot(str(job["id"]))
        if latest_last_completed is not None and slot_timestamp <= int(latest_last_completed):
            # Skip duplicate, return early
            return

        # Execute job with timeout enforcement
        try:
            await asyncio.wait_for(
                _dispatch_job_action(job),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            # Job exceeded timeout limit
            duration_ms = int((time.perf_counter() - started) * 1000)

            # Log timeout failure
            logger.error(
                "scheduler_job_timeout",
                job_name=job.get("name"),
                timeout_seconds=timeout_seconds,
                elapsed_ms=duration_ms,
                slot_timestamp=slot_timestamp,
            )

            # Record failure in execution log
            await log_operation_end(
                operation_id=operation_id,
                status="failed",
                duration_ms=duration_ms,
                error_details={
                    "timeout": True,
                    "timeout_seconds": timeout_seconds,
                    "job_name": job.get("name"),
                    "slot_timestamp": slot_timestamp,
                },
            )

            # Send Telegram notification
            await _send_timeout_notification(job, timeout_seconds, duration_ms)

            # Still update last_completed_slot to prevent infinite retries
            await _update_last_completed_slot(str(job["id"]), slot_timestamp)

            return  # Exit after timeout handling

        # Normal completion path
        await _update_last_completed_slot(str(job["id"]), slot_timestamp)

        duration_ms = int((time.perf_counter() - started) * 1000)
        await log_operation_end(
            operation_id=operation_id,
            status="completed",
            duration_ms=duration_ms,
        )
        await _update_execution_log_details(...)

    except Exception as exc:
        # Handle all other exceptions (not timeout)
        await log_operation_end(operation_id=operation_id, status="failed", ...)
```

**Key Changes**:
1. Read `scheduler.job_timeout_seconds` from config at function start
2. Wrap `_dispatch_job_action()` with `asyncio.wait_for(timeout=timeout_seconds)`
3. Add dedicated `except asyncio.TimeoutError:` block BEFORE general exception handler
4. Call new `_send_timeout_notification()` helper function
5. Update `last_completed_slot` even for timed-out jobs (prevent retry loop)

#### Task 4.4.2: Implement Timeout Notification Helper
**File**: `src/sohnbot/capabilities/scheduler/executor.py`
**Location**: After `_dispatch_job_action()` function (~line 285)

```python
async def _send_timeout_notification(job: dict[str, Any], timeout_seconds: int, elapsed_ms: int) -> None:
    """Send Telegram notification when job times out (fire-and-forget)."""
    try:
        from ...config.manager import get_config_manager
        from ...gateway.telegram_client import send_message

        # Get admin chat ID from config
        try:
            admin_chat_id = get_config_manager().get("telegram.admin_chat_id")
        except Exception:
            logger.warning("scheduler_timeout_notification_no_admin_chat", job_name=job.get("name"))
            return

        # Format notification message
        job_name = job.get("name", "unknown")
        action = job.get("action", "unknown")
        elapsed_sec = elapsed_ms / 1000

        message = (
            f"⚠️ **Scheduled Job Timeout**\n\n"
            f"**Job**: {job_name}\n"
            f"**Action**: {action}\n"
            f"**Timeout Limit**: {timeout_seconds}s\n"
            f"**Elapsed**: {elapsed_sec:.1f}s\n"
            f"**Scheduled Slot**: {job.get('_slot_timestamp', 'unknown')}"
        )

        # Send notification (non-blocking)
        await send_message(chat_id=admin_chat_id, text=message)

        logger.info(
            "scheduler_timeout_notification_sent",
            job_name=job_name,
            admin_chat_id=admin_chat_id,
        )

    except Exception as exc:
        # Never crash on notification failure
        logger.warning(
            "scheduler_timeout_notification_failed",
            job_name=job.get("name"),
            error=str(exc),
        )
```

**Design Notes**:
- Fire-and-forget pattern: notification failure MUST NOT crash executor
- Reuses existing `send_message()` from Story 1.3 (telegram_client.py)
- Markdown formatting for readability in Telegram
- Admin chat ID read from config (fallback: log warning and skip notification)

#### Task 4.4.3: Update Imports
**File**: `src/sohnbot/capabilities/scheduler/executor.py`
**Location**: Top of file

Add import for asyncio (if not already present):
```python
import asyncio  # For asyncio.wait_for and asyncio.TimeoutError
```

Verify existing imports are sufficient:
```python
from ...config.manager import get_config_manager  # Already imported
```

#### Task 4.4.4: Update Config Schema Documentation
**File**: `config/default.toml`
**Location**: Lines 58-72 (scheduler section)

**Current Config** (Story 4.3):
```toml
[scheduler]
enabled = true
tick_seconds = 60
max_concurrent_jobs = 3
job_timeout_seconds = 600  # ← Already exists
```

**Updated Config** (add comment clarification):
```toml
[scheduler]
enabled = true
tick_seconds = 60
max_concurrent_jobs = 3

# Job timeout enforcement (Story 4.4)
# Jobs exceeding this duration will be forcibly terminated
# Timeout applies to job action execution only (not idempotency checks)
# Minimum value: 1 second, Default: 600 seconds (10 minutes)
job_timeout_seconds = 600
```

---

## Testing Strategy

### Unit Tests
**File**: `tests/unit/test_executor_timeout.py` (new file)

```python
"""Unit tests for scheduler job timeout enforcement (Story 4.4)."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sohnbot.capabilities.scheduler.executor import (
    _execute_single_job,
    _send_timeout_notification,
)


@pytest.mark.asyncio
async def test_job_timeout_enforcement():
    """Test that jobs exceeding timeout are terminated with TimeoutError."""

    # Mock slow job that takes 2 seconds
    async def slow_action(job):
        await asyncio.sleep(2.0)

    with patch("sohnbot.capabilities.scheduler.executor._dispatch_job_action", side_effect=slow_action), \
         patch("sohnbot.capabilities.scheduler.executor.get_config_manager") as mock_config, \
         patch("sohnbot.capabilities.scheduler.executor.log_operation_start", new_callable=AsyncMock), \
         patch("sohnbot.capabilities.scheduler.executor.log_operation_end", new_callable=AsyncMock) as mock_log_end, \
         patch("sohnbot.capabilities.scheduler.executor._get_last_completed_slot", return_value=None), \
         patch("sohnbot.capabilities.scheduler.executor._update_last_completed_slot", new_callable=AsyncMock), \
         patch("sohnbot.capabilities.scheduler.executor._send_timeout_notification", new_callable=AsyncMock) as mock_notify:

        # Configure 1 second timeout
        mock_config.return_value.get.return_value = "1"

        job = {
            "id": "test-job-id",
            "name": "slow-job",
            "action": "agent_query",
            "cron_expr": "* * * * *",
            "timezone": "UTC",
            "_slot_timestamp": int(datetime.now(timezone.utc).timestamp()),
        }

        # Execute job (should timeout after 1 second)
        await _execute_single_job(job)

        # Verify timeout was logged as failure
        assert mock_log_end.called
        call_kwargs = mock_log_end.call_args[1]
        assert call_kwargs["status"] == "failed"
        assert call_kwargs["error_details"]["timeout"] is True

        # Verify notification was sent
        assert mock_notify.called


@pytest.mark.asyncio
async def test_timeout_updates_last_completed_slot():
    """Test that timed-out jobs still update last_completed_slot."""

    async def slow_action(job):
        await asyncio.sleep(2.0)

    with patch("sohnbot.capabilities.scheduler.executor._dispatch_job_action", side_effect=slow_action), \
         patch("sohnbot.capabilities.scheduler.executor.get_config_manager") as mock_config, \
         patch("sohnbot.capabilities.scheduler.executor.log_operation_start", new_callable=AsyncMock), \
         patch("sohnbot.capabilities.scheduler.executor.log_operation_end", new_callable=AsyncMock), \
         patch("sohnbot.capabilities.scheduler.executor._get_last_completed_slot", return_value=None), \
         patch("sohnbot.capabilities.scheduler.executor._update_last_completed_slot", new_callable=AsyncMock) as mock_update, \
         patch("sohnbot.capabilities.scheduler.executor._send_timeout_notification", new_callable=AsyncMock):

        mock_config.return_value.get.return_value = "1"

        job = {
            "id": "test-job-id",
            "name": "slow-job",
            "action": "agent_query",
            "cron_expr": "* * * * *",
            "timezone": "UTC",
            "_slot_timestamp": 1234567890,
        }

        await _execute_single_job(job)

        # Verify last_completed_slot was updated despite timeout
        mock_update.assert_called_once_with("test-job-id", 1234567890)


@pytest.mark.asyncio
async def test_timeout_notification_format():
    """Test timeout notification message format."""

    with patch("sohnbot.capabilities.scheduler.executor.get_config_manager") as mock_config, \
         patch("sohnbot.capabilities.scheduler.executor.send_message", new_callable=AsyncMock) as mock_send:

        mock_config.return_value.get.return_value = "123456789"

        job = {
            "id": "test-job",
            "name": "timeout-test",
            "action": "agent_query",
            "_slot_timestamp": 1234567890,
        }

        await _send_timeout_notification(job, timeout_seconds=600, elapsed_ms=650000)

        # Verify message sent to admin chat
        assert mock_send.called
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["chat_id"] == "123456789"
        assert "timeout-test" in call_kwargs["text"]
        assert "600s" in call_kwargs["text"]
        assert "650.0s" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_timeout_notification_failure_does_not_crash():
    """Test that notification failures are logged but do not raise exceptions."""

    with patch("sohnbot.capabilities.scheduler.executor.get_config_manager") as mock_config, \
         patch("sohnbot.capabilities.scheduler.executor.send_message", side_effect=Exception("Network error")):

        mock_config.return_value.get.return_value = "123456789"

        job = {"id": "test", "name": "test-job", "action": "heartbeat"}

        # Should not raise exception
        await _send_timeout_notification(job, timeout_seconds=600, elapsed_ms=1000)


@pytest.mark.asyncio
async def test_timeout_minimum_value_clamped():
    """Test that timeout < 1 second is clamped to 1."""

    async def instant_action(job):
        pass  # Completes immediately

    with patch("sohnbot.capabilities.scheduler.executor._dispatch_job_action", side_effect=instant_action), \
         patch("sohnbot.capabilities.scheduler.executor.get_config_manager") as mock_config, \
         patch("sohnbot.capabilities.scheduler.executor.log_operation_start", new_callable=AsyncMock), \
         patch("sohnbot.capabilities.scheduler.executor.log_operation_end", new_callable=AsyncMock), \
         patch("sohnbot.capabilities.scheduler.executor._get_last_completed_slot", return_value=None), \
         patch("sohnbot.capabilities.scheduler.executor._update_last_completed_slot", new_callable=AsyncMock):

        # Configure invalid timeout (0 seconds)
        mock_config.return_value.get.return_value = "0"

        job = {
            "id": "test-job",
            "name": "instant-job",
            "action": "heartbeat",
            "cron_expr": "* * * * *",
            "timezone": "UTC",
            "_slot_timestamp": int(datetime.now(timezone.utc).timestamp()),
        }

        # Should not crash (timeout clamped to 1)
        await _execute_single_job(job)
```

### Integration Tests
**File**: `tests/integration/test_timeout_notification.py` (new file)

```python
"""Integration test for timeout notification delivery (Story 4.4)."""

import asyncio

import pytest

from sohnbot.capabilities.scheduler.executor import _send_timeout_notification
from sohnbot.persistence.db import get_db, init_db


@pytest.mark.asyncio
async def test_timeout_notification_delivery(tmp_path):
    """Test that timeout notifications are sent to Telegram (with mock client)."""

    # Initialize test database
    test_db = tmp_path / "test.db"
    await init_db(str(test_db))

    # This test requires telegram_client mock
    # In real integration test, you would use a test chat ID
    # For now, verify the function can be called without crashing

    job = {
        "id": "integration-test-job",
        "name": "timeout-integration-test",
        "action": "agent_query",
        "_slot_timestamp": 1234567890,
    }

    # Should not raise exception even if config missing
    await _send_timeout_notification(job, timeout_seconds=600, elapsed_ms=700000)
```

---

## Dependencies

### Required Stories
- ✅ **Story 4.1**: Job Creation & Persistence (provides `jobs` table and `job_manager.py`)
- ✅ **Story 4.2**: Idempotent Job Execution with Catch-Up (provides `executor.py` and `_execute_single_job`)
- ✅ **Story 4.3**: Timezone-Aware Scheduling (provides current executor implementation)
- ✅ **Story 1.8**: Structured Operation Logging & Notifications (provides notification infrastructure)
- ✅ **Story 1.3**: Telegram Gateway (provides `send_message` function)

### External Dependencies
- **asyncio**: Standard library (Python 3.11+)
- **structlog**: Already in pyproject.toml (logging)
- **aiosqlite**: Already in pyproject.toml (database access)

### Configuration Dependencies
- `config.scheduler.job_timeout_seconds`: Default 600 (already in default.toml)
- `config.telegram.admin_chat_id`: Required for timeout notifications

---

## Migration Plan

### Database Changes
**None required** - Uses existing `execution_log.error_details` JSON column

### Configuration Changes
**None required** - `job_timeout_seconds` already exists in default.toml

### Deployment Steps
1. Deploy code changes to `executor.py`
2. Verify `telegram.admin_chat_id` configured in environment
3. Restart scheduler service to apply timeout wrapper
4. Monitor logs for `scheduler_job_timeout` events
5. Test with artificially low timeout (e.g., 5 seconds) on staging job

---

## Rollback Plan

If timeout enforcement causes issues:

1. **Immediate Mitigation**: Set `job_timeout_seconds = 999999` (effectively disable timeout)
2. **Code Rollback**: Remove `asyncio.wait_for()` wrapper, revert to direct `_dispatch_job_action()` call
3. **Monitoring**: Check for jobs that actually need > 600 seconds (may indicate job design problem)

---

## Story Intelligence from Previous Stories

### Story 4.3 Learnings
- Executor loop already handles exceptions gracefully (Story 4.2 pattern)
- `_execute_single_job` has clear failure domain boundaries
- `last_completed_slot` update is critical for preventing retry loops
- Structured logging uses consistent event naming: `scheduler_job_*`

### Story 1.8 Learnings
- Notification infrastructure uses `send_message()` from telegram_client.py
- Notifications should be fire-and-forget (do not block primary operation)
- Admin chat ID configured via `telegram.admin_chat_id` in config

### Story 4.2 Learnings
- `log_operation_end()` accepts `error_details` dict for structured failure metadata
- Executor uses `asyncio.TaskGroup` for concurrent job execution
- Job execution isolated in try/except to prevent one failure from affecting others

---

## Definition of Done

- [x] Code implemented and committed to feature branch
- [x] All acceptance criteria met (AC-030.1 through AC-030.5)
- [x] Unit tests pass with >90% coverage on new code
- [x] Integration test verifies notification delivery
- [x] Code review completed (focus on timeout boundary placement)
- [x] Timeout tested with artificially low value (5 seconds) on dev environment
- [x] Documentation updated (config comments in default.toml)
- [x] Story status updated to 'review' in sprint-status.yaml

---

## Open Questions
None - Story is well-defined with clear implementation path.

---

## Related Documentation
- `config/default.toml`: Scheduler configuration section
- `src/sohnbot/capabilities/scheduler/executor.py`: Executor loop implementation
- `src/sohnbot/gateway/telegram_client.py`: Notification delivery
- `_bmad-output/planning-artifacts/epics.md`: Epic 4 requirements (lines 956-976)

---

## Dev Agent Record

### Agent Model Used
- GPT-5 Codex (CLI)

### Debug Log References
- `.venv/bin/pytest tests/unit/test_executor.py tests/integration/test_executor_integration.py tests/integration/test_scheduler_integration.py tests/unit/test_commands.py`
- `.venv/bin/pytest tests/unit/test_executor.py tests/integration/test_executor_integration.py`

### Completion Notes
- Added timeout enforcement in `scheduler.executor._execute_single_job` using `asyncio.wait_for`.
- Implemented config-based timeout resolution with fallback/default and clamp-to-1-second behavior.
- Added dedicated timeout failure path with:
  - structured `scheduler_job_timeout` log event
  - `execution_log` failure entry with `error_details.timeout=true`
  - `execution_log.details.timeout=true` for query filtering
  - `last_completed_slot` update on timeout to prevent infinite retry loops
- Added fire-and-forget timeout notification flow using `notification_outbox` enqueue.
- Added timeout config documentation comments to `config/default.toml`.
- Added unit/integration tests for timeout enforcement, clamp behavior, slot update behavior, and notification enqueue delivery.

### File List
- `_bmad-output/implementation-artifacts/4-4-job-timeout-enforcement.md`
- `config/default.toml`
- `src/sohnbot/capabilities/scheduler/executor.py`
- `tests/unit/test_executor.py`
- `tests/integration/test_executor_integration.py`
