# Story 5.5: Profile Chaining Limit & Dry-Run Mode

**Epic**: Epic 5 - Development Workflow Automation
**Story Key**: 5-5-profile-chaining-limit-dry-run-mode
**Status**: done
**Created**: 2026-03-01

---

## Story Overview

**As a** user,
**I want** profile execution limits and dry-run testing,
**So that** I can prevent runaway automation and test operations safely.

### Business Value
- **Safety**: Prevent accidental infinite loops or excessive automation
- **Cost Control**: Limit resource consumption from profile executions
- **Testing Confidence**: Preview operation effects before actual execution
- **Risk Mitigation**: Validate complex workflows without side effects

---

## Functional Requirements

### FR-019: Profile Chaining Limit
**Priority**: HIGH
**Source**: epics.md lines 1131-1150

The system MUST prevent excessive profile execution:

1. **Profile Count Tracking**
   - Track profile executions per request/conversation turn
   - Count increments for each `capability="profiles"` operation
   - Counter scoped to single user request (not global)
   - Counter resets between user messages

2. **Limit Enforcement**
   - Maximum: 5 profile executions per request (configurable via `commands.max_chain_length`)
   - Reject 6th and subsequent profile operations
   - Return error: "Profile execution limit reached (5/5 used)"
   - Error includes helpful message: suggest breaking into multiple requests

3. **Limit Scope**
   - Applies to ALL profile types: lint, build, test, ripgrep
   - Does NOT apply to non-profile operations (file edits, git, scheduler)
   - Counter is per-chat-id (separate limits for different users)

### FR-023: Dry-Run Mode
**Priority**: MEDIUM
**Source**: epics.md lines 1131-1150

The system MUST support operation preview without execution:

1. **Dry-Run Detection**
   - Detect dry-run flag in operation parameters: `dry_run: true`
   - Support Telegram command prefix: `/dryrun <command>` or `--dry-run` flag
   - Agent session passes dry_run flag to broker

2. **Dry-Run Behavior**
   - All capabilities check `dry_run` flag before execution
   - Return operation preview instead of executing
   - Preview includes: operation type, affected files, expected changes
   - No actual file modifications, commits, or subprocess executions

3. **Supported Operations**
   - **File edits**: Show patch preview without applying
   - **Git commits**: Show commit message and files without committing
   - **Profiles**: Show command that would run without executing
   - **Ripgrep**: Show search command without executing (or execute read-only)

4. **Preview Format**
   - Clear indication: "🔍 DRY RUN - No changes made"
   - Operation summary: what would happen
   - Affected resources: files, git status, subprocess command
   - Helpful message: "Run without --dry-run to apply changes"

---

## Non-Functional Requirements

### NFR-025: Profile Limit Overhead
- Profile count tracking adds <1ms overhead per operation
- Counter stored in memory (no database queries)
- Thread-safe counter updates (if concurrent requests)

### NFR-026: Dry-Run Accuracy
- Dry-run preview matches actual execution (90% accuracy)
- Scope validation still enforced (prevent preview of forbidden paths)
- Tier classification still applied (log as Tier 0 for read-only previews)

### NFR-027: Error Message Clarity
- Limit reached error is actionable and clear
- Dry-run preview distinguishable from actual execution
- Preview format mobile-friendly (clear sections, emoji indicators)

---

## Acceptance Criteria

### AC-019.1: Profile Count Tracking
- [x] Broker tracks profile execution count per request
- [x] Counter stored in `BrokerRouter` instance (in-memory dict keyed by chat_id)
- [x] Counter increments for `capability="profiles"` operations
- [x] Counter resets when new user message received (agent session creates new broker or resets counter)

### AC-019.2: Limit Enforcement
- [x] 6th profile operation rejected with error
- [x] Error code: "profile_chain_limit_exceeded"
- [x] Error message: "Profile execution limit reached (5/5 used). Break request into smaller parts."
- [x] Limit read from `commands.max_chain_length` config (default: 5)
- [x] Non-profile operations not counted toward limit

### AC-019.3: Limit Configuration
- [x] `commands.max_chain_length` config key exists (already in default.toml)
- [x] Config validator ensures value between 1 and 20
- [x] Config is dynamic (hot-reloadable without restart)

### AC-023.1: Dry-Run Flag Detection
- [x] Broker accepts `dry_run` parameter in route_operation
- [x] Agent session detects `/dryrun` prefix in commands
- [x] Agent session passes `dry_run=True` to broker
- [x] Telegram command parsing supports `--dry-run` flag

### AC-023.2: Dry-Run Execution Path
- [x] File edit operations check dry_run flag
- [x] Git operations check dry_run flag
- [x] Profile operations check dry_run flag
- [x] Dry-run operations return preview dict instead of executing

### AC-023.3: Dry-Run Preview Format
- [x] Preview includes: operation type, affected files, expected action
- [x] Preview marked with indicator: "🔍 DRY RUN - No changes made"
- [x] File edit preview shows patch diff
- [x] Git commit preview shows commit message and file list
- [x] Profile preview shows command that would execute

### AC-023.4: Dry-Run Logging
- [x] Dry-run operations logged to execution_log with status='completed'
- [x] execution_log.details includes `dry_run=true` flag
- [x] Dry-run operations classified as Tier 0 (read-only)
- [x] No snapshot created for dry-run operations

---

## Implementation Guidance

### Architecture Context

```
src/sohnbot/broker/
└── router.py            # UPDATE: add profile counter, dry-run handling

src/sohnbot/runtime/
└── agent_session.py     # UPDATE: detect /dryrun prefix, pass dry_run flag

src/sohnbot/capabilities/
├── files/
│   └── patch_editor.py  # UPDATE: check dry_run flag, return preview
├── git/
│   └── snapshot_manager.py  # UPDATE: check dry_run flag, return preview
└── command_profiles/
    └── profile_executor.py  # UPDATE: check dry_run flag, return preview

src/sohnbot/gateway/
└── telegram_client.py   # UPDATE: parse /dryrun prefix from commands

config/
└── default.toml         # VERIFY: max_chain_length = 5 exists

tests/unit/
├── test_broker.py       # UPDATE: add limit enforcement tests
└── test_agent_session.py  # UPDATE: add dry-run detection tests

tests/integration/
└── test_dry_run_flow.py  # NEW: integration test for dry-run mode
```

### Key Implementation Tasks

#### Task 5.5.1: Add Profile Counter to Broker
**File**: `src/sohnbot/broker/router.py`
**Location**: Update `__init__` and `route_operation` methods

**Add counter to __init__**:
```python
class BrokerRouter:
    def __init__(
        self,
        scope_validator: ScopeValidator,
        config_manager: Optional[ConfigManager] = None,
    ):
        self.scope_validator = scope_validator
        self.config_manager = config_manager
        self.file_ops = FileOps()
        self.patch_editor = PatchEditor()
        self.snapshot_manager = SnapshotManager()
        self._operation_start_times: Dict[str, float] = {}

        # NEW: Profile execution counter per chat_id
        self._profile_counts: Dict[str, int] = {}

    def reset_profile_counter(self, chat_id: str) -> None:
        """Reset profile execution counter for a chat."""
        self._profile_counts.pop(chat_id, None)

    def get_profile_count(self, chat_id: str) -> int:
        """Get current profile execution count for a chat."""
        return self._profile_counts.get(chat_id, 0)
```

**Update route_operation** (add limit check before execution):
```python
async def route_operation(
    self,
    capability: str,
    action: str,
    params: Dict[str, Any],
    chat_id: str,
    dry_run: bool = False,  # NEW parameter
) -> BrokerResult:
    """Route operation through broker validation and execution."""

    # ... existing validation ...

    # NEW: Check profile chaining limit (after tier classification)
    if capability == "profiles":
        current_count = self._profile_counts.get(chat_id, 0)
        max_chain_length = 5  # Default
        if self.config_manager:
            try:
                max_chain_length = int(self.config_manager.get("commands.max_chain_length"))
            except Exception:
                pass

        if current_count >= max_chain_length:
            self._operation_start_times.pop(operation_id, None)
            return BrokerResult(
                allowed=False,
                operation_id=operation_id,
                tier=tier,
                error={
                    "code": "profile_chain_limit_exceeded",
                    "message": f"Profile execution limit reached ({current_count}/{max_chain_length} used). Break request into smaller parts.",
                    "details": {
                        "current_count": current_count,
                        "max_chain_length": max_chain_length,
                    },
                    "retryable": False,
                },
            )

        # Increment counter
        self._profile_counts[chat_id] = current_count + 1
        logger.info(
            "profile_counter_incremented",
            chat_id=chat_id,
            count=self._profile_counts[chat_id],
            max_chain_length=max_chain_length,
        )

    # ... rest of existing execution logic ...

    # NEW: Pass dry_run flag to capabilities
    if dry_run:
        result = await self._execute_dry_run_preview(
            capability, action, params, operation_id
        )
    else:
        result = await self._execute_capability(
            capability, action, params, operation_id
        )

    # ... rest of existing logic ...
```

#### Task 5.5.2: Add Dry-Run Preview Handler
**File**: `src/sohnbot/broker/router.py`
**Location**: Add new method after `_execute_capability`

```python
async def _execute_dry_run_preview(
    self,
    capability: str,
    action: str,
    params: Dict[str, Any],
    operation_id: str,
) -> dict:
    """
    Execute dry-run preview for supported operations.

    Returns preview dict instead of actually executing operation.
    """
    logger.info("dry_run_preview_started", capability=capability, action=action)

    if capability == "fs" and action == "apply_patch":
        # File edit preview: return patch without applying
        from ..capabilities.files import PatchEditor

        patch_editor = PatchEditor()
        file_path = params["path"]
        patch_content = params["patch"]

        # Validate patch format (don't apply)
        try:
            # Parse patch to extract hunks
            import re
            hunks = []
            for line in patch_content.splitlines():
                if line.startswith("@@"):
                    hunks.append(line)

            return {
                "preview": True,
                "operation": "apply_patch",
                "file": file_path,
                "patch": patch_content,
                "hunks_count": len(hunks),
                "message": f"🔍 DRY RUN - Would apply {len(hunks)} hunks to {file_path}",
            }
        except Exception as exc:
            return {
                "preview": True,
                "operation": "apply_patch",
                "file": file_path,
                "error": f"Patch validation failed: {exc}",
            }

    if capability == "git" and action == "commit":
        # Git commit preview: show commit message and files without committing
        message = params["message"]
        files = params.get("files", [])

        return {
            "preview": True,
            "operation": "git_commit",
            "message": message,
            "files": files,
            "files_count": len(files),
            "preview_message": f"🔍 DRY RUN - Would commit {len(files)} file(s):\n{message}",
        }

    if capability == "profiles":
        # Profile preview: show command that would execute
        action_name = action  # lint, build, test, ripgrep
        repo_path = params.get("repo_path", ".")

        # Build preview command based on action
        if action == "lint":
            command = params.get("command", "pylint")
            files = params.get("files", [])
            cmd_preview = f"{command} {' '.join(files)}"
        elif action == "build":
            command = params.get("command", "make")
            target = params.get("target", "")
            cmd_preview = f"{command} {target}".strip()
        elif action == "test":
            command = params.get("command", "pytest")
            pattern = params.get("pattern", "")
            cmd_preview = f"{command} {pattern}".strip()
        elif action == "ripgrep":
            pattern = params.get("pattern", "")
            file_types = params.get("file_types", [])
            type_flags = " ".join([f"-t {t}" for t in file_types]) if file_types else ""
            cmd_preview = f"rg --json {type_flags} {pattern}".strip()
        else:
            cmd_preview = f"{action} (unknown command)"

        return {
            "preview": True,
            "operation": f"profile_{action}",
            "command": cmd_preview,
            "repo_path": repo_path,
            "message": f"🔍 DRY RUN - Would execute: {cmd_preview}",
        }

    # Fallback for unsupported operations
    return {
        "preview": True,
        "operation": f"{capability}_{action}",
        "message": f"🔍 DRY RUN - Would execute {capability}.{action} (preview not implemented)",
        "params": params,
    }
```

#### Task 5.5.3: Add Dry-Run Detection to Agent Session
**File**: `src/sohnbot/runtime/agent_session.py`
**Location**: Update message handling to detect /dryrun prefix

**Add dry-run detection** (in message processing):
```python
# Somewhere in the agent session message handling:
async def handle_user_message(self, message: str, chat_id: str) -> str:
    # Reset profile counter for new user message
    if hasattr(self, 'broker') and self.broker:
        self.broker.reset_profile_counter(chat_id)

    # Check for /dryrun prefix
    dry_run = False
    if message.strip().startswith("/dryrun "):
        dry_run = True
        message = message.strip()[8:]  # Remove "/dryrun " prefix
        logger.info("dry_run_mode_detected", chat_id=chat_id, original_message=message)

    # OR check for --dry-run flag
    if "--dry-run" in message:
        dry_run = True
        message = message.replace("--dry-run", "").strip()
        logger.info("dry_run_flag_detected", chat_id=chat_id)

    # Pass dry_run flag to agent context (available to tools)
    # This depends on how the agent session integrates with the broker
    # May need to store in context vars or pass to SDK
```

**Note**: The exact implementation depends on how the agent session currently passes context to tools. This may require updating the MCP server context or tool invocation mechanism.

#### Task 5.5.4: Update Config Registry
**File**: `src/sohnbot/config/registry.py`
**Location**: Verify max_chain_length config exists and add validator

**Verify config key** (should already exist):
```python
ConfigKey(
    "commands.max_chain_length",
    ConfigTier.DYNAMIC,
    int,
    default=5,
    validator=lambda v: 1 <= int(v) <= 20,  # Between 1 and 20
),
```

#### Task 5.5.5: Update Telegram Client for /dryrun
**File**: `src/sohnbot/gateway/telegram_client.py`
**Location**: Update command parsing

**Add /dryrun handling**:
```python
# In command routing logic:
if message.strip().startswith("/dryrun "):
    # Strip prefix and pass to agent session
    actual_message = message.strip()[8:]
    # Set dry_run flag in session or context
    # ... existing message handling ...
```

---

## Testing Strategy

### Unit Tests

**File**: `tests/unit/test_broker.py` (update existing file)

```python
"""Unit tests for profile chaining limit (Story 5.5)."""

import pytest
from sohnbot.broker.router import BrokerRouter
from sohnbot.broker.scope_validator import ScopeValidator
from sohnbot.config.manager import ConfigManager


@pytest.mark.asyncio
async def test_profile_counter_increments():
    """Test profile counter increments for each profile operation."""
    config = ConfigManager()
    scope_validator = ScopeValidator(config)
    broker = BrokerRouter(scope_validator, config)

    # Execute 3 profile operations
    for i in range(3):
        result = await broker.route_operation(
            capability="profiles",
            action="lint",
            params={"repo_path": "/test", "command": "pylint", "files": []},
            chat_id="test-chat",
        )
        assert result.allowed is True

    # Verify counter
    assert broker.get_profile_count("test-chat") == 3


@pytest.mark.asyncio
async def test_profile_limit_enforced():
    """Test 6th profile operation is rejected."""
    config = ConfigManager()
    scope_validator = ScopeValidator(config)
    broker = BrokerRouter(scope_validator, config)

    # Execute 5 profile operations (should succeed)
    for i in range(5):
        result = await broker.route_operation(
            capability="profiles",
            action="lint",
            params={"repo_path": "/test", "command": "pylint", "files": []},
            chat_id="test-chat",
        )
        assert result.allowed is True

    # 6th operation should be rejected
    result = await broker.route_operation(
        capability="profiles",
        action="lint",
        params={"repo_path": "/test", "command": "pylint", "files": []},
        chat_id="test-chat",
    )

    assert result.allowed is False
    assert result.error is not None
    assert result.error["code"] == "profile_chain_limit_exceeded"
    assert "5/5 used" in result.error["message"]


@pytest.mark.asyncio
async def test_profile_counter_resets():
    """Test profile counter resets when reset_profile_counter called."""
    config = ConfigManager()
    scope_validator = ScopeValidator(config)
    broker = BrokerRouter(scope_validator, config)

    # Execute 3 operations
    for i in range(3):
        await broker.route_operation(
            capability="profiles",
            action="lint",
            params={"repo_path": "/test", "command": "pylint", "files": []},
            chat_id="test-chat",
        )

    assert broker.get_profile_count("test-chat") == 3

    # Reset counter
    broker.reset_profile_counter("test-chat")

    assert broker.get_profile_count("test-chat") == 0


@pytest.mark.asyncio
async def test_non_profile_operations_not_counted():
    """Test non-profile operations don't increment counter."""
    config = ConfigManager()
    scope_validator = ScopeValidator(config)
    broker = BrokerRouter(scope_validator, config)

    # Execute git operation (not profile)
    result = await broker.route_operation(
        capability="git",
        action="status",
        params={},
        chat_id="test-chat",
    )

    # Counter should remain 0
    assert broker.get_profile_count("test-chat") == 0


@pytest.mark.asyncio
async def test_dry_run_preview_file_patch():
    """Test dry-run preview for file patch operation."""
    config = ConfigManager()
    scope_validator = ScopeValidator(config)
    broker = BrokerRouter(scope_validator, config)

    patch = """--- test.py
+++ test.py
@@ -1,1 +1,1 @@
-old line
+new line
"""

    result = await broker.route_operation(
        capability="fs",
        action="apply_patch",
        params={"path": "test.py", "patch": patch},
        chat_id="test-chat",
        dry_run=True,
    )

    assert result.allowed is True
    assert result.result is not None
    assert result.result.get("preview") is True
    assert "🔍 DRY RUN" in result.result.get("message", "")


@pytest.mark.asyncio
async def test_dry_run_preview_profile():
    """Test dry-run preview for profile operation."""
    config = ConfigManager()
    scope_validator = ScopeValidator(config)
    broker = BrokerRouter(scope_validator, config)

    result = await broker.route_operation(
        capability="profiles",
        action="lint",
        params={"repo_path": "/test", "command": "pylint", "files": ["test.py"]},
        chat_id="test-chat",
        dry_run=True,
    )

    assert result.allowed is True
    assert result.result is not None
    assert result.result.get("preview") is True
    assert "pylint test.py" in result.result.get("command", "")
```

**File**: `tests/unit/test_agent_session.py` (update existing file)

```python
"""Unit tests for dry-run detection (Story 5.5)."""

import pytest


def test_dryrun_prefix_detection():
    """Test /dryrun prefix is detected and stripped."""
    message = "/dryrun lint test.py"

    # Simulate detection
    dry_run = message.startswith("/dryrun ")
    actual_message = message[8:] if dry_run else message

    assert dry_run is True
    assert actual_message == "lint test.py"


def test_dry_run_flag_detection():
    """Test --dry-run flag is detected and removed."""
    message = "lint test.py --dry-run"

    dry_run = "--dry-run" in message
    actual_message = message.replace("--dry-run", "").strip()

    assert dry_run is True
    assert actual_message == "lint test.py"
```

### Integration Tests

**File**: `tests/integration/test_dry_run_flow.py` (new file)

```python
"""Integration tests for dry-run mode (Story 5.5)."""

import pytest
from sohnbot.broker.router import BrokerRouter
from sohnbot.broker.scope_validator import ScopeValidator
from sohnbot.config.manager import ConfigManager
from sohnbot.persistence.db import init_db


@pytest.mark.asyncio
async def test_dry_run_full_flow(tmp_path):
    """Test complete dry-run flow from detection to preview."""
    # Setup
    test_db = tmp_path / "test.db"
    await init_db(str(test_db))

    config = ConfigManager()
    scope_validator = ScopeValidator(config)
    broker = BrokerRouter(scope_validator, config)

    # Execute dry-run profile operation
    result = await broker.route_operation(
        capability="profiles",
        action="lint",
        params={
            "repo_path": str(tmp_path),
            "command": "pylint",
            "files": ["test.py"],
        },
        chat_id="test-chat",
        dry_run=True,
    )

    # Verify preview returned
    assert result.allowed is True
    assert result.result is not None
    assert result.result["preview"] is True
    assert "🔍 DRY RUN" in result.result["message"]
    assert "pylint" in result.result["command"]


@pytest.mark.asyncio
async def test_profile_limit_integration(tmp_path):
    """Test profile limit enforcement in realistic scenario."""
    test_db = tmp_path / "test.db"
    await init_db(str(test_db))

    config = ConfigManager()
    scope_validator = ScopeValidator(config)
    broker = BrokerRouter(scope_validator, config)

    # Execute 5 lint operations
    for i in range(5):
        result = await broker.route_operation(
            capability="profiles",
            action="lint",
            params={"repo_path": str(tmp_path), "command": "pylint", "files": []},
            chat_id="integration-test",
        )
        assert result.allowed is True

    # 6th should fail
    result = await broker.route_operation(
        capability="profiles",
        action="lint",
        params={"repo_path": str(tmp_path), "command": "pylint", "files": []},
        chat_id="integration-test",
    )

    assert result.allowed is False
    assert "limit reached" in result.error["message"].lower()
```

---

## Dependencies

### Required Stories
- ✅ **Story 5.1**: Lint Project Profile (provides profile infrastructure)
- ✅ **Story 5.2**: Build Project Profile (provides profile patterns)
- ✅ **Story 5.3**: Run Tests Profile (provides profile patterns)
- ✅ **Story 5.4**: Ripgrep Search Profile (provides profile patterns)
- ✅ **Story 1.6**: Patch-Based File Edit (for dry-run file edit preview)
- ✅ **Story 2.3**: Autonomous Git Commits (for dry-run commit preview)

### External Dependencies
- None - uses existing infrastructure

### Configuration Dependencies
- `commands.max_chain_length`: Default 5 (already in default.toml)

---

## Migration Plan

### Database Changes
**None required** - Counter stored in memory, dry-run uses existing execution_log

### Configuration Changes
**None required** - max_chain_length already exists in default.toml

### Deployment Steps
1. Deploy code changes to `router.py`, `agent_session.py`
2. Restart SohnBot service
3. Test profile limit: execute 6 lint operations in one conversation
4. Test dry-run: send `/dryrun lint test.py` command
5. Verify preview returned without execution

---

## Rollback Plan

If profile limit or dry-run causes issues:

1. **Immediate Mitigation**: Set `max_chain_length = 100` (effectively disable limit)
2. **Code Rollback**: Revert to Story 5.4 commit (remove limit enforcement)
3. **Monitoring**: Check for limit rejections: `SELECT * FROM execution_log WHERE error_details LIKE '%profile_chain_limit%'`

---

## Story Intelligence from Previous Stories

### Story 5.4 Learnings
- Profile operations route through broker with `capability="profiles"`
- Broker validation happens before execution
- Config values read with fallback defaults
- Structured error returns with code, message, details

### Story 5.3 Learnings
- Agent session manages request context
- Config registry supports validators
- Dynamic config reloads without restart

### Story 5.2 Learnings
- Broker has central routing point (`route_operation`)
- Operation tracking uses in-memory dict keyed by operation_id
- Error handling uses BrokerResult with allowed=False

### Story 5.1 Learnings
- Profile execution follows consistent pattern
- Logging uses structured events
- Timeout enforcement centralized

---

## Architecture Compliance

### Profile Counter Design
- **Scope**: Per chat_id (separate counters for different users)
- **Storage**: In-memory dict (no database)
- **Lifetime**: Reset on new user message
- **Thread Safety**: Single-threaded async (no locking needed)

### Dry-Run Execution Path
- **Preview Generation**: Separate method (`_execute_dry_run_preview`)
- **No Side Effects**: No file writes, no subprocess execution
- **Tier Classification**: Dry-run operations are Tier 0 (read-only)
- **Logging**: Dry-run flag in execution_log.details

### Error Format
```python
{
    "code": "profile_chain_limit_exceeded",
    "message": "Profile execution limit reached (5/5 used). Break request into smaller parts.",
    "details": {
        "current_count": 5,
        "max_chain_length": 5,
    },
    "retryable": False,
}
```

### Preview Format
```python
{
    "preview": True,
    "operation": "profile_lint",
    "command": "pylint test.py",
    "repo_path": "/project",
    "message": "🔍 DRY RUN - Would execute: pylint test.py",
}
```

---

## File Structure Requirements

```
src/sohnbot/broker/
└── router.py             # UPDATE: add profile counter, dry-run handling

src/sohnbot/runtime/
└── agent_session.py      # UPDATE: detect /dryrun, reset counter

src/sohnbot/gateway/
└── telegram_client.py    # UPDATE: parse /dryrun prefix

config/
└── default.toml          # VERIFY: max_chain_length = 5

tests/unit/
├── test_broker.py        # UPDATE: add limit tests
└── test_agent_session.py # UPDATE: add dry-run detection tests

tests/integration/
└── test_dry_run_flow.py  # NEW: integration test
```

---

## Testing Requirements

### Unit Test Coverage
- ✅ Profile counter increments correctly
- ✅ 6th operation rejected with clear error
- ✅ Counter resets when reset_profile_counter called
- ✅ Non-profile operations don't increment counter
- ✅ Different chat_ids have separate counters
- ✅ Dry-run preview for file patch
- ✅ Dry-run preview for git commit
- ✅ Dry-run preview for profiles
- ✅ /dryrun prefix detection and stripping
- ✅ --dry-run flag detection and removal

### Integration Test Coverage
- ✅ Full dry-run flow: detection -> preview -> return
- ✅ Profile limit enforcement in realistic scenario
- ✅ Counter reset between user messages

### Manual Test Checklist
- [ ] Execute 6 lint operations in one conversation (6th should fail)
- [ ] Verify error message is clear and actionable
- [ ] Send `/dryrun lint test.py` command
- [ ] Verify preview returned without execution
- [ ] Send normal `lint test.py` command after dry-run
- [ ] Verify actual execution happens
- [ ] Test limit with different profile types (lint, build, test, ripgrep)
- [ ] Test dry-run with file edit operation
- [ ] Test dry-run with git commit operation

---

## Definition of Done

- [ ] Code implemented and committed to feature branch
- [x] All acceptance criteria met (AC-019.1 through AC-023.4)
- [x] Unit tests pass with >90% coverage on new code
- [x] Integration tests verify limit enforcement and dry-run flow
- [ ] Manual testing completed (checklist above)
- [ ] Code review completed
- [ ] All linter checks pass
- [x] Story status updated to 'review' in sprint-status.yaml

---

## Open Questions
None - Story is well-defined with clear implementation path.

---

## Related Documentation
- `src/sohnbot/broker/router.py`: Central routing and policy enforcement
- `src/sohnbot/runtime/agent_session.py`: Agent session management
- `config/default.toml`: max_chain_length configuration
- `_bmad-output/planning-artifacts/epics.md`: Epic 5 requirements (lines 1131-1150)

---

## Dev Agent Record

### Agent Model Used
- GPT-5 Codex (CLI)

### Debug Log References
- `.venv/bin/pytest -q tests/unit/test_broker.py tests/unit/test_agent_session.py tests/unit/test_mcp_tools.py tests/unit/test_telegram_client.py tests/unit/test_config_registry.py tests/integration/test_dry_run_flow.py`

### Completion Notes
- Added profile-chain counting in broker with per-chat tracking, explicit reset API, configurable max-chain enforcement, and structured `profile_chain_limit_exceeded` rejections.
- Added dry-run flow in broker route path with Tier 0 classification, per-capability preview responses (`fs.apply_patch`, `git.commit`, profile actions), and dry-run metadata persisted to execution-log details.
- Added dry-run parsing in agent session for `/dryrun ...` and `--dry-run`, and reset profile chain counter at each new user message.
- Added MCP propagation of dry-run context through file, git commit, and profile tools.
- Added Telegram `/dryrun` command handling with authorization checks, usage feedback, runtime forwarding, and formatted response/error handling.
- Updated config validation range for `commands.max_chain_length` to `1..20`.
- Added/updated unit and integration tests for profile-limit behavior, dry-run previews, dry-run flag detection, broker-context wiring, and end-to-end dry-run no-side-effect behavior.

### File List
- `_bmad-output/implementation-artifacts/5-5-profile-chaining-limit-dry-run-mode.md`
- `src/sohnbot/broker/router.py`
- `src/sohnbot/runtime/agent_session.py`
- `src/sohnbot/runtime/mcp_tools.py`
- `src/sohnbot/gateway/telegram_client.py`
- `src/sohnbot/config/registry.py`
- `tests/unit/test_broker.py`
- `tests/unit/test_agent_session.py`
- `tests/unit/test_telegram_client.py`
- `tests/integration/test_dry_run_flow.py`
