# Story 5.2: Build Project Profile

Status: done

## Story

As a user,
I want to execute project build command,
so that I can verify builds succeed before committing.

## Acceptance Criteria

1. **Given** a project with a build command configured (e.g., `make`, `npm run build`, `cargo build`)
   **When** I request build execution via `profiles__build` MCP tool
   **Then** the build command runs with an optional target argument
   **And** timeout is enforced at 300 seconds (5 minutes)

2. **Given** build execution completes (success or failure)
   **When** results are returned from the capability
   **Then** stdout, stderr, exit code, and a boolean `passed` flag are included in the result

3. **Given** build execution completes
   **When** result is processed by the broker
   **Then** operation is logged as Tier 0 (read-only) — no snapshot is created

4. **Given** build execution completes
   **When** broker routes the result through the notification system
   **Then** a Telegram notification summarizes the build outcome (passed/failed, exit code)

5. **Given** a `repo_path` is provided to the tool
   **When** the broker validates the request
   **Then** `repo_path` is validated against configured scope roots before subprocess spawning

6. **Given** an optional `target` argument is provided
   **When** the broker validates the request
   **Then** `target` is checked for shell metacharacters and rejected if unsafe

## Tasks / Subtasks

- [x] Task 1: Add `execute_build_profile` to capability module (AC: 1, 2)
  - [x] 1.1 Add `execute_build_profile(repo_path, command, target, timeout_seconds)` to `src/sohnbot/capabilities/command_profiles/profile_executor.py` — follow the same `asyncio.create_subprocess_exec` pattern as `execute_lint_profile`, but accept an optional `target: str` instead of `files: list`
  - [x] 1.2 Return structured dict: `{passed, exit_code, stdout, stderr, command_used, target}`
  - [x] 1.3 Implement 300s timeout using `asyncio.timeout()`, kill + `await proc.wait()` on timeout (no zombie processes — same fix as Story 5.1 H1)
  - [x] 1.4 Export `execute_build_profile` from `src/sohnbot/capabilities/command_profiles/__init__.py`

- [x] Task 2: Add config keys for build command (AC: 1)
  - [x] 2.1 Add `_validate_build_command(value: str) -> bool` validator function to `src/sohnbot/config/registry.py` — same metacharacter rejection logic as `_validate_lint_command` (reuse `_SAFE_COMMAND_RE`)
  - [x] 2.2 Add `"commands.build_command"` ConfigKey to `REGISTRY` in `src/sohnbot/config/registry.py` (dynamic, str, default `"make"`, validator=`_validate_build_command`)
  - [x] 2.3 Add `build_command = "make"` under `[commands]` section in `config/default.toml` (after `lint_timeout_seconds`, before `build_timeout_seconds`)

- [x] Task 3: Add `("profiles", "build")` to Tier 0 in operation classifier (AC: 3)
  - [x] 3.1 Add `("profiles", "build"),  # Read-only execution` to `READ_ONLY_ACTIONS` set in `src/sohnbot/broker/operation_classifier.py` (after `("profiles", "lint")`)

- [x] Task 4: Extend profiles validation in Broker Router (AC: 5, 6)
  - [x] 4.1 In `src/sohnbot/broker/router.py`, extend the `if capability == "profiles":` validation block (around line 409): change `if action == "lint" and "repo_path" not in params:` to also cover `action == "build"` (use `if action in {"lint", "build"} and "repo_path" not in params:`)
  - [x] 4.2 After scope validation, add a `target` validation block: if `params.get("target")` is not None or empty, validate it with `_SAFE_COMMAND_RE` (import at top of method or inline); reject with `invalid_request` if unsafe characters detected

- [x] Task 5: Wire `profiles/build` into Broker `_execute_capability` (AC: 1, 2, 3)
  - [x] 5.1 In `src/sohnbot/broker/router.py`, inside the `if capability == "profiles":` block in `_execute_capability()`, add an `if action == "build":` branch after the existing `if action == "lint":` branch
  - [x] 5.2 Import `execute_build_profile` from `..capabilities.command_profiles`
  - [x] 5.3 Pull `commands.build_command` and `commands.build_timeout_seconds` from `config_manager.get()` (with `"make"` and `300` as fallbacks)
  - [x] 5.4 Call `execute_build_profile(repo_path=..., command=..., target=..., timeout_seconds=int(timeout))`

- [x] Task 6: Extend notification formatter for build profile (AC: 4)
  - [x] 6.1 In `src/sohnbot/broker/router.py`, add `elif capability == "profiles" and action == "build" and status == "completed":` case in `_format_notification_message()` (immediately after the existing lint case)
  - [x] 6.2 Format: `"✅ PASSED Build profile | exit_code=0 | repo=..."` or `"❌ FAILED Build profile | exit_code=1 | repo=..."`

- [x] Task 7: Implement `profiles__build` MCP tool (AC: 1, 5)
  - [x] 7.1 Add `@tool("profiles__build", "Run project build command", {"repo_path": str, "target": str})` in `src/sohnbot/runtime/mcp_tools.py` immediately after the `profiles__lint` tool definition
  - [x] 7.2 Accept params: `repo_path: str`, `target: str` (optional, empty = no explicit target)
  - [x] 7.3 Route through `broker.route_operation(capability="profiles", action="build", params=..., chat_id=chat_id)`
  - [x] 7.4 On success: return `"{status} (exit {exit_code})\n{stdout+stderr combined, truncated to 2000 chars}"` — same combined output pattern as `profiles__lint` (Story 5.1 M1 fix)
  - [x] 7.5 Register `profiles_build` in the `tools=[...]` list immediately after `profiles_lint`

- [x] Task 8: Tests (AC: 1, 2, 3, 4, 5, 6)
  - [x] 8.1 Add `execute_build_profile` unit tests in `tests/unit/test_profile_executor.py` — success, failure, timeout (assert `await proc.wait()` called on timeout), optional target included in command
  - [x] 8.2 Add `profiles__build` tests in `tests/unit/test_mcp_tools.py` — mock broker, verify tool schema and routing, test with and without target
  - [x] 8.3 Add broker tests in `tests/unit/test_broker.py` — missing repo_path, empty repo_path, out-of-scope repo_path, unsafe target, and success routing for `("profiles", "build")`
  - [x] 8.4 Add `classify_tier("profiles", "build", 0) == 0` test in `tests/unit/test_broker.py`

## Dev Notes

### Architecture Path — IMPORTANT

The epics file says: `Updates: src/sohnbot/capabilities/profiles.py (execute_build_profile)`
The architecture spec says: `src/sohnbot/capabilities/command_profiles/`
**Resolution: Follow the architecture — same correction as Story 5.1.**

The actual files to touch are:
- `src/sohnbot/capabilities/command_profiles/profile_executor.py` — add `execute_build_profile`
- `src/sohnbot/capabilities/command_profiles/__init__.py` — export `execute_build_profile`

Do NOT create a top-level `src/sohnbot/capabilities/profiles.py`.

### `execute_build_profile` Implementation Pattern

Follow the exact same pattern as `execute_lint_profile` in `profile_executor.py`. Key differences:
- Parameter is `target: str` (single optional target) instead of `files: list[str]`
- Default timeout is `300` seconds instead of `60`
- Return dict key is `target` instead of `files_linted`
- Log events: `"build_profile_started"`, `"build_profile_timeout"`, `"build_profile_completed"`

```python
async def execute_build_profile(
    repo_path: str,
    command: str,
    target: str,
    timeout_seconds: int = 300,
) -> dict:
    """Run a build command as a subprocess with timeout enforcement.

    Args:
        repo_path: Working directory for the subprocess (project root).
        command: Build command string, e.g. "make" or "npm run build".
                 Multi-word strings are split on whitespace.
        target: Optional build target appended after the command (e.g. "dist", "all").
                Empty string means no explicit target.
        timeout_seconds: Hard kill timeout in seconds (default 300).

    Returns:
        dict with keys:
            passed (bool): True iff exit_code == 0
            exit_code (int): Subprocess return code
            stdout (str): Decoded standard output
            stderr (str): Decoded standard error
            command_used (str): The command string that was executed
            target (str): The build target that was passed

    Raises:
        TimeoutError: When subprocess exceeds timeout_seconds; process is killed.
    """
    cmd_parts = command.split()
    if target:
        cmd_parts.append(target)

    logger.info(
        "build_profile_started",
        repo_path=repo_path,
        cmd_parts=cmd_parts,
        timeout_seconds=timeout_seconds,
    )

    proc: asyncio.subprocess.Process | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_path,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()

    except TimeoutError:
        if proc is not None:
            proc.kill()
            await proc.wait()  # CRITICAL: prevent zombie processes (Story 5.1 H1 fix)
        logger.warning(
            "build_profile_timeout",
            repo_path=repo_path,
            timeout_seconds=timeout_seconds,
        )
        raise

    exit_code = proc.returncode
    passed = exit_code == 0

    logger.info(
        "build_profile_completed",
        repo_path=repo_path,
        exit_code=exit_code,
        passed=passed,
    )

    return {
        "passed": passed,
        "exit_code": exit_code,
        "stdout": stdout_bytes.decode("utf-8", errors="replace"),
        "stderr": stderr_bytes.decode("utf-8", errors="replace"),
        "command_used": command,
        "target": target,
    }
```

**Do NOT use `subprocess.run()` or `shell=True`** — asyncio subprocess keeps the event loop non-blocking and prevents shell injection.

### Config Keys

**Already in registry.py and default.toml (NO changes needed):**
- `commands.build_timeout_seconds` — default `300`, dynamic, range `60–1800`
  [Source: `src/sohnbot/config/registry.py:225-231`, `config/default.toml:77`]

**Must be ADDED by this story:**
- `commands.build_command` — default `"make"`, dynamic, type `str`, with security validator
  - Registry: add after `"commands.lint_command"` entry (~line 217)
  - TOML: add `build_command = "make"` under `[commands]` section after `lint_timeout_seconds`

**Validator pattern** (copy/adapt from `_validate_lint_command`):
```python
def _validate_build_command(value: str) -> bool:
    """Reject empty strings and shell metacharacters in build command."""
    if not value or not value.strip():
        raise ValueError("build_command must not be empty")
    if not _SAFE_COMMAND_RE.match(value):
        raise ValueError(
            "build_command contains disallowed characters; "
            "use alphanumeric, spaces, dashes, underscores, dots, and slashes only"
        )
    return True
```

`_SAFE_COMMAND_RE` is already defined at `src/sohnbot/config/registry.py:26` — reuse it.

### Tier 0 Classification — Must Add

`("profiles", "build")` is NOT yet in `READ_ONLY_ACTIONS` in `operation_classifier.py`. This MUST be added or the broker will classify it as Tier 2 (multi-file modification) which will trigger a snapshot creation.

[Source: `src/sohnbot/broker/operation_classifier.py:34`]
```python
READ_ONLY_ACTIONS = {
    ...
    ("profiles", "lint"),  # Read-only execution  ← already exists
    ("profiles", "build"),  # Read-only execution  ← MUST ADD
}
```

### Broker Validation Block Extension

In `src/sohnbot/broker/router.py` at line ~410, the current check is:
```python
if action == "lint" and "repo_path" not in params:
```

Change to:
```python
if action in {"lint", "build"} and "repo_path" not in params:
```

The rest of the validation block (empty repo_path check, scope validation, files traversal check) applies to all profiles actions and does NOT need modification for `action == "build"`.

**However**, add a `target` validation after the existing validation block:
```python
target = params.get("target") or ""
if target and not _SAFE_COMMAND_RE.match(target):
    self._operation_start_times.pop(operation_id, None)
    return BrokerResult(
        allowed=False,
        operation_id=operation_id,
        tier=tier,
        error={
            "code": "invalid_request",
            "message": "target contains disallowed characters",
            "details": {"target": target},
            "retryable": False,
        },
    )
```

Note: `_SAFE_COMMAND_RE` lives in `registry.py`, not in `router.py`. Import it at the top of the validation block or use an inline pattern. Prefer importing from registry: `from ..config.registry import _SAFE_COMMAND_RE` (if that's not already imported). Alternatively, define the same inline regex `re.compile(r'^[a-zA-Z0-9_./-][\w ./_-]*$')`.

### Broker `_execute_capability` Addition

In `router.py`, inside `if capability == "profiles":` block (~line 875), add after the lint block:
```python
if action == "build":
    from ..capabilities.command_profiles import execute_build_profile
    command = (
        self.config_manager.get("commands.build_command")
        if self.config_manager
        else "make"
    )
    timeout = (
        self.config_manager.get("commands.build_timeout_seconds")
        if self.config_manager
        else 300
    )
    return await execute_build_profile(
        repo_path=params["repo_path"],
        command=command,
        target=params.get("target") or "",
        timeout_seconds=int(timeout),
    )
```

### Notification Formatter

In `_format_notification_message()` in `router.py` (~line 906), add after the lint case:
```python
if capability == "profiles" and action == "build" and status == "completed":
    data = result or {}
    passed = "✅ PASSED" if data.get("passed") else "❌ FAILED"
    exit_code = data.get("exit_code", "?")
    repo = params.get("repo_path", "-")
    return f"{passed} Build profile | exit_code={exit_code} | repo={repo}"
```

### MCP Tool Pattern

```python
@tool("profiles__build", "Run project build command", {"repo_path": str, "target": str})
async def profiles_build(args):
    """Run build profile via broker."""
    ctx = get_contextvars()
    chat_id = ctx.get("chat_id", "unknown")
    repo_path = args.get("repo_path")
    target = args.get("target") or ""
    logger.info(
        "mcp_tool_invoked",
        tool="profiles__build",
        repo_path=repo_path,
        chat_id=chat_id,
    )

    result = await broker.route_operation(
        capability="profiles",
        action="build",
        params={"repo_path": repo_path, "target": target},
        chat_id=chat_id,
    )

    if not result.allowed:
        error_msg = (result.error or {}).get("message", "Operation denied")
        logger.warning("mcp_tool_denied", tool="profiles__build", error=error_msg)
        return _as_mcp_text(f"❌ Build denied: {error_msg}")

    data = result.result or {}
    status = "✅ PASSED" if data.get("passed") else "❌ FAILED"
    exit_code = data.get("exit_code", "?")
    stdout = data.get("stdout", "")
    stderr = data.get("stderr", "")
    output = "\n".join(part for part in (stdout, stderr) if part)
    return _as_mcp_text(f"{status} (exit {exit_code})\n{output[:2000]}")
```

Register `profiles_build` in `tools=[...]` immediately after `profiles_lint` (~line 736).

### No Snapshot Required

Tier 0 operations skip snapshot creation. Once `("profiles", "build")` is in `READ_ONLY_ACTIONS`, the `tier == 0` result means the snapshot block in `route_operation()` is never entered. No other changes needed.

### Project Structure Notes

- `src/sohnbot/capabilities/command_profiles/profile_executor.py` — **ADD** `execute_build_profile` function (do NOT create a separate file; both lint and build live here)
- `src/sohnbot/capabilities/command_profiles/__init__.py` — **MODIFY**: add `execute_build_profile` to import and `__all__`
- `src/sohnbot/broker/operation_classifier.py:34` — **MODIFY**: add `("profiles", "build")` to `READ_ONLY_ACTIONS`
- `src/sohnbot/broker/router.py:410` — **MODIFY**: extend `action == "lint"` check to `action in {"lint", "build"}`
- `src/sohnbot/broker/router.py:~470` — **MODIFY**: add `target` validation after existing files traversal check
- `src/sohnbot/broker/router.py:875–893` — **MODIFY**: add `if action == "build":` block inside profiles `_execute_capability`
- `src/sohnbot/broker/router.py:906–911` — **MODIFY**: add build case in `_format_notification_message`
- `src/sohnbot/runtime/mcp_tools.py:630` — **ADD** `profiles__build` tool definition after `profiles__lint`
- `src/sohnbot/runtime/mcp_tools.py:736` — **MODIFY**: add `profiles_build` to `tools=[...]` list
- `src/sohnbot/config/registry.py:26` — reuse `_SAFE_COMMAND_RE` (already defined, no change)
- `src/sohnbot/config/registry.py:~29` — **ADD** `_validate_build_command` validator function
- `src/sohnbot/config/registry.py:~217` — **ADD** `"commands.build_command"` ConfigKey to REGISTRY
- `config/default.toml:75` — **MODIFY** [commands] section: add `build_command = "make"`
- `tests/unit/test_profile_executor.py` — **MODIFY**: add build profile unit tests
- `tests/unit/test_mcp_tools.py` — **MODIFY**: add `profiles__build` tests
- `tests/unit/test_broker.py` — **MODIFY**: add broker validation + tier classification tests

### Previous Story Intelligence (Story 5.1)

**Critical fixes from Story 5.1 that MUST carry forward:**
- **H1 (Zombie Process):** After `proc.kill()`, always call `await proc.wait()` to reap the process. This is already in the code template above.
- **H2 (Security Validator):** `lint_command` has `_validate_lint_command` rejecting metacharacters. Build command MUST have an equivalent `_validate_build_command`. Do NOT skip this.
- **H3 (Path Traversal):** Story 5.1 validates `files` list items for `..` traversal. Build uses a `target` string, not a file list — the `_SAFE_COMMAND_RE` validation for `target` is the equivalent safeguard.
- **M1 (Combined Output):** MCP tool must combine `stdout + stderr` in response, not use `stdout or stderr`. The template above already does this.
- **M2 (Empty repo_path):** Empty string for `repo_path` must be rejected before scope check. Already handled by the existing empty-check block in the profiles validation section.
- **M3 (Integration Tests):** Broker integration tests are required: missing repo_path, empty repo_path, out-of-scope, unsafe target, and success routing.

**Patterns established in Story 5.1 to follow consistently:**
- `profile_executor.py` holds all profile execution functions (lint AND build go here)
- `__init__.py` exports only — no logic in `__init__.py`
- Broker router profiles block uses lazy imports (`from ..capabilities.command_profiles import ...` inside the if-block)
- MCP tool function name is snake_case (`profiles_build`), decorator name is dunder-style (`"profiles__build"`)
- Tier 0 means NO snapshot, NO file count, operation logged as read-only

**Files created/modified by Story 5.1:**
- `src/sohnbot/capabilities/command_profiles/profile_executor.py` (created)
- `src/sohnbot/capabilities/command_profiles/__init__.py` (modified)
- `src/sohnbot/broker/router.py` (modified)
- `src/sohnbot/runtime/mcp_tools.py` (modified)
- `src/sohnbot/config/registry.py` (modified)
- `config/default.toml` (modified)
- `tests/unit/test_profile_executor.py` (created)
- `tests/unit/test_mcp_tools.py` (modified)
- `tests/unit/test_broker.py` (modified)

**Pre-existing failing test to be aware of:**
- `test_config_manager.py::test_static_config_validation` fails with a regex mismatch — this is pre-existing, NOT introduced by this story. Do not "fix" it as part of this story.

### References

- Epic 5 story 5.2 definition: [Source: `_bmad-output/planning-artifacts/epics.md:1057-1078`]
- Architecture command_profiles module: [Source: `_bmad-output/planning-artifacts/architecture.md:221`]
- Tier classification READ_ONLY_ACTIONS: [Source: `src/sohnbot/broker/operation_classifier.py:25-35`]
- Existing _validate_lint_command pattern: [Source: `src/sohnbot/config/registry.py:26-38`]
- Existing commands.build_timeout_seconds registry entry: [Source: `src/sohnbot/config/registry.py:225-231`]
- Existing commands config in default.toml: [Source: `config/default.toml:73-79`]
- Profiles validation block (lint as model): [Source: `src/sohnbot/broker/router.py:408-484`]
- Profiles _execute_capability block (lint as model): [Source: `src/sohnbot/broker/router.py:875-893`]
- Profiles notification format (lint as model): [Source: `src/sohnbot/broker/router.py:906-911`]
- profiles__lint MCP tool (model): [Source: `src/sohnbot/runtime/mcp_tools.py:597-629`]
- tools=[...] list: [Source: `src/sohnbot/runtime/mcp_tools.py:715-739`]
- execute_lint_profile function (model): [Source: `src/sohnbot/capabilities/command_profiles/profile_executor.py:9-85`]
- command_profiles __init__.py: [Source: `src/sohnbot/capabilities/command_profiles/__init__.py`]

## Senior Developer Review (AI)

**Review Date:** 2026-03-01
**Outcome:** Changes Requested → Fixed

### Action Items (all resolved)

- [x] [High] Zombie process risk: CancelledError in execute_build_profile (and execute_lint_profile) bypassed the proc.kill()/wait() cleanup when outer broker timeout fires first — added `except asyncio.CancelledError:` handler with `asyncio.shield(proc.wait())` to both functions [`profile_executor.py`]
- [x] [Medium] Inline regex `_re.compile(...)` recompiled on every route_operation call with non-empty target — replaced with module-level import of `_SAFE_COMMAND_RE` from registry (alias `_SAFE_PROFILE_RE`) [`router.py`]
- [x] [Medium] AC4 (Telegram notification) had no unit test — `_format_notification_message` for build/passed and build/failed untested — added `test_format_notification_build_passed` and `test_format_notification_build_failed` [`test_broker.py`]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

- Implemented `execute_build_profile` using `asyncio.create_subprocess_exec` (not `shell=True`) with `asyncio.timeout()` for hard kill on timeout
- `await proc.wait()` called after `proc.kill()` to prevent zombie processes (Story 5.1 H1 lesson carried forward)
- `commands.build_command` (dynamic, default `"make"`) added to registry with `_validate_build_command` security validator (Story 5.1 H2 lesson carried forward)
- `commands.build_timeout_seconds` was already in registry (default 300) and default.toml — no change needed
- `("profiles", "build")` added to `READ_ONLY_ACTIONS` in operation_classifier.py — Tier 0 (no snapshot)
- Broker router extended: `action in {"lint", "build"}` for missing repo_path check; `target` validated against `_SAFE_COMMAND_RE` inline (Story 5.1 H3 lesson adapted for target string)
- `profiles/build` `_execute_capability` block added after lint block with lazy import of `execute_build_profile`
- `_format_notification_message` extended with profiles/build case: `"✅ PASSED Build profile | exit_code=... | repo=..."`
- `profiles__build` MCP tool registered with `{"repo_path": str, "target": str}` schema; stdout+stderr combined in response (Story 5.1 M1 lesson)
- 7 new unit tests in `test_profile_executor.py` for `TestExecuteBuildProfile`
- 3 new tests in `test_mcp_tools.py` for `profiles__build` (schema, routing, denial)
- 6 new broker tests in `test_broker.py` (Tier 0 classification, missing/empty repo_path, out-of-scope, unsafe target, success routing)
- `mcp__sohnbot__profiles__build` added to allowed tools list in `test_mcp_tools.py`
- Pre-existing failing test `test_config_manager.py::test_static_config_validation` (regex mismatch) confirmed pre-existing, NOT introduced by this story
- Final test run: 80 passed, 1 skipped, 1 pre-existing failure — all 80 passing tests green

### File List

- `src/sohnbot/capabilities/command_profiles/profile_executor.py` (modified — added `execute_build_profile` function)
- `src/sohnbot/capabilities/command_profiles/__init__.py` (modified — added `execute_build_profile` to imports and `__all__`)
- `src/sohnbot/broker/operation_classifier.py` (modified — added `("profiles", "build")` to `READ_ONLY_ACTIONS`)
- `src/sohnbot/broker/router.py` (modified — extended profiles validation block, added profiles/build `_execute_capability` branch, added build case in `_format_notification_message`)
- `src/sohnbot/runtime/mcp_tools.py` (modified — added `profiles__build` tool + registered in tools list)
- `src/sohnbot/config/registry.py` (modified — added `_validate_build_command` validator and `commands.build_command` ConfigKey)
- `config/default.toml` (modified — added `build_command = "make"` under `[commands]`)
- `tests/unit/test_profile_executor.py` (modified — added `TestExecuteBuildProfile` (7 tests) + `TestExecuteLintProfileCancellation` + `test_build_cancellation_kills_process`)
- `tests/unit/test_mcp_tools.py` (modified — added 3 `profiles__build` tests; added `mcp__sohnbot__profiles__build` to allowed tools list)
- `tests/unit/test_broker.py` (modified — added Tier 0 classification test; 5 broker integration tests; 2 notification formatter tests)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified — story status updated)
