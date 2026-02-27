# Story 1.7: Rollback to Previous Snapshot

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to restore files to any previous snapshot,
so that I can recover from unwanted changes.

## Acceptance Criteria

**Given** snapshot branches exist (snapshot/*)
**When** I request to rollback to a specific snapshot
**Then** available snapshots are listed with timestamps
**And** selected snapshot is checked out (preserves git history, creates new commit)
**And** rollback operation completes in <30s (NFR-007)
**And** operation is logged to execution_log as Tier 1
**And** notification confirms successful rollback with branch name

## Tasks / Subtasks

- [x] Extend `SnapshotManager` with rollback operations (AC: list snapshots, rollback to snapshot)
  - [x] Add `list_snapshots(repo_path: str) -> list[dict]` — returns snapshot branches with metadata
  - [x] Parse snapshot branch names: `snapshot/edit-YYYY-MM-DD-HHMM(-suffix)?`
  - [x] Extract timestamp from branch name and return formatted list
  - [x] Add `rollback_to_snapshot(repo_path: str, snapshot_ref: str, operation_id: str) -> dict` — restores files from snapshot
  - [x] Use `git checkout <snapshot_ref> -- .` to restore all files from snapshot branch
  - [x] Create commit with message: `Rollback to snapshot: <snapshot_ref> (operation: <operation_id[:8]>)`
  - [x] Command sequence: `git checkout <snapshot_ref> -- .` then `git commit -m "..."`
  - [x] Return `{"snapshot_ref": str, "commit_hash": str, "files_restored": int}`
  - [x] Raise `GitCapabilityError` on all failures with codes: `snapshot_not_found`, `rollback_failed`, `commit_failed`

- [x] Add git capability routing to broker (AC: broker integration)
  - [x] In `src/sohnbot/broker/router.py`: add `"git"` capability handling to `route_operation()`
  - [x] Add parameter validation for `git` operations (validate `snapshot_ref` is non-empty for rollback)
  - [x] Add `_execute_capability()` routing for `"git"` capability with actions: `list_snapshots`, `rollback`
  - [x] Wire `SnapshotManager.list_snapshots()` and `SnapshotManager.rollback_to_snapshot()`
  - [x] Update tier classification: `operation_classifier.py` maps `("git", "rollback")` to Tier 1
  - [x] Rollback operations do NOT create snapshots (they restore to snapshots) — skip `_create_snapshot()` call for git.rollback

- [x] Create MCP tools for git operations (AC: MCP integration)
  - [x] In `src/sohnbot/runtime/mcp_tools.py`: add `git__list_snapshots` tool
  - [x] Tool schema: `{"type": "function", "function": {"name": "git__list_snapshots", "parameters": {"repo_path": "string"}}}`
  - [x] Returns formatted list: `Available snapshots:\n1. snapshot/edit-2026-02-27-1430 (Feb 27, 2026 14:30 UTC)\n2. ...`
  - [x] Add `git__rollback` tool
  - [x] Tool schema: `{"type": "function", "function": {"name": "git__rollback", "parameters": {"repo_path": "string", "snapshot_ref": "string"}}}`
  - [x] Response format: `✅ Restored to snapshot: <snapshot_ref>. Commit: <commit_hash[:8]>. Files: <count>`
  - [x] On error: `❌ Operation denied: <message>` (existing pattern)
  - [x] Both tools route through broker for scope validation and audit logging

- [x] Notification for rollback operations (AC: notification)
  - [x] Update broker's `_send_notification()` to handle `git.rollback` operations
  - [x] Message format: `✅ Rollback complete. Restored to: <snapshot_ref>. Commit: <commit_hash[:8]>`
  - [x] Notification is best-effort (failure does NOT block BrokerResult)

- [x] Testing (AC: all)
  - [x] Unit tests `tests/unit/test_snapshot_manager.py` (extend existing file): `list_snapshots` parsing, `rollback_to_snapshot` happy path, error codes (12 new tests)
  - [x] Integration tests `tests/integration/test_rollback_operations.py`: full broker route, `execution_log` populated, scope validation, notification sent (8 tests)
  - [x] Full regression: 224 passed, 5 skipped (baseline from story 1.6; add ~20 new tests)

## Dev Notes

### Critical Architecture Requirements

- **Broker is the enforcement boundary for git operations**: Just like file operations, git rollback must route through broker for scope validation, audit logging, and tier classification. The `SnapshotManager` should NOT do scope validation — it only performs git operations.
  [Source: _bmad-output/planning-artifacts/architecture.md#Core Architectural Requirements]

- **NO history rewriting**: Rollback uses `git checkout <snapshot_ref> -- .` (restore files) + `git commit` (preserve history), NOT `git reset --hard` or `git revert`. This maintains complete audit trail and allows forward recovery if needed.
  [Source: _bmad-output/planning-artifacts/epics.md#Story 1.7 Implementation Notes]

- **Validation order for git operations** — follow this exact sequence in `router.py`:
  ```
  1. Hook allowlist gate (already enforced via PreToolUse)
  2. Broker: generate operation_id, classify tier → ("git", "rollback") = Tier 1
  3. Broker: validate params (repo_path, snapshot_ref non-empty)
  4. Broker: scope validation on repo_path (repo must be within configured scope roots)
  5. Broker: log_operation_start()
  6. Broker: SKIP _create_snapshot() for git.rollback (rollback operations don't need snapshots)
  7. Capability: SnapshotManager.rollback_to_snapshot()
  8. Broker: log_operation_end(snapshot_ref=..., duration_ms=...)
  9. Notification (best-effort)
  ```
  [Source: _bmad-output/implementation-artifacts/1-6-patch-based-file-edit-with-snapshot-creation.md#Validation Order]

- **Tier 1 classification**: `operation_classifier.py` needs a new entry for `("git", "rollback")` → Tier 1. Rollback is a modification operation but doesn't need a snapshot (it IS the snapshot restoration).

- **Scope validation applies to repo paths**: The broker's `ScopeValidator` checks file paths. For git operations, validate that the `repo_path` is within configured scope roots (same validation logic).

### Technical Requirements

**Extend `SnapshotManager` (`src/sohnbot/capabilities/git/snapshot_manager.py`):**

```python
class SnapshotManager:
    # Existing: create_snapshot, find_repo_root, _run_git_branch

    def list_snapshots(self, repo_path: str) -> list[dict[str, Any]]:
        """
        List all snapshot branches in the repository.

        Returns:
            List of dicts: [{"ref": "snapshot/edit-...", "timestamp": "2026-02-27 14:30 UTC"}, ...]

        Implementation:
            1. Run: git -C <repo_path> branch --list "snapshot/*"
            2. Parse each line: "  snapshot/edit-YYYY-MM-DD-HHMM(-suffix)?"
            3. Extract timestamp from name: YYYY-MM-DD-HHMM → "Feb 27, 2026 14:30 UTC"
            4. Return sorted by timestamp descending (newest first)
            5. If git fails: raise GitCapabilityError(code="list_snapshots_failed")
        """

    async def rollback_to_snapshot(
        self,
        repo_path: str,
        snapshot_ref: str,
        operation_id: str,
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        """
        Restore files from a snapshot branch without rewriting history.

        Args:
            repo_path: Absolute path to git repository root
            snapshot_ref: Snapshot branch name (e.g., "snapshot/edit-2026-02-27-1430")
            operation_id: UUID tracking ID for commit message
            timeout_seconds: Maximum time for git operations (default: 30s per NFR-007)

        Returns:
            {"snapshot_ref": str, "commit_hash": str, "files_restored": int}

        Raises:
            GitCapabilityError: snapshot_not_found, rollback_failed, commit_failed

        Implementation:
            1. Verify snapshot exists: git -C <repo_path> rev-parse --verify <snapshot_ref>
               - On failure: GitCapabilityError(code="snapshot_not_found")
            2. Restore files: git -C <repo_path> checkout <snapshot_ref> -- .
               - This restores ALL files from snapshot to working directory
               - Keeps current branch unchanged (no checkout of snapshot branch)
            3. Create commit: git -C <repo_path> commit -m "Rollback to snapshot: <snapshot_ref> (operation: <operation_id[:8]>)"
               - If no changes (already at snapshot state): return early with commit_hash from HEAD
            4. Get commit hash: git -C <repo_path> rev-parse --short HEAD
            5. Count files changed: git -C <repo_path> diff-tree --no-commit-id --name-only -r HEAD | wc -l
            6. Return dict with snapshot_ref, commit_hash, files_restored
        """
```

- **Error handling**: All git subprocess failures must raise `GitCapabilityError` with appropriate codes and structured messages. Reuse the existing `GitCapabilityError` dataclass (already in `snapshot_manager.py` from story 1.6).

- **Timeout enforcement**: Use `asyncio.wait_for()` with timeout_seconds for all git commands (same pattern as `create_snapshot()`). Default timeout: 30s (per NFR-007).

- **Git command safety**: All commands use `git -C <repo_path>` to ensure operations run in correct repository context, not current working directory.

**Update `BrokerRouter` in `src/sohnbot/broker/router.py`:**

```python
# In route_operation():
if capability == "git":
    # Validate required parameters
    if action == "list_snapshots" and "repo_path" not in params:
        return BrokerResult(allowed=False, operation_id=operation_id, error={"code": "missing_repo_path", "message": "repo_path required"})
    if action == "rollback" and ("repo_path" not in params or "snapshot_ref" not in params):
        return BrokerResult(allowed=False, operation_id=operation_id, error={"code": "missing_params", "message": "repo_path and snapshot_ref required"})

    # Scope validation: repo_path must be within configured roots
    repo_path = params.get("repo_path")
    if repo_path:
        scope_result = self.scope_validator.validate_path(repo_path)
        if not scope_result.allowed:
            return BrokerResult(allowed=False, operation_id=operation_id, tier=tier, error=scope_result.to_dict())

# In _execute_capability(), add after existing "fs" block:
if capability == "git":
    timeout = self.config_manager.get("git.operation_timeout_seconds") if self.config_manager else 30
    if action == "list_snapshots":
        return {"snapshots": self.snapshot_manager.list_snapshots(params["repo_path"])}
    if action == "rollback":
        return await self.snapshot_manager.rollback_to_snapshot(
            repo_path=params["repo_path"],
            snapshot_ref=params["snapshot_ref"],
            operation_id=operation_id,
            timeout_seconds=timeout,
        )

# IMPORTANT: Skip _create_snapshot() for git.rollback
# In route_operation() after tier classification, add check:
# if capability == "git" and action == "rollback":
#     snapshot_ref = None  # Don't create snapshot for rollback operations
# else:
#     if tier in (1, 2):
#         snapshot_ref = await self._create_snapshot(operation_id, params.get("path"))
```

**Add tier classification in `src/sohnbot/broker/operation_classifier.py`:**

```python
def classify_tier(capability: str, action: str, file_count: int) -> int:
    # ... existing code ...

    # Git operations
    if capability == "git":
        if action in {"status", "diff"}:
            return 0  # Read-only (future stories)
        if action == "rollback":
            return 1  # Single-repo modification
        if action == "commit":
            return 2  # Multi-file modification (future stories)

    return 2  # Default: Tier 2
```

**Add MCP tools in `src/sohnbot/runtime/mcp_tools.py`:**

```python
# Add to tool list:
{
    "type": "function",
    "function": {
        "name": "git__list_snapshots",
        "description": "List available snapshot branches with timestamps",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to git repository"},
            },
            "required": ["repo_path"],
        },
    },
},
{
    "type": "function",
    "function": {
        "name": "git__rollback",
        "description": "Restore files to a previous snapshot state",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to git repository"},
                "snapshot_ref": {"type": "string", "description": "Snapshot branch name (e.g., snapshot/edit-2026-02-27-1430)"},
            },
            "required": ["repo_path", "snapshot_ref"],
        },
    },
},

# Add handler functions:
async def git__list_snapshots(repo_path: str) -> str:
    """Route git list_snapshots through broker."""
    result = await broker.route_operation("git", "list_snapshots", {"repo_path": repo_path}, chat_id)
    if not result.allowed:
        return f"❌ Operation denied: {result.error.get('message', 'Unknown error')}"
    snapshots = result.result.get("snapshots", [])
    if not snapshots:
        return "No snapshots found."
    lines = ["Available snapshots:"]
    for i, snap in enumerate(snapshots, 1):
        lines.append(f"{i}. {snap['ref']} ({snap['timestamp']})")
    return "\n".join(lines)

async def git__rollback(repo_path: str, snapshot_ref: str) -> str:
    """Route git rollback through broker."""
    result = await broker.route_operation("git", "rollback", {"repo_path": repo_path, "snapshot_ref": snapshot_ref}, chat_id)
    if not result.allowed:
        return f"❌ Operation denied: {result.error.get('message', 'Unknown error')}"
    data = result.result
    return f"✅ Restored to snapshot: {data['snapshot_ref']}. Commit: {data['commit_hash']}. Files: {data['files_restored']}"
```

### Architecture Compliance

- **Broker layer responsibilities** (keep unchanged from story 1.6):
  - Scope validation: broker only
  - Tier classification: `operation_classifier.py` only
  - Audit logging: `persistence/audit.py` only
  - Snapshot creation: broker `_create_snapshot()` only (SKIP for git.rollback)

- **SnapshotManager scope**: git operations only (create_snapshot, list_snapshots, rollback_to_snapshot), no scope validation

- **Error shapes MUST use `{code, message, details, retryable}`**: `GitCapabilityError.to_dict()` is already canonical from story 1.6

- **No database migration needed**: `execution_log` already has `snapshot_ref` column; rollback operations will populate it with the snapshot being restored to

### Library / Framework Requirements

- **Git CLI (already required)**: `git` must be in PATH (documented in README from story 1.6)
  - Commands used: `git branch --list`, `git rev-parse --verify`, `git checkout <ref> -- .`, `git commit`, `git rev-parse --short`, `git diff-tree`
  - All commands use `git -C <repo_path>` for safe execution context

- **`asyncio.create_subprocess_exec`** for git commands — same pattern as story 1.6 `create_snapshot()`

- **`datetime.strptime`** for parsing snapshot timestamps from branch names (format: `YYYY-MM-DD-HHMM`)

- **`structlog`** for structured logging — consistent with all existing modules

- Maintain: `ruff check src/`, `mypy src/`, `pytest tests/` all clean

### File Structure Requirements

**Files to modify:**
- `src/sohnbot/capabilities/git/snapshot_manager.py` — add `list_snapshots()` and `rollback_to_snapshot()` methods
- `src/sohnbot/broker/router.py` — add `"git"` capability routing, param validation, skip snapshot creation for rollback
- `src/sohnbot/broker/operation_classifier.py` — add `("git", "rollback")` → Tier 1 mapping
- `src/sohnbot/runtime/mcp_tools.py` — add `git__list_snapshots` and `git__rollback` tools with handlers
- `tests/unit/test_snapshot_manager.py` — extend with new method tests (12 new tests)

**New test files:**
- `tests/integration/test_rollback_operations.py` — full broker route tests for git operations (8 tests)

### Testing Requirements

**Unit tests `tests/unit/test_snapshot_manager.py` (extend existing):**
- `list_snapshots` happy path: returns sorted list with parsed timestamps
- `list_snapshots` with no snapshots: returns empty list
- `list_snapshots` git failure: raises `GitCapabilityError(code="list_snapshots_failed")`
- `rollback_to_snapshot` happy path: restores files, creates commit, returns data
- `rollback_to_snapshot` snapshot not found: raises `GitCapabilityError(code="snapshot_not_found")`
- `rollback_to_snapshot` checkout failure: raises `GitCapabilityError(code="rollback_failed")`
- `rollback_to_snapshot` commit failure: raises `GitCapabilityError(code="commit_failed")`
- `rollback_to_snapshot` timeout: raises `GitCapabilityError(code="snapshot_timeout")`
- `rollback_to_snapshot` no changes: returns commit_hash from HEAD
- Mock `asyncio.create_subprocess_exec` — same approach as existing tests in `test_snapshot_manager.py`

**Integration tests `tests/integration/test_rollback_operations.py`:**
- Full broker route: `broker.route_operation("git", "list_snapshots", {"repo_path": ...}, chat_id)` → success
- Full broker route: `broker.route_operation("git", "rollback", {"repo_path": ..., "snapshot_ref": ...}, chat_id)` → success
- Verify `execution_log.snapshot_ref` is populated with restored snapshot name
- Verify `execution_log.tier == 1` for git.rollback
- Verify scope validation blocks rollback outside configured roots
- Verify notification sent after successful rollback (best-effort)
- Regression: `pytest tests/` full suite must pass (baseline 224 passed, 5 skipped from story 1.6)

### Previous Story Intelligence (From 1.6)

- **Reuse `GitCapabilityError` from `snapshot_manager.py`**: Same dataclass shape, same `to_dict()` method. Add new error codes: `snapshot_not_found`, `rollback_failed`, `commit_failed`, `list_snapshots_failed`.

- **`asyncio.create_subprocess_exec` pattern is established**: create process → `asyncio.wait_for(process.communicate(), timeout=...)` → `process.kill()` on timeout. Use identically for all new git commands.

- **Broker routing pattern** from story 1.6: Each capability gets param validation, scope validation, tier classification, then `_execute_capability()` routes to the right method. Follow the same pattern for `"git"` capability.

- **MCP tool pattern** from story 1.6: Tool schema → async handler function → `broker.route_operation()` → format result. Use identical pattern for git tools.

- **Test baseline is 224 passed, 5 skipped** (after story 1.6 fixes). Your changes must not decrease this count. Run full `pytest tests/ -v` before submitting for review.

- **Notification pattern** from story 1.6: `_send_notification()` in broker wraps gateway call in try/except, logs failure, never propagates error. Extend for `git.rollback` with format: `✅ Rollback complete. Restored to: <snapshot_ref>. Commit: <commit_hash[:8]>`.

### Git Intelligence Summary

Recent commits (from story 1.6 and review):
- `a4a5a38` Merge remote-tracking branch 'origin/claude/bmad-bmm-create-story-sGb00'
- `4570545` docs: update story 1.6 file list and CR notes for README update
- `d0a59cf` docs: document git and ripgrep as runtime CLI dependencies
- `03582de` Story 1.6 code review fixes: 2 HIGH + 5 MEDIUM + 1 LOW
- `f98bd99` Story 1.6: Implement patch-based file edit with snapshot creation

Key learnings:
- Story 1.6 established `SnapshotManager` and `GitCapabilityError` — reuse these
- Code review caught missing validations and hardcoded values — validate all params in broker
- Git CLI dependency is documented in README — no additional documentation needed
- Async subprocess pattern is proven and tested — follow it exactly

Workflow: implement → full test run → `code-review` before marking done. Story 1.6 required real fixes after review.

### Key Implementation Gotchas (Pre-emptive)

1. **Rollback does NOT create a snapshot**: The broker's `_create_snapshot()` call at line 173-175 in `router.py` must be SKIPPED for `git.rollback` operations. Rollback IS the snapshot restoration, not a modification that needs protection.

2. **`git checkout <ref> -- .` syntax**: The `-- .` is critical — it means "checkout all files from <ref> into working directory" WITHOUT switching branches. Omitting `-- .` would switch the current branch, which is NOT what we want.

3. **Commit after checkout**: After `git checkout <snapshot_ref> -- .`, the working directory has restored files but they're unstaged. You must `git commit` to persist the rollback. This creates a new commit on the current branch showing the rollback operation.

4. **Handle "no changes" case**: If the current state already matches the snapshot (user rolled back to same snapshot twice), `git checkout` succeeds but `git commit` will fail with "nothing to commit". Handle this gracefully: return current HEAD commit_hash and files_restored=0.

5. **Snapshot branch format parsing**: Snapshot names are `snapshot/edit-YYYY-MM-DD-HHMM` or `snapshot/edit-YYYY-MM-DD-HHMM-suffix`. Parse carefully: split on `/`, then on `-`, extract date/time components. Use `datetime.strptime("%Y-%m-%d-%H%M")` for timestamp.

6. **Scope validation for repo paths**: The `ScopeValidator` validates file paths. For git operations, pass the `repo_path` (not individual files) to scope validator. The repo root must be within configured scope roots.

7. **`git diff-tree` for file count**: After commit, count files changed with: `git diff-tree --no-commit-id --name-only -r HEAD | wc -l`. This gives the number of files in the commit.

8. **Async all the way**: `rollback_to_snapshot()` is async because it calls subprocess. Don't forget `await` when calling it from broker.

9. **Timeout budget**: Rollback has 3 git commands (rev-parse, checkout, commit). NFR-007 requires <30s total. Use the full 30s timeout for the entire operation, not per-command.

10. **Error messages must be actionable**: When snapshot_not_found, include the snapshot_ref in error details so user knows what failed. When rollback_failed, include stderr from git command.

### Project Structure Notes

- Follows subsystem layout: `capabilities/git/snapshot_manager.py` for git ops (established in story 1.6)
- Broker layer in `broker/router.py` (architectural heart)
- MCP tools in `runtime/mcp_tools.py` (agent interface)
- Operation classification in `broker/operation_classifier.py` (tier logic)
- All patterns established in stories 1.1-1.6 — no new architecture introduced

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 1.7: Rollback to Previous Snapshot]
- [Source: _bmad-output/planning-artifacts/architecture.md#Core Architectural Requirements]
- [Source: _bmad-output/planning-artifacts/architecture.md#Operation Risk Classification (Tier 1)]
- [Source: _bmad-output/planning-artifacts/prd.md#Tier 1: Single-File Scoped Edits]
- [Source: _bmad-output/implementation-artifacts/1-6-patch-based-file-edit-with-snapshot-creation.md#Validation Order]
- [Source: _bmad-output/implementation-artifacts/1-6-patch-based-file-edit-with-snapshot-creation.md#Git Intelligence Summary]
- [Source: src/sohnbot/capabilities/git/snapshot_manager.py#GitCapabilityError, create_snapshot pattern]
- [Source: src/sohnbot/broker/router.py#route_operation, _execute_capability]
- [Source: src/sohnbot/broker/operation_classifier.py#classify_tier]
- [Source: src/sohnbot/runtime/mcp_tools.py#MCP tool pattern]
- [Source: docs/PRD.md#FR-006: Rollback to Previous State]
- [Source: docs/PRD.md#NFR-007: Git operations <30s]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

None - implementation proceeded smoothly following established patterns from story 1.6

### Completion Notes List

- ✅ Implemented `list_snapshots()` in SnapshotManager: parses `snapshot/edit-YYYY-MM-DD-HHMM` branch names, extracts timestamps, returns sorted list (newest first)
- ✅ Implemented `rollback_to_snapshot()` in SnapshotManager: verifies snapshot exists, restores files via `git checkout <ref> -- .`, creates commit, handles "nothing to commit" case gracefully
- ✅ Added git capability routing to broker: parameter validation, scope validation for repo_path, execution routing for list_snapshots and rollback actions
- ✅ Modified snapshot creation logic: skips `_create_snapshot()` for git.rollback and git.list_snapshots (rollback IS the snapshot operation)
- ✅ Updated tier classification: added git operations with rollback and list_snapshots mapped to Tier 1
- ✅ Replaced git__rollback stub with real implementation, added git__list_snapshots tool in mcp_tools.py
- ✅ Added notification support for git.rollback: format includes snapshot_ref and commit_hash
- ✅ Extended unit tests: 9 new tests in test_snapshot_manager.py for list_snapshots and rollback_to_snapshot with all error paths
- ✅ Created integration tests: 8 tests in test_rollback_operations.py covering full broker route, scope validation, tier classification, notification
- ✅ All error codes properly handled: snapshot_not_found, rollback_failed, commit_failed, list_snapshots_failed, snapshot_timeout
- ✅ Followed all architecture patterns from story 1.6: async subprocess execution, timeout handling, structured error responses

### File List

**Modified files:**
- src/sohnbot/capabilities/git/snapshot_manager.py — added list_snapshots() and rollback_to_snapshot() methods
- src/sohnbot/broker/router.py — added git capability validation, routing, modified snapshot creation logic, added operation_id to _execute_capability
- src/sohnbot/broker/operation_classifier.py — added git operation tier mappings
- src/sohnbot/runtime/mcp_tools.py — replaced git__rollback stub, added git__list_snapshots tool
- tests/unit/test_snapshot_manager.py — added 9 new unit tests for list_snapshots and rollback_to_snapshot

**New files:**
- tests/integration/test_rollback_operations.py — 8 integration tests for git operations through broker

