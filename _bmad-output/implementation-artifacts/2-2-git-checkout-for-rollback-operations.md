# Story 2.2: Git Checkout for Rollback Operations

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to checkout snapshot branches for rollback,
So that I can restore previous states during recovery operations.

## Acceptance Criteria

**Given** snapshot branches exist locally
**When** I request to checkout a snapshot branch
**Then** branch is checked out (restricted to local branches only, no remote)
**And** operation is logged as Tier 1
**And** checkout is used for rollback operations (FR-013)

## Tasks / Subtasks

- [x] Task 1: Implement git_checkout Function in git_ops.py (AC: 1, 2)
  - [x] Add `git_checkout(repo_path: str, branch_name: str, timeout_seconds: int = 10) -> dict` to `git_ops.py`
  - [x] Validate branch_name is LOCAL only (reject remote refs like `origin/main`)
  - [x] Use regex validation: `^[a-zA-Z0-9_/-]+$` (no `origin/`, no `remotes/`, no `../`)
  - [x] Execute `git checkout <branch>` using existing `_run_git_command()` helper
  - [x] Return structured dict: `{"branch": str, "commit_hash": str}`
  - [x] Use `git rev-parse --short HEAD` to get commit hash after checkout
  - [x] Reuse `GitCapabilityError` exception with codes: `invalid_branch`, `checkout_failed`, `checkout_timeout`
  - [x] Enforce 10-second timeout (NFR-007)

- [x] Task 2: Add Branch Name Validation (AC: 2 - local only)
  - [x] Reject remote branch references: `origin/*`, `remotes/*`
  - [x] Reject path traversal attempts: `../`, `..\\`
  - [x] Reject special refs: `HEAD~`, `HEAD^`, `@{-1}` (only simple branch names)
  - [x] Accept valid patterns: `main`, `feature/new-feature`, `snapshot/edit-2026-02-27-1430`
  - [x] Return clear error: `"Branch checkout restricted to local branches only. Remote checkout not permitted."`

- [x] Task 3: Register MCP Tool (AC: All)
  - [x] Update `src/sohnbot/runtime/mcp_tools.py`
  - [x] Register `mcp__sohnbot__git__checkout` tool
  - [x] Input schema: `{"repo_path": str, "branch_name": str}` (both required)
  - [x] Map tool call to `git_checkout()` function via broker

- [x] Task 4: Broker Integration (AC: 3)
  - [x] Update `src/sohnbot/broker/operation_classifier.py`
  - [x] Classify `git_checkout` as **Tier 1** (state-changing, modifies working tree)
  - [x] Update `src/sohnbot/broker/router.py` to route `git.checkout` operations
  - [x] Ensure operation is logged to `execution_log` with start/end timestamps
  - [x] No snapshot creation before checkout (checkout itself is a recovery operation)

- [x] Task 5: Integration with Story 1.7 Rollback (AC: 4)
  - [x] Document relationship: Story 1.7 uses `git checkout <ref> -- .` (file restore)
  - [x] This story adds branch switching: `git checkout <branch>` (working tree switch)
  - [x] Both operations serve rollback use cases:
    - Story 1.7: Restore files from snapshot to current branch (creates commit)
    - Story 2.2: Switch to snapshot branch for inspection (no commit created)
  - [x] Ensure both can coexist in `git_ops.py`

- [x] Task 6: Testing
  - [x] Add unit tests to `tests/unit/test_git_ops.py` (minimum 6 new tests):
    - git_checkout success case
    - git_checkout local branch validation (valid cases)
    - git_checkout remote branch rejection (invalid cases)
    - git_checkout path traversal rejection
    - git_checkout non-existent branch error
    - git_checkout timeout handling
  - [x] Add integration test to `tests/integration/test_git_operations.py`:
    - Full Telegram → Broker → Git checkout flow
    - Verify working tree changes after checkout
    - Verify execution_log entry creation
  - [x] Test interaction with Story 1.7 rollback operation

- [x] Review Follow-ups (AI)
  - [x] [AI-Review][MEDIUM] Option Injection Risk: Branch names starting with `-` could be interpreted as flags. Use `--` separator in git command. [src/sohnbot/capabilities/git/git_ops.py:204]
  - [x] [AI-Review][MEDIUM] Permissive Validation Regex: Current regex allows starting with `/` or `-`. Should be more restrictive. [src/sohnbot/capabilities/git/git_ops.py:189]
  - [x] [AI-Review][LOW] Redundant Tiering Logic: `git` `checkout` is defined twice in `operation_classifier.py`. [src/sohnbot/broker/operation_classifier.py:44, 52]
  - [x] [AI-Review][LOW] Suboptimal `list_snapshots` Tiering: Currently Tier 1, should be Tier 0 (read-only list). [src/sohnbot/broker/operation_classifier.py:53]

## Dev Notes

### Epic 2 Context

**Epic Goal:** Extend Epic 1's snapshot capability with full git integration and autonomous commit workflow.

**Epic Progress:**
- ✅ Story 2.1: Git Status & Diff Queries (COMPLETED - just reviewed)
- 🔄 Story 2.2: Git Checkout for Rollback Operations (THIS STORY)
- ⏳ Story 2.3: Autonomous Git Commits
- ⏳ Story 2.4: Enhanced Snapshot Branch Management

**Why Story 2.2:**
This story extends the rollback capability from Story 1.7 by allowing users to switch to snapshot branches for inspection, not just restore files. This is useful for examining the snapshot state before deciding whether to apply the rollback.

### Architecture Context

**Governed Operator Spine:**
- Git checkout is a **Tier 1** operation (state-changing, modifies working tree)
- Must route through Broker for policy enforcement and logging
- Unlike file edits, checkout does NOT create a snapshot beforehand (checkout itself is a recovery operation)
- Operation must be logged to `execution_log` with start/end timestamps

**Security Constraint - LOCAL BRANCHES ONLY:**
- **CRITICAL**: Story explicitly requires restriction to local branches only
- Prevent remote checkout to avoid unexpected network operations and security risks
- Reject patterns: `origin/main`, `remotes/origin/feature`, `refs/remotes/*`
- Accept patterns: `main`, `develop`, `feature/xyz`, `snapshot/edit-2026-02-27-1430`

**Relationship to Story 1.7 (Rollback to Previous Snapshot):**

Story 1.7 already implemented rollback using `git checkout <snapshot_ref> -- .`:
```python
# Story 1.7: snapshot_manager.py:353
checkout_cmd = ["git", "-C", repo_path, "checkout", snapshot_ref, "--", "."]
```

This restores FILES from a snapshot to the current branch (then creates a commit).

Story 2.2 implements branch switching using `git checkout <branch>`:
```python
# Story 2.2: git_ops.py (NEW)
checkout_cmd = ["git", "-C", repo_path, "checkout", branch_name]
```

This switches the entire working tree to the snapshot branch.

**Key Difference:**
- `git checkout <ref> -- .` = Restore specific files/paths (stays on current branch)
- `git checkout <branch>` = Switch to a different branch (changes HEAD)

Both serve rollback use cases but with different semantics.

### Critical Implementation Patterns

**1. Follow Story 2.1 Git Operations Pattern**

Story 2.1 established `git_ops.py` with `_run_git_command()` helper:
- Centralized error handling (git binary missing, timeout, non-git repo)
- Consistent `GitCapabilityError` exception structure
- Async subprocess execution with timeout enforcement
- Reference: [Source: src/sohnbot/capabilities/git/git_ops.py:11-60]

**MUST REUSE** `_run_git_command()` helper for consistency:

```python
async def git_checkout(
    repo_path: str,
    branch_name: str,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    """
    Checkout a local git branch.

    SECURITY: Restricted to local branches only. Remote checkout not permitted.
    """
    # Validate branch_name is local only
    _validate_local_branch(branch_name)

    cmd = ["git", "-C", repo_path, "checkout", branch_name]
    stdout, stderr = await _run_git_command(
        cmd, repo_path, timeout_seconds, "checkout_timeout"
    )

    # Get commit hash after checkout
    hash_cmd = ["git", "-C", repo_path, "rev-parse", "--short", "HEAD"]
    hash_stdout, _ = await _run_git_command(
        hash_cmd, repo_path, 5, "checkout_timeout"
    )

    return {
        "branch": branch_name,
        "commit_hash": hash_stdout.strip(),
    }
```

**2. Local Branch Validation Pattern**

Epic 1 established strict validation patterns for security:
- Path traversal prevention (Story 1.4)
- Scope validation (Story 1.4)
- Input sanitization (all stories)

Apply the same rigor to branch name validation:

```python
def _validate_local_branch(branch_name: str) -> None:
    """
    Validate branch name is local only (no remote refs).

    Raises GitCapabilityError if validation fails.
    """
    # Reject remote patterns
    if branch_name.startswith(("origin/", "remotes/", "refs/remotes/")):
        raise GitCapabilityError(
            code="invalid_branch",
            message="Branch checkout restricted to local branches only. Remote checkout not permitted.",
            details={"branch_name": branch_name},
            retryable=False,
        )

    # Reject path traversal
    if ".." in branch_name:
        raise GitCapabilityError(
            code="invalid_branch",
            message="Invalid branch name",
            details={"branch_name": branch_name},
            retryable=False,
        )

    # Reject special refs (only simple branch names)
    if any(char in branch_name for char in ["~", "^", "@"]):
        raise GitCapabilityError(
            code="invalid_branch",
            message="Branch checkout requires simple branch name. Special refs not permitted.",
            details={"branch_name": branch_name},
            retryable=False,
        )

    # Basic format validation
    import re
    if not re.match(r'^[a-zA-Z0-9_/-]+$', branch_name):
        raise GitCapabilityError(
            code="invalid_branch",
            message="Invalid branch name format",
            details={"branch_name": branch_name},
            retryable=False,
        )
```

**3. MCP Tool Registration Pattern (from Story 2.1)**

Story 2.1 established the pattern for git MCP tools:
```python
# Story 2.1: mcp_tools.py
{
    "type": "function",
    "function": {
        "name": "mcp__sohnbot__git__status",
        "description": "Query git repository status...",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "..."}
            },
            "required": ["repo_path"]
        }
    }
}
```

Follow the same pattern for `git__checkout`:
- Tool name: `mcp__sohnbot__git__checkout`
- Required params: `repo_path`, `branch_name`
- Description should mention LOCAL ONLY restriction
- Route through broker's `route_operation()` method

**4. Broker Tier Classification (from Story 2.1 & 1.7)**

Story 2.1 classified git status/diff as Tier 0 (read-only).
Story 1.7 classified git rollback as Tier 1 (state-changing).

Story 2.2 checkout is **Tier 1** (state-changing):
```python
# operation_classifier.py
if operation_type == "git":
    if action in ["status", "diff"]:
        return 0  # Read-only
    elif action in ["checkout", "rollback", "commit"]:
        return 1  # State-changing
```

### Project Structure Notes

**Files to Modify:**
```
src/sohnbot/capabilities/git/git_ops.py (add git_checkout function)
src/sohnbot/runtime/mcp_tools.py (register mcp__sohnbot__git__checkout)
src/sohnbot/broker/operation_classifier.py (add "checkout" to Tier 1 classification)
src/sohnbot/broker/router.py (route git.checkout operations)
tests/unit/test_git_ops.py (add 6+ new tests)
tests/integration/test_git_operations.py (add checkout flow test)
```

**Files to Reference (DO NOT MODIFY):**
```
src/sohnbot/capabilities/git/snapshot_manager.py (reference for rollback context)
```

**Module Structure After Story 2.2:**
```
src/sohnbot/capabilities/git/
├── __init__.py (exports: GitCapabilityError, SnapshotManager, git_status, git_diff, git_checkout)
├── snapshot_manager.py (existing - from Story 1.6, 1.7)
└── git_ops.py (modified - from Story 2.1, add git_checkout)
```

### Technical Constraints

**Timeout Enforcement (NFR-007):**
- Default timeout: 10 seconds for checkout
- Use `asyncio.wait_for()` with proper cleanup on timeout
- Follow existing pattern from `_run_git_command()` helper

**Error Handling Priority:**
1. **Branch validation** (before subprocess) → `invalid_branch` error
2. **FileNotFoundError** (git binary missing) → `git_not_found` error
3. **TimeoutError** (operation timeout) → `checkout_timeout` error
4. **Non-zero exit code** (checkout failed) → `checkout_failed` error with stderr

**Git Checkout Exit Codes:**
- 0: Success
- 1: Branch doesn't exist or checkout failed
- 128: Not a git repository

Parse stderr for specific error messages:
- "pathspec '...' did not match" → Branch not found
- "not a git repository" → Not a git repo (already handled by `_run_git_command`)

### Previous Story Intelligence

**From Story 2.1 (Git Status & Diff Queries - JUST COMPLETED):**

Key learnings from Story 2.1 completion notes:
- `git_ops.py` module structure established with `_run_git_command()` helper
- Error handling pattern proven effective across git operations
- MCP tool registration pattern established for git capabilities
- Broker integration for git operations validated
- Testing approach: 8+ unit tests + integration test
- Performance: git operations consistently meeting NFR-002 requirements

**Files Created/Modified in Story 2.1:**
```
src/sohnbot/capabilities/git/git_ops.py (new) ← EXTEND THIS
src/sohnbot/capabilities/git/__init__.py (modified) ← EXTEND THIS
src/sohnbot/broker/router.py (modified) ← EXTEND THIS
src/sohnbot/runtime/mcp_tools.py (modified) ← EXTEND THIS
src/sohnbot/broker/operation_classifier.py (modified) ← EXTEND THIS
```

**Code Review Findings from Story 2.1:**
- ✅ Porcelain v2 parsing was made robust (LOW finding)
- ✅ Duplicate classification logic removed (MEDIUM finding)
- ✅ File list completeness verified (MEDIUM finding)

Apply these learnings: Test edge cases thoroughly, avoid duplicate logic, maintain complete file lists.

**From Story 1.7 (Rollback to Previous Snapshot):**

Story 1.7 implemented rollback using `git checkout <ref> -- .`:
- Validates snapshot exists with `git rev-parse --verify <ref>`
- Uses `git checkout <snapshot_ref> -- .` to restore files
- Creates commit after restoration to preserve history
- **CRITICAL DISTINCTION**: Story 1.7 restores FILES, Story 2.2 switches BRANCHES

Reference for integration:
- [Source: src/sohnbot/capabilities/git/snapshot_manager.py:284-383]
- [Source: _bmad-output/implementation-artifacts/1-7-rollback-to-previous-snapshot.md]

### Git Checkout Specifics (Technical Reference)

**Git Checkout Modes:**

1. **Branch Checkout** (Story 2.2 - THIS STORY):
   ```bash
   git checkout <branch>
   ```
   - Switches HEAD to the specified branch
   - Updates working tree to match branch's commit
   - Changes tracked files, leaves untracked alone

2. **File/Path Checkout** (Story 1.7 - EXISTING):
   ```bash
   git checkout <ref> -- <pathspec>
   ```
   - Restores specific files/paths from <ref>
   - Does NOT switch branches (HEAD stays put)
   - Used for targeted file restoration

**Git Checkout Error Messages:**
```
error: pathspec 'nonexistent' did not match any file(s) known to git
→ Branch doesn't exist

error: Your local changes to the following files would be overwritten by checkout:
→ Uncommitted changes conflict

fatal: not a git repository (or any of the parent directories): .git
→ Not in a git repo (already handled by _run_git_command)
```

**Validation Strategy:**
- Pre-validate branch name format (before subprocess)
- Let git handle existence check (simpler, more reliable)
- Parse stderr for specific error context

### Latest Tech Information

**Git Branch Checkout Best Practices (2026):**
- Use `git switch <branch>` (modern alternative to `git checkout <branch>`)
  - However, `git checkout` is more widely supported (Git 2.x+)
  - Story 2.2 uses `git checkout` for maximum compatibility
- Always specify timeout for automation
- Use `-C <path>` to specify working directory
- Example: `git -C /path/to/repo checkout main`

**Python asyncio subprocess (2026):**
- Use `asyncio.create_subprocess_exec()` for async operations
- Always use `asyncio.wait_for()` for timeout enforcement
- Proper cleanup: `process.kill(); await process.wait()` on timeout
- Already implemented in `_run_git_command()` helper from Story 2.1

**Security Best Practices for Git Automation:**
- Never trust user input for branch names
- Validate against allowlist patterns
- Reject remote refs to prevent unexpected network calls
- Reject path traversal and special refs
- Log all checkout operations for audit

### References

**Epic & Story Source:**
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 2: Git Operations & Version Control]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.2: Git Checkout for Rollback Operations]

**Story 2.1 Patterns (JUST COMPLETED):**
- [Source: src/sohnbot/capabilities/git/git_ops.py] - _run_git_command helper, error handling
- [Source: _bmad-output/implementation-artifacts/2-1-git-status-diff-queries.md] - Complete implementation details
- [Source: tests/unit/test_git_ops.py] - Testing patterns

**Story 1.7 Context (Rollback Implementation):**
- [Source: src/sohnbot/capabilities/git/snapshot_manager.py:284-383] - rollback_to_snapshot implementation
- [Source: _bmad-output/implementation-artifacts/1-7-rollback-to-previous-snapshot.md] - Rollback story context

**Broker & MCP Integration:**
- [Source: src/sohnbot/broker/router.py] - Operation routing
- [Source: src/sohnbot/broker/operation_classifier.py] - Tier classification
- [Source: src/sohnbot/runtime/mcp_tools.py] - MCP tool registration

**Security & Validation Patterns:**
- [Source: _bmad-output/implementation-artifacts/1-4-scope-validation-path-traversal-prevention.md] - Path validation patterns

**Development Environment:**
- [Source: docs/development_environment.md] - Git installation instructions
- [Source: _bmad-output/implementation-artifacts/retro-action-item-2-findings.md] - System binaries audit

## Dev Agent Record

### Agent Model Used

GPT-5 Codex (CLI)

### Debug Log References

- `python3 -m compileall src tests` (pass)
- `.venv/bin/pytest -q tests/unit/test_git_ops.py tests/integration/test_git_operations.py tests/unit/test_broker.py tests/unit/test_mcp_tools.py tests/integration/test_broker_integration.py` (pass: 43 passed, 2 skipped)

### Completion Notes List

- Added `git_checkout(repo_path, branch_name, timeout_seconds)` to `git_ops.py` using existing `_run_git_command()` execution path.
- Implemented strict local-branch validation rejecting `origin/*`, `remotes/*`, traversal patterns (`../`, `..\\`), and special refs (`~`, `^`, `@{...}`).
- Added checkout result payload with post-checkout `git rev-parse --short HEAD` commit hash.
- Mapped checkout command failures to `checkout_failed` and preserved timeout handling via `checkout_timeout`.
- Registered MCP tool `git__checkout` with required schema (`repo_path`, `branch_name`) and broker routing.
- Updated broker routing/validation for git checkout and enforced no pre-checkout snapshot creation for this recovery operation.
- Updated operation classification so `git.checkout` is consistently Tier 1.
- Added 6+ unit tests for checkout behavior and integration test validating checkout flow + `execution_log` persistence.
- Verified Story 2.2 coexistence with Story 1.7 semantics: branch switch (`git checkout <branch>`) complements file restore (`git checkout <ref> -- .`).
- Hardened checkout invocation against option-injection by switching through `git switch -- <branch>` and rejecting unsafe branch prefixes.
- Tightened branch-name validation to forbid names starting with `/` or `-` and require a safe leading character.
- Removed redundant checkout tiering path and corrected `git.list_snapshots` classification to Tier 0 (read-only).
- ✅ Resolved review finding [MEDIUM]: option/flag injection path closed.
- ✅ Resolved review finding [MEDIUM]: branch regex validation tightened.
- ✅ Resolved review finding [LOW]: duplicate checkout tier logic removed.
- ✅ Resolved review finding [LOW]: list_snapshots moved to Tier 0.

### File List

- src/sohnbot/capabilities/git/git_ops.py (modified)
- src/sohnbot/capabilities/git/__init__.py (modified)
- src/sohnbot/runtime/mcp_tools.py (modified)
- src/sohnbot/runtime/agent_session.py (modified)
- src/sohnbot/broker/router.py (modified)
- src/sohnbot/broker/operation_classifier.py (modified)
- tests/unit/test_git_ops.py (modified)
- tests/unit/test_broker.py (modified)
- tests/unit/test_mcp_tools.py (modified)
- tests/integration/test_git_operations.py (modified)
