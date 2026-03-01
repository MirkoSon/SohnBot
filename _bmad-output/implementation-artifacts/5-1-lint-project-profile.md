# Story 5.1: Lint Project Profile

Status: review

## Story

As a user,
I want to execute the project linter on specified files or the full project,
so that code quality is validated before commits.

## Acceptance Criteria

1. **Given** a project with a linter configured (e.g., pylint, eslint)
   **When** I request lint execution via `profiles__lint` MCP tool
   **Then** linter runs with the configured command and optional file path arguments

2. **Given** lint is running
   **When** execution exceeds 60 seconds
   **Then** the subprocess is killed and a timeout error is returned

3. **Given** lint execution completes (success or failure)
   **When** results are returned from the capability
   **Then** stdout, stderr, exit code, and a boolean `passed` flag are included in the result

4. **Given** lint execution completes
   **When** result is processed by the broker
   **Then** operation is logged as Tier 0 (read-only) — no snapshot is created

5. **Given** lint execution completes
   **When** broker routes the result through the notification system
   **Then** a Telegram notification summarizes the lint outcome (passed/failed, exit code)

6. **Given** a file path is provided to the tool
   **When** the broker validates the request
   **Then** path is validated against configured scope roots before subprocess spawning

## Tasks / Subtasks

- [x] Task 1: Create `execute_lint_profile` capability function (AC: 1, 2, 3)
  - [x] 1.1 Create `src/sohnbot/capabilities/command_profiles/profile_executor.py` with `execute_lint_profile(repo_path, files, command, timeout_seconds)` using `asyncio.create_subprocess_exec`
  - [x] 1.2 Return structured dict: `{passed, exit_code, stdout, stderr, command_used, files_linted}`
  - [x] 1.3 Implement 60s timeout using `asyncio.timeout()` / `asyncio.wait_for()`, kill subprocess on timeout
  - [x] 1.4 Update `src/sohnbot/capabilities/command_profiles/__init__.py` to export `execute_lint_profile`

- [x] Task 2: Add config keys for lint command (AC: 1)
  - [x] 2.1 Add `commands.lint_command` (dynamic, str, default `"pylint"`) to `src/sohnbot/config/registry.py`
  - [x] 2.2 Add `lint_command = "pylint"` under `[commands]` section in `config/default.toml`

- [x] Task 3: Wire profiles capability into the Broker Router (AC: 4, 5)
  - [x] 3.1 Import `execute_lint_profile` in `src/sohnbot/broker/router.py`
  - [x] 3.2 Add `profiles` capability block in `_execute_capability()` for action `"lint"`
  - [x] 3.3 Pull `commands.lint_command` and `commands.lint_timeout_seconds` from `config_manager.get()`
  - [x] 3.4 Update `_format_notification_message()` to produce a human-readable lint summary

- [x] Task 4: Implement `profiles__lint` MCP tool (AC: 1, 6)
  - [x] 4.1 Add `@tool("profiles__lint", ...)` in `src/sohnbot/runtime/mcp_tools.py`
  - [x] 4.2 Accept params: `repo_path: str`, `files: list` (optional, empty = full project)
  - [x] 4.3 Route through `broker.route_operation(capability="profiles", action="lint", params=...)`
  - [x] 4.4 Register `profiles__lint` in the `tools=[...]` list at the bottom of `create_sohnbot_mcp_server()`

- [x] Task 5: Tests (AC: 1, 2, 3, 4)
  - [x] 5.1 Create `tests/unit/test_profile_executor.py` — unit test `execute_lint_profile` with mocked subprocess (success, failure, timeout)
  - [x] 5.2 Add `profiles__lint` coverage in `tests/unit/test_mcp_tools.py` (mock broker, verify tool schema and routing)
  - [x] 5.3 Add broker Tier 0 classification test for `("profiles", "lint")` in `tests/unit/test_broker.py` (pre-existing, confirmed passing)

## Dev Notes

### Architecture Path Discrepancy — IMPORTANT

The epics note says: `Creates: src/sohnbot/capabilities/profiles.py`
The architecture spec says: `src/sohnbot/capabilities/command_profiles/profiles.py`

**Resolution: Follow the architecture.** The `command_profiles/` directory already exists at `src/sohnbot/capabilities/command_profiles/` with an `__init__.py`. Create files inside it. Do NOT create a top-level `profiles.py` at `src/sohnbot/capabilities/profiles.py`.

The implementation file to create is: `src/sohnbot/capabilities/command_profiles/profile_executor.py`

### Broker Integration Pattern

All capabilities route through the Broker — `profiles` is no different. The broker's `_execute_capability` already has a placeholder that returns a stub for unknown capabilities. You need to add an `if capability == "profiles":` block.

**Critical**: Do NOT call `execute_lint_profile` directly from the MCP tool. Route through `broker.route_operation()`.

The Tier 0 classification for `("profiles", "lint")` is **already wired** in `src/sohnbot/broker/operation_classifier.py:34`:
```python
("profiles", "lint"),  # Read-only execution
```
No changes to `operation_classifier.py` are needed for Story 5.1.

### Subprocess Execution Pattern

Use `asyncio.create_subprocess_exec` (not `shell=True` — prevents command injection):

```python
import asyncio

async def execute_lint_profile(
    repo_path: str,
    command: str,
    files: list[str],
    timeout_seconds: int = 60,
) -> dict:
    cmd_parts = command.split() + files  # e.g., ["pylint", "src/"]
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
        proc.kill()
        raise

    exit_code = proc.returncode
    return {
        "passed": exit_code == 0,
        "exit_code": exit_code,
        "stdout": stdout_bytes.decode("utf-8", errors="replace"),
        "stderr": stderr_bytes.decode("utf-8", errors="replace"),
        "command_used": command,
        "files_linted": files,
    }
```

**Do NOT use `subprocess.run()` or `shell=True`** — asyncio subprocess keeps the event loop non-blocking.

### Config Keys

**Already in registry + TOML (no change needed):**
- `commands.lint_timeout_seconds` — default `60`, dynamic, range `10–300`
  [Source: `src/sohnbot/config/registry.py:195-202`, `config/default.toml:75`]

**Must be added by this story:**
- `commands.lint_command` — default `"pylint"`, dynamic, type `str`
  - Registry: `src/sohnbot/config/registry.py` under `# COMMAND PROFILES` section
  - TOML: `config/default.toml` under `[commands]` section, add `lint_command = "pylint"`

### MCP Tool Schema Pattern

Follow the established pattern in `src/sohnbot/runtime/mcp_tools.py`. Every tool:
1. Gets `chat_id` from `get_contextvars()`
2. Calls `broker.route_operation(capability=..., action=..., params=..., chat_id=chat_id)`
3. Checks `result.allowed` and returns `_as_mcp_text(...)` for both success and denial

```python
@tool("profiles__lint", "Run project linter", {"repo_path": str, "files": list})
async def profiles_lint(args):
    ctx = get_contextvars()
    chat_id = ctx.get("chat_id", "unknown")
    repo_path = args.get("repo_path")
    files = args.get("files") or []
    logger.info("mcp_tool_invoked", tool="profiles__lint", repo_path=repo_path, chat_id=chat_id)

    result = await broker.route_operation(
        capability="profiles",
        action="lint",
        params={"repo_path": repo_path, "files": files},
        chat_id=chat_id,
    )

    if not result.allowed:
        error_msg = (result.error or {}).get("message", "Operation denied")
        return _as_mcp_text(f"❌ Lint denied: {error_msg}")

    data = result.result or {}
    status = "✅ PASSED" if data.get("passed") else "❌ FAILED"
    exit_code = data.get("exit_code", "?")
    stdout = data.get("stdout", "")
    return _as_mcp_text(f"{status} (exit {exit_code})\n{stdout[:2000]}")  # truncate for Telegram
```

Register `profiles_lint` in the `tools=[...]` list at the bottom of `create_sohnbot_mcp_server()`.

### Broker `_execute_capability` Addition

In `src/sohnbot/broker/router.py`, add inside `_execute_capability()` before the final `return await self._execute_capability_placeholder(...)`:

```python
if capability == "profiles":
    if action == "lint":
        from ..capabilities.command_profiles import execute_lint_profile
        command = (
            self.config_manager.get("commands.lint_command")
            if self.config_manager
            else "pylint"
        )
        timeout = (
            self.config_manager.get("commands.lint_timeout_seconds")
            if self.config_manager
            else 60
        )
        return await execute_lint_profile(
            repo_path=params["repo_path"],
            command=command,
            files=params.get("files") or [],
            timeout_seconds=int(timeout),
        )
```

**Parameter validation** in `route_operation()` for `capability == "profiles"` and `action == "lint"`:
- `repo_path` is required — add a validation block similar to the `git` capability check
- `repo_path` must pass scope validation (same as git capability) — add scope check

### Notification Message Enhancement

In `_format_notification_message()` in `router.py`, add a profiles/lint case:

```python
if capability == "profiles" and action == "lint" and status == "completed":
    data = result or {}
    passed = "✅ PASSED" if data.get("passed") else "❌ FAILED"
    exit_code = data.get("exit_code", "?")
    return f"{passed} Lint profile | exit_code={exit_code} | repo={params.get('repo_path', '-')}"
```

### No Snapshot Required

Tier 0 operations skip snapshot creation. The broker already handles this:
[Source: `src/sohnbot/broker/router.py:425-436`]
```python
if (
    tier in (1, 2)
    and not (...)
    and capability != "scheduler"
):
    snapshot_ref = await self._create_snapshot(...)
```
Since `tier == 0` for profiles/lint, snapshot block is never entered. No changes needed.

### Scope Validation Requirement

The `repo_path` parameter must be validated against scope roots before subprocess execution. Add validation in `route_operation()` for `capability == "profiles"` following the same pattern as `capability == "git"`:

```python
if capability == "profiles":
    if action == "lint" and "repo_path" not in params:
        # return BrokerResult with invalid_request error
        ...
    repo_path = params.get("repo_path")
    if repo_path:
        is_valid, error_msg = self.scope_validator.validate_path(repo_path)
        if not is_valid:
            # return BrokerResult with scope_violation error (same pattern as git)
            ...
```

### Project Structure Notes

- `src/sohnbot/capabilities/command_profiles/__init__.py` — currently empty (1 line), will export `execute_lint_profile`
- `src/sohnbot/capabilities/command_profiles/profile_executor.py` — CREATE new file, primary implementation
- `src/sohnbot/broker/router.py:663-796` — `_execute_capability()` method, add profiles block before final return
- `src/sohnbot/broker/router.py:408` — TODO comment for profile limits (Story 5.5), leave as-is for now
- `src/sohnbot/runtime/mcp_tools.py:676-704` — `tools=[...]` list, add `profiles_lint`
- `config/default.toml:73-78` — `[commands]` section, add `lint_command`
- `src/sohnbot/config/registry.py:194-222` — `COMMAND PROFILES` section, add `commands.lint_command`

### References

- Epic 5 story definition: [Source: `_bmad-output/planning-artifacts/epics.md:1032-1054`]
- Architecture command_profiles module: [Source: `_bmad-output/planning-artifacts/architecture.md:221-224`]
- Tier classification (profiles already set): [Source: `src/sohnbot/broker/operation_classifier.py:34`]
- Config registry pattern: [Source: `src/sohnbot/config/registry.py:194-222`]
- Config default.toml commands section: [Source: `config/default.toml:73-78`]
- Broker route_operation validation patterns: [Source: `src/sohnbot/broker/router.py:200-335`]
- Broker _execute_capability pattern: [Source: `src/sohnbot/broker/router.py:663-796`]
- MCP tool registration pattern: [Source: `src/sohnbot/runtime/mcp_tools.py:676-705`]
- Broker notification format: [Source: `src/sohnbot/broker/router.py:798-861`]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

- Implemented `execute_lint_profile` using `asyncio.create_subprocess_exec` (not `shell=True`) with `asyncio.timeout()` for hard kill on timeout
- `commands.lint_command` (dynamic, default "pylint") added to registry and default.toml
- Broker router wired: profiles/lint scope validation + `_execute_capability` block + `_format_notification_message` entry
- `profiles__lint` MCP tool registered via `@tool` decorator with `repo_path: str, files: list` schema
- 7 new unit tests in `test_profile_executor.py`; 3 new tests added to `test_mcp_tools.py`
- `classify_tier("profiles", "lint", 0) == 0` was already in `test_broker.py` (confirmed passing)
- Pre-existing failing test `test_config_manager.py::test_static_config_validation` (regex mismatch) confirmed pre-existing, NOT introduced by this story

### File List

- `src/sohnbot/capabilities/command_profiles/profile_executor.py` (created)
- `src/sohnbot/capabilities/command_profiles/__init__.py` (modified — exports execute_lint_profile)
- `src/sohnbot/broker/router.py` (modified — profiles validation block, _execute_capability profiles/lint, _format_notification_message profiles/lint)
- `src/sohnbot/runtime/mcp_tools.py` (modified — profiles__lint tool + registered in tools list)
- `src/sohnbot/config/registry.py` (modified — commands.lint_command added)
- `config/default.toml` (modified — lint_command = "pylint" under [commands])
- `tests/unit/test_profile_executor.py` (created — 7 unit tests)
- `tests/unit/test_mcp_tools.py` (modified — 3 new profiles__lint tests, profiles__lint added to allowed tools list)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified — story status updates)
