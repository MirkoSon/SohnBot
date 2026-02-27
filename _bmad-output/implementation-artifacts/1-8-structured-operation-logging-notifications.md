# Story 1.8: Structured Operation Logging & Notifications

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want all operations logged with complete audit trail and status notifications,
so that I can track what SohnBot has done and receive timely updates.

## Acceptance Criteria

**Given** any operation is executed (file, git, etc.)
**When** the operation starts
**Then** broker logs: timestamp, chat ID, operation type, file paths, tier to execution_log
**And** when operation completes, broker logs: result status, error details (if any), duration
**And** notification is sent to Telegram within 10s (NFR-005)
**And** notification includes: operation type, files affected, result, snapshot branch (if created)
**And** user can disable notifications: /notify off (logs still captured)
**And** 100% of operations have audit log entry (NFR-014)

## Tasks / Subtasks

- [x] Task 1: Create notification_outbox table migration (AC: 1, 2, 3, 4, 5, 6)
  - [x] Create `src/sohnbot/persistence/migrations/0002_notifications.sql`
  - [x] Add notification_outbox table with columns: id (PRIMARY KEY), operation_id (FK to execution_log), chat_id, status (pending/sent/failed), message_text, created_at, sent_at, retry_count, error_details
  - [x] Add CHECK constraint for status IN ('pending', 'sent', 'failed')
  - [x] Add CHECK constraint for retry_count >= 0
  - [x] Add index on (status, created_at) for worker polling
  - [x] Add config table entry for notifications_enabled per chat_id
  - [x] Verify migration applies successfully via scripts/migrate.py

- [x] Task 2: Implement notification outbox operations (AC: 1, 2, 3, 4, 5, 6)
  - [x] Create `src/sohnbot/persistence/notification.py`
  - [x] Implement `enqueue_notification(operation_id, chat_id, message_text)` - inserts pending notification
  - [x] Implement `get_pending_notifications(limit=10)` - fetches oldest pending notifications
  - [x] Implement `mark_notification_sent(notification_id)` - updates status to 'sent', sets sent_at
  - [x] Implement `mark_notification_failed(notification_id, error_details)` - updates status to 'failed', increments retry_count
  - [x] Implement `get_notifications_enabled(chat_id)` - checks config table
  - [x] Implement `set_notifications_enabled(chat_id, enabled)` - updates config table
  - [x] Add unit tests for all functions (9 tests minimum)

- [x] Task 3: Create notification worker (AC: 3, 4)
  - [x] Create `src/sohnbot/gateway/notification_worker.py`
  - [x] Implement `NotificationWorker` class with `start()` and `stop()` methods
  - [x] Poll outbox every 5 seconds for pending notifications
  - [x] Send via telegram_client (reuse existing TelegramClient)
  - [x] Mark as sent on success, failed on error
  - [x] Implement exponential backoff for retries (max 3 attempts)
  - [x] Log worker activity via structlog
  - [x] Graceful shutdown on stop signal
  - [x] Add unit tests (5 tests minimum)

- [x] Task 4: Update broker to enqueue notifications (AC: 1, 2, 3, 4, 5, 6)
  - [x] Update `src/sohnbot/broker/router.py`
  - [x] After log_operation_end(), call enqueue_notification() if notifications enabled
  - [x] Format notification message with: operation type, files affected, result status, snapshot_ref (if any)
  - [x] Use emoji indicators: ✅ success, ❌ failure, ⏱️ timeout
  - [x] Ensure notifications never block operation completion
  - [x] Remove direct notifier callback (replace with outbox pattern)
  - [x] Update unit tests (3 new tests)

- [x] Task 5: Add /notify command (AC: 5)
  - [x] Update `src/sohnbot/gateway/commands.py` (or create if doesn't exist)
  - [x] Implement `/notify on` - enables notifications for chat_id
  - [x] Implement `/notify off` - disables notifications for chat_id
  - [x] Implement `/notify status` - shows current notification setting
  - [x] Add unit tests (3 tests)

- [x] Task 6: Integration testing (AC: 1, 2, 3, 4, 5, 6)
  - [x] Create `tests/integration/test_notification_flow.py`
  - [x] Test: operation creates execution_log entry
  - [x] Test: notification enqueued to outbox
  - [x] Test: worker polls and sends notification
  - [x] Test: notification disabled via /notify off blocks enqueue
  - [x] Test: failed notification retries with backoff
  - [x] Test: 100% audit coverage (all operations logged)
  - [x] Add 8 integration tests minimum

- [x] Task 7: Verify NFR compliance (AC: 3, 6)
  - [x] Verify notification latency <10s (NFR-005)
  - [x] Verify 100% audit log completeness (NFR-014)
  - [x] Verify operations never block on notification failures
  - [x] Verify notification worker survives telegram API failures
  - [x] Add observability metrics for notification lag

- [x] Review Follow-ups (AI)
  - [x] [AI-Review][CRITICAL] Worker not started: The `NotificationWorker` is never instantiated or started in the application code. It only exists in tests. [src/sohnbot/gateway/notification_worker.py]
  - [x] [AI-Review][MEDIUM] Missing Worker Supervision: No mechanism to ensure the worker task stays alive or restarts on crash.
  - [x] [AI-Review][LOW] Dead Code in Broker: `BrokerRouter` still accepts a `notifier` parameter that is no longer used. [src/sohnbot/broker/router.py:39]

## Dev Notes

### Architecture Context

**Logging & Observability Pattern** (Architecture Decision 4):
- **Dual Logging**: structlog for files (debugging) + SQLite audit trail (operations)
- **Persistent Outbox**: notification_outbox table guarantees delivery across crashes
- **Independent Failure Domains**: logging ≠ audit ≠ notification ≠ operation
- **Never Blocking**: Operations complete regardless of notification/logging status
- **Guaranteed Delivery**: Persistent outbox + background worker + retry logic

**Current State Analysis**:
1. ✅ **execution_log table exists** (src/sohnbot/persistence/migrations/0001_init.sql)
   - Columns: operation_id, timestamp, capability, action, chat_id, tier, status, file_paths, snapshot_ref, duration_ms, error_details, details
   - Indexes: status+timestamp, operation_id, timestamp

2. ✅ **Audit functions exist** (src/sohnbot/persistence/audit.py)
   - `log_operation_start()` - inserts 'in_progress' record
   - `log_operation_end()` - updates status to 'completed' or 'failed' with duration and snapshot_ref

3. ✅ **Broker calls audit functions** (src/sohnbot/broker/router.py)
   - Calls log_operation_start() before execution (line 254)
   - Calls log_operation_end() after execution (lines 287, 316, 336, 352)
   - Already has optional `notifier` callback parameter (line 39)

4. ❌ **notification_outbox table does NOT exist** - needs creation in this story
5. ❌ **No notification worker** - needs creation in this story
6. ❌ **No /notify command** - needs creation in this story

### Critical Implementation Patterns

**1. Migration Pattern** (from 0001_init.sql):
```sql
-- notification_outbox: Persistent queue for user notifications
CREATE TABLE IF NOT EXISTS notification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'sent', 'failed')),
    message_text TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    sent_at INTEGER,
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
    error_details TEXT,
    FOREIGN KEY (operation_id) REFERENCES execution_log(operation_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_notification_outbox_status_created
    ON notification_outbox(status, created_at);
```

**2. Outbox Operations Pattern** (from architecture.md):
```python
async def enqueue_notification(operation_id: str, chat_id: str, message_text: str) -> None:
    """Enqueue notification to outbox (never blocks)."""
    db = await get_db()
    await db.execute(
        """INSERT INTO notification_outbox
           (operation_id, chat_id, status, message_text, created_at)
           VALUES (?, ?, 'pending', ?, ?)""",
        (operation_id, chat_id, message_text, int(datetime.now().timestamp()))
    )
    await db.commit()
```

**3. Worker Loop Pattern** (from architecture.md):
```python
class NotificationWorker:
    async def start(self):
        """Background worker polling outbox every 5s."""
        while self.running:
            pending = await get_pending_notifications(limit=10)
            for notif in pending:
                try:
                    await self.telegram_client.send_message(notif['chat_id'], notif['message_text'])
                    await mark_notification_sent(notif['id'])
                except Exception as e:
                    await mark_notification_failed(notif['id'], str(e))
            await asyncio.sleep(5)
```

**4. Broker Integration Pattern** (update router.py after log_operation_end):
```python
# After log_operation_end() call:
if await get_notifications_enabled(chat_id):
    message = self._format_notification(capability, action, result, snapshot_ref)
    await enqueue_notification(operation_id, chat_id, message)
```

**5. Notification Message Format** (from architecture.md):
- **Success**: `✅ File edited: path/to/file.py. Snapshot: snapshot/edit-2026-02-27-1430`
- **Failure**: `❌ File edit failed: path/to/file.py. Error: invalid_patch`
- **Timeout**: `⏱️ File search timed out: pattern="test" path=/repo`
- **Rollback**: `✅ Rollback complete. Restored to: snapshot/edit-2026-02-27-1430. Commit: abc123`

### Testing Standards

**Unit Tests (minimum 17 tests)**:
- notification.py functions (9 tests): enqueue, get_pending, mark_sent, mark_failed, get_enabled, set_enabled, edge cases
- notification_worker.py (5 tests): start/stop, polling, send success, send failure, retry logic
- router.py updates (3 tests): enqueue on success, skip when disabled, format message correctly

**Integration Tests (minimum 8 tests)**:
- End-to-end flow: operation → log → enqueue → worker → telegram
- Notification disabled flow
- Retry with exponential backoff
- Worker crash recovery (outbox persistence)
- 100% audit coverage validation
- Latency verification (<10s)
- Concurrent operations (multiple notifications)
- Failed telegram API handling

### Project Structure Notes

**New Files**:
- `src/sohnbot/persistence/migrations/0002_notifications.sql`
- `src/sohnbot/persistence/notification.py`
- `src/sohnbot/gateway/notification_worker.py`
- `src/sohnbot/gateway/commands.py` (or update if exists)
- `tests/unit/test_notification.py`
- `tests/unit/test_notification_worker.py`
- `tests/integration/test_notification_flow.py`

**Modified Files**:
- `src/sohnbot/broker/router.py` - replace direct notifier with enqueue_notification()
- `tests/unit/test_broker.py` - update tests for new notification pattern

**Dependencies** (verify in pyproject.toml):
- python-telegram-bot (already exists from story 1.3)
- structlog (already exists)
- aiosqlite (already exists)

### Architecture Alignment

**Pattern Compliance**:
- ✅ **Broker-centric**: All notifications enqueued via broker (no capability bypass)
- ✅ **Async First**: Worker uses asyncio event loop, never blocks operations
- ✅ **Error Isolation**: Notification failures don't affect operation success
- ✅ **Persistence**: Outbox survives crashes (WAL mode SQLite)
- ✅ **Retry Logic**: Exponential backoff for failed sends (max 3 attempts)
- ✅ **Observability**: structlog events for worker activity
- ✅ **STRICT Tables**: notification_outbox uses STRICT mode
- ✅ **Naming**: notification_outbox (plural table), snake_case columns
- ✅ **Transactions**: One transaction per enqueue/mark operation

**NFR Compliance**:
- NFR-005: Notifications delivered <10s (worker polls every 5s)
- NFR-014: 100% audit log completeness (log_operation_start/end for all operations)
- NFR-006: Persistent outbox ensures delivery across crashes

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 1.8]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 4: Logging & Observability]
- [Source: _bmad-output/planning-artifacts/architecture.md#Notification Patterns]
- [Source: src/sohnbot/persistence/migrations/0001_init.sql]
- [Source: src/sohnbot/persistence/audit.py]
- [Source: src/sohnbot/broker/router.py]
- [Source: src/sohnbot/gateway/telegram_client.py]
- [Source: _bmad-output/implementation-artifacts/1-7-rollback-to-previous-snapshot.md] (pattern reference for TDD and broker integration)

### Story 1.7 Learnings Applied

From previous story (Rollback to Previous Snapshot):
1. **TDD Approach**: Write tests first (RED), implement (GREEN), refactor (REFACTOR)
2. **Broker Validation**: Always validate parameters before execution
3. **Error Dataclasses**: Use structured error patterns (NotificationError for this story)
4. **Async Subprocess Pattern**: Reuse asyncio.create_subprocess_exec with timeout for worker
5. **Git Command Safety**: Use git -C pattern (not applicable here, but shows established patterns)
6. **Database Fixtures**: Reuse setup_database fixture from test_rollback_operations.py

### Technical Constraints

**Database Constraints**:
- notification_outbox MUST use STRICT mode
- Foreign key constraint on operation_id → execution_log.operation_id
- CHECK constraints on status and retry_count
- Index on (status, created_at) for efficient worker polling

**Worker Constraints**:
- Poll interval: 5 seconds
- Batch size: 10 notifications per poll
- Max retry attempts: 3
- Backoff: exponential (5s, 25s, 125s)
- Graceful shutdown: finish current batch before stopping

**Broker Constraints**:
- NEVER block on notification enqueue
- ALWAYS log operation even if notification fails
- Check notifications_enabled before enqueue
- Include snapshot_ref in notification if present

**Telegram Constraints**:
- Max 1 emoji per message (per architecture.md)
- Format: `[emoji] [operation type]: [details]`
- Use existing TelegramClient from gateway/telegram_client.py

## Dev Agent Record

### Agent Model Used

GPT-5 Codex (CLI)

### Debug Log References

- Targeted Story 1.8 tests:
  - `.venv/bin/python -m pytest tests/unit/test_notification.py tests/unit/test_notification_worker.py tests/unit/test_commands.py tests/integration/test_notification_flow.py -v`
- Full regression:
  - `PYTHONPATH=src .venv/bin/python -m pytest -v`
  - Result: `266 passed, 5 skipped`
- Review follow-up verification:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_notification_worker.py tests/unit/test_telegram_client.py tests/integration/test_patch_edit_operations.py tests/integration/test_rollback_operations.py tests/integration/test_notification_flow.py -v`

### Completion Notes List

- Implemented persistent notification outbox migration (`0002_notifications.sql`) with FK to `execution_log`, CHECK constraints, and polling index.
- Added notification persistence APIs for enqueue, pending fetch, sent/failed updates, retry scheduling, and per-chat notification enablement.
- Added notification worker with polling, delivery, retry/backoff, lag metric logging, and graceful lifecycle methods.
- Integrated broker operation completion paths with outbox enqueue and structured notification message formatting.
- Added `/notify on|off|status` command handling and wired command in Telegram client.
- Added Story 1.8 unit/integration test coverage for persistence, worker, command handling, broker enqueue flow, retry behavior, and NFR latency/completeness checks.
- Fixed worker batch processing to process direct batch invocations (used by tests and operationally valid for manual batch runs).
- Kept FK integrity in unit tests by seeding `execution_log` entries before enqueue scenarios.
- Updated legacy notifier-based integration assertions to validate outbox behavior after architecture shift to persistent notifications.
- Hardened fallback patch applier by rejecting `/dev/null` new/delete file headers with deterministic `patch_apply_failed`.
- ✅ Resolved review finding [CRITICAL]: `NotificationWorker` is now started/stopped as part of `TelegramClient` lifecycle.
- ✅ Resolved review finding [MEDIUM]: Added crash supervision with automatic worker restart after unexpected task termination.
- ✅ Resolved review finding [LOW]: Removed unused `notifier` argument/state from `BrokerRouter` and updated integration tests to assert outbox behavior.

### File List

- src/sohnbot/persistence/migrations/0002_notifications.sql (new)
- src/sohnbot/persistence/notification.py (new)
- src/sohnbot/persistence/__init__.py (modified)
- src/sohnbot/gateway/notification_worker.py (new)
- src/sohnbot/gateway/commands.py (new)
- src/sohnbot/gateway/telegram_client.py (modified)
- src/sohnbot/broker/router.py (modified)
- src/sohnbot/capabilities/files/patch_editor.py (modified)
- tests/unit/test_notification.py (new)
- tests/unit/test_notification_worker.py (new)
- tests/unit/test_commands.py (new)
- tests/integration/test_notification_flow.py (new)
- tests/integration/test_patch_edit_operations.py (modified)
- tests/integration/test_rollback_operations.py (modified)
- tests/unit/test_telegram_client.py (modified)

### Change Log

- 2026-02-27: Implemented Story 1.8 structured operation logging notifications (outbox migration, persistence APIs, worker, broker enqueue flow, `/notify` commands, and test coverage). Completed full regression with `PYTHONPATH=src` (`266 passed, 5 skipped`).
- 2026-02-27: Addressed code review findings - 3 items resolved (worker runtime startup, worker crash supervision, broker notifier dead-code removal).
