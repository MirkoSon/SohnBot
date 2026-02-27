# Story 2.1: Git Status & Diff Queries

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to query git status and view diffs for my repositories,
So that I can understand the current state of my code.

## Acceptance Criteria

**Given** a git repository exists within scope
**When** I request git status
**Then** modified files, staged files, branch name, commit status are returned
**And** git status completes in <500ms for repos with 100K files (NFR-002)
**And** I can view diffs for uncommitted changes (staged, working tree, commit-to-commit)
**And** diffs are returned in unified diff format
**And** git diff completes in <1s for diffs up to 10K lines (NFR-002)

## Tasks / Subtasks

- [x] Task 1: Create Git Capability Module (AC: 1, 2)
  - [x] Create `src/sohnbot/capabilities/git/__init__.py`
  - [x] Create `src/sohnbot/capabilities/git/git_ops.py` with `git_status()` and `git_diff()` functions
  - [x] Implement structured `GitCapabilityError` exception class (follow pattern from `snapshot_manager.py`)
  - [x] Use `asyncio.create_subprocess_exec()` for async git command execution
  - [x] Implement robust error handling for missing git binary (catch `FileNotFoundError`)

- [x] Task 2: Implement git_status Function (AC: 1, 2)
  - [x] Execute `git status --porcelain=v2 --branch` for machine-parseable output
  - [x] Parse branch tracking information (current branch, ahead/behind counts)
  - [x] Parse modified/staged/untracked files from porcelain format
  - [x] Return structured dict: `{"branch": str, "ahead": int, "behind": int, "modified": list, "staged": list, "untracked": list}`
  - [x] Handle non-git directories gracefully with clear error message
  - [x] Enforce 10-second timeout (NFR-007)
  - [x] Optimize for <500ms performance (NFR-002)

- [x] Task 3: Implement git_diff Function (AC: 3, 4)
  - [x] Support three diff modes:
    - Working tree vs staged: `git diff` (default)
    - Staged vs HEAD: `git diff --cached`
    - Commit-to-commit: `git diff <commit1> <commit2>`
  - [x] Return diffs in unified diff format (default git output)
  - [x] Accept optional parameters: `diff_type`, `file_path`, `commit_refs`
  - [x] Enforce 30-second timeout (NFR-007)
  - [x] Optimize for <1s performance for diffs up to 10K lines (NFR-002)
  - [x] Handle binary files gracefully

- [x] Task 4: Register MCP Tools (AC: All)
  - [x] Update `src/sohnbot/runtime/mcp_tools.py`
  - [x] Register `mcp__sohnbot__git__status` tool
  - [x] Register `mcp__sohnbot__git__diff` tool
  - [x] Define input schemas for both tools (repo_path required)
  - [x] Map tool calls to `git_status()` and `git_diff()` functions

- [x] Task 5: Broker Integration (AC: All)
  - [x] Update `src/sohnbot/broker/operation_classifier.py`
  - [x] Classify both operations as **Tier 0** (read-only, no state modification)
  - [x] Ensure operations are logged to `execution_log` via broker
  - [x] No snapshot creation required (read-only operations)

- [x] Task 6: Integration and Testing
  - [x] Add unit tests for `git_ops.py` (minimum 8 tests):
    - git_status success case
    - git_status non-git directory error
    - git_status git binary not found error
    - git_status timeout handling
    - git_diff working tree vs staged
    - git_diff staged vs HEAD
    - git_diff commit-to-commit
    - git_diff binary file handling
  - [x] Add integration test verifying Telegram → Broker → Git capability flow
  - [x] Test cross-platform compatibility (Windows paths vs Unix paths)
  - [x] Verify performance meets NFR-002 requirements

- [x] Review Follow-ups (AI)
  - [x] [AI-Review][MEDIUM] Missing File List entries: `docs/development_environment.md` and `_bmad-output/implementation-artifacts/retro-action-item-2-findings.md` are not documented. [git status]
  - [x] [AI-Review][MEDIUM] Redundant Classification Logic: `git_status` and `git_diff` are defined twice in `src/sohnbot/broker/operation_classifier.py`. [src/sohnbot/broker/operation_classifier.py:35]
  - [x] [AI-Review][LOW] Brittle Porcelain v2 Parsing: `_parse_porcelain_v2` in `git_ops.py` uses potentially brittle path splitting. [src/sohnbot/capabilities/git/git_ops.py:100]

## Dev Notes

### Epic 2 Context

**Epic Goal:** Extend Epic 1's snapshot capability with full git integration and autonomous commit workflow.

**Epic Deliverables:**
- Story 2.1: Git Status & Diff Queries (THIS STORY)
- Story 2.2: Git Checkout for Rollback Operations
- Story 2.3: Autonomous Git Commits
- Story 2.4: Enhanced Snapshot Branch Management

**Why Story 2.1 First:**
This story provides the foundation for git integration. Stories 2.2, 2.3, and 2.4 will build upon the `git_ops.py` module and error handling patterns established here.

### Architecture Context

**Governed Operator Spine:**
- Git operations MUST go through the Broker for policy enforcement and logging
- Read-only operations (git status, git diff) are classified as **Tier 0**
- No state modification = no snapshot creation required
- Operations MUST be logged to `execution_log` with start/end timestamps

**Broker Classification (from architecture.md):**
- **Tier 0**: Read-only operations (list_files, read_file, search_files, **git_status**, **git_diff**)
- **Tier 1**: State-changing operations requiring snapshots (patch_file, git_commit, git_checkout)
- **Tier 2**: Destructive operations (delete_file, force_push) - NOT in this epic
- **Tier 3**: External commands (web_search, run_profile) - NOT in this story

**Git Binary Dependency (Action Item #2 Findings):**
✅ **CRITICAL LEARNING FROM EPIC 1 RETROSPECTIVE:**
- Epic 1 encountered environment issues where git binary was not found across different platforms (WSL/Windows/Cloud)
- Action Item #2 audit confirmed: `snapshot_manager.py` already has EXCELLENT error handling pattern
- **MUST FOLLOW THIS PATTERN for consistency:**

```python
try:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
except FileNotFoundError as exc:
    raise GitCapabilityError(
        code="git_not_found",
        message="git CLI is required for git operations. See docs/development_environment.md for installation instructions",
        details={"repo_path": repo_path},
        retryable=False,
    ) from exc
```

**Why This Pattern is Critical:**
- Catches missing git binary before subprocess execution fails
- Provides structured error with clear message
- References documentation for user to fix the issue
- Marks as non-retryable (installing git requires manual intervention)
- Consistent with existing `snapshot_manager.py` and `file_ops.py` patterns

### Critical Implementation Patterns

**1. Follow Existing Git Capability Pattern**

`snapshot_manager.py` (from Story 1.6) already established the pattern for git operations:
- Use `asyncio.create_subprocess_exec()` for async execution (NOT `subprocess.run()` for new async code)
- Catch `FileNotFoundError` for missing git binary
- Catch `asyncio.TimeoutError` for timeout enforcement
- Use structured `GitCapabilityError` exception
- Parse git output with proper encoding: `.decode("utf-8", errors="replace")`

**2. Error Handling Priority**

Based on Action Item #2 findings and Epic 1 learnings:
1. **FileNotFoundError** (git binary missing) → Clear user-facing error with docs reference
2. **asyncio.TimeoutError** (operation timeout) → Retryable error with timeout details
3. **Non-zero exit code** (git command failed) → Parse stderr for specific error context
4. **Invalid repo** (not a git repository) → Clear error: "Path is not a git repository"

**3. MCP Tool Registration Pattern**

From Story 1.3 (Telegram Gateway):
- Tool names follow format: `mcp__sohnbot__{capability}__{function}`
- Examples: `mcp__sohnbot__git__status`, `mcp__sohnbot__git__diff`
- Input schema MUST include `repo_path` (absolute path to git repository)
- Tool description should be clear and concise for Claude's agent
- Return values should be structured dicts, not raw strings

**4. Broker Integration Pattern**

From Story 1.2 (Broker Foundation):
- All operations MUST route through broker's `route_operation()` method
- Broker logs operation start with `log_operation_start(operation_id, operation_type, tier, metadata)`
- Broker logs operation end with `log_operation_end(operation_id, status, result_or_error)`
- Operation metadata should include: `{"repo_path": str, "operation": "git_status" | "git_diff"}`

### Project Structure Notes

**New Files to Create:**
```
src/sohnbot/capabilities/git/__init__.py
src/sohnbot/capabilities/git/git_ops.py
tests/unit/test_git_ops.py
tests/integration/test_git_operations.py
```

**Existing Files to Modify:**
```
src/sohnbot/runtime/mcp_tools.py (register new MCP tools)
src/sohnbot/broker/operation_classifier.py (add Tier 0 classification for git_status and git_diff)
```

**Existing Files to Reference (DO NOT MODIFY):**
```
src/sohnbot/capabilities/git/snapshot_manager.py (reference for error handling pattern)
src/sohnbot/capabilities/files/file_ops.py (reference for ripgrep error handling pattern)
src/sohnbot/broker/router.py (reference for operation logging)
```

**Directory Structure:**
```
src/sohnbot/capabilities/git/
├── __init__.py (exports: GitCapabilityError, SnapshotManager, git_status, git_diff)
├── snapshot_manager.py (existing - DO NOT MODIFY)
└── git_ops.py (NEW - create this file)
```

### Technical Constraints

**Performance Requirements (NFR-002):**
- `git status` MUST complete in <500ms for repos with 100K files
- `git diff` MUST complete in <1s for diffs up to 10K lines
- Use `git status --porcelain=v2` for faster machine-parseable output (vs verbose format)
- Consider limiting diff output size if performance is an issue

**Timeout Enforcement (NFR-007):**
- Default timeout for git operations: 10 seconds for status, 30 seconds for diff
- Use `asyncio.wait_for(process.communicate(), timeout=timeout_seconds)`
- On timeout, kill the process: `process.kill(); await process.wait()`

**Cross-Platform Compatibility (Epic 1 Retro Learning):**
- Use `pathlib.Path` for path handling (NOT string concatenation)
- Git commands are cross-platform compatible (git.exe on Windows, git on Unix)
- DO NOT use shell=True (security risk + platform inconsistency)
- Path separators are handled by `pathlib` and git itself

**Error Message Quality (Epic 1 Retro Action Item #2):**
- Always reference documentation: `docs/development_environment.md`
- Provide actionable guidance: "Install git via: brew install git (macOS), apt install git (Linux), choco install git (Windows)"
- Include context in error details: repo_path, command attempted, stderr output

### Previous Story Intelligence (Story 1.9 Learnings)

**From Story 1.9 (Ambiguous Request Postponement):**
- Async safety is critical: use `asyncio` primitives, never block the event loop
- Structured error handling with clear codes: `code`, `message`, `details`, `retryable`
- Notification system is available via `enqueue_notification()` for async messaging
- Database migrations are sequential: next migration will be `0005_*.sql`

**File Patterns Established in Epic 1:**
- Capabilities live in `src/sohnbot/capabilities/{category}/`
- Each capability has its own module file (e.g., `file_ops.py`, `git_ops.py`)
- Error classes are defined in the same module or `__init__.py`
- Unit tests mirror source structure: `tests/unit/test_{module}.py`
- Integration tests are workflow-based: `tests/integration/test_{workflow}.py`

**Testing Patterns from Epic 1:**
- Use `pytest` as test framework
- Mock external dependencies (git subprocess, file system) in unit tests
- Integration tests use real git repos (create temp repos with `tmp_path` fixture)
- Minimum 5 unit tests per module (higher for complex logic)
- Test both success and failure paths
- Test performance with `time` assertions where NFRs exist

### Git Command Specifics (Technical Reference)

**git status --porcelain=v2 Output Format:**
```
# branch.oid <commit-hash>
# branch.head <branch-name>
# branch.upstream <upstream-branch>
# branch.ab +<ahead> -<behind>
1 M. N... 100644 100644 100644 <hash> <hash> path/to/modified-file.py
1 .M N... 100644 100644 100644 <hash> <hash> path/to/staged-file.py
? path/to/untracked-file.py
```

- Lines starting with `#` are headers
- `1 M.` = modified in working tree (not staged)
- `1 .M` = modified and staged
- `?` = untracked file
- Branch tracking: `+X -Y` means X ahead, Y behind

**git diff Output Modes:**
1. `git diff` - Working tree vs staged (unstaged changes)
2. `git diff --cached` or `git diff --staged` - Staged vs HEAD (staged changes)
3. `git diff <commit1> <commit2>` - Commit-to-commit diff
4. `git diff <commit>` - Working tree vs specific commit
5. `git diff -- <file>` - Limit to specific file(s)

**Unified Diff Format:**
```diff
diff --git a/file.py b/file.py
index 123abc..456def 100644
--- a/file.py
+++ b/file.py
@@ -10,7 +10,7 @@ def function():
     old line
-    removed line
+    added line
     context line
```

### Latest Tech Information

**Git Version Requirements:**
- Minimum: Git 2.x (as documented in `docs/development_environment.md`)
- `--porcelain=v2` format introduced in Git 2.11.0 (2016) - safe to use
- `--no-optional-locks` flag (optional) prevents background operations from interfering

**Python asyncio Best Practices (2026):**
- Use `asyncio.create_subprocess_exec()` for async subprocess (NOT `subprocess.run()`)
- Always use `asyncio.wait_for()` for timeout enforcement
- Properly cleanup: `process.kill(); await process.wait()` on timeout
- Handle process communication: `stdout, stderr = await process.communicate()`

**Git Best Practices for Automation:**
- Use `--porcelain` formats for machine-parseable output
- Avoid `--no-pager` unless needed (already default for automation)
- Use `-C <path>` to specify working directory (vs `cd` + `git`)
- Example: `git -C /path/to/repo status --porcelain=v2`

### References

**Architecture Source:**
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 2: Git Operations & Version Control]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.1: Git Status & Diff Queries]

**System Binary Error Handling Pattern:**
- [Source: src/sohnbot/capabilities/git/snapshot_manager.py:140-146] - git binary FileNotFoundError handling
- [Source: src/sohnbot/capabilities/files/file_ops.py:184-190] - ripgrep binary FileNotFoundError handling
- [Source: _bmad-output/implementation-artifacts/retro-action-item-2-findings.md] - Complete system binaries audit

**Broker Integration Pattern:**
- [Source: src/sohnbot/broker/router.py] - Operation routing and logging
- [Source: src/sohnbot/broker/operation_classifier.py] - Tier classification logic

**MCP Tool Registration Pattern:**
- [Source: src/sohnbot/runtime/mcp_tools.py] - Existing tool registrations
- [Source: _bmad-output/implementation-artifacts/1-3-telegram-gateway-claude-agent-sdk-integration.md] - MCP integration story

**Development Environment Setup:**
- [Source: docs/development_environment.md] - Git installation instructions for all platforms
- [Source: README.md:65-74] - Runtime CLI dependencies table

## Dev Agent Record

### Agent Model Used

GPT-5 Codex (CLI)

### Debug Log References

- `python3 -m compileall src tests` (pass)
- `.venv/bin/pytest -q tests/unit/test_git_ops.py tests/integration/test_git_operations.py tests/integration/test_broker_integration.py tests/unit/test_broker.py tests/unit/test_mcp_tools.py` (pass: 35 passed, 2 skipped)

### Completion Notes List

- Implemented async git capability module with `git_status()` and `git_diff()` in `git_ops.py`, reusing structured `GitCapabilityError`.
- Added robust subprocess handling for git binary missing, non-git repository, command failure, and timeout enforcement.
- Added porcelain v2 parser for branch/ahead/behind/modified/staged/untracked git status fields.
- Implemented three diff modes: `working_tree`, `staged`, and `commit` (commit-to-commit), with optional file scoping.
- Wired broker git execution path to actual git ops and enforced `repo_path` validation for status/diff actions.
- Replaced MCP git status/diff stubs with real broker mappings and response formatting.
- Added unit test suite `test_git_ops.py` with 8 focused scenarios, plus integration test `test_git_operations.py`.
- Updated existing broker integration test to pass required `repo_path` for git status completeness checks.
- Removed redundant git Tier 0 classification branch in `operation_classifier.py` to avoid duplicate logic paths.
- Hardened porcelain v2 path parsing with explicit tab-delimited extraction and fallback token parsing, including rename/copy path records.
- Added targeted regression coverage for porcelain rename records and reran focused broker/git unit tests.
- ✅ Resolved review finding [MEDIUM]: File List now includes requested documentation artifact entries.
- ✅ Resolved review finding [MEDIUM]: duplicate classification logic removed.
- ✅ Resolved review finding [LOW]: porcelain parser made more robust against format variance.

### File List

- src/sohnbot/capabilities/git/git_ops.py (new)
- src/sohnbot/capabilities/git/__init__.py (modified)
- src/sohnbot/broker/router.py (modified)
- src/sohnbot/runtime/mcp_tools.py (modified)
- src/sohnbot/broker/operation_classifier.py (modified)
- tests/unit/test_git_ops.py (new)
- tests/integration/test_git_operations.py (new)
- tests/integration/test_broker_integration.py (modified)
- docs/development_environment.md (modified)
- _bmad-output/implementation-artifacts/retro-action-item-2-findings.md (modified)
