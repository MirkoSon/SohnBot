# Story 7.2: Subprocess & Process Lifecycle Hardening

Status: draft

## Story

As a developer,
I want all subprocesses to be killed cleanly (including grandchildren) and all async tasks to be tracked,
So that SohnBot cannot leak zombie processes or orphan fire-and-forget coroutines.

## Acceptance Criteria

**Given** a command profile spawns a subprocess that itself spawns child processes
**When** the operation times out or is cancelled
**Then** the entire process group is killed (not just the direct child)
**And** `os.killpg(os.getpgid(proc.pid), signal.SIGTERM)` is used on POSIX with SIGKILL fallback
**And** `start_new_session=True` is passed to all `create_subprocess_exec` calls in profile_executor.py

**Given** a git operation is in-flight via `_run_git_command`
**When** the calling coroutine is cancelled (`asyncio.CancelledError`)
**Then** the subprocess is killed before the coroutine exits
**And** the cancellation is re-raised after cleanup
**And** no orphaned `git` process remains

**Given** a scheduler job times out and a notification task is created
**When** `asyncio.create_task()` is used for the timeout notification
**Then** the task reference is stored in a module-level `_background_tasks: set[asyncio.Task]`
**And** a `done_callback` removes completed tasks from the set
**And** no "Task was destroyed but it is pending" warnings appear

## Tasks / Subtasks

- [ ] Task 1: Add process group kills to profile_executor.py (AC: 1)
  - [ ] Add `import os, signal, sys` to profile_executor.py
  - [ ] Create helper `_kill_process_group(proc)`:
    ```python
    def _kill_process_group(proc):
        if sys.platform != "win32":
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        else:
            proc.kill()
    ```
  - [ ] Add `start_new_session=True` to `create_subprocess_exec` at lines ~50, ~140, ~232, ~306 (lint, build, test, ripgrep profiles)
  - [ ] Replace all `proc.kill()` calls in timeout handlers with `_kill_process_group(proc)`
  - [ ] After SIGTERM, add short wait (0.5s) then SIGKILL fallback if still alive

- [ ] Task 2: Add CancelledError handling to git_ops._run_git_command (AC: 2)
  - [ ] Wrap `await asyncio.wait_for(process.communicate(), ...)` in try/except
  - [ ] Add `except asyncio.CancelledError:` block after the TimeoutError handler
  - [ ] In the CancelledError handler: kill process, await wait, re-raise
  - [ ] Pattern:
    ```python
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    ```

- [ ] Task 3: Add task reference retention for fire-and-forget tasks (AC: 3)
  - [ ] Add `_background_tasks: set[asyncio.Task] = set()` at module level in `executor.py`
  - [ ] Modify `_fire_timeout_notification()` at line 239:
    ```python
    task = asyncio.create_task(_runner(), name=f"scheduler-timeout-notify-{...}")
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    ```
  - [ ] Apply same pattern to any other bare `create_task()` calls found in the codebase (check `postponement_manager.py` lines 171-173 for retry tasks)

- [ ] Task 4: Testing (AC: all)
  - [ ] Test: `start_new_session=True` is passed in all profile subprocess calls (inspect mock args)
  - [ ] Test: timeout in profile_executor kills process group (mock `os.killpg`, verify called)
  - [ ] Test: CancelledError during git command kills subprocess and re-raises
  - [ ] Test: fire-and-forget task is tracked in `_background_tasks` set and removed on completion
  - [ ] Test: no "Task was destroyed" warnings in test output

## Dev Notes

### Epic 7 Context

**This story:** Fixes F-01 (CRITICAL — zombie grandchildren), F-05 (HIGH — CancelledError), F-10 (MEDIUM — orphaned tasks).

**Independent of:** Stories 7.1, 7.3, 7.4 — can execute in parallel.

### Architecture and Safety Guardrails

1. **Process Group Kills:**
   - `start_new_session=True` creates a new process group for the child, so grandchildren inherit the group ID
   - `os.killpg()` sends signal to entire group — no zombies
   - SIGTERM first (graceful), then SIGKILL after 0.5s if needed
   - Windows: `start_new_session` not supported — use `proc.kill()` which terminates the process tree on Windows via `TerminateProcess`

2. **CancelledError Handling:**
   - `asyncio.CancelledError` is NOT a subclass of `Exception` in Python 3.9+; it's a `BaseException`
   - Must be caught explicitly — the existing `except Exception` blocks won't catch it
   - Must re-raise after cleanup — swallowing `CancelledError` breaks structured concurrency

3. **Task Reference Pattern:**
   - Python GC may collect unreferenced tasks before they complete
   - Standard pattern: keep a strong reference in a set, remove via `done_callback`
   - This is a documented Python asyncio best practice

### File-Level Guidance

**Primary files to modify:**
- `src/sohnbot/capabilities/command_profiles/profile_executor.py` — add `start_new_session=True`, replace `proc.kill()` with `_kill_process_group()`
- `src/sohnbot/capabilities/git/git_ops.py` — add `except asyncio.CancelledError` to `_run_git_command()`
- `src/sohnbot/capabilities/scheduler/executor.py` — add `_background_tasks` set, update `_fire_timeout_notification()`
- `src/sohnbot/runtime/postponement_manager.py` — apply same task retention pattern to retry notification tasks (lines 171-173)

**Files to reference (do not redesign):**
- `src/sohnbot/capabilities/command_profiles/profile_executor.py:69-76` — existing CancelledError handling in lint profile (copy this pattern to git_ops)

**Files to update for testing:**
- `tests/unit/test_profile_executor.py` — add process group kill tests
- `tests/unit/test_executor.py` — add task retention tests

### References

- [Source: _bmad-output/implementation-artifacts/security-audit-findings-v1.md#F-01]
- [Source: _bmad-output/implementation-artifacts/security-audit-findings-v1.md#F-05]
- [Source: _bmad-output/implementation-artifacts/security-audit-findings-v1.md#F-10]
