# Security Audit — Remaining Action Items

**Reviewer**: Claude Opus 4.6
**Date**: 2026-03-02
**Source**: `security-audit-findings-v1.md` — post-remediation verification
**Scope**: Gaps remaining after Epic 7 hardening pass

---

## Summary

Of the 12 original findings, **9 are fully resolved**, **2 are partially resolved**, and **1 was not addressed**. This document provides copy-paste-ready remediation for each remaining gap.

| Finding | Severity | Status | Gap |
|---------|----------|--------|-----|
| F-01 | CRITICAL | PARTIAL | `git_ops.py` and `snapshot_manager.py` lack `start_new_session` and process group kills |
| F-06 | HIGH | PARTIAL | Missing `shutil.which()` pre-execution check in `profile_executor.py` |
| F-07 | HIGH | MINOR GAP | Secondary `ZoneInfo()` call in `_execute_single_job` unprotected |
| F-09 | HIGH | NOT FIXED | `BrokerResult.result` remains `Optional[dict]` — no typed result models |

---

## Action Item 1: Process Group Kills in Git Modules (F-01)

**Priority**: MUST FIX before deployment
**Risk**: Grandchild process leaks on timeout/cancellation in all git + snapshot operations
**Effort**: ~30 minutes

### Problem

`profile_executor.py` was correctly hardened with `start_new_session=True` and `os.killpg()`. The git modules were not. They still use bare `process.kill()` which only kills the direct child.

**Affected locations:**

| File | Line | Context |
|------|------|---------|
| `git_ops.py` | 20-24 | `create_subprocess_exec` — missing `start_new_session=True` |
| `git_ops.py` | 42 | `process.kill()` in TimeoutError handler |
| `git_ops.py` | 52 | `process.kill()` in CancelledError handler |
| `snapshot_manager.py` | 135, 194, 408, 515, 557, 593, 626, 656, 668 | `create_subprocess_exec` — all missing `start_new_session=True` |
| `snapshot_manager.py` | 153, 213, 426, 533, 568, 604 | `process.kill()` — all should use process group kill |

### Fix for `git_ops.py`

**Step 1** — Add imports at the top of the file:

```python
import os
import signal
import sys
```

**Step 2** — Add the `_kill_process_tree` helper after the imports:

```python
async def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the subprocess and its entire process group."""
    if proc.returncode is not None:
        return
    if sys.platform != "win32":
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    if proc.returncode is None:
        proc.kill()
    await proc.wait()
```

**Step 3** — In `_run_git_command`, add `start_new_session=True` to the subprocess creation:

```python
# Line 20-24: change to:
process = await asyncio.create_subprocess_exec(
    *cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    start_new_session=True,  # ADD THIS
)
```

**Step 4** — Replace both `process.kill()` calls with `_kill_process_tree`:

```python
# Line 41-43 (TimeoutError handler): change to:
except asyncio.TimeoutError as exc:
    await _kill_process_tree(process)
    raise GitCapabilityError(...)

# Line 50-54 (CancelledError handler): change to:
except asyncio.CancelledError:
    if process.returncode is None:
        await _kill_process_tree(process)
    raise
```

### Fix for `snapshot_manager.py`

**Step 1** — Add imports:

```python
import os
import signal
import sys
```

**Step 2** — Add the same `_kill_process_tree` helper to the module (or extract to a shared `src/sohnbot/capabilities/git/_process.py` utility).

**Step 3** — Add `start_new_session=True` to every `create_subprocess_exec` call. There are **9 call sites** at lines: 135, 194, 408, 515, 557, 593, 626, 656, 668.

For each, add the keyword argument:

```python
process = await asyncio.create_subprocess_exec(
    *cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    start_new_session=True,  # ADD THIS
)
```

**Step 4** — Replace every `process.kill()` with `await _kill_process_tree(process)` at lines: 153, 213, 426, 533, 568, 604.

### Recommended Refactor

Extract a shared helper to avoid duplication:

```
src/sohnbot/capabilities/git/_process.py
```

```python
"""Shared subprocess utilities for git capability modules."""

import asyncio
import os
import signal
import sys


async def kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the subprocess and its entire process group.

    On POSIX: sends SIGKILL to the process group (kills grandchildren).
    On Windows: falls back to proc.kill() (Windows has no process groups).
    """
    if proc.returncode is not None:
        return
    if sys.platform != "win32":
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    if proc.returncode is None:
        proc.kill()
    await proc.wait()
```

Then import from both `git_ops.py` and `snapshot_manager.py`:

```python
from ._process import kill_process_tree
```

### Verification

Add a test case in `tests/unit/test_git_ops.py`:

```python
async def test_run_git_command_timeout_kills_process_group(monkeypatch):
    """Verify that timeout uses process group kill, not bare proc.kill()."""
    killed_pgids = []

    def fake_killpg(pgid, sig):
        killed_pgids.append((pgid, sig))

    monkeypatch.setattr(os, "killpg", fake_killpg)
    # ... set up a slow subprocess, trigger timeout, assert killed_pgids is non-empty
```

---

## Action Item 2: `shutil.which()` Pre-Execution Check (F-06)

**Priority**: SHOULD FIX before GA
**Risk**: Misleading error messages if a command in the allowlist isn't installed; marginal security improvement
**Effort**: ~10 minutes

### Problem

`_validate_command()` in `profile_executor.py` correctly validates against `ALLOWED_PROFILE_COMMANDS`, but does not verify the binary actually exists on `PATH` before execution. If a command is in the allowlist but not installed, the user gets a raw `FileNotFoundError` from `create_subprocess_exec` instead of a clear error.

### Fix

In `src/sohnbot/capabilities/command_profiles/profile_executor.py`, add `shutil` import and extend `_validate_command`:

```python
# At the top of the file, add:
import shutil

# Replace _validate_command (lines 37-48) with:
def _validate_command(command: str) -> tuple[bool, str]:
    """Validate command binary against safe allowlist, traversal checks, and PATH availability."""
    stripped = (command or "").strip()
    if not stripped:
        return False, "Command must not be empty"

    binary = stripped.split()[0]
    if "/" in binary or "\\" in binary or ".." in binary:
        return False, "Command binary must not contain path separators or traversal tokens"
    if binary not in ALLOWED_PROFILE_COMMANDS:
        return False, f"Command '{binary}' is not in the allowed profile command list"

    # Verify the binary is actually installed and on PATH
    resolved = shutil.which(binary)
    if resolved is None:
        return False, f"Command '{binary}' is in the allowlist but was not found on PATH"

    return True, ""
```

### Verification

Add a test in `tests/unit/test_profile_executor.py`:

```python
def test_validate_command_rejects_missing_binary(monkeypatch):
    """Allowlisted command not on PATH should fail validation."""
    monkeypatch.setattr(shutil, "which", lambda _: None)
    valid, msg = _validate_command("ruff")
    assert not valid
    assert "not found on PATH" in msg
```

---

## Action Item 3: Secondary ZoneInfo Guard in Scheduler (F-07)

**Priority**: SHOULD FIX before GA
**Risk**: If a job's timezone becomes invalid mid-execution (e.g., corrupted DB value), the outer `except Exception` at line ~383 catches it but doesn't produce a clean skip+notify like the primary guard at line 96-135
**Effort**: ~5 minutes

### Problem

In `src/sohnbot/capabilities/scheduler/executor.py`, `_execute_single_job()` at line 287:

```python
job_tz_name = str(job.get("timezone") or "UTC")
job_now = _utc_now().astimezone(ZoneInfo(job_tz_name))  # <-- unprotected
```

This is the *second* place `ZoneInfo` is instantiated for the same job. The first (at line ~96) has proper fail-closed handling. This one relies on the assumption that if it passed the first check, it'll pass here too — but they're in different functions with different `job` dict instances.

### Fix

Wrap the call in a try/except consistent with the primary guard:

```python
# In _execute_single_job(), lines 286-287, replace with:
job_tz_name = str(job.get("timezone") or "UTC")
try:
    job_now = _utc_now().astimezone(ZoneInfo(job_tz_name))
except (KeyError, Exception) as exc:
    logger.error(
        "scheduler_job_timezone_failed",
        timezone=job_tz_name,
        job_name=job.get("name"),
        error=str(exc),
    )
    await log_operation_end(
        operation_id=operation_id,
        status="failed",
        duration_ms=int((time.perf_counter() - started) * 1000),
        error_details={"message": f"Invalid timezone in execution: {job_tz_name}"},
    )
    return
```

---

## Action Item 4: Typed Capability Result Models (F-09)

**Priority**: NICE TO HAVE (next sprint)
**Risk**: Silent runtime key errors if a capability function renames a return field; all consumers use untyped `.get()` access
**Effort**: ~2-3 hours

### Problem

Every capability function returns `dict[str, Any]`. `BrokerResult.result` is `Optional[dict]`. The MCP tools layer accesses keys like `result.get("passed")`, `result.get("exit_code")`, `result.get("commit_hash")` with zero compile-time guarantees.

### Fix

**Step 1** — Create `src/sohnbot/capabilities/result_types.py`:

```python
"""Typed result models for capability operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union


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


@dataclass(frozen=True, slots=True)
class RipgrepProfileResult(ProfileResult):
    query: str


@dataclass(frozen=True, slots=True)
class GitStatusResult:
    branch: str
    ahead: int
    behind: int
    staged: list[dict[str, str]]
    unstaged: list[dict[str, str]]
    untracked: list[str]


@dataclass(frozen=True, slots=True)
class GitDiffResult:
    diff_text: str
    mode: str
    file_count: int


@dataclass(frozen=True, slots=True)
class GitCommitResult:
    commit_hash: str
    message: str
    snapshot_ref: str | None


@dataclass(frozen=True, slots=True)
class FileReadResult:
    content: str
    path: str
    size_bytes: int
    encoding: str


@dataclass(frozen=True, slots=True)
class FileListResult:
    files: list[dict[str, Any]]
    total_count: int
    directory: str


@dataclass(frozen=True, slots=True)
class FileSearchResult:
    matches: list[dict[str, Any]]
    query: str
    total_matches: int


@dataclass(frozen=True, slots=True)
class PatchResult:
    patched_path: str
    hunks_applied: int
    snapshot_ref: str | None


@dataclass(frozen=True, slots=True)
class WebSearchResult:
    query: str
    results: list[dict[str, Any]]
    cached: bool


@dataclass(frozen=True, slots=True)
class SchedulerJobResult:
    job_id: str
    action: str
    status: str


@dataclass(frozen=True, slots=True)
class RollbackResult:
    snapshot_ref: str
    commit_hash: str
    files_restored: int


# Union of all possible results
CapabilityResult = Union[
    LintProfileResult,
    TestProfileResult,
    BuildProfileResult,
    RipgrepProfileResult,
    GitStatusResult,
    GitDiffResult,
    GitCommitResult,
    FileReadResult,
    FileListResult,
    FileSearchResult,
    PatchResult,
    WebSearchResult,
    SchedulerJobResult,
    RollbackResult,
]
```

**Step 2** — Update `BrokerResult` in `src/sohnbot/broker/router.py`:

```python
from ..capabilities.result_types import CapabilityResult

@dataclass
class BrokerResult:
    """Result of broker policy decision and operation execution."""
    allowed: bool
    operation_id: str
    tier: Optional[int] = None
    snapshot_ref: Optional[str] = None
    error: Optional[dict] = None
    result: Optional[CapabilityResult] = None
```

**Step 3** — Update each capability function to return the typed dataclass instead of a raw dict. For example, in `profile_executor.py:execute_lint_profile`:

```python
# Replace the return dict at line 172-179 with:
from ..result_types import LintProfileResult

return LintProfileResult(
    passed=passed,
    exit_code=exit_code,
    stdout=stdout_bytes.decode("utf-8", errors="replace"),
    stderr=stderr_bytes.decode("utf-8", errors="replace"),
    command_used=command,
    files_linted=files,
)
```

**Step 4** — Update `mcp_tools.py` to use attribute access (`.passed`) instead of `.get("passed")`.

**Step 5** — For backward compatibility during migration, add a `.to_dict()` method to the base:

```python
@dataclass(frozen=True, slots=True)
class ProfileResult:
    # ... fields ...

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)
```

### Verification

Run `mypy src/sohnbot/` — any `.get()` call on a typed result will now produce a type error, catching mismatches at lint time rather than runtime.

---

## Checklist

- [ ] **Action 1**: Process group kills in `git_ops.py` + `snapshot_manager.py` — **MUST** before deploy
- [ ] **Action 2**: `shutil.which()` in `profile_executor.py` — **SHOULD** before GA
- [ ] **Action 3**: Secondary ZoneInfo guard in `executor.py` — **SHOULD** before GA
- [ ] **Action 4**: Typed result models + BrokerResult update — **NICE TO HAVE** next sprint
