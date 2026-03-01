# SohnBot Security Audit Findings — v1.0

**Auditor**: Claude Opus 4.6 (adversarial mode)
**Date**: 2026-03-01
**Scope**: Full codebase — `src/sohnbot/` (all modules)
**Methodology**: Manual static analysis across five architectural pillars

---

## Executive Summary

This codebase was built fast and it shows. The architecture is sound in concept — broker-mediated policy enforcement, scope validation, tiered operations — but the implementation is riddled with concurrency hazards, incomplete process lifecycle management, and a TOCTOU gap in the scope validator that undermines the entire sandbox model. Twelve findings are documented below, four of which are **CRITICAL**.

---

## Finding Index

| ID | Severity | Pillar | Title |
|----|----------|--------|-------|
| F-01 | CRITICAL | Zombie Processes | `proc.kill()` does not kill process groups — grandchild zombies |
| F-02 | CRITICAL | Concurrency | Single shared `aiosqlite` connection used from concurrent coroutines without transactional isolation |
| F-03 | CRITICAL | Sandbox Escape | `ScopeValidator` is vulnerable to TOCTOU symlink race |
| F-04 | CRITICAL | Concurrency | `web.py` opens ad-hoc DB connections bypassing WAL/busy_timeout pragmas |
| F-05 | HIGH | Zombie Processes | `_run_git_command` in `git_ops.py` has no `CancelledError` handler — orphaned processes |
| F-06 | HIGH | Sandbox Escape | Dynamic config allows arbitrary executable paths for command profiles |
| F-07 | HIGH | Exception Swallowing | Scheduler silently falls back to UTC on timezone parse failure |
| F-08 | HIGH | Concurrency | `_operation_start_times` / `_profile_counts` race in BrokerRouter |
| F-09 | HIGH | Type Safety | All capability results are `dict[str, Any]` with zero compile-time shape guarantees |
| F-10 | MEDIUM | Zombie Processes | Fire-and-forget `asyncio.create_task` in scheduler with no reference retention |
| F-11 | MEDIUM | Concurrency | `SnapshotManager.list_snapshots()` uses blocking `subprocess.run()` in async context |
| F-12 | MEDIUM | Exception Swallowing | `_safe_http_server_loop` silently returns on crash — no restart, no alert |

---

## CRITICAL Findings

### F-01: `proc.kill()` does not kill process groups — grandchild zombies

**Pillar**: Zombie Processes & Timeouts
**Files**: `src/sohnbot/capabilities/command_profiles/profile_executor.py:59-61`, `src/sohnbot/capabilities/git/git_ops.py:42-43`, `src/sohnbot/capabilities/git/snapshot_manager.py:153-154`

**Problem**: Every subprocess timeout and cancellation handler in the codebase calls `proc.kill()`, which sends `SIGKILL` to the direct child process only. If that child has spawned its own children (e.g., `make` spawning `gcc`, `pytest` spawning worker processes, `pylint` spawning sub-linters), those grandchild processes become orphans and continue running indefinitely. Over time, this leaks PIDs, file descriptors, and potentially holds locks on the repository.

The `create_subprocess_exec` calls do not set `start_new_session=True`, so there is no process group to kill.

**Proof of concept**: Run `profiles__build` with `command=make` on a project with a long compilation. Timeout fires, `make` is killed, but `gcc`/`cc1` processes remain running.

**Remediation**:

```python
# src/sohnbot/capabilities/command_profiles/profile_executor.py

import os
import signal

# In each execute_*_profile function, change subprocess creation to:
proc = await asyncio.create_subprocess_exec(
    *cmd_parts,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=repo_path,
    start_new_session=True,  # NEW: create process group
)

# Replace every `proc.kill()` call with:
def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Kill the entire process group, not just the direct child."""
    if proc.pid is None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        # Process already exited or we lack permissions
        try:
            proc.kill()
        except ProcessLookupError:
            pass
```

Apply the same pattern to `git_ops.py:_run_git_command` and all subprocess calls in `snapshot_manager.py`.

---

### F-02: Single shared `aiosqlite` connection used from concurrent coroutines without transactional isolation

**Pillar**: Concurrency & Database Locks
**Files**: `src/sohnbot/persistence/db.py:24-77`, `src/sohnbot/persistence/notification.py`, `src/sohnbot/capabilities/scheduler/executor.py:148-163`

**Problem**: `DatabaseManager.get_connection()` caches a single `aiosqlite.Connection` instance globally. Every module — notification worker, scheduler executor, broker audit logging, snapshot collector — shares this one connection.

`aiosqlite` serializes operations through a single background thread, but SQLite's implicit transaction model means interleaved `execute()` + `commit()` calls from different coroutines corrupt transactional boundaries. Scenario:

1. Scheduler executor calls `db.execute("UPDATE jobs SET last_completed_slot = ...")` on job A
2. Before the scheduler calls `db.commit()`, the notification worker calls `db.execute("UPDATE notification_outbox SET status = 'sent' ...")` and then `db.commit()`
3. The notification worker's `commit()` also commits the scheduler's uncommitted UPDATE
4. If the scheduler job subsequently fails and should have been rolled back, the `last_completed_slot` update is already permanently committed — the job will never re-execute that slot

Additionally, `get_connection()` has a TOCTOU race: two coroutines can both see `self._connection is None`, both create connections, and one is leaked.

**Remediation**:

```python
# src/sohnbot/persistence/db.py

import asyncio

class DatabaseManager:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._connection: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()  # NEW: protect connection creation

    async def get_connection(self) -> aiosqlite.Connection:
        if self._connection is not None:
            return self._connection

        async with self._lock:
            # Double-check after acquiring lock
            if self._connection is not None:
                return self._connection

            conn = await aiosqlite.connect(str(self.db_path))
            # ... pragma setup ...
            self._connection = conn
            return conn
```

For transactional isolation, every write-path function should use explicit transactions:

```python
# Example fix for scheduler executor
async def _update_last_completed_slot(job_id: str, slot_timestamp: int) -> None:
    db = await get_db()
    async with db.execute("BEGIN IMMEDIATE"):
        await db.execute(
            "UPDATE jobs SET last_completed_slot = ? WHERE id = ?",
            (slot_timestamp, job_id),
        )
        await db.commit()
```

Longer term, consider a connection-per-operation model using a connection pool or `async with aiosqlite.connect(...)` context managers for write operations.

---

### F-03: `ScopeValidator` is vulnerable to TOCTOU symlink race

**Pillar**: Escaping the Sandbox
**Files**: `src/sohnbot/broker/scope_validator.py:78-92`, `src/sohnbot/capabilities/files/file_ops.py:76-132`

**Problem**: `ScopeValidator.validate_path()` calls `Path.resolve(strict=False)` which resolves symlinks at validation time, then returns success. The actual file operation (read, list, search, patch) happens later in a separate function call. Between validation and use, the filesystem can change.

Attack scenario:
1. Attacker (or concurrent process) places `~/Projects/repo/innocent.txt` -> points to a real file
2. User requests `fs__read` with path `~/Projects/repo/innocent.txt`
3. `ScopeValidator` resolves the symlink, confirms it points inside `~/Projects/`, passes validation
4. Between validation and `file_ops.read_file()`, the attacker replaces the symlink: `innocent.txt` -> `/etc/shadow`
5. `read_file()` follows the new symlink and reads `/etc/shadow`

Note: `resolve(strict=False)` doesn't require the target to exist, making this easier to exploit.

Additionally, `resolve(strict=False)` on a **non-existent** path resolves what it can and appends the rest literally. If a symlink exists at an intermediate directory component, the validator might resolve it to a path inside scope while the actual file operation would resolve differently.

**Remediation**:

```python
# src/sohnbot/broker/scope_validator.py

import os

class ScopeValidator:
    def validate_path(self, path: Any) -> tuple[bool, str]:
        try:
            path_str = self._coerce_to_path_string(path)
        except TypeError:
            return False, "Path outside allowed scope: invalid path type"
        if not path_str:
            return False, "Path outside allowed scope: empty path"

        try:
            normalized = self._normalize_path(path_str)
        except (ValueError, RuntimeError) as e:
            return False, f"Invalid path: {e}"

        # NEW: Reject any path containing symlinks in its component chain
        # This prevents TOCTOU races where symlinks change between
        # validation and use.
        try:
            real_parent = Path(path_str).expanduser()
            # Walk each component and check for symlinks
            current = Path(real_parent.anchor)
            for part in real_parent.parts[1:]:
                current = current / part
                if current.is_symlink():
                    return False, (
                        f"Path contains symlink at '{current}'. "
                        "Symlinked paths are not permitted for safety."
                    )
        except (OSError, ValueError):
            pass  # If we can't stat, resolve() below will catch it

        for root in self.allowed_roots:
            try:
                normalized.relative_to(root)
                return True, ""
            except ValueError:
                continue

        return False, f"Path outside allowed scope: {path_str}"
```

Additionally, `file_ops.py` should re-validate the real path immediately before opening:

```python
# src/sohnbot/capabilities/files/file_ops.py

def read_file(self, path: str, max_size_mb: int = 10) -> dict[str, Any]:
    file_path = Path(path)
    # Re-resolve to catch TOCTOU symlink swaps
    real_path = file_path.resolve(strict=True)
    if real_path != file_path.resolve(strict=False):
        raise FileCapabilityError(
            code="symlink_resolution_mismatch",
            message="Path resolution changed between validation and read",
            details={"path": str(file_path), "resolved": str(real_path)},
            retryable=False,
        )
    # ... rest of read_file using real_path ...
```

---

### F-04: `web.py` opens ad-hoc DB connections bypassing WAL/busy_timeout pragmas

**Pillar**: Concurrency & Database Locks
**Files**: `src/sohnbot/capabilities/web.py:339`, `src/sohnbot/capabilities/web.py:405`, `src/sohnbot/capabilities/web.py:429`

**Problem**: `_get_cached_search()`, `_store_search_cache()`, and `cleanup_expired_cache()` all open their own `aiosqlite.connect(db_path)` connections directly, completely bypassing the `DatabaseManager`. These ad-hoc connections:

1. Do **not** set `PRAGMA busy_timeout=5000` — they get the default 0ms timeout, meaning any lock contention results in immediate `SQLITE_BUSY` errors
2. Do **not** set `PRAGMA journal_mode=WAL` — they default to DELETE journal mode
3. Contend with the main `DatabaseManager` connection that IS in WAL mode, creating mixed-mode access patterns that SQLite documentation explicitly warns against
4. Each function creates and destroys a connection per call, adding overhead and lock contention

This means a web search happening concurrently with a scheduler job write or notification update will fail with `SQLITE_BUSY` approximately 100% of the time if both hit the DB within the same WAL checkpoint window.

**Remediation**:

```python
# src/sohnbot/capabilities/web.py

# Replace ALL instances of:
#   async with aiosqlite.connect(db_path) as db:
# With:
#   db = await get_db()

from ..persistence.db import get_db

async def _get_cached_search(db_path: str, query_hash: str) -> dict[str, Any] | None:
    """Return cached search result when present and not expired."""
    try:
        db = await get_db()
        cursor = await db.execute(
            """
            SELECT query, mode, results_json, created_at
            FROM search_cache
            WHERE query_hash = ?
              AND expires_at > datetime('now')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (query_hash,),
        )
        row = await cursor.fetchone()
        await cursor.close()
    except Exception as exc:
        logger.warning("cache_lookup_error", query_hash=query_hash, error=str(exc))
        return None
    # ... rest unchanged ...
```

Apply the same change to `_store_search_cache` and `cleanup_expired_cache`. Remove the `db_path` parameter from all these functions since they should use the global connection.

---

## HIGH Findings

### F-05: `_run_git_command` has no `CancelledError` handler — orphaned processes

**Pillar**: Zombie Processes & Timeouts
**Files**: `src/sohnbot/capabilities/git/git_ops.py:19-69`

**Problem**: The `_run_git_command` helper handles `TimeoutError` but not `asyncio.CancelledError`. If the parent task is cancelled (e.g., Telegram user disconnects, broker timeout fires, session teardown), `wait_for` propagates `CancelledError` without killing the subprocess. The git process becomes an orphan.

Compare with `profile_executor.py` which correctly handles `CancelledError` — this is inconsistent and indicates the git module was written at a different time without the same defensive patterns.

The same gap exists in `snapshot_manager.py:rollback_to_snapshot` which has multiple `create_subprocess_exec` calls with no `CancelledError` handling.

**Remediation**:

```python
# src/sohnbot/capabilities/git/git_ops.py

async def _run_git_command(
    cmd: list[str],
    repo_path: str,
    timeout_seconds: int,
    timeout_code: str,
) -> tuple[str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # F-01 fix
        )
    except FileNotFoundError as exc:
        raise GitCapabilityError(...) from exc

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise GitCapabilityError(...) from exc
    except asyncio.CancelledError:          # NEW
        if process.returncode is None:      # NEW
            process.kill()                  # NEW
            try:                            # NEW
                await asyncio.shield(process.wait())  # NEW
            except asyncio.CancelledError:  # NEW
                pass                        # NEW
        raise                               # NEW

    # ... rest unchanged ...
```

---

### F-06: Dynamic config allows arbitrary executable paths for command profiles

**Pillar**: Escaping the Sandbox
**Files**: `src/sohnbot/config/registry.py:26`, `src/sohnbot/capabilities/command_profiles/profile_executor.py:38`

**Problem**: The `_SAFE_COMMAND_RE` regex is `r'^[a-zA-Z0-9_./-][\w ./_-]*$'`. This permits:
- Absolute paths: `/usr/bin/rm`, `/bin/sh`
- Traversal paths: `../../bin/evil`
- Any binary on the filesystem reachable by path

Since `commands.lint_command`, `commands.build_command`, `commands.test_command`, and `commands.ripgrep_command` are all **dynamic** config keys (hot-reloadable), an attacker with database write access (or a bug in config update validation) could change the lint command to `/bin/sh` and the next `profiles__lint` call would execute `/bin/sh` with user-controlled file arguments.

Even without DB access: the commands are split on whitespace (`command.split()`), and the regex allows spaces. So `python3 -c` is a valid lint command. When combined with a `files` list like `["import os; os.system('...')"]`, this becomes arbitrary code execution. Wait — the `files` entries are validated against `PurePosixPath` for `..` but not against the safe command regex, and `file_ops` doesn't restrict filenames to safe patterns.

**Remediation**:

```python
# src/sohnbot/config/registry.py

import shutil

_SAFE_COMMAND_NAMES = frozenset({
    "pylint", "flake8", "ruff", "mypy", "black", "isort",  # linters
    "make", "npm", "cargo", "gradle", "mvn",                # build
    "pytest", "unittest", "cargo",                           # test
    "rg", "ripgrep",                                         # search
})

def _validate_command_allowlist(value: str) -> bool:
    """Validate command is a known-safe tool name (no paths allowed)."""
    parts = value.strip().split()
    if not parts:
        raise ValueError("Command must not be empty")
    executable = parts[0]
    # Reject absolute/relative paths — only bare command names
    if "/" in executable or "\\" in executable:
        raise ValueError(
            f"Command must be a bare executable name, not a path: {executable}"
        )
    # Validate against allowlist
    if executable not in _SAFE_COMMAND_NAMES:
        raise ValueError(
            f"Command '{executable}' not in allowed list: "
            f"{', '.join(sorted(_SAFE_COMMAND_NAMES))}"
        )
    # Validate flags (remaining parts) against safe regex
    for flag in parts[1:]:
        if not flag.startswith("-"):
            raise ValueError(f"Non-flag argument in command: {flag}")
    return True
```

Also add a runtime check in `profile_executor.py`:

```python
# Verify the resolved executable exists and is in PATH (not a traversal)
import shutil

resolved = shutil.which(cmd_parts[0])
if resolved is None:
    raise FileNotFoundError(f"Command not found: {cmd_parts[0]}")
```

---

### F-07: Scheduler silently falls back to UTC on timezone parse failure

**Pillar**: Exception Swallowing
**Files**: `src/sohnbot/capabilities/scheduler/executor.py:96-99`

**Problem**:

```python
try:
    job_tz_now = current.astimezone(ZoneInfo(job_tz_name))
except Exception:  # noqa: BLE001
    logger.warning("scheduler_timezone_fallback_utc", ...)
    job_tz_now = current.astimezone(timezone.utc)
```

If a job is configured for `America/New_York` (UTC-5) and the timezone database is corrupted or missing, the scheduler silently evaluates the cron expression in UTC. A job scheduled for `0 18 * * *` in New York (6 PM ET = 11 PM UTC) would fire at 6 PM UTC (1 PM ET) instead — 5 hours early.

The warning is logged but never surfaced to the admin. The job executes successfully at the wrong time, with the `last_completed_slot` updated, preventing correction on the next tick.

**Remediation**:

```python
# src/sohnbot/capabilities/scheduler/executor.py

try:
    job_tz_now = current.astimezone(ZoneInfo(job_tz_name))
except (KeyError, Exception) as exc:
    logger.error(
        "scheduler_timezone_parse_failed",
        timezone=job_tz_name,
        job_name=job.get("name"),
        error=str(exc),
    )
    # Do NOT fall back to UTC — skip the job entirely and alert
    await enqueue_notification(
        operation_id=f"tz-error-{job.get('id', 'unknown')}",
        chat_id=_resolve_timeout_notification_chat_id() or "unknown",
        message_text=(
            f"SCHEDULER ERROR: Job '{job.get('name')}' skipped — "
            f"timezone '{job_tz_name}' could not be resolved. "
            f"Fix the timezone configuration."
        ),
    )
    continue  # Skip this job, don't silently run it in the wrong timezone
```

---

### F-08: `_operation_start_times` / `_profile_counts` race in BrokerRouter

**Pillar**: Concurrency & Database Locks
**Files**: `src/sohnbot/broker/router.py:78-79`

**Problem**: `BrokerRouter._profile_counts` is a plain `dict` accessed with a read-modify-write pattern:

```python
current_count = self._profile_counts.get(chat_id, 0)
# ... (potential await/yield point in validation above) ...
self._profile_counts[chat_id] = current_count + 1
```

If the Claude Agent SDK invokes two MCP tools concurrently for the same chat (which it can — e.g., `profiles__lint` and `profiles__test` in parallel), both could read `current_count = 0`, both pass the chain limit check, and both set `count = 1`. This allows exceeding `max_chain_length`.

Similarly, `_operation_start_times` is never cleaned up for operations that fail during validation (before reaching `_calculate_duration`). Each failed validation adds an entry that is only cleaned by explicit `pop()` in some — but not all — error paths, leading to a slow memory leak.

**Remediation**:

```python
# src/sohnbot/broker/router.py

import asyncio

class BrokerRouter:
    def __init__(self, ...):
        # ...
        self._profile_lock = asyncio.Lock()

    async def _check_and_increment_profile_count(
        self, chat_id: str, max_chain_length: int
    ) -> tuple[bool, int]:
        """Atomically check and increment profile count. Returns (allowed, count)."""
        async with self._profile_lock:
            current = self._profile_counts.get(chat_id, 0)
            if current >= max_chain_length:
                return False, current
            self._profile_counts[chat_id] = current + 1
            return True, current + 1
```

---

### F-09: All capability results are `dict[str, Any]` with zero compile-time shape guarantees

**Pillar**: Type Safety Leaks
**Files**: All capability modules, `src/sohnbot/broker/router.py:47-55`, `src/sohnbot/runtime/mcp_tools.py`

**Problem**: Every capability function returns `dict[str, Any]`. The `BrokerResult.result` field is `Optional[dict]`. The MCP tools then blindly call `.get("passed")`, `.get("exit_code")`, `.get("commit_hash")`, etc. with no compile-time verification that these keys exist.

If a capability function changes its return shape (e.g., renames `"passed"` to `"success"`), the MCP formatting layer will silently produce wrong output — `None` instead of the actual value. This has likely already happened: note how `mcp_tools.py:199` accesses `result.error.get("message")` without the null-safe `(result.error or {})` pattern used elsewhere — evidence of inconsistent access patterns.

**Remediation**: Define typed result dataclasses for each capability:

```python
# src/sohnbot/capabilities/command_profiles/models.py
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ProfileResult:
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    command_used: str

@dataclass(frozen=True, slots=True)
class LintProfileResult(ProfileResult):
    files_linted: list[str]

@dataclass(frozen=True, slots=True)
class TestProfileResult(ProfileResult):
    pattern: str

@dataclass(frozen=True, slots=True)
class BuildProfileResult(ProfileResult):
    target: str
```

Then update `BrokerResult` to use a union type:

```python
from typing import Union

CapabilityResult = Union[
    LintProfileResult,
    TestProfileResult,
    BuildProfileResult,
    GitStatusResult,
    # ... etc
]

@dataclass
class BrokerResult:
    allowed: bool
    operation_id: str
    tier: Optional[int] = None
    snapshot_ref: Optional[str] = None
    error: Optional[dict] = None
    result: Optional[CapabilityResult] = None
```

---

## MEDIUM Findings

### F-10: Fire-and-forget `asyncio.create_task` with no reference retention

**Pillar**: Zombie Processes & Timeouts
**Files**: `src/sohnbot/capabilities/scheduler/executor.py:239`

**Problem**:

```python
asyncio.create_task(_runner(), name=f"scheduler-timeout-notify-{...}")
```

The returned `Task` object is not stored anywhere. Per Python docs: *"Important: Save a reference to the result of this function, to avoid a task disappearing mid-execution."* The garbage collector can collect the task object, and Python 3.12+ will log `"Task was destroyed but it is pending!"`.

Additionally, if this task raises an exception, it becomes a "fire-and-forget exception" that is never retrieved, triggering asyncio's `Task exception was never retrieved` warning.

**Remediation**:

```python
# src/sohnbot/capabilities/scheduler/executor.py

# Module-level set to prevent GC
_background_tasks: set[asyncio.Task] = set()

def _send_timeout_notification(...) -> None:
    async def _runner() -> None:
        try:
            await _enqueue_timeout_notification(...)
        except Exception as exc:
            logger.warning("notification_delivery_failed", ...)

    task = asyncio.create_task(_runner(), name=...)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
```

---

### F-11: `SnapshotManager.list_snapshots()` uses blocking `subprocess.run()` in async context

**Pillar**: Concurrency
**Files**: `src/sohnbot/capabilities/git/snapshot_manager.py:193-228`

**Problem**: `list_snapshots()` is a synchronous method that calls `subprocess.run()`, which blocks the asyncio event loop for the duration of the git command (up to the 10-second timeout). During this block, no other coroutine can execute — including the notification worker, scheduler ticks, and Telegram message handling.

This is called from the broker router's `_execute_capability`, which is awaited in the async `route_operation` method.

**Remediation**:

```python
# Convert to async and use create_subprocess_exec
async def list_snapshots(self, repo_path: str) -> list[dict[str, Any]]:
    returncode, stdout, stderr = await self._run_git_async(
        ["git", "-C", repo_path, "branch", "--list", "snapshot/*"],
        repo_path=repo_path,
        deadline=datetime.now(timezone.utc) + timedelta(seconds=10),
        timeout_code="list_snapshots_timeout",
    )
    # ... rest of parsing logic unchanged ...
```

And update the call site in `router.py` to `await` it.

---

### F-12: `_safe_http_server_loop` silently returns on crash — no restart, no alert

**Pillar**: Exception Swallowing
**Files**: `src/sohnbot/main.py:133-146`

**Problem**:

```python
async def _safe_http_server_loop(host: str, port: int) -> None:
    try:
        await http_server_loop(host=host, port=port)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("http_server_task_failed", ...)
```

When the HTTP observability server crashes, this function catches the exception, logs it, and returns normally. The `TaskGroup` in `run_main()` does not restart it. The HTTP server is silently gone for the rest of the process lifetime. No notification is sent to the admin.

Compare with `NotificationWorker` which has auto-restart logic (`_on_worker_done` + `_restart_after_delay`). The HTTP server has no such mechanism.

**Remediation**:

```python
# src/sohnbot/main.py

async def _safe_http_server_loop(host: str, port: int) -> None:
    """Run HTTP server loop with crash recovery."""
    max_restarts = 5
    restart_delay = 5

    for attempt in range(max_restarts):
        try:
            await http_server_loop(host=host, port=port)
            return  # Clean exit
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "http_server_task_failed",
                host=host,
                port=port,
                attempt=attempt + 1,
                max_restarts=max_restarts,
                error=str(exc),
                exc_info=True,
            )
            if attempt + 1 < max_restarts:
                await asyncio.sleep(restart_delay * (attempt + 1))
            else:
                logger.critical(
                    "http_server_restart_exhausted",
                    host=host,
                    port=port,
                )
```

---

## Summary of Remediation Priority

**Immediate (before any deployment)**:
1. **F-01**: Add `start_new_session=True` and process group kills — prevents unbounded resource leaks
2. **F-02**: Add connection creation lock and explicit transactions — prevents data corruption
3. **F-04**: Route web.py through DatabaseManager — prevents SQLITE_BUSY crashes
4. **F-05**: Add CancelledError handlers to git_ops.py — prevents orphaned processes

**Before GA**:
5. **F-03**: Harden ScopeValidator against symlink TOCTOU — prevents sandbox escape
6. **F-06**: Restrict command configs to an allowlist — prevents arbitrary code execution via config
7. **F-07**: Fail-closed on timezone errors — prevents silent wrong-time execution
8. **F-08**: Add lock to profile counting — prevents chain limit bypass

**Next sprint**:
9. **F-09**: Typed result models — prevents silent runtime key errors
10. **F-10**: Retain task references — prevents GC collection warnings
11. **F-11**: Convert list_snapshots to async — prevents event loop blocking
12. **F-12**: Add HTTP server restart logic — prevents silent observability loss
