# Story 7.4: Broker Safety & Input Hardening

Status: draft

## Story

As a developer,
I want the broker to be safe under concurrent access and restrict command profile inputs to a known-safe allowlist,
So that concurrent Telegram messages cannot corrupt broker state and command profiles cannot be hijacked for arbitrary execution.

## Acceptance Criteria

**Given** two Telegram messages arrive simultaneously, both triggering profile execution
**When** the broker increments `_profile_counts` for chaining enforcement
**Then** the increment is atomic (protected by `asyncio.Lock`)
**And** the chaining limit of 5 per request is correctly enforced even under concurrency
**And** `_operation_start_times` reads and writes are similarly protected

**Given** a command profile config contains `command: "/usr/bin/malicious-binary"`
**When** the profile executor validates the command
**Then** the command is rejected because it is not in the allowed command allowlist
**And** only known-safe commands are permitted (e.g., `pylint`, `flake8`, `ruff`, `eslint`, `mypy`, `pytest`, `npm`, `make`, `cargo`, `go`, `rg`, `tsc`)
**And** commands containing path separators (`/`, `\`) or traversal (`..`) are rejected
**And** the rejected command is logged as a security event

**Given** a scheduled job has `timezone: "Invalid/Nonexistent"`
**When** the scheduler evaluates this job's next run slot
**Then** the job is SKIPPED (not executed in UTC fallback)
**And** an error notification is sent to Telegram: "Job [name] skipped: invalid timezone [tz]"
**And** the job is logged as failed with error details
**And** other jobs in the same tick continue executing normally

## Tasks / Subtasks

- [ ] Task 1: Add asyncio.Lock to broker state maps (AC: 1)
  - [ ] Add `self._state_lock = asyncio.Lock()` to `BrokerRouter.__init__` (or wherever `_profile_counts` / `_operation_start_times` are initialized)
  - [ ] Wrap all reads/writes of `_profile_counts` in `async with self._state_lock:`
  - [ ] Wrap all reads/writes of `_operation_start_times` in `async with self._state_lock:`
  - [ ] Verify the lock scope is narrow (protect only the dict operations, not entire request handling)

- [ ] Task 2: Create command allowlist in profile_executor.py (AC: 2)
  - [ ] Define `ALLOWED_PROFILE_COMMANDS: frozenset[str]` at module level:
    ```python
    ALLOWED_PROFILE_COMMANDS = frozenset({
        "pylint", "flake8", "ruff", "eslint", "mypy", "black", "isort",
        "pytest", "python", "npm", "npx", "node", "make", "cargo", "go",
        "rg", "tsc", "prettier", "biome",
    })
    ```
  - [ ] Create `_validate_command(command: str) -> tuple[bool, str]`:
    1. Split command on whitespace, take first element as the binary name
    2. Reject if binary contains `/`, `\`, or `..`
    3. Reject if binary not in `ALLOWED_PROFILE_COMMANDS`
    4. Return `(False, error_message)` on rejection, `(True, "")` on acceptance
  - [ ] Call `_validate_command()` at the top of each `execute_*_profile()` function before subprocess creation
  - [ ] On rejection: log `"profile_command_rejected"` as a security event and raise `ValueError`

- [ ] Task 3: Fail-closed scheduler timezone handling (AC: 3)
  - [ ] Modify `executor.py:95-99` — replace the `except Exception: ... fallback_utc` with:
    ```python
    except Exception:
        logger.error(
            "scheduler_invalid_timezone",
            timezone=job_tz_name,
            job_name=job.get("name"),
        )
        await enqueue_notification(
            chat_id="scheduler",
            message=f"Job '{job.get('name')}' skipped: invalid timezone '{job_tz_name}'",
        )
        continue  # Skip this job, don't execute in UTC fallback
    ```
  - [ ] Ensure the `continue` skips to the next job in the loop (verify loop structure)
  - [ ] Add import for `enqueue_notification` if not already present

- [ ] Task 4: Testing (AC: all)
  - [ ] Test: concurrent `asyncio.gather` on broker operations — no corruption of `_profile_counts`
  - [ ] Test: command with `/usr/bin/` prefix is rejected
  - [ ] Test: command with `..` is rejected
  - [ ] Test: command `rg` (in allowlist) is accepted
  - [ ] Test: command `evil-binary` (not in allowlist) is rejected
  - [ ] Test: rejected command logs security event
  - [ ] Test: invalid timezone skips job and sends notification
  - [ ] Test: valid timezone continues to work normally
  - [ ] Test: other jobs in same tick execute despite one having invalid timezone

## Dev Notes

### Epic 7 Context

**This story:** Fixes F-06 (HIGH — command injection via profile config), F-07 (HIGH — fail-open timezone), F-08 (HIGH — broker concurrency).

**Independent of:** All other Story 7.x — can execute in parallel.

### Architecture and Safety Guardrails

1. **Asyncio Lock Scope:**
   - `asyncio.Lock` is a coroutine-level lock (not thread-level) — appropriate for single-event-loop architecture
   - Lock contention is minimal because the protected operations are O(1) dict lookups/updates
   - Do NOT hold the lock during I/O or subprocess calls — only for in-memory state access

2. **Command Allowlist Design:**
   - Allowlist (not blocklist) — any command not explicitly permitted is denied
   - Only the base command name is validated (e.g., `pytest`), not arguments
   - Arguments are already handled safely via `create_subprocess_exec` (no shell interpolation)
   - The allowlist is configurable via code only (not user-facing config) — adding commands requires a code change

3. **Fail-Closed Timezone:**
   - Current behavior: bad timezone silently falls back to UTC, potentially running at wrong time
   - New behavior: bad timezone skips the job entirely and alerts the user
   - This is the correct security posture — silent fallback is a fail-open pattern

### File-Level Guidance

**Primary files to modify:**
- `src/sohnbot/broker/router.py` — add `_state_lock`, protect `_profile_counts` and `_operation_start_times`
- `src/sohnbot/capabilities/command_profiles/profile_executor.py` — add `ALLOWED_PROFILE_COMMANDS`, `_validate_command()`, call at top of each profile
- `src/sohnbot/capabilities/scheduler/executor.py` — modify `_scheduler_tick()` lines 95-99 for fail-closed timezone

**Files to reference (do not redesign):**
- `src/sohnbot/config/registry.py:26` — `_SAFE_COMMAND_RE` pattern (similar validation concept)
- `src/sohnbot/persistence/notification.py` — `enqueue_notification()` function signature

**Files to update for testing:**
- `tests/unit/test_broker.py` — add concurrency tests
- `tests/unit/test_profile_executor.py` — add command validation tests
- `tests/unit/test_executor.py` — add timezone fail-closed tests

### References

- [Source: _bmad-output/implementation-artifacts/security-audit-findings-v1.md#F-06]
- [Source: _bmad-output/implementation-artifacts/security-audit-findings-v1.md#F-07]
- [Source: _bmad-output/implementation-artifacts/security-audit-findings-v1.md#F-08]
- [Source: docs/PRD.md#DR-004 — Command Injection Prevention]
