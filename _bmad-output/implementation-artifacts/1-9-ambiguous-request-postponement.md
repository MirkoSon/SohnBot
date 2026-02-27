# Story 1.9: Ambiguous Request Postponement

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want SohnBot to request clarification when my request is ambiguous,
So that unclear operations don't fail or execute incorrectly.

## Acceptance Criteria

**Given** a natural language request is ambiguous (agent cannot determine intent)
**When** the agent detects ambiguity
**Then** clarification is requested via Telegram: "Did you mean [option A] or [option B]?"
**And** if no response within 60 seconds, operation is postponed
**And** retry notification is sent after 30 minutes
**And** if still no response, operation is cancelled safely
**And** ambiguous operations are never auto-approved

## Tasks / Subtasks

- [x] Task 1: Update Agent Session for Ambiguity Detection
  - [x] Update `src/sohnbot/runtime/agent_session.py` to add ambiguity detection logic
  - [x] Implement mechanism to identify when a request lacks sufficient specificity to safely execute
  - [x] Create function to generate clarification options (e.g., "[option A] or [option B]")
  - [x] Send clarification request via `telegram_client.send_message`
  - [x] Wait for user response for up to 60 seconds

- [x] Task 2: Create Postponement Manager
  - [x] Create `src/sohnbot/runtime/postponement_manager.py`
  - [x] Implement tracking for postponed operations (in-memory or SQLite depending on best practice for volatility)
  - [x] Update `execution_log` table with 'postponed' status if no response within 60s
  - [x] Create scheduled job to handle 30-minute retry notification (using existing `Scheduler` infra)

- [x] Task 3: Implement Retry and Cancellation Logic
  - [x] Create logic triggered by scheduler after 30 minutes
  - [x] Send retry notification via `notification_outbox` / broker
  - [x] Wait for further response
  - [x] If no response, securely cancel the operation and update `execution_log` status to 'cancelled'

- [x] Task 4: Integration and Testing
  - [x] Add unit tests for `postponement_manager.py` (minimum 5 tests)
  - [x] Update `agent_session.py` tests for ambiguity detection (minimum 3 tests)
  - [x] Add integration tests verifying ambiguity -> postponement -> notification -> cancellation flow
  - [x] Verify 100% of ambiguous requests are never auto-approved

- [x] Review Follow-ups (AI)
  - [x] [AI-Review][HIGH] Persistence of postponement state: Current state is in-memory only and will be lost on process restart. [src/sohnbot/runtime/postponement_manager.py:27]
  - [x] [AI-Review][MEDIUM] Redundant clarification response: User receives two separate messages upon clarification within 60s. [src/sohnbot/gateway/message_router.py:64]
  - [x] [AI-Review][MEDIUM] Missing File List entries: 8 modified files are not documented in the story File List. [git status]
  - [x] [AI-Review][LOW] Heuristic ambiguity detection: Logic is currently simple and may need more robust LLM-based evaluation in the future. [src/sohnbot/runtime/agent_session.py:168]

## Dev Notes

### Architecture Context

**Governed Operator Spine**
- Safety is paramount. If intent is unclear, we must not guess or auto-approve.
- Ambiguity detection happens *before* Broker validation since we don't know the exact operation yet.
- Postponement status must be properly recorded in the `execution_log`.

**Logging & Observability Pattern** (From Story 1.8)
- Always use `enqueue_notification(operation_id, chat_id, message_text)` to send the retry notifications.
- Ensure the async flow is maintained and never blocks the main event loop.

### Critical Implementation Patterns

**1. Ambiguity Detection**
- The detection mechanism needs to be robust. Consider using LLM evaluation or explicit keyword parsing.

**2. Scheduler Integration**
- Use the existing boundary-aligned tick loop and `JobManager`.
- Create a specific job type or one-off scheduled task for the 30-minute reminder.

### Project Structure Notes

**New Files**:
- `src/sohnbot/runtime/postponement_manager.py`
- `tests/unit/test_postponement.py`

**Modified Files**:
- `src/sohnbot/runtime/agent_session.py`
- (Potentially) `src/sohnbot/persistence/audit.py` to support new statuses ('postponed', 'cancelled')

### Technical Constraints

- **Timeouts**: The 60-second wait MUST NOT block the Telegram polling loop or the main event loop.
- **State**: How is the context of the ambiguous request saved so it can be resumed if the user *does* reply?

## Review Follow-ups (To be filled during code review)

- [x] [AI-Review] Validate async safety of the 60s wait period.
- [x] [AI-Review] Verify `execution_log` state transitions.

> Ultimate context engine analysis completed - comprehensive developer guide created.

## Dev Agent Record

### Agent Model Used

GPT-5 Codex (CLI)

### Debug Log References

- `python3 -m compileall src tests` (pass)
- `pytest -q tests/unit/test_agent_session.py tests/unit/test_postponement.py tests/unit/test_telegram_client.py tests/unit/test_persistence.py tests/integration/test_telegram_to_broker.py` (could not run: `pytest` not installed)
- `poetry run pytest ...` (could not run: `poetry` not installed)

### Completion Notes List

- Added ambiguity detection and clarification option generation in `AgentSession`, with clarification prompt delivery via `telegram_client.send_message`.
- Added `PostponementManager` to track pending ambiguous operations with 60s clarification timeout, 30m retry notification scheduling, and safe cancellation.
- Added postponed-response resume handling in `MessageRouter` so postponed operations can continue after clarification.
- Added migration `0003_execution_log_status_extension.sql` and audit logging support for `postponed` and `cancelled` status transitions.
- Added/updated unit and integration tests for ambiguity, postponement lifecycle, Telegram routing, and persistence constraints.
- Verified syntax integrity with `python3 -m compileall src tests`.
- Added persistent postponement state storage (`postponed_operation`) and runtime recovery on session initialization so pending/postponed operations survive process restarts.
- Removed duplicate clarification acknowledgement path (live clarification now suppresses extra message and only final response is sent).
- Added injectable ambiguity evaluator hook in `AgentSession` to allow future LLM-based ambiguity detection beyond heuristics.
- Executed focused regression tests via `.venv/bin/pytest` with all targeted tests passing.
- ✅ Resolved review finding [HIGH]: postponement lifecycle is persisted and recovered after restart.
- ✅ Resolved review finding [MEDIUM]: duplicate clarification response removed for in-flight requests.
- ✅ Resolved review finding [MEDIUM]: File List updated with all modified files for this story.
- ✅ Resolved review finding [LOW]: ambiguity detection now supports pluggable evaluator for robust future implementation.

### File List

- src/sohnbot/runtime/postponement_manager.py (new)
- src/sohnbot/runtime/agent_session.py (modified)
- src/sohnbot/gateway/message_router.py (modified)
- src/sohnbot/gateway/telegram_client.py (modified)
- src/sohnbot/persistence/audit.py (modified)
- src/sohnbot/persistence/__init__.py (modified)
- src/sohnbot/persistence/postponement.py (new)
- src/sohnbot/persistence/migrations/0003_execution_log_status_extension.sql (new)
- src/sohnbot/persistence/migrations/0004_postponed_operation_state.sql (new)
- tests/unit/test_postponement.py (new)
- tests/unit/test_agent_session.py (modified)
- tests/unit/test_telegram_client.py (modified)
- tests/unit/test_persistence.py (modified)
- tests/integration/test_telegram_to_broker.py (modified)

### Change Log

- 2026-02-27: Implemented Story 1.9 ambiguity clarification with postponement, retry notification enqueue, cancellation state transitions, and coverage updates.
- 2026-02-27: Addressed AI-review findings with restart-safe postponement persistence/recovery, duplicate clarification response suppression, expanded file documentation, and ambiguity evaluator extensibility.
