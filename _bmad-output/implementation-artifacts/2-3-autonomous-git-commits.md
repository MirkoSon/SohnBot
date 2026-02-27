# Story 2.3: Autonomous Git Commits

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want SohnBot to autonomously create commits after successful operations,
So that changes are tracked in version control automatically.

## Acceptance Criteria

**Given** file edits have been successfully applied and validated (lint/build passed)
**When** the edit operation completes
**Then** a git commit is created autonomously
**And** commit message follows format: "[Type]: [Summary]" (e.g., "Fix: Resolve linting errors")
**And** commit includes all modified files from the operation
**And** operation is logged as Tier 1
**And** notification confirms commit with SHA and message

## Tasks / Subtasks

- [x] Task 1: Implement git_commit Function in git_ops.py (AC: 1, 2, 3)
  - [x] Add `git_commit(repo_path: str, message: str, file_paths: list[str] | None = None, timeout_seconds: int = 30) -> dict` to `git_ops.py`
  - [x] Execute `git add <files>` for specified file_paths (or `git add -A` if None)
  - [x] Execute `git commit -m "<message>"` using existing `_run_git_command()` helper
  - [x] Return structured dict: `{"commit_hash": str, "message": str, "files_changed": int}`
  - [x] Use `git rev-parse --short HEAD` to get commit hash after commit
  - [x] Use `git diff-tree --no-commit-id --name-only -r HEAD` to count files changed
  - [x] Reuse `GitCapabilityError` exception with codes: `commit_failed`, `nothing_to_commit`, `commit_timeout`
  - [x] Enforce 30-second timeout (NFR-007)

- [x] Task 2: Implement Commit Message Validation (AC: 2)
  - [x] Validate commit message format: `[Type]: [Summary]`
  - [x] Supported types: `Fix`, `Feat`, `Refactor`, `Docs`, `Test`, `Chore`, `Style`
  - [x] Reject empty messages
  - [x] Reject messages without type prefix
  - [x] Max message length: 72 characters for first line (standard git practice)
  - [x] Return clear error: `"Commit message must follow format: [Type]: [Summary]"`

- [x] Task 3: Handle "Nothing to Commit" Gracefully (AC: 1)
  - [x] Detect `git commit` exit code 1 with "nothing to commit" in stderr
  - [x] Return structured result (not error): `{"commit_hash": None, "message": "No changes to commit", "files_changed": 0}`
  - [x] Log as successful operation (not failure)
  - [x] This is NOT an error condition (file edits may not result in changes)

- [x] Task 4: Register MCP Tool (AC: All)
  - [x] Update `src/sohnbot/runtime/mcp_tools.py`
  - [x] Register `mcp__sohnbot__git__commit` tool
  - [x] Input schema: `{"repo_path": str, "message": str, "file_paths": list[str] | None}` (repo_path and message required)
  - [x] Map tool call to `git_commit()` function via broker

- [x] Task 5: Broker Integration (AC: 4)
  - [x] Update `src/sohnbot/broker/operation_classifier.py`
  - [x] Classify `git_commit` as **Tier 1** (state-changing, creates commit)
  - [x] Update `src/sohnbot/broker/router.py` to route `git.commit` operations
  - [x] Ensure operation is logged to `execution_log` with start/end timestamps
  - [x] No snapshot creation before commit (commit itself is the persistence mechanism)

- [x] Task 6: Notification Integration (AC: 5)
  - [x] Update notification logic to handle git commit results
  - [x] Message format: `✅ Commit created: <commit_hash>. Message: "<message>". Files: <count>`
  - [x] Handle "nothing to commit" case: `ℹ️ No changes to commit`
  - [x] Use existing `enqueue_notification()` system from Story 1.8

- [x] Task 7: Testing
  - [x] Add unit tests to `tests/unit/test_git_ops.py` (minimum 8 new tests):
    - git_commit success case
    - git_commit with specific file paths
    - git_commit with all changes (file_paths=None)
    - git_commit nothing to commit (graceful handling)
    - git_commit invalid message format
    - git_commit empty message rejection
    - git_commit timeout handling
    - git_commit git binary not found
  - [x] Add integration test to `tests/integration/test_git_operations.py`:
    - Full Telegram → Broker → Git commit flow
    - Verify commit exists in git history
    - Verify execution_log entry creation
    - Verify notification sent

- [x] Review Follow-ups (AI)
  - [x] [AI-Review][MEDIUM] Unvalidated File Paths: `git_commit` does not validate individual `file_paths` against the allowed scope or repository root. [src/sohnbot/capabilities/git/git_ops.py:312]
  - [x] [AI-Review][MEDIUM] Commit Message Shell Safety: Total message length is not capped. Add a maximum length check (e.g. 4096 chars). [src/sohnbot/capabilities/git/git_ops.py:284]
  - [x] [AI-Review][LOW] Redundant `add -A`: Defaulting to `add -A` when `file_paths` is None could include unintended changes from the working tree. Consider making `file_paths` required or safer. [src/sohnbot/capabilities/git/git_ops.py:328]

## Dev Notes

### Epic 2 Context

**Epic Goal:** Extend Epic 1's snapshot capability with full git integration and autonomous commit workflow.

**Epic Progress:**
- ✅ Story 2.1: Git Status & Diff Queries (COMPLETED)
- ✅ Story 2.2: Git Checkout for Rollback Operations (COMPLETED - in review)
- 🔄 Story 2.3: Autonomous Git Commits (THIS STORY)
- ⏳ Story 2.4: Enhanced Snapshot Branch Management

**Why Story 2.3:**
This story completes the core git integration by adding commit capability. Combined with Stories 2.1 and 2.2, users can now:
- Query git status/diff (Story 2.1)
- Checkout branches (Story 2.2)
- Create commits autonomously (Story 2.3)

This enables the full autonomous edit-commit workflow mentioned in the PRD.

### Architecture Context

**Governed Operator Spine:**
- Git commit is a **Tier 1** operation (state-changing, creates permanent git history)
- Must route through Broker for policy enforcement and logging
- Unlike file edits, commit does NOT create a snapshot beforehand (commit itself IS the persistence)
- Operation must be logged to `execution_log` with start/end timestamps

**Integration with Epic 5 (Future):**
The story acceptance criteria mention "after lint/build validation" integration with Epic 5. However:
- **Epic 5 is currently in backlog** (not yet implemented)
- Story 2.3 implements the `git_commit()` function itself as a standalone capability
- Epic 5 integration will come later when profiles are implemented
- For now, `git_commit` is an MCP tool that can be called directly or programmatically

**When Epic 5 is implemented:**
- Lint profile (Story 5.1) runs validation
- Build profile (Story 5.2) runs build
- If both pass → automatically trigger `git_commit` via broker
- If either fails → skip commit, report errors

**For Story 2.3 scope:**
- Implement `git_commit()` function
- Make it callable as MCP tool
- Future trigger logic is out of scope

**Relationship to Story 1.6 (Patch-Based File Edit):**

Story 1.6 creates git snapshots BEFORE file modifications:
```python
# Story 1.6: Broker creates snapshot before Tier 1 operations
if tier >= 1:
    snapshot_ref = await self._create_snapshot(file_path)
```

Story 2.3 creates git commits AFTER file modifications:
```python
# Story 2.3: Create commit after successful file edit
result = await git_commit(repo_path, message, file_paths)
```

**Workflow sequence:**
1. User requests file edit → Story 1.6 creates snapshot
2. Broker applies patch → File is modified
3. (Future Epic 5) Run lint/build validation
4. Story 2.3 creates commit → Changes are persisted

### Critical Implementation Patterns

**1. Follow Stories 2.1 & 2.2 Git Operations Pattern**

Stories 2.1 and 2.2 established `git_ops.py` with `_run_git_command()` helper:
- Centralized error handling (git binary missing, timeout, non-git repo)
- Consistent `GitCapabilityError` exception structure
- Async subprocess execution with timeout enforcement
- Reference: [Source: src/sohnbot/capabilities/git/git_ops.py:12-68]

**MUST REUSE** `_run_git_command()` helper for consistency:

```python
async def git_commit(
    repo_path: str,
    message: str,
    file_paths: list[str] | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """
    Create a git commit with specified files and message.

    Args:
        repo_path: Absolute path to git repository root
        message: Commit message (must follow format: "[Type]: [Summary]")
        file_paths: List of file paths to commit (None = all changes)
        timeout_seconds: Maximum time for git operations

    Returns:
        {"commit_hash": str | None, "message": str, "files_changed": int}

    Raises:
        GitCapabilityError: Invalid message format, commit failed, timeout
    """
    # Validate message format
    _validate_commit_message(message)

    # Stage files
    if file_paths:
        for path in file_paths:
            add_cmd = ["git", "-C", repo_path, "add", path]
            await _run_git_command(add_cmd, repo_path, 10, "commit_timeout")
    else:
        # Stage all changes
        add_cmd = ["git", "-C", repo_path, "add", "-A"]
        await _run_git_command(add_cmd, repo_path, 10, "commit_timeout")

    # Create commit
    commit_cmd = ["git", "-C", repo_path, "commit", "-m", message]
    try:
        stdout, stderr = await _run_git_command(
            commit_cmd, repo_path, timeout_seconds, "commit_timeout"
        )
    except GitCapabilityError as exc:
        # Handle "nothing to commit" gracefully (not an error)
        if exc.code == "git_command_failed" and "nothing to commit" in exc.details.get("stderr", "").lower():
            return {
                "commit_hash": None,
                "message": "No changes to commit",
                "files_changed": 0,
            }
        raise

    # Get commit hash
    hash_cmd = ["git", "-C", repo_path, "rev-parse", "--short", "HEAD"]
    hash_stdout, _ = await _run_git_command(hash_cmd, repo_path, 5, "commit_timeout")
    commit_hash = hash_stdout.strip()

    # Get files changed count
    files_cmd = ["git", "-C", repo_path, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"]
    files_stdout, _ = await _run_git_command(files_cmd, repo_path, 5, "commit_timeout")
    files_changed = len([f for f in files_stdout.strip().split("\n") if f])

    return {
        "commit_hash": commit_hash,
        "message": message,
        "files_changed": files_changed,
    }
```

**2. Commit Message Validation Pattern**

Follow conventional commit format (widely adopted standard):
- **Format**: `[Type]: [Summary]`
- **Types**: Fix, Feat, Refactor, Docs, Test, Chore, Style
- **Example**: `Fix: Resolve authentication timeout issue`

```python
def _validate_commit_message(message: str) -> None:
    """
    Validate commit message format.

    Raises GitCapabilityError if validation fails.
    """
    if not message or not message.strip():
        raise GitCapabilityError(
            code="invalid_commit_message",
            message="Commit message cannot be empty",
            details={"message": message},
            retryable=False,
        )

    # Check format: [Type]: [Summary]
    import re
    pattern = r"^\[(Fix|Feat|Refactor|Docs|Test|Chore|Style)\]:\s+.+$"
    if not re.match(pattern, message):
        raise GitCapabilityError(
            code="invalid_commit_message",
            message="Commit message must follow format: [Type]: [Summary]",
            details={"message": message, "expected_format": "[Type]: [Summary]"},
            retryable=False,
        )

    # Check length (first line should be ≤ 72 chars)
    first_line = message.split("\n")[0]
    if len(first_line) > 72:
        raise GitCapabilityError(
            code="invalid_commit_message",
            message="Commit message first line should be ≤ 72 characters",
            details={"message": message, "length": len(first_line)},
            retryable=False,
        )
```

**3. "Nothing to Commit" Graceful Handling**

This is NOT an error condition - it's a valid outcome:
- File edit operation may not result in any actual changes
- Example: Patch applies cleanly but file content is unchanged
- Should return success with `commit_hash: None`

Git exit codes:
- **0**: Commit created successfully
- **1**: Nothing to commit (working tree clean)
- **128**: Not a git repository (already handled by `_run_git_command`)

**4. MCP Tool Registration Pattern (from Stories 2.1 & 2.2)**

Follow established pattern:
```python
# mcp_tools.py
{
    "type": "function",
    "function": {
        "name": "mcp__sohnbot__git__commit",
        "description": "Create a git commit with specified message and files",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to git repository"},
                "message": {"type": "string", "description": "Commit message (format: [Type]: [Summary])"},
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File paths to commit (optional, commits all if omitted)"
                }
            },
            "required": ["repo_path", "message"]
        }
    }
}
```

**5. Broker Tier Classification (from Stories 2.1 & 2.2)**

Story 2.1: Tier 0 (git status, git diff - read-only)
Story 2.2: Tier 1 (git checkout - state-changing)
Story 2.3: **Tier 1** (git commit - state-changing, creates permanent history)

```python
# operation_classifier.py
if operation_type == "git":
    if action in ["status", "diff", "list_snapshots"]:
        return 0  # Read-only
    elif action in ["checkout", "commit", "rollback"]:
        return 1  # State-changing
```

### Project Structure Notes

**Files to Modify:**
```
src/sohnbot/capabilities/git/git_ops.py (add git_commit function)
src/sohnbot/capabilities/git/__init__.py (export git_commit if needed)
src/sohnbot/runtime/mcp_tools.py (register mcp__sohnbot__git__commit)
src/sohnbot/broker/operation_classifier.py (add "commit" to Tier 1 classification)
src/sohnbot/broker/router.py (route git.commit operations, add notification handling)
tests/unit/test_git_ops.py (add 8+ new tests)
tests/integration/test_git_operations.py (add commit flow test)
```

**Files to Reference (DO NOT MODIFY):**
```
src/sohnbot/capabilities/git/snapshot_manager.py (reference for git patterns)
src/sohnbot/capabilities/files/patch_editor.py (reference for file edit context)
```

**Module Structure After Story 2.3:**
```
src/sohnbot/capabilities/git/
├── __init__.py (exports: GitCapabilityError, SnapshotManager, git_status, git_diff, git_checkout, git_commit)
├── snapshot_manager.py (existing - from Stories 1.6, 1.7)
└── git_ops.py (modified - from Stories 2.1, 2.2, add git_commit)
```

### Technical Constraints

**Timeout Enforcement (NFR-007):**
- Default timeout: 30 seconds for commit operation
- Use `asyncio.wait_for()` with proper cleanup on timeout
- Follow existing pattern from `_run_git_command()` helper

**Git Commit Workflow:**
1. `git add <files>` or `git add -A` (stage changes)
2. `git commit -m "<message>"` (create commit)
3. `git rev-parse --short HEAD` (get commit hash)
4. `git diff-tree --no-commit-id --name-only -r HEAD` (count files changed)

**Error Handling Priority:**
1. **Message validation** (before subprocess) → `invalid_commit_message` error
2. **FileNotFoundError** (git binary missing) → `git_not_found` error
3. **TimeoutError** (operation timeout) → `commit_timeout` error
4. **Nothing to commit** (exit code 1) → Success result with commit_hash=None
5. **Other non-zero exit code** → `commit_failed` error with stderr

**Git Commit Exit Codes:**
- 0: Commit created successfully
- 1: Nothing to commit, working tree clean
- 128: Not a git repository

Parse stderr for specific error messages:
- "nothing to commit, working tree clean" → Graceful handling (not error)
- "not a git repository" → Already handled by `_run_git_command`
- "Author identity unknown" → Commit failed with clear message

**Commit Message Best Practices:**
- First line ≤ 72 characters (git standard)
- Use conventional commit format for consistency
- Clear, descriptive summary
- Type prefix helps categorize commits

### Previous Story Intelligence

**From Story 2.2 (Git Checkout - JUST COMPLETED):**

Key learnings from Story 2.2 completion notes:
- `git_ops.py` module extended with `git_checkout()` function
- Validation patterns established (local branch only, path traversal prevention)
- Option injection protection: use `git switch -- <branch>` pattern
- Testing approach: 6+ unit tests + integration test
- Code review findings addressed: option injection, regex validation, duplicate logic

**Security Lessons Applied to Story 2.3:**
- Validate commit message format before subprocess execution
- Use `--` separator in git commands to prevent option injection
- Consider message content for potential command injection risks

**From Story 2.1 (Git Status & Diff Queries):**

Established patterns:
- `_run_git_command()` helper for consistent error handling
- `GitCapabilityError` exception structure
- MCP tool registration pattern
- Broker integration for git operations
- Performance: git operations meeting NFR requirements

**From Story 1.6 (Patch-Based File Edit with Snapshot Creation):**

Context for commit workflow:
- Snapshots are created BEFORE Tier 1 operations (file edits)
- Commits are created AFTER file edits (this story)
- Workflow: Snapshot → Edit → (Validate) → Commit
- Epic 5 (lint/build profiles) will add validation step between Edit and Commit

**From Story 1.8 (Structured Operation Logging & Notifications):**

Notification system patterns:
- Use `enqueue_notification(operation_id, chat_id, message_text)` for async notifications
- Format: `✅ Success message` or `❌ Error message` or `ℹ️ Info message`
- Notifications are best-effort (failure does NOT block operation)
- Reference: [Source: src/sohnbot/gateway/notification_worker.py]

### Git Commit Specifics (Technical Reference)

**Git Add Modes:**
1. **Specific files**: `git add <file1> <file2>` - Stage specific files
2. **All changes**: `git add -A` - Stage all modified, new, and deleted files
3. **Modified only**: `git add -u` - Stage modified and deleted (not new files)

For Story 2.3: Use mode 1 or 2 based on `file_paths` parameter.

**Git Commit Options:**
- `-m "<message>"` - Commit message
- `-a` - Automatically stage all modified files (NOT used in this story - we stage explicitly with `git add`)
- `--allow-empty` - Allow empty commits (NOT used - we handle gracefully instead)

**Getting Commit Information:**
```bash
# Get commit hash (short form)
git rev-parse --short HEAD
# Output: abc1234

# Get commit hash (full form)
git rev-parse HEAD
# Output: abc1234567890abcdef1234567890abcdef123456

# Get files changed in last commit
git diff-tree --no-commit-id --name-only -r HEAD
# Output:
# src/file1.py
# src/file2.py

# Count files changed
git diff-tree --no-commit-id --name-only -r HEAD | wc -l
# Output: 2
```

**Commit Message Format:**
Conventional Commits specification (widely adopted):
- `[Fix]: <summary>` - Bug fix
- `[Feat]: <summary>` - New feature
- `[Refactor]: <summary>` - Code refactoring (no functional change)
- `[Docs]: <summary>` - Documentation changes
- `[Test]: <summary>` - Test additions/changes
- `[Chore]: <summary>` - Maintenance tasks
- `[Style]: <summary>` - Code style/formatting changes

**Nothing to Commit Handling:**
```bash
$ git commit -m "Test commit"
On branch main
nothing to commit, working tree clean
$ echo $?
1

$ git status --short
$ echo $?
0
```

Exit code 1 with "nothing to commit" in stderr is normal, not an error.

### Latest Tech Information

**Git Best Practices for Automation (2026):**
- Use `git add` then `git commit` (not `git commit -a`)
- Explicit staging gives better control over what gets committed
- Always validate commit message format
- Use short commit hashes for display (8 characters)
- Timeout for commit operations (30s default)

**Python asyncio subprocess (2026):**
- Use `asyncio.create_subprocess_exec()` for async operations
- Already implemented in `_run_git_command()` helper from Stories 2.1 & 2.2
- Proper cleanup: `process.kill(); await process.wait()` on timeout

**Conventional Commits:**
- Industry standard for commit message format
- Enables automated changelog generation
- Improves commit history readability
- Tools like `semantic-release` rely on this format

### References

**Epic & Story Source:**
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 2: Git Operations & Version Control]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.3: Autonomous Git Commits]

**Story 2.2 Patterns (JUST COMPLETED):**
- [Source: src/sohnbot/capabilities/git/git_ops.py] - git_checkout implementation, validation patterns
- [Source: _bmad-output/implementation-artifacts/2-2-git-checkout-for-rollback-operations.md] - Complete implementation details
- [Source: tests/unit/test_git_ops.py] - Testing patterns

**Story 2.1 Patterns:**
- [Source: src/sohnbot/capabilities/git/git_ops.py:12-68] - _run_git_command helper
- [Source: _bmad-output/implementation-artifacts/2-1-git-status-diff-queries.md] - Git operations patterns

**Story 1.6 Context (File Edit with Snapshot):**
- [Source: src/sohnbot/capabilities/git/snapshot_manager.py] - Snapshot creation (before edits)
- [Source: _bmad-output/implementation-artifacts/1-6-patch-based-file-edit-with-snapshot-creation.md] - Edit workflow context

**Story 1.8 Context (Notifications):**
- [Source: src/sohnbot/gateway/notification_worker.py] - Notification system
- [Source: _bmad-output/implementation-artifacts/1-8-structured-operation-logging-notifications.md] - Notification patterns

**Broker & MCP Integration:**
- [Source: src/sohnbot/broker/router.py] - Operation routing
- [Source: src/sohnbot/broker/operation_classifier.py] - Tier classification
- [Source: src/sohnbot/runtime/mcp_tools.py] - MCP tool registration

**Epic 5 Context (Future Integration):**
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 5: Development Workflow Automation] - Lint/build profiles (not yet implemented)

**Development Environment:**
- [Source: docs/development_environment.md] - Git installation instructions
- [Source: _bmad-output/implementation-artifacts/retro-action-item-2-findings.md] - System binaries audit

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- Added/finalized `git_commit` implementation and commit-message validation in `src/sohnbot/capabilities/git/git_ops.py`
- Added commit export in `src/sohnbot/capabilities/git/__init__.py`
- Updated commit Tier 1 classification in `src/sohnbot/broker/operation_classifier.py`
- Added commit route + commit notification formatting in `src/sohnbot/broker/router.py`
- Replaced `git__commit` MCP stub with broker-backed implementation in `src/sohnbot/runtime/mcp_tools.py`
- Fixed indentation syntax issue in `tests/unit/test_git_ops.py` checkout-timeout test
- Added integration test `test_broker_git_commit_flow_execution_log_and_notification` in `tests/integration/test_git_operations.py`
- Review follow-up fixes applied in `git_ops`:
  - validated commit `file_paths` stay within repository root and reject empty/option-like paths
  - capped total commit message length to 4096 characters
  - changed default staging from `git add -A` to safer `git add -u`
- Added unit tests for review follow-ups in `tests/unit/test_git_ops.py`
- Validation attempt:
  - `pytest` unavailable (`pytest: command not found`)
  - `poetry` unavailable (`poetry: command not found`)
  - `python3 -m pytest` unavailable (`No module named pytest`)
  - Syntax verification succeeded via `python3 -m py_compile` on changed Python files

### Completion Notes List

- Implemented autonomous git commit capability with staged-file and stage-all modes.
- Enforced commit message validation with supported prefixes and 72-char first-line limit.
- Implemented graceful no-op commit handling (`No changes to commit`) as success output.
- Integrated commit action through broker and MCP tool path with Tier 1 classification.
- Added commit-specific outbox notification formatting including commit hash/message/file count.
- Added required unit commit tests and an integration commit flow test covering git history, execution log, and notification content.
- ✅ Resolved review finding [MEDIUM]: validated per-file commit paths against repository root.
- ✅ Resolved review finding [MEDIUM]: added hard commit-message length cap (4096 chars).
- ✅ Resolved review finding [LOW]: replaced default `add -A` with safer `add -u` for implicit staging.

### File List

- src/sohnbot/capabilities/git/git_ops.py
- src/sohnbot/capabilities/git/__init__.py
- src/sohnbot/broker/operation_classifier.py
- src/sohnbot/broker/router.py
- src/sohnbot/runtime/mcp_tools.py
- tests/unit/test_git_ops.py
- tests/integration/test_git_operations.py
