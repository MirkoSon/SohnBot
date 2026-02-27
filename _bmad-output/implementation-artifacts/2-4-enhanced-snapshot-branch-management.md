# Story 2.4: Enhanced Snapshot Branch Management

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want automatic snapshot pruning and enhanced snapshot tracking,
So that snapshot branches don't accumulate indefinitely.

## Acceptance Criteria

**Given** snapshot branches accumulate over time
**When** snapshots are older than 30 days (configurable)
**Then** snapshots are auto-pruned weekly
**And** pruning is logged to execution_log
**And** snapshot naming follows: snapshot/[operation]-[YYYY-MM-DD-HHMM]
**And** snapshot count is tracked for observability (NFR-021)

## Tasks / Subtasks

- [x] Task 1: Implement prune_snapshots Function in snapshot_manager.py (AC: 1, 2)
  - [x] Add `prune_snapshots(repo_path: str, retention_days: int = 30, timeout_seconds: int = 60) -> dict` to `SnapshotManager`
  - [x] Use existing `list_snapshots()` to get all snapshot branches
  - [x] Parse timestamps from branch names: `snapshot/edit-YYYY-MM-DD-HHMM`
  - [x] Calculate age of each snapshot (compare to current UTC time)
  - [x] Delete snapshots older than `retention_days` using `git branch -D <branch>`
  - [x] Return structured dict: `{"pruned_count": int, "pruned_refs": list[str], "retained_count": int}`
  - [x] Reuse `GitCapabilityError` exception with codes: `prune_failed`, `prune_timeout`
  - [x] Enforce 60-second timeout (NFR-007)

- [x] Task 2: Handle Edge Cases and Safety (AC: 2)
  - [x] Skip current branch (don't prune if HEAD is on snapshot branch)
  - [x] Skip branches with unparseable timestamps (log warning)
  - [x] Handle empty snapshot list gracefully (return pruned_count=0)
  - [x] Handle git command failures gracefully (don't fail entire prune on single branch error)
  - [x] Log each pruned branch for audit trail

- [x] Task 3: Configuration Management (AC: 1)
  - [x] Add configuration key: `snapshot.retention_days` (default: 30)
  - [x] Document in `config/default.toml` with comment explaining pruning behavior
  - [x] Allow override via dynamic config (SQLite config table)
  - [x] Validate retention_days > 0

- [x] Task 4: Register MCP Tool (AC: All)
  - [x] Update `src/sohnbot/runtime/mcp_tools.py`
  - [x] Register `mcp__sohnbot__git__prune_snapshots` tool
  - [x] Input schema: `{"repo_path": str, "retention_days": int | None}` (repo_path required)
  - [x] Map tool call to `prune_snapshots()` function via broker

- [x] Task 5: Broker Integration (AC: 3)
  - [x] Update `src/sohnbot/broker/operation_classifier.py`
  - [x] Classify `prune_snapshots` as **Tier 1** (state-changing, deletes branches)
  - [x] Update `src/sohnbot/broker/router.py` to route `git.prune_snapshots` operations
  - [x] Ensure operation is logged to `execution_log` with start/end timestamps
  - [x] No snapshot creation before pruning (pruning is cleanup, not modification)

- [x] Task 6: Observability Integration (AC: 4)
  - [x] Add snapshot count tracking
  - [x] Expose via `list_snapshots()` return value (add total count)
  - [x] Log pruning operations with: repo_path, pruned_count, retained_count
  - [x] Enable future integration with Epic 3 observability

- [x] Task 7: Testing
  - [x] Add unit tests to `tests/unit/test_snapshot_manager.py` (minimum 8 new tests):
    - prune_snapshots with old snapshots (successful pruning)
    - prune_snapshots with retention_days parameter
    - prune_snapshots with no snapshots
    - prune_snapshots with all recent snapshots (nothing to prune)
    - prune_snapshots skips current branch
    - prune_snapshots handles unparseable branch names
    - prune_snapshots timeout handling
    - prune_snapshots git binary not found
  - [x] Add integration test to `tests/integration/test_git_operations.py`:
    - Create multiple snapshots with different timestamps
    - Run prune_snapshots with specific retention
    - Verify old snapshots deleted, recent ones retained
    - Verify execution_log entry creation

- [x] Review Follow-ups (AI)
  - [x] [AI-Review][MEDIUM] Inconsistent Sync Execution: `prune_snapshots` uses sync `_run_git_sync` helper. For consistency with the async architecture, it should be refactored to use `asyncio.create_subprocess_exec`. [src/sohnbot/capabilities/git/snapshot_manager.py:348]
  - [x] [AI-Review][LOW] Configuration Duplication: Both `git.snapshot_retention_days` and `snapshot.retention_days` exist in the registry/config. These should be consolidated. [config/default.toml:53, 58]

## Dev Notes

### Epic 2 Context

**Epic Goal:** Extend Epic 1's snapshot capability with full git integration and autonomous commit workflow.

**Epic Progress:**
- ✅ Story 2.1: Git Status & Diff Queries (COMPLETED)
- ✅ Story 2.2: Git Checkout for Rollback Operations (COMPLETED)
- ✅ Story 2.3: Autonomous Git Commits (COMPLETED - in review)
- 🔄 Story 2.4: Enhanced Snapshot Branch Management (THIS STORY - **FINAL STORY IN EPIC 2!**)

**Why Story 2.4:**
This story completes Epic 2 by adding snapshot lifecycle management. Without pruning, snapshot branches would accumulate indefinitely, cluttering the repository. This story ensures automatic cleanup of old snapshots while retaining recent ones for rollback capability.

**Epic 2 Completion:**
After this story, Epic 2 will be complete! The full git integration includes:
- ✅ Query git status/diff (Story 2.1)
- ✅ Checkout branches (Story 2.2)
- ✅ Create commits (Story 2.3)
- 🔄 Manage snapshot lifecycle (Story 2.4)

### Architecture Context

**Governed Operator Spine:**
- Snapshot pruning is a **Tier 1** operation (state-changing, deletes git branches)
- Must route through Broker for policy enforcement and logging
- No snapshot creation before pruning (pruning is cleanup, not modification)
- Operation must be logged to `execution_log` with start/end timestamps

**Integration with Epic 4 (Future):**
The story acceptance criteria mention "auto-pruned weekly" with "scheduled job runs weekly (uses scheduler from Epic 4)". However:
- **Epic 4 (Scheduled Automation) is currently in backlog** (not yet implemented)
- Story 2.4 implements the `prune_snapshots()` function itself as a standalone capability
- Automatic weekly scheduling will come later when Epic 4 is implemented
- For now, `prune_snapshots` is an MCP tool that can be called manually or programmatically

**When Epic 4 is implemented:**
- Story 4.1: Job creation and persistence
- Story 4.2: Idempotent job execution
- Create a scheduled job: `prune_snapshots` runs weekly
- Configuration: `snapshot.retention_days` controls how old snapshots get pruned

**For Story 2.4 scope:**
- Implement `prune_snapshots()` function
- Make it callable as MCP tool
- Add configuration for retention_days
- Future automatic scheduling is out of scope

**Relationship to Story 1.6 & 1.7:**

Story 1.6 implemented snapshot creation:
```python
# Story 1.6: Create snapshot before Tier 1 operations
snapshot_ref = await snapshot_manager.create_snapshot(repo_path, operation_id)
```

Story 1.7 implemented snapshot listing and rollback:
```python
# Story 1.7: List and rollback to snapshots
snapshots = snapshot_manager.list_snapshots(repo_path)
result = await snapshot_manager.rollback_to_snapshot(repo_path, snapshot_ref, operation_id)
```

Story 2.4 implements snapshot pruning:
```python
# Story 2.4: Prune old snapshots
result = snapshot_manager.prune_snapshots(repo_path, retention_days=30)
```

**Snapshot lifecycle:**
1. **Create** (Story 1.6) → Snapshot created before file modifications
2. **List** (Story 1.7) → View available snapshots
3. **Rollback** (Story 1.7) → Restore files from snapshot
4. **Prune** (Story 2.4) → Delete old snapshots

### Critical Implementation Patterns

**1. Extend Existing SnapshotManager Class**

Story 1.6 created `snapshot_manager.py` with `SnapshotManager` class.
Story 1.7 extended it with `list_snapshots()` and `rollback_to_snapshot()`.
Story 2.4 extends it with `prune_snapshots()`.

**MUST ADD** to existing `SnapshotManager` class (don't create new module):

```python
# snapshot_manager.py
class SnapshotManager:
    # ... existing methods: create_snapshot, list_snapshots, rollback_to_snapshot

    def prune_snapshots(
        self,
        repo_path: str,
        retention_days: int = 30,
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        """
        Prune snapshot branches older than retention_days.

        Args:
            repo_path: Absolute path to git repository root
            retention_days: Delete snapshots older than this many days (default: 30)
            timeout_seconds: Maximum time for git operations

        Returns:
            {"pruned_count": int, "pruned_refs": list[str], "retained_count": int}

        Raises:
            GitCapabilityError: If git command fails or timeout
        """
        import subprocess
        from datetime import datetime, timezone, timedelta

        # Validate retention_days
        if retention_days <= 0:
            raise GitCapabilityError(
                code="invalid_retention_days",
                message="Retention days must be greater than 0",
                details={"retention_days": retention_days},
                retryable=False,
            )

        # Get all snapshots
        snapshots = self.list_snapshots(repo_path)

        if not snapshots:
            return {
                "pruned_count": 0,
                "pruned_refs": [],
                "retained_count": 0,
            }

        # Get current branch to avoid pruning it
        current_branch_cmd = ["git", "-C", repo_path, "branch", "--show-current"]
        try:
            current_branch_result = subprocess.run(
                current_branch_cmd,
                capture_output=True,
                check=False,
                timeout=5,
            )
            current_branch = current_branch_result.stdout.decode("utf-8", errors="replace").strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            current_branch = ""

        # Calculate cutoff date
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

        pruned_refs = []
        retained_count = 0

        for snapshot in snapshots:
            ref = snapshot["ref"]

            # Skip current branch
            if ref == current_branch:
                logger.info("prune_skipped_current_branch", ref=ref)
                retained_count += 1
                continue

            # Parse timestamp from branch name
            try:
                # Extract timestamp: snapshot/edit-YYYY-MM-DD-HHMM(-suffix)?
                parts = ref.split("snapshot/edit-")[1].split("-")
                year = int(parts[0])
                month = int(parts[1])
                day = int(parts[2])
                time = parts[3][:4]  # HHMM
                hour = int(time[:2])
                minute = int(time[2:])

                snapshot_date = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)

                # Check if older than retention period
                if snapshot_date < cutoff_date:
                    # Prune this snapshot
                    delete_cmd = ["git", "-C", repo_path, "branch", "-D", ref]
                    try:
                        delete_result = subprocess.run(
                            delete_cmd,
                            capture_output=True,
                            check=False,
                            timeout=10,
                        )
                        if delete_result.returncode == 0:
                            pruned_refs.append(ref)
                            logger.info("snapshot_pruned", ref=ref, age_days=(datetime.now(timezone.utc) - snapshot_date).days)
                        else:
                            logger.warning("snapshot_prune_failed", ref=ref, stderr=delete_result.stderr.decode("utf-8", errors="replace"))
                            retained_count += 1
                    except subprocess.TimeoutExpired:
                        logger.warning("snapshot_prune_timeout", ref=ref)
                        retained_count += 1
                else:
                    retained_count += 1

            except (IndexError, ValueError) as exc:
                # Skip branches with unparseable timestamps
                logger.warning("snapshot_timestamp_parse_failed", ref=ref, error=str(exc))
                retained_count += 1
                continue

        return {
            "pruned_count": len(pruned_refs),
            "pruned_refs": pruned_refs,
            "retained_count": retained_count,
        }
```

**2. Configuration Management Pattern**

Story 1.1 established configuration system with `config/default.toml`.
Story 2.4 adds snapshot retention configuration.

Add to `config/default.toml`:
```toml
[snapshot]
# Retention period for snapshot branches (in days)
# Snapshots older than this will be pruned when prune_snapshots is called
# Default: 30 days
retention_days = 30
```

**3. MCP Tool Registration Pattern (from Stories 2.1, 2.2, 2.3)**

Follow established pattern:
```python
# mcp_tools.py
{
    "type": "function",
    "function": {
        "name": "mcp__sohnbot__git__prune_snapshots",
        "description": "Prune snapshot branches older than retention period",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to git repository"},
                "retention_days": {
                    "type": "integer",
                    "description": "Delete snapshots older than this many days (optional, uses config default)"
                }
            },
            "required": ["repo_path"]
        }
    }
}
```

**4. Broker Tier Classification (from Stories 2.1, 2.2, 2.3)**

Story 2.1: Tier 0 (git status, git diff, list_snapshots - read-only)
Story 2.2: Tier 1 (git checkout - state-changing)
Story 2.3: Tier 1 (git commit - state-changing)
Story 2.4: **Tier 1** (prune_snapshots - state-changing, deletes branches)

```python
# operation_classifier.py
if operation_type == "git":
    if action in ["status", "diff", "list_snapshots"]:
        return 0  # Read-only
    elif action in ["checkout", "commit", "rollback", "prune_snapshots"]:
        return 1  # State-changing
```

**5. Safety Considerations**

Snapshot pruning is destructive (deletes branches). Implement safety measures:
- **Don't prune current branch**: Check `git branch --show-current` first
- **Graceful failure**: If one branch fails to delete, continue with others
- **Clear logging**: Log each pruned branch for audit trail
- **Validation**: Ensure retention_days > 0
- **Skip unparseable branches**: Don't delete branches we can't parse timestamps from

### Project Structure Notes

**Files to Modify:**
```
src/sohnbot/capabilities/git/snapshot_manager.py (add prune_snapshots method)
src/sohnbot/runtime/mcp_tools.py (register mcp__sohnbot__git__prune_snapshots)
src/sohnbot/broker/operation_classifier.py (add "prune_snapshots" to Tier 1)
src/sohnbot/broker/router.py (route git.prune_snapshots operations)
config/default.toml (add snapshot.retention_days config)
tests/unit/test_snapshot_manager.py (add 8+ new tests)
tests/integration/test_git_operations.py (add prune flow test)
```

**Files to Reference (DO NOT MODIFY unless needed):**
```
src/sohnbot/config/manager.py (reference for config access)
```

**Module Structure After Story 2.4:**
```
src/sohnbot/capabilities/git/
├── __init__.py (exports: GitCapabilityError, SnapshotManager, git_status, git_diff, git_checkout, git_commit)
├── snapshot_manager.py (modified - add prune_snapshots method)
└── git_ops.py (existing - from Stories 2.1, 2.2, 2.3)
```

### Technical Constraints

**Timeout Enforcement (NFR-007):**
- Default timeout: 60 seconds for entire pruning operation
- Individual git commands: 10 seconds per branch delete
- Use `subprocess.run()` with timeout parameter (sync operations OK for pruning)

**Git Branch Deletion:**
- Use `git branch -D <branch>` (force delete, don't check if merged)
- Snapshots are auxiliary branches, safe to force delete
- Parse exit codes:
  - 0: Success
  - 1: Branch doesn't exist (already deleted, not an error)
  - 128: Not a git repository

**Date Parsing and Comparison:**
```python
from datetime import datetime, timezone, timedelta

# Snapshot branch name: snapshot/edit-2026-02-27-1430
# Parse to: datetime(2026, 2, 27, 14, 30, tzinfo=timezone.utc)

# Calculate cutoff
retention_days = 30
cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

# Compare
if snapshot_date < cutoff_date:
    # Prune this snapshot
```

**Observability (NFR-021):**
- Snapshot count tracked in `list_snapshots()` return value
- Pruning operations logged with counts
- Future Epic 3 integration: expose snapshot metrics

### Previous Story Intelligence

**From Story 2.3 (Autonomous Git Commits - JUST COMPLETED):**

Key learnings from Story 2.3 completion notes:
- Git operations module well-established in `git_ops.py`
- Validation patterns proven effective
- MCP tool registration consistent
- Broker integration tested and working
- Code review process surfaced security issues (validation, length caps)

**Apply to Story 2.4:**
- Validate retention_days parameter (must be > 0)
- Consider edge cases (current branch, unparseable names)
- Test error handling thoroughly
- Document safety considerations

**From Story 2.2 (Git Checkout):**
- Security patterns: option injection prevention
- Branch name validation
- Current branch handling (don't checkout current branch)

**Apply to Story 2.4:**
- Don't prune current branch (similar safety check)
- Handle branch names safely

**From Story 2.1 (Git Status & Diff):**
- `_run_git_command()` helper pattern
- Error handling consistency
- MCP tool patterns

**Story 2.4 uses sync operations** (`subprocess.run()`) like Story 1.7's `list_snapshots()`, not async like Story 2.1-2.3. This is OK for:
- Operations that don't block the main event loop (pruning is infrequent)
- Batch operations (prune multiple branches)
- Less time-critical operations

**From Story 1.7 (Rollback to Previous Snapshot):**

Story 1.7 implemented `list_snapshots()` which Story 2.4 reuses:
```python
# Story 1.7: List snapshots
snapshots = snapshot_manager.list_snapshots(repo_path)
# Returns: [{"ref": "snapshot/edit-...", "timestamp": "Feb 27, 2026 14:30 UTC"}, ...]
```

Story 2.4 builds on this to implement pruning:
```python
# Story 2.4: Use list_snapshots then prune old ones
snapshots = self.list_snapshots(repo_path)
for snapshot in snapshots:
    if snapshot_date < cutoff_date:
        # Delete branch
```

**From Story 1.6 (Patch-Based File Edit with Snapshot Creation):**

Snapshot naming convention established:
- Format: `snapshot/edit-YYYY-MM-DD-HHMM`
- Optional suffix: `-{operation_id[:4]}` on collision
- Example: `snapshot/edit-2026-02-27-1430` or `snapshot/edit-2026-02-27-1430-a1b2`

Story 2.4 must parse these names to extract timestamps for age calculation.

### Git Branch Management Specifics (Technical Reference)

**Git Branch Commands:**

1. **List branches with pattern:**
   ```bash
   git branch --list "snapshot/*"
   # Output:
   #   snapshot/edit-2026-01-15-0930
   #   snapshot/edit-2026-02-20-1445
   #   snapshot/edit-2026-02-27-1430
   ```

2. **Delete branch (force):**
   ```bash
   git branch -D snapshot/edit-2026-01-15-0930
   # Output: Deleted branch snapshot/edit-2026-01-15-0930 (was abc1234).
   ```

3. **Get current branch:**
   ```bash
   git branch --show-current
   # Output: main
   # (or empty if detached HEAD)
   ```

**Git Branch Exit Codes:**
- `git branch -D <branch>`:
  - 0: Successfully deleted
  - 1: Branch doesn't exist
  - 128: Not a git repository

**Pruning Algorithm:**
```
1. Get all snapshots via list_snapshots()
2. Get current branch (skip if it's a snapshot)
3. Calculate cutoff date (now - retention_days)
4. For each snapshot:
   a. Parse timestamp from branch name
   b. If older than cutoff → delete with git branch -D
   c. If newer than cutoff → retain
   d. If parse fails → skip (log warning)
   e. If delete fails → skip (log warning, continue)
5. Return pruned count, pruned refs, retained count
```

**Safety Checks:**
- ✅ Don't prune current branch (HEAD)
- ✅ Graceful handling of parse failures
- ✅ Graceful handling of delete failures
- ✅ Validate retention_days > 0
- ✅ Timeout per-operation to prevent hanging

### Latest Tech Information

**Git Best Practices for Branch Management (2026):**
- Use `git branch -D` (force delete) for cleanup operations
- Check current branch before pruning
- Log all deletions for audit trail
- Consider retention policies (30 days is common default)

**Python datetime Best Practices:**
- Always use timezone-aware datetime (use `timezone.utc`)
- Use `timedelta` for date arithmetic
- Parse dates carefully, handle parse failures gracefully

**Observability Best Practices (NFR-021):**
- Track counts: total snapshots, pruned, retained
- Log each pruned branch individually
- Expose metrics for monitoring (future Epic 3)

### References

**Epic & Story Source:**
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 2: Git Operations & Version Control]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.4: Enhanced Snapshot Branch Management]

**Story 2.3 Patterns (JUST COMPLETED):**
- [Source: src/sohnbot/capabilities/git/git_ops.py] - Git operations patterns
- [Source: _bmad-output/implementation-artifacts/2-3-autonomous-git-commits.md] - Complete implementation details

**Story 1.7 Context (List Snapshots & Rollback):**
- [Source: src/sohnbot/capabilities/git/snapshot_manager.py:179-282] - list_snapshots implementation
- [Source: _bmad-output/implementation-artifacts/1-7-rollback-to-previous-snapshot.md] - Snapshot management context

**Story 1.6 Context (Snapshot Creation):**
- [Source: src/sohnbot/capabilities/git/snapshot_manager.py:72-117] - create_snapshot implementation
- [Source: _bmad-output/implementation-artifacts/1-6-patch-based-file-edit-with-snapshot-creation.md] - Snapshot naming convention

**Broker & MCP Integration:**
- [Source: src/sohnbot/broker/router.py] - Operation routing
- [Source: src/sohnbot/broker/operation_classifier.py] - Tier classification
- [Source: src/sohnbot/runtime/mcp_tools.py] - MCP tool registration

**Configuration System:**
- [Source: src/sohnbot/config/manager.py] - Configuration access
- [Source: config/default.toml] - Default configuration values

**Epic 4 Context (Future Integration):**
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 4: Scheduled Automation] - Scheduler for automatic pruning (not yet implemented)

**Development Environment:**
- [Source: docs/development_environment.md] - Git installation instructions
- [Source: _bmad-output/implementation-artifacts/retro-action-item-2-findings.md] - System binaries audit

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- Added `SnapshotManager.prune_snapshots()` with retention filtering, current-branch skip, and per-branch safe-delete behavior in `src/sohnbot/capabilities/git/snapshot_manager.py`
- Added snapshot datetime parsing and sync git runner helper for timeout/error mapping in `src/sohnbot/capabilities/git/snapshot_manager.py`
- Extended snapshot listing observability (`snapshots_listed` log) and preserved unparseable snapshot refs with `timestamp="Unknown"` for safe pruning
- Added dynamic config key `snapshot.retention_days` in `src/sohnbot/config/registry.py` and default config docs in `config/default.toml`
- Added broker route support for `git.prune_snapshots` and list snapshot `total_count` in `src/sohnbot/broker/router.py`
- Classified `git.prune_snapshots` as Tier 1 in `src/sohnbot/broker/operation_classifier.py`
- Registered MCP tool `git__prune_snapshots` and updated list snapshots output count in `src/sohnbot/runtime/mcp_tools.py`
- Added/updated tests:
  - `tests/unit/test_snapshot_manager.py`
  - `tests/unit/test_broker.py`
  - `tests/unit/test_mcp_tools.py`
  - `tests/integration/test_git_operations.py`
- Validation:
  - `python3 -m py_compile ...` passed for all changed Python files
  - `python3 -m pytest ...` could not run in this environment (`No module named pytest`)
- Review follow-up fixes:
  - refactored `prune_snapshots()` to async command execution via `asyncio.create_subprocess_exec` (`_run_git_async`)
  - removed duplicated config key `git.snapshot_retention_days` from registry/defaults; kept `snapshot.retention_days` as single source

### Completion Notes List

- Implemented snapshot lifecycle cleanup with configurable retention and safe branch pruning.
- Added broker + MCP integration for `git.prune_snapshots` as a Tier 1 state-changing operation.
- Added observability counters for snapshot listing and pruning summary logs.
- Added 8+ unit tests for prune edge cases plus integration coverage for broker prune flow and execution log entry.
- ✅ Resolved review finding [MEDIUM]: prune flow now uses async subprocess execution consistently.
- ✅ Resolved review finding [LOW]: consolidated retention config to `snapshot.retention_days` only.

### File List

- src/sohnbot/capabilities/git/snapshot_manager.py
- src/sohnbot/broker/router.py
- src/sohnbot/broker/operation_classifier.py
- src/sohnbot/runtime/mcp_tools.py
- src/sohnbot/config/registry.py
- config/default.toml
- tests/unit/test_snapshot_manager.py
- tests/unit/test_broker.py
- tests/unit/test_mcp_tools.py
- tests/integration/test_git_operations.py
