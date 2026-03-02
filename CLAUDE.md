# CLAUDE.md - AI Assistant Guidelines for SohnBot

This document provides architectural invariants, security guidelines, and development patterns for AI assistants working on the SohnBot codebase.

## Project Overview

SohnBot is a policy-enforced local autonomous execution system with Telegram interface. All operations route through a central broker layer that enforces safety boundaries and operation policies.

**Architecture:** Broker-centric with capability modules, persistence layer, and Telegram gateway.

## Critical Architectural Invariants

### 1. Regex Pattern Safety (A-05 Resolution)

**INVARIANT:** User-facing search MUST route through ripgrep; Python `re` module is permitted only for constant internal patterns on controlled inputs.

**Rationale:**
- Ripgrep has built-in catastrophic backtracking protection
- User-supplied patterns are never compiled as Python regex
- All `re.compile()` uses in the codebase are pre-compiled constants on internal data

**Permitted `re` usage:**
- `web.py` — HTML tag stripping with constant pattern
- `registry.py` — Command validation with constant pattern
- `git_ops.py` — Branch name validation with constant pattern
- `patch_editor.py` — Diff hunk parsing with constant pattern

**Prohibited:**
- `re.compile(user_input)` — NEVER compile user-supplied strings as regex
- `re.search(user_pattern, ...)` — User patterns must go through ripgrep

**Implementation:** User search requests route through `capabilities/command_profiles/profile_executor.py:execute_ripgrep_profile()` which delegates to the `rg` CLI.

### 2. Scope Validation (F-03 Resolution)

**INVARIANT:** All file paths MUST be validated through `ScopeValidator` before any I/O operation.

**Two-phase validation:**
1. **Initial validation** in broker router before operation routing
2. **Boundary re-validation** immediately before I/O (TOCTOU mitigation)

**Implementation:**
- `broker/scope_validator.py` — Uses `os.path.realpath()` to resolve symlinks
- `capabilities/files/file_ops.py` — Re-validates at I/O boundary
- `capabilities/files/patch_editor.py` — Re-validates before write

**Critical:** The race window is reduced to microseconds but not eliminated. Full TOCTOU elimination requires `O_NOFOLLOW` at syscall level (deferred to Phase 3).

### 3. Subprocess Lifecycle (F-01, F-05 Resolution)

**INVARIANT:** All subprocesses MUST use `asyncio.create_subprocess_exec` with proper cleanup.

**Process group termination (POSIX):**
- Use `start_new_session=True` to create process groups
- Kill entire group with `os.killpg(os.getpgid(proc.pid), signal.SIGTERM)`
- Fallback to SIGKILL after grace period (0.5s)

**CancelledError handling:**
```python
except asyncio.CancelledError:
    if process.returncode is None:
        process.kill()
        await process.wait()
    raise  # MUST re-raise
```

**Implementation:**
- `capabilities/command_profiles/profile_executor.py` — Process group termination helper
- `capabilities/git/git_ops.py` — CancelledError cleanup in `_run_git_command`

### 4. Database Concurrency (F-02, F-04 Resolution)

**INVARIANT:** All database writes MUST use `DatabaseManager.execute_write()` with write lock.

**Write serialization:**
- `asyncio.Lock` prevents concurrent writes to SQLite
- `BEGIN IMMEDIATE` acquires RESERVED lock immediately
- WAL mode allows concurrent reads

**Implementation:**
```python
async with self._write_lock:
    await conn.execute("BEGIN IMMEDIATE")
    # ... write operations ...
    await conn.commit()
```

**Location:** `persistence/db.py:DatabaseManager.execute_write()`

### 5. Configuration System (A-01, A-10 Resolution)

**INVARIANT:** Dynamic config changes MUST persist to the `config` table in SQLite.

**Two-tier system:**
- **Static tier:** Requires restart (database path, scope roots, observability host)
- **Dynamic tier:** Hot-reloadable with persistence (timeouts, thresholds, logging level)

**Implementation:**
- `config/manager.py` — `update_dynamic_config()` calls `_persist_to_database()`
- `persistence/migrations/0008_widen_jobs_action_check.sql` — Schema support
- Persisted values override TOML defaults on restart

### 6. Correlation ID Tracing (A-08 Resolution)

**INVARIANT:** Every Telegram-initiated request MUST have a correlation_id for operation chain traceability.

**Lifecycle:**
1. Generated in `gateway/telegram_client.py:handle_message()` as `uuid4()`
2. Bound to structlog context via `bind_contextvars(correlation_id=...)`
3. Stored in `execution_log` table via `persistence/audit.py:log_operation_start()`
4. Displayed in `/logs` output (first 8 chars)
5. Unbound in finally block

**Scheduler operations:** Use `correlation_id = f"scheduler-{job_name}-{slot}"`

### 7. Telegram Rate Limiting (A-04 Resolution)

**INVARIANT:** All outbound Telegram messages MUST respect the configured rate limit.

**Sliding-window token bucket:**
- Default: 30 messages per minute
- Configurable via `telegram.max_messages_per_minute`
- Blocks caller until token available (no message dropping)

**Implementation:** `gateway/rate_limiter.py:RateLimiter` integrated into `TelegramClient.send_message()`

### 8. Command Profile Safety (F-06 Resolution)

**INVARIANT:** Command profile executables MUST be allowlisted; path separators and traversal are forbidden.

**Allowlist (in `profile_executor.py`):**
```python
ALLOWED_PROFILE_COMMANDS = frozenset({
    "pylint", "flake8", "ruff", "eslint", "mypy", "black", "isort",
    "pytest", "python", "npm", "npx", "node", "make", "cargo", "go",
    "rg", "tsc", "prettier", "biome",
})
```

**Validation:**
- Reject if command contains `/`, `\`, or `..`
- Reject if base command not in allowlist
- Log rejection as security event

## Development Patterns

### Error Handling

**Structured errors:** Use capability-specific error classes (e.g., `FileCapabilityError`, `GitCapabilityError`) with:
- `code` — Machine-readable error code
- `message` — Human-readable description
- `details` — Context dict for debugging
- `retryable` — Boolean indicating if operation can be retried

### Async Task Management

**Background task retention:**
```python
_background_tasks: set[asyncio.Task] = set()

task = asyncio.create_task(some_coroutine(), name="task-name")
_background_tasks.add(task)
task.add_done_callback(_background_tasks.discard)
```

**Prevents:** "Task was destroyed but it is pending" warnings

### Testing Patterns

**Unit tests:**
- Mock external dependencies (git, ripgrep, Telegram API)
- Use `pytest.mark.asyncio` for async tests
- Platform-specific tests: `@pytest.mark.skipif(sys.platform == "win32")`

**Integration tests:**
- Use temporary SQLite databases
- Clean up temp files in finally blocks
- Test boundary conditions (scope violations, timeouts, concurrency)

## Security Checklist

Before merging security-sensitive changes:

- [ ] All file paths validated through `ScopeValidator`
- [ ] No user input compiled as regex patterns
- [ ] Subprocess cleanup handles CancelledError
- [ ] Database writes use `execute_write()` with lock
- [ ] Command executables validated against allowlist
- [ ] No secrets logged or stored in plaintext
- [ ] Rate limiting applied to external API calls
- [ ] Error messages don't leak system paths

## Runtime Dependencies

**Required at runtime (must be in PATH):**
- `git` 2.x+ — Snapshot branch creation
- `rg` (ripgrep) — File search operations

**Missing dependency behavior:**
- Operations fail with clear error messages
- Health checks report dependency status
- Observability `/health` endpoint shows availability

## Configuration Guidelines

**Static config (requires restart):**
- Database path
- Scope allowed roots
- Observability HTTP host/port
- Telegram bot token
- API keys

**Dynamic config (hot-reloadable):**
- Timeouts
- Logging level
- Thresholds (search volume, retry counts)
- Scheduler tick interval

**Validation:** All config changes validated against `config/registry.py` constraints (type, min/max, custom validators)

## Traceability

**Epic 7 (Security Hardening) addressed:**
- 4 CRITICAL findings (database, TOCTOU, subprocess, config)
- 5 HIGH findings (CancelledError, command injection, timezone, concurrency, acknowledgment)
- 3 MEDIUM findings (task orphans, blocking calls, HTTP crash, correlation ID)

**Documentation:**
- `_bmad-output/implementation-artifacts/security-audit-findings-v1.md` — Original audit
- `_bmad-output/implementation-artifacts/epic-7-security-hardening-spec-compliance.md` — Epic spec
- Stories 7.1 through 7.7 — Implementation details

---

**Last Updated:** 2026-03-02
**Epic:** 7 (Security Hardening & Specification Compliance)
