# Story 5.3: Run Tests Profile

Status: review

## Story

As a user,
I want to execute project test suite,
so that I can verify tests pass before committing.

## Acceptance Criteria

1. **Given** a project with a test suite configured (e.g., pytest, jest, cargo test)
   **When** I request test execution via `profiles__test` MCP tool
   **Then** test command runs with an optional pattern argument (test file/pattern)
   **And** timeout is enforced at 600 seconds (10 minutes)

2. **Given** test execution completes (success or failure)
   **When** results are returned from the capability
   **Then** stdout, stderr, exit code, and a boolean `passed` flag are included in the result

3. **Given** test execution completes
   **When** result is processed by the broker
   **Then** operation is logged as Tier 0 (read-only) — no snapshot is created

4. **Given** test execution completes
   **When** broker routes the result through the notification system
   **Then** a Telegram notification summarizes the test outcome (passed/failed, exit code)

5. **Given** a `repo_path` is provided to the tool
   **When** the broker validates the request
   **Then** `repo_path` is validated against configured scope roots before subprocess spawning

6. **Given** an optional `pattern` argument is provided
   **When** the broker validates the request
   **Then** `pattern` is checked for shell metacharacters and rejected if unsafe

## Tasks / Subtasks

- [x] Task 1: Add `execute_test_profile` to capability module (AC: 1, 2)
  - [x] 1.1 Add `execute_test_profile(repo_path, command, pattern, timeout_seconds)` to `src/sohnbot/capabilities/command_profiles/profile_executor.py` — follow the same `asyncio.create_subprocess_exec` pattern as `execute_build_profile`, but accept `pattern: str` instead of `target: str`, and default timeout of 600s
  - [x] 1.2 Return structured dict: `{passed, exit_code, stdout, stderr, command_used, pattern}`
  - [x] 1.3 Implement 600s timeout using `asyncio.timeout()`, kill + `await proc.wait()` on timeout (prevent zombie processes — Story 5.1 H1 fix)
  - [x] 1.4 Add `asyncio.CancelledError` handler with `asyncio.shield(proc.wait())` (Story 5.2 review fix)
  - [x] 1.5 Export `execute_test_profile` from `src/sohnbot/capabilities/command_profiles/__init__.py`

- [x] Task 2: Add config key for test command (AC: 1)
  - [x] 2.1 Add `_validate_test_command(value: str) -> bool` validator function to `src/sohnbot/config/registry.py` — same metacharacter rejection logic as `_validate_build_command` (reuse `_SAFE_COMMAND_RE`)
  - [x] 2.2 Add `"commands.test_command"` ConfigKey to `REGISTRY` in `src/sohnbot/config/registry.py` (dynamic, str, default `"pytest"`, validator=`_validate_test_command`) — add after `"commands.build_command"` entry (~line 235)
  - [x] 2.3 Add `test_command = "pytest"` under `[commands]` section in `config/default.toml` (after `build_command`, before `lint_timeout_seconds`) — NOTE: `test_timeout_seconds = 600` is **already present** in default.toml, do NOT add it again

- [x] Task 3: Add `("profiles", "test")` to Tier 0 in operation classifier (AC: 3)
  - [x] 3.1 Add `("profiles", "test"),  # Read-only execution` to `READ_ONLY_ACTIONS` set in `src/sohnbot/broker/operation_classifier.py` (after `("profiles", "build")` at line 35)

- [x] Task 4: Extend profiles validation in Broker Router (AC: 5, 6)
  - [x] 4.1 In `src/sohnbot/broker/router.py`, extend the validation check at line 411: change `if action in {"lint", "build"} and "repo_path" not in params:` to `if action in {"lint", "build", "test"} and "repo_path" not in params:`
  - [x] 4.2 After the existing `target` validation block (~line 502), add a `pattern` validation block: if `params.get("pattern")` is not None/empty, validate it with `_SAFE_PROFILE_RE` (already imported as alias at line 36); reject with `invalid_request` if unsafe characters detected

- [x] Task 5: Wire `profiles/test` into Broker `_execute_capability` (AC: 1, 2, 3)
  - [x] 5.1 In `src/sohnbot/broker/router.py`, inside the `if capability == "profiles":` block in `_execute_capability()` (~line 892), add an `if action == "test":` branch after the existing `if action == "build":` branch
  - [x] 5.2 Import `execute_test_profile` from `..capabilities.command_profiles` (lazy import inside the if-block)
  - [x] 5.3 Pull `commands.test_command` and `commands.test_timeout_seconds` from `config_manager.get()` (with `"pytest"` and `600` as fallbacks)
  - [x] 5.4 Call `execute_test_profile(repo_path=..., command=..., pattern=..., timeout_seconds=int(timeout))`

- [x] Task 6: Extend notification formatter for test profile (AC: 4)
  - [x] 6.1 In `src/sohnbot/broker/router.py`, add `elif capability == "profiles" and action == "test" and status == "completed":` case in `_format_notification_message()` (immediately after the existing build case at ~line 953)
  - [x] 6.2 Format: `"✅ PASSED Test profile | exit_code=0 | repo=..."` or `"❌ FAILED Test profile | exit_code=1 | repo=..."`

- [x] Task 7: Implement `profiles__test` MCP tool (AC: 1, 5)
  - [x] 7.1 Add `@tool("profiles__test", "Run project test suite", {"repo_path": str, "pattern": str})` in `src/sohnbot/runtime/mcp_tools.py` immediately after the `profiles__build` tool definition (~line 664)
  - [x] 7.2 Accept params: `repo_path: str`, `pattern: str` (optional, empty = run full test suite)
  - [x] 7.3 Route through `broker.route_operation(capability="profiles", action="test", params=..., chat_id=chat_id)`
  - [x] 7.4 On success: return `"{status} (exit {exit_code})\n{stdout+stderr combined, truncated to 2000 chars}"` — same combined output pattern as `profiles__build`
  - [x] 7.5 Register `profiles_test` in the `tools=[...]` list immediately after `profiles_build` (~line 771)

- [x] Task 8: Tests (AC: 1, 2, 3, 4, 5, 6)
  - [x] 8.1 Add `TestExecuteTestProfile` class in `tests/unit/test_profile_executor.py` — success, failure, timeout (assert `await proc.wait()` called on timeout), optional pattern included in command, cancellation kills process
  - [x] 8.2 Add `profiles__test` tests in `tests/unit/test_mcp_tools.py` — mock broker, verify tool schema and routing, test with and without pattern; add `mcp__sohnbot__profiles__test` to allowed tools list
  - [x] 8.3 Add broker tests in `tests/unit/test_broker.py` — missing repo_path, empty repo_path, out-of-scope repo_path, unsafe pattern, and success routing for `("profiles", "test")`
  - [x] 8.4 Add `classify_tier("profiles", "test", 0) == 0` test in `tests/unit/test_broker.py`
  - [x] 8.5 Add `_format_notification_message` tests for test/passed and test/failed cases in `tests/unit/test_broker.py`

## Dev Notes

### Architecture Path — IMPORTANT

The epics file says: `Updates: src/sohnbot/capabilities/profiles.py (execute_test_profile)`
The architecture spec says: `src/sohnbot/capabilities/command_profiles/`
**Resolution: Follow the architecture — same correction as Stories 5.1 and 5.2.**

The actual files to touch are:
- `src/sohnbot/capabilities/command_profiles/profile_executor.py` — add `execute_test_profile`
- `src/sohnbot/capabilities/command_profiles/__init__.py` — export `execute_test_profile`

Do NOT create a top-level `src/sohnbot/capabilities/profiles.py`.

### `execute_test_profile` Implementation Pattern

Follow the exact same pattern as `execute_build_profile` in `profile_executor.py`. Key differences:
- Parameter is `pattern: str` (single optional test file/pattern) instead of `target: str`
- Default timeout is `600` seconds instead of `300`
- Return dict key is `pattern` instead of `target`
- Log events: `"test_profile_started"`, `"test_profile_timeout"`, `"test_profile_completed"`

```python
async def execute_test_profile(
    repo_path: str,
    command: str,
    pattern: str,
    timeout_seconds: int = 600,
) -> dict:
    """Run a test command as a subprocess with timeout enforcement.

    Args:
        repo_path: Working directory for the subprocess (project root).
        command: Test command string, e.g. "pytest" or "cargo test".
                 Multi-word strings are split on whitespace.
        pattern: Optional test file or pattern appended after the command
                 (e.g. "tests/unit/", "test_broker.py", "-k auth").
                 Empty string means no explicit pattern (run full suite).
        timeout_seconds: Hard kill timeout in seconds (default 600).

    Returns:
        dict with keys:
            passed (bool): True iff exit_code == 0
            exit_code (int): Subprocess return code
            stdout (str): Decoded standard output
            stderr (str): Decoded standard error
            command_used (str): The command string that was executed
            pattern (str): The test pattern that was passed

    Raises:
        TimeoutError: When subprocess exceeds timeout_seconds; process is killed.
    """
    cmd_parts = command.split()
    if pattern:
        cmd_parts.append(pattern)

    logger.info(
        "test_profile_started",
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
            "test_profile_timeout",
            repo_path=repo_path,
            timeout_seconds=timeout_seconds,
        )
        raise

    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            proc.kill()
            try:
                await asyncio.shield(proc.wait())
            except asyncio.CancelledError:
                pass
        raise

    exit_code = proc.returncode
    passed = exit_code == 0

    logger.info(
        "test_profile_completed",
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
        "pattern": pattern,
    }
```

**Do NOT use `subprocess.run()` or `shell=True`** — asyncio subprocess keeps the event loop non-blocking and prevents shell injection.

### Config Keys

**Already in registry.py and default.toml (NO changes needed):**
- `commands.test_timeout_seconds` — default `600`, dynamic, range `60–3600`
  [Source: `src/sohnbot/config/registry.py:250-256`, `config/default.toml:79`]

**Must be ADDED by this story:**
- `commands.test_command` — default `"pytest"`, dynamic, type `str`, with security validator
  - Registry: add after `"commands.build_command"` entry (~line 235 in `src/sohnbot/config/registry.py`)
  - TOML: add `test_command = "pytest"` under `[commands]` section after `build_command = "make"` (line 77 in `config/default.toml`)

**Validator pattern** (copy/adapt from `_validate_build_command`):
```python
def _validate_test_command(value: str) -> bool:
    """Reject empty strings and shell metacharacters in test command."""
    if not value or not value.strip():
        raise ValueError("test_command must not be empty")
    if not _SAFE_COMMAND_RE.match(value):
        raise ValueError(
            "test_command contains disallowed characters; "
            "use alphanumeric, spaces, dashes, underscores, dots, and slashes only"
        )
    return True
```

`_SAFE_COMMAND_RE` is already defined at `src/sohnbot/config/registry.py:26` — reuse it.

### Tier 0 Classification — Must Add

`("profiles", "test")` is NOT yet in `READ_ONLY_ACTIONS` in `operation_classifier.py`. This MUST be added or the broker will classify it as Tier 2 (multi-file modification) which will trigger a snapshot creation.

[Source: `src/sohnbot/broker/operation_classifier.py:22-36`]
```python
READ_ONLY_ACTIONS = {
    ...
    ("profiles", "lint"),   # Read-only execution  ← already exists (line 34)
    ("profiles", "build"),  # Read-only execution  ← already exists (line 35)
    ("profiles", "test"),   # Read-only execution  ← MUST ADD
}
```

### Broker Validation Block Extension

In `src/sohnbot/broker/router.py` at line 411, the current check is:
```python
if action in {"lint", "build"} and "repo_path" not in params:
```

Change to:
```python
if action in {"lint", "build", "test"} and "repo_path" not in params:
```

The rest of the validation block (empty repo_path check, scope validation, files traversal check, target metacharacter check) is unaffected by this change.

**Add `pattern` validation** after the existing `target` validation block (~line 502):
```python
pattern = params.get("pattern") or ""
if pattern and not _SAFE_PROFILE_RE.match(pattern):
    self._operation_start_times.pop(operation_id, None)
    return BrokerResult(
        allowed=False,
        operation_id=operation_id,
        tier=tier,
        error={
            "code": "invalid_request",
            "message": "pattern contains disallowed characters",
            "details": {"pattern": pattern},
            "retryable": False,
        },
    )
```

Note: `_SAFE_PROFILE_RE` is already imported at `src/sohnbot/broker/router.py:36` as an alias for `_SAFE_COMMAND_RE` from registry. No additional import needed.

### Broker `_execute_capability` Addition

In `router.py`, inside `if capability == "profiles":` block (~line 892), add after the build block (~line 928):
```python
if action == "test":
    from ..capabilities.command_profiles import execute_test_profile
    command = (
        self.config_manager.get("commands.test_command")
        if self.config_manager
        else "pytest"
    )
    timeout = (
        self.config_manager.get("commands.test_timeout_seconds")
        if self.config_manager
        else 600
    )
    return await execute_test_profile(
        repo_path=params["repo_path"],
        command=command,
        pattern=params.get("pattern") or "",
        timeout_seconds=int(timeout),
    )
```

### Notification Formatter

In `_format_notification_message()` in `router.py` (~line 953), add after the build case:
```python
if capability == "profiles" and action == "test" and status == "completed":
    data = result or {}
    passed = "✅ PASSED" if data.get("passed") else "❌ FAILED"
    exit_code = data.get("exit_code", "?")
    repo = params.get("repo_path", "-")
    return f"{passed} Test profile | exit_code={exit_code} | repo={repo}"
```

### MCP Tool Pattern

```python
@tool("profiles__test", "Run project test suite", {"repo_path": str, "pattern": str})
async def profiles_test(args):
    """Run test profile via broker."""
    ctx = get_contextvars()
    chat_id = ctx.get("chat_id", "unknown")
    repo_path = args.get("repo_path")
    pattern = args.get("pattern") or ""
    logger.info(
        "mcp_tool_invoked",
        tool="profiles__test",
        repo_path=repo_path,
        chat_id=chat_id,
    )

    result = await broker.route_operation(
        capability="profiles",
        action="test",
        params={"repo_path": repo_path, "pattern": pattern},
        chat_id=chat_id,
    )

    if not result.allowed:
        error_msg = (result.error or {}).get("message", "Operation denied")
        logger.warning("mcp_tool_denied", tool="profiles__test", error=error_msg)
        return _as_mcp_text(f"❌ Test denied: {error_msg}")

    data = result.result or {}
    status = "✅ PASSED" if data.get("passed") else "❌ FAILED"
    exit_code = data.get("exit_code", "?")
    stdout = data.get("stdout", "")
    stderr = data.get("stderr", "")
    output = "\n".join(part for part in (stdout, stderr) if part)
    return _as_mcp_text(f"{status} (exit {exit_code})\n{output[:2000]}")
```

Register `profiles_test` in `tools=[...]` immediately after `profiles_build` (~line 771).

### No Snapshot Required

Tier 0 operations skip snapshot creation. Once `("profiles", "test")` is in `READ_ONLY_ACTIONS`, the `tier == 0` result means the snapshot block in `route_operation()` is never entered. No other changes needed.

### Project Structure Notes

- `src/sohnbot/capabilities/command_profiles/profile_executor.py` — **ADD** `execute_test_profile` function (do NOT create a separate file; lint, build, and test all live here)
- `src/sohnbot/capabilities/command_profiles/__init__.py` — **MODIFY**: add `execute_test_profile` to import and `__all__`
- `src/sohnbot/broker/operation_classifier.py:35` — **MODIFY**: add `("profiles", "test")` after `("profiles", "build")`
- `src/sohnbot/broker/router.py:411` — **MODIFY**: extend `action in {"lint", "build"}` to `action in {"lint", "build", "test"}`
- `src/sohnbot/broker/router.py:~502` — **MODIFY**: add `pattern` validation after existing `target` validation block
- `src/sohnbot/broker/router.py:~928` — **MODIFY**: add `if action == "test":` block inside profiles `_execute_capability`
- `src/sohnbot/broker/router.py:~953` — **MODIFY**: add test case in `_format_notification_message`
- `src/sohnbot/runtime/mcp_tools.py:~665` — **ADD** `profiles__test` tool definition after `profiles__build`
- `src/sohnbot/runtime/mcp_tools.py:~771` — **MODIFY**: add `profiles_test` to `tools=[...]` list
- `src/sohnbot/config/registry.py:~41` — **ADD** `_validate_test_command` validator function (after `_validate_build_command`)
- `src/sohnbot/config/registry.py:~235` — **ADD** `"commands.test_command"` ConfigKey to REGISTRY (after `"commands.build_command"`)
- `config/default.toml:~78` — **MODIFY** [commands] section: add `test_command = "pytest"` after `build_command = "make"`
- `tests/unit/test_profile_executor.py` — **MODIFY**: add `TestExecuteTestProfile` class (min 5 tests: success, failure, timeout, optional pattern, cancellation)
- `tests/unit/test_mcp_tools.py` — **MODIFY**: add `profiles__test` tests; add `mcp__sohnbot__profiles__test` to allowed tools list
- `tests/unit/test_broker.py` — **MODIFY**: add Tier 0 classification test; 5 broker integration tests; 2 notification formatter tests

### Previous Story Intelligence

**Critical fixes from Stories 5.1 and 5.2 that MUST carry forward:**
- **H1 (Zombie Process):** After `proc.kill()`, always call `await proc.wait()` to reap the process. Template above includes this.
- **H1b (CancelledError):** After 5.2 review, `asyncio.CancelledError` handler with `asyncio.shield(proc.wait())` is required. Template above includes this.
- **H2 (Security Validator):** `lint_command` and `build_command` both have validators rejecting metacharacters. Test command MUST have an equivalent `_validate_test_command`. Do NOT skip this.
- **H3 (Arg Validation):** Build uses `_SAFE_PROFILE_RE` for `target`; test uses the same for `pattern`. The validation must be in the router, not in the capability function.
- **M1 (Combined Output):** MCP tool must combine `stdout + stderr` in response. Template above does this.
- **M2 (Empty repo_path):** Empty string for `repo_path` must be rejected before scope check. Already handled by existing empty-check block — no change needed as long as `"test"` is added to the action set check at line 411.
- **M3 (Integration Tests):** Broker integration tests are required: missing repo_path, empty repo_path, out-of-scope, unsafe pattern, and success routing.
- **AC4 test (Notification):** `_format_notification_message` tests for both passed and failed are required (added after 5.2 review).

**Patterns established in Stories 5.1/5.2 to follow consistently:**
- `profile_executor.py` holds ALL profile execution functions (lint, build, test go here)
- `__init__.py` exports only — no logic in `__init__.py`
- Broker router profiles block uses lazy imports (`from ..capabilities.command_profiles import ...` inside the if-block)
- MCP tool function name is snake_case (`profiles_test`), decorator name is dunder-style (`"profiles__test"`)
- Tier 0 means NO snapshot, operation logged as read-only

**Files created/modified by Story 5.2 (reference baseline):**
- `src/sohnbot/capabilities/command_profiles/profile_executor.py` (contains `execute_lint_profile` + `execute_build_profile`)
- `src/sohnbot/capabilities/command_profiles/__init__.py` (exports both)
- `src/sohnbot/broker/operation_classifier.py` (has lint + build in READ_ONLY_ACTIONS)
- `src/sohnbot/broker/router.py` (profiles validation + execute + notify for lint and build)
- `src/sohnbot/runtime/mcp_tools.py` (has profiles__lint + profiles__build tools)
- `src/sohnbot/config/registry.py` (has lint_command, build_command, test_timeout_seconds)
- `config/default.toml` (has lint_command, build_command, test_timeout_seconds)
- `tests/unit/test_profile_executor.py` (TestExecuteLintProfile + TestExecuteBuildProfile)
- `tests/unit/test_mcp_tools.py` (profiles__lint + profiles__build tests)
- `tests/unit/test_broker.py` (broker integration + tier + notification tests)

**Pre-existing failing test to be aware of:**
- `test_config_manager.py::test_static_config_validation` fails with a regex mismatch — this is pre-existing, NOT introduced by this story. Do not "fix" it as part of this story.

**Current test count baseline:** 80 passed, 1 skipped, 1 pre-existing failure (from Story 5.2 completion notes).

### Git Intelligence

Recent commits (for context):
- `f792b95` Fix code review findings for story 5.2: zombie process + regex + notification tests
- `c184c50` Implement story 5.2: Build Project Profile
- `8701c52` Create story 5.2: Build Project Profile
- `a11800f` Merge pull request #6 from MirkoSon/claude/create-story-5.1-FU3ql

Story 5.2 was implemented then had code review fixes applied. All patterns are now stable and well-tested. Story 5.3 follows the same established pattern without deviation.

### References

- Epic 5 story 5.3 definition: [Source: `_bmad-output/planning-artifacts/epics.md:1081-1103`]
- Architecture command_profiles module: [Source: `_bmad-output/planning-artifacts/architecture.md:221-224`]
- Architecture timeout reference (tests: 600s): [Source: `_bmad-output/planning-artifacts/architecture.md:97`]
- Tier classification READ_ONLY_ACTIONS: [Source: `src/sohnbot/broker/operation_classifier.py:22-36`]
- Existing `_validate_build_command` pattern: [Source: `src/sohnbot/config/registry.py:41-50`]
- Existing `commands.test_timeout_seconds` registry entry: [Source: `src/sohnbot/config/registry.py:250-256`]
- Existing commands config in default.toml: [Source: `config/default.toml:73-79`]
- Profiles validation block (build as model): [Source: `src/sohnbot/broker/router.py:409-502`]
- `_SAFE_PROFILE_RE` import: [Source: `src/sohnbot/broker/router.py:36`]
- Profiles `_execute_capability` block (build as model): [Source: `src/sohnbot/broker/router.py:911-928`]
- Profiles notification format (build as model): [Source: `src/sohnbot/broker/router.py:948-953`]
- `profiles__build` MCP tool (model): [Source: `src/sohnbot/runtime/mcp_tools.py:631-663`]
- `tools=[...]` list: [Source: `src/sohnbot/runtime/mcp_tools.py:770-771`]
- `execute_build_profile` function (model): [Source: `src/sohnbot/capabilities/command_profiles/profile_executor.py:97-184`]
- `command_profiles/__init__.py`: [Source: `src/sohnbot/capabilities/command_profiles/__init__.py`]
- FR-017 requirement: [Source: `_bmad-output/planning-artifacts/epics.md:39`]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
### Completion Notes List

- Implemented `execute_test_profile` in `profile_executor.py` following the exact same pattern as `execute_build_profile`. Uses `asyncio.create_subprocess_exec` (no shell injection risk), `asyncio.timeout()` for 600s hard kill, zombie-process prevention via `await proc.wait()` after `proc.kill()`, and `asyncio.CancelledError` handler with `asyncio.shield(proc.wait())`.
- Added `_validate_test_command` security validator and `"commands.test_command"` ConfigKey to registry. `test_timeout_seconds` was already present — not duplicated.
- Added `test_command = "pytest"` to `config/default.toml` under `[commands]`. `test_timeout_seconds = 600` was already present.
- Added `("profiles", "test")` to `READ_ONLY_ACTIONS` in `operation_classifier.py` — ensures Tier 0 classification (no snapshot created).
- Extended broker router: `action in {"lint", "build", "test"}` for missing repo_path check; added `pattern` metacharacter validation block after `target` block.
- Added `if action == "test":` branch in `_execute_capability` with lazy import of `execute_test_profile` and config fallbacks.
- Added test profile notification formatter case in `_format_notification_message`.
- Added `profiles__test` MCP tool in `mcp_tools.py` with combined stdout+stderr output (2000 char truncation), registered in tools list.
- Added 18 new tests: 7 in `TestExecuteTestProfile` (success, failure, timeout, no-pattern, with-pattern, cwd, cancellation), 3 MCP tool tests (schema, routing, denial), 8 broker tests (tier classification, 5 validation, 2 notification formatter). All 76 tests in the 3 affected test files pass.
- Pre-existing failures confirmed NOT introduced by this story: `test_config_manager.py::test_static_config_validation` (regex mismatch) and `test_health_checks.py::test_check_sqlite_writable_warns_if_not_wal` (sqlite WAL transaction issue).

### File List

- `src/sohnbot/capabilities/command_profiles/profile_executor.py` (modified — added `execute_test_profile`)
- `src/sohnbot/capabilities/command_profiles/__init__.py` (modified — exported `execute_test_profile`)
- `src/sohnbot/broker/operation_classifier.py` (modified — added `("profiles", "test")` to READ_ONLY_ACTIONS)
- `src/sohnbot/broker/router.py` (modified — validation, _execute_capability, _format_notification_message)
- `src/sohnbot/runtime/mcp_tools.py` (modified — added `profiles__test` tool + registered in tools list)
- `src/sohnbot/config/registry.py` (modified — added `_validate_test_command` + `"commands.test_command"` ConfigKey)
- `config/default.toml` (modified — added `test_command = "pytest"`)
- `tests/unit/test_profile_executor.py` (modified — added `TestExecuteTestProfile` class, 7 tests)
- `tests/unit/test_mcp_tools.py` (modified — added 3 `profiles__test` tests + `mcp__sohnbot__profiles__test` to allowed list)
- `tests/unit/test_broker.py` (modified — added 8 tests: tier, 5 validation, 2 notification formatter)
- `_bmad-output/implementation-artifacts/5-3-run-tests-profile.md` (this story file)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (updated status)
