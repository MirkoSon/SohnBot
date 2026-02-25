---
document_type: Product Requirements Document
project_name: SohnBot
version: 2.1-governed-operator
date: 2026-02-25
status: ALIGNED
classification: internal
inputDocuments:
  - E:\GIT\SohnBot\docs\ProductBrief.md
  - E:\GIT\SohnBot\docs\PRD.md
enhancement_source: E:\GIT\SohnBot\docs\PRD-validation-report.md
governance_alignment: Governed operator philosophy (autonomous, structural safety, non-babysitting)
---

# Product Requirements Document v2.0 – SohnBot (Local Autonomous Telegram Agent)

---

## Executive Summary

**Vision:**
Build a private, autonomous AI agent that operates locally as a trusted development companion—capable of editing code, managing repositories, searching the web, and running scheduled workflows—while remaining structurally safe, observable, and recoverable.

**Differentiator:**
Structural safety over prompt-based safety. Security comes from architectural constraints (scope isolation, capability boundaries, Git recoverability), not from trusting model behavior or requiring frequent human confirmations.

**Governed Operator Philosophy:**
SohnBot is a governed operator, not a supervised assistant. It operates autonomously within strict structural boundaries. Human intervention is exceptional, not routine. Recoverability (snapshots + Git rollback) is the primary safety mechanism. Babysitting is not required for normal operation.

**Target Users:**
- Primary: Technically skilled developers operating on local machines
- Comfortable with Git and system tooling
- Want AI assistance without giving up control
- Trust structural safety over prompt-based approvals

**Business Objective:**
Enable safe local AI automation for development workflows, reducing friction in repetitive tasks while maintaining complete recoverability and control through architecture, not supervision.

**Key Innovation:**
Governed, modular local automation system that operates autonomously within structural guardrails—not "an AI with a shell" or "a supervised assistant" but a "controlled operator" that acts independently within defined scope.

---

## Success Criteria

**SC-001: Autonomous Operation**
- System operates autonomously for 30+ consecutive days without manual intervention
- Measured by: System uptime logs and intervention tracking
- Target: 95th percentile of 30-day periods require zero manual fixes

**SC-002: Data Integrity**
- Zero data corruption incidents outside allowed scopes (~/Projects, ~/Notes)
- Measured by: File integrity checks, scope violation logs
- Target: 100% of operations remain within configured roots

**SC-003: Scheduling Reliability**
- Zero duplicate scheduled job executions
- Measured by: Job execution logs with slot tracking
- Target: 100% idempotent job execution over 30-day period

**SC-004: Recoverability**
- 100% Git state recoverability for all changes
- Measured by: Snapshot restoration tests, rollback success rate
- Target: Any change reversible within 60 seconds

**SC-005: Task Efficiency**
- Web search and automation improve task completion time by 30%
- Measured by: Time tracking on common tasks (before/after comparison)
- Target: 5 common workflows complete 30% faster with agent assistance

**SC-006: User Trust**
- User reports high trust in agent after 30 days of operation
- Measured by: Post-deployment survey (1-10 scale)
- Target: Trust rating ≥8/10 after 30-day usage period

---

## Operation Risk Classification

SohnBot classifies all operations into risk tiers to determine appropriate structural safety mechanisms. Safety comes from architecture (snapshots, scope boundaries, logging), not from confirmation prompts.

### Tier 0: Read-Only Operations

**Examples:** File read (FR-002), search (FR-003), git status (FR-010), git diff (FR-011)

**Safety mechanism:** Scope validation (FR-020)

**Execution policy:** Always allowed, no snapshot required

**Logging:** Standard operation log (FR-022)

**User interaction:** None required

---

### Tier 1: Single-File Scoped Edits

**Examples:** Single-file patch (FR-004), lint fix on one file

**Safety mechanism:** Auto-snapshot before edit (FR-005) + scope validation (FR-020)

**Execution policy:** Snapshot → Execute → Log

**User interaction:** None required (autonomous execution)

**Rollback:** User can restore via FR-006 if needed

---

### Tier 2: Multi-File Scoped Edits

**Examples:** Multi-file refactoring (UJ-007), batch edits across project

**Safety mechanism:** Auto-snapshot before edits (FR-005) + enhanced logging + scope validation

**Execution policy:** Snapshot → Execute → Enhanced log with affected files

**User interaction:** None required (autonomous execution)

**Notification:** Post-execution summary sent to Telegram (FR-034)

**Rollback:** User can restore entire operation via FR-006

---

### Tier 3: Destructive Operations (Future Phase Only)

**Examples:** File deletion, mass rename, repository deletion

**Safety mechanism:** Not implemented in Phase 1 MVP

**Execution policy:** Requires explicit command syntax (not natural language)

**Future design:** Will require user confirmation via explicit destructive command syntax

---

### Core Principle

**The system does not require routine approvals. Recoverability is the safety valve.**

Snapshots + Git + logging provide complete undo capability. Users intervene only when they want to rollback, not before operations execute.

---

## Product Scope

### Phase 1: MVP (Months 1-2)
**Goal:** Validate core autonomous file operations with structural safety

**Core Capabilities:**
- Telegram gateway for remote control
- File operations (read, search, patch-based edits) within scoped directories
- Git integration (status, diff, commit) with automatic snapshots
- Basic command profiles (lint, build, test)
- SQLite persistence for operation logs
- Basic observability (operation logging, status queries)

**Success Metric:** User successfully automates 3+ daily workflows with zero scope violations

### Phase 2: Enhanced Automation (Months 3-4)
**Goal:** Add scheduling and web research capabilities

**Additional Capabilities:**
- Internal scheduler with idempotent catch-up logic
- Brave web search integration with caching
- Heartbeat system for daily summaries
- Enhanced command profiles
- Dry-run mode for testing operations

**Success Metric:** Scheduled jobs run reliably for 30+ days without duplicates or misses

### Phase 3: Cross-Platform & Polish (Months 5-6)
**Goal:** Extend to Linux/macOS, add advanced features

**Additional Capabilities:**
- Cross-platform support (Linux, macOS)
- Configurable permission tiers
- Automatic snapshot pruning
- Read-only analysis mode
- Performance optimization

**Success Metric:** Runs on 3 platforms with <5% platform-specific code

### Future Vision
- Plugin system for custom modules
- Limited shell profile (optional, user-configured)
- Remote deployment to home server
- Multi-device orchestration
- Structured NLP training for better command translation

---

## User Journeys

### UJ-001: Morning Repository Summary
**Actor:** Developer (Mirko)
**Frequency:** Daily (scheduled 9am)
**Goal:** Understand overnight changes across all project repositories

**Steps:**
1. Scheduled job triggers at 9:00am (user's local timezone)
2. System scans all repos in ~/Projects for commits since last summary (24h window)
3. For each repo with changes:
   - Run `git log --since="24 hours ago" --oneline`
   - Run `git diff --stat HEAD~1`
   - Summarize: repo name, commit count, files changed, key changes
4. Generate consolidated summary message
5. Post summary to Telegram with format:
   ```
   📊 Morning Repo Summary (9:00 AM)

   sohn-bot/ - 3 commits, 8 files
   - Added scheduler module
   - Fixed path validation bug

   notes/ - 1 commit, 2 files
   - Updated project roadmap
   ```
6. User reviews summary in <60 seconds

**Success Criteria:**
- Summary delivered within 5 minutes of 9am trigger
- All repos scanned automatically
- User understands changes without opening IDE

**Traces to:** SC-003 (scheduling), SC-005 (efficiency)

---

### UJ-002: Autonomous Lint & Commit
**Actor:** Agent (autonomous, user-initiated)
**Frequency:** On-demand
**Goal:** Fix linting errors and commit changes without manual intervention

**Steps:**
1. User sends Telegram message: "Fix the linting errors in auth.js"
2. Agent reads ~/Projects/[current-project]/auth.js
3. Agent identifies linting errors
4. Agent generates patch to fix errors
5. **TIER 1 OPERATION (Single-file):**
   - Create git snapshot branch: `snapshot/lint-auth-[timestamp]`
   - Apply patch to auth.js
   - Run `lint_project` command profile (FR-015)
6. **If lint succeeds:**
   - Run `git commit -m "Fix: Resolve linting errors in auth.js"`
   - Post to Telegram: "✅ Committed: Fix linting errors in auth.js"
   - Include snapshot branch name in notification
7. **If lint fails:**
   - Rollback changes automatically (checkout snapshot branch)
   - Retry fix once with different approach
   - If still failing: notify user with error details
   - Post to Telegram: "❌ Unable to fix linting errors. Manual review needed. Snapshot: snapshot/lint-auth-[timestamp]"

**Success Criteria:**
- Bug fixed and committed without manual approval steps
- User notified post-execution with snapshot reference
- Failed attempts rollback automatically
- No babysitting required

**Traces to:** SC-001 (autonomous), SC-004 (recoverability), SC-005 (efficiency)

---

### UJ-003: Recovery from Unwanted Changes
**Actor:** Developer (Mirko)
**Frequency:** Edge case (when agent makes unwanted changes)
**Goal:** Quickly rollback unwanted file modifications

**Steps:**
1. Agent makes file changes and commits (UJ-002 scenario)
2. User notices unwanted changes: "That commit removed a function I needed"
3. User sends Telegram: "/rollback auth.js" or "undo last changes to auth.js"
4. Agent responds:
   ```
   🔄 Available Rollback Points:
   1. [2 min ago] Fix linting errors - auth.js
   2. [1 hour ago] Add validation logic - auth.js, helpers.js
   3. [Yesterday] Refactor authentication - auth.js, config.js

   Reply with number to restore, or 'cancel'
   ```
5. User replies: "1"
6. Agent:
   - Checks out snapshot branch from step 1
   - Restores auth.js to pre-change state
   - Creates new commit: "Revert: Restore auth.js to pre-lint state"
   - Posts to Telegram: "✅ Restored auth.js to 2 minutes ago"
7. User verifies file restored correctly

**Success Criteria:**
- Rollback completes in <60 seconds
- User can browse available restore points
- Restoration preserves git history

**Traces to:** SC-004 (recoverability)

---

### UJ-004: Scheduled Weekly Notes Digest
**Actor:** Agent (scheduled)
**Frequency:** Weekly (Sunday 6pm)
**Goal:** Summarize week's notes changes for review

**Steps:**
1. Scheduled job triggers: Sunday 6:00pm
2. System scans ~/Notes for files modified in last 7 days
3. For each modified file:
   - Extract filename and modification date
   - Read first paragraph or heading
   - Identify type: new file, updated file, or deleted
4. Generate digest:
   ```
   📚 Weekly Notes Digest (Feb 18-25)

   New Notes (3):
   - project-ideas.md - "Autonomous agent concepts"
   - meeting-notes-2026-02-20.md - "Team sync on Q1 goals"

   Updated Notes (5):
   - roadmap.md - Added Phase 2 milestones
   - reading-list.md - Added 3 articles on LLM safety

   Summary: 8 total changes, 3 new files, 5 updates
   ```
5. Post digest to Telegram
6. User reviews weekly activity

**Success Criteria:**
- Digest delivered every Sunday at 6pm (no duplicates even if system restarts)
- All notes changes captured
- Helps user remember weekly progress

**Traces to:** SC-003 (scheduling), SC-005 (efficiency)

---

### UJ-005: Research-Assisted Code Fix
**Actor:** Developer + Agent
**Frequency:** On-demand
**Goal:** Use web search to fix unknown error

**Steps:**
1. User encounters error: "ModuleNotFoundError: anthropic-sdk"
2. User sends Telegram: "How do I fix: ModuleNotFoundError anthropic-sdk"
3. Agent performs Brave search: "python anthropic-sdk installation fix"
4. Agent reads top 3 search results (cached for 7 days)
5. Agent synthesizes answer:
   ```
   🔍 Search Results:

   The error indicates the Anthropic SDK isn't installed.

   Fix:
   pip install anthropic

   Sources:
   - docs.anthropic.com/installation
   - stackoverflow.com/q/12345

   Would you like me to run this command via the install_package profile?
   ```
6. User replies: "yes"
7. Agent runs `pip install anthropic` via command profile
8. Agent confirms: "✅ Package installed successfully"

**Success Criteria:**
- Search provides accurate answer within 30 seconds
- User can request automated fix
- Search results cached to save API costs

**Traces to:** SC-005 (efficiency - search improves correctness)

---

### UJ-006: Daily Heartbeat Status
**Actor:** Agent (scheduled)
**Frequency:** Daily (6pm)
**Goal:** Provide operational visibility without manual checks

**Steps:**
1. Scheduled job triggers: 6:00pm daily
2. System collects stats from last 24 hours:
   - Operations performed (file edits, commits, searches)
   - Errors encountered (if any)
   - Scheduled jobs executed
   - Scope violations attempted (should be 0)
3. Generate heartbeat message:
   ```
   💓 Daily Heartbeat (6:00 PM)

   Operations: 12
   - 5 file edits
   - 3 git commits
   - 2 web searches
   - 2 scheduled jobs

   Status: ✅ All systems normal
   Errors: 0
   Scope violations: 0

   Uptime: 15 days, 4 hours
   ```
4. Post to Telegram
5. User glances at status (takes <10 seconds)

**Success Criteria:**
- Heartbeat delivered daily at 6pm
- User aware of agent activity without manual inspection
- Errors surface immediately

**Traces to:** SC-001 (autonomous operation), SC-006 (user trust)

---

### UJ-007: Safe Multi-File Refactoring
**Actor:** Agent (user-initiated)
**Frequency:** Occasional
**Goal:** Refactor code across multiple files with automatic safety

**Steps:**
1. User requests: "Rename function 'processData' to 'processUserData' across the project"
2. Agent searches project for all occurrences: `ripgrep "processData"`
3. Agent identifies affected files: auth.js, helpers.js, tests.js (3 files)
4. **TIER 2 OPERATION (Multi-file):**
   - Create snapshot branch: `snapshot/refactor-processData-[timestamp]`
   - Generate patches for all 3 files
   - Apply all patches
5. Agent runs `lint_project` and `run_tests` profiles
6. **If tests pass:**
   - Commit: "Refactor: Rename processData to processUserData"
   - Post to Telegram:
     ```
     ✅ Refactoring Complete

     Files changed: 3
     - auth.js (2 occurrences)
     - helpers.js (5 occurrences)
     - tests.js (3 occurrences)

     Tests: All passing
     Snapshot: snapshot/refactor-processData-2026-02-25-1430
     ```
7. **If tests fail:**
   - Rollback to snapshot branch automatically
   - Post to Telegram:
     ```
     ❌ Refactoring Rolled Back

     Tests failed after refactoring.
     Changes reverted to snapshot: snapshot/refactor-processData-2026-02-25-1430

     Error: [test failure details]
     ```

**Success Criteria:**
- Multi-file changes execute autonomously with snapshot protection
- User notified post-execution with results
- Automatic rollback if tests fail
- No pre-execution approvals required

**Traces to:** SC-002 (data integrity), SC-004 (recoverability), SC-001 (autonomous)

---

### UJ-008: Configure New Scheduled Task
**Actor:** Developer (Mirko)
**Frequency:** Occasional setup
**Goal:** Set up new recurring automation task

**Steps:**
1. User wants daily TODO scan at 8am
2. User sends natural language: "Scan all project files for TODO comments every morning at 8am and send me a list"
3. Agent interprets request and posts confirmation:
   ```
   📅 New Scheduled Job

   Name: Daily TODO Scan
   Frequency: Every day at 8:00 AM (local time)
   Action: Search all files in ~/Projects for "TODO" comments
   Output: Send list to Telegram

   Confirm creation? (yes/no)
   ```
4. User confirms: "yes"

**Note:** Scheduled job creation requires explicit confirmation because it creates persistent automated behavior. This is an exceptional case where confirmation prevents unintended recurring operations.
5. Agent creates job in SQLite:
   ```sql
   INSERT INTO jobs (name, cron_expression, timezone, action_type, enabled)
   VALUES ('Daily TODO Scan', '0 8 * * *', 'America/New_York', 'search_and_report', true)
   ```
6. Agent responds: "✅ Job scheduled. Next run: Tomorrow 8:00 AM"
7. Next day at 8am, job executes automatically
8. User can modify/disable: "/schedule list" to see all jobs

**Success Criteria:**
- Natural language converts to structured schedule
- User confirms before job creation
- Job persists across system restarts

**Traces to:** SC-003 (scheduling reliability)

---

## Domain Requirements

### Security Domain

**DR-001: Authentication & Authorization**
- Telegram bot token stored in environment variable (not committed to Git)
- Only allowlisted Telegram chat IDs can interact with agent
- Chat ID validation occurs before any command processing
- Measured by: Zero unauthorized access attempts succeed

**DR-002: Scope Isolation & Path Traversal Prevention**
- All file paths normalized to absolute paths before validation
- Path traversal attacks (../, symlinks) detected and rejected
- Operations outside ~/Projects and ~/Notes return error before execution
- Measured by: 100% of path traversal attempts blocked in security testing

**DR-003: API Key Management**
- Brave API key stored in environment variable (.env file or system environment)
- Key loaded at startup from environment
- Not logged in operation logs
- Not committed to git (via .gitignore)
- Key rotation supported: update .env, restart process
- Measured by: Keys never appear in logs or git history (manual audit)

**Note:** Practical environment variable storage. No false implication of enterprise-grade encryption or key vaults.

**DR-004: Command Injection Prevention**
- Command profiles use argument schema validation
- Arguments sanitized before shell execution
- No direct shell command string interpolation
- Regex patterns validated for catastrophic backtracking
- Measured by: Injection attack tests achieve 0% success rate

**DR-005: Audit Logging**
- All operations logged: timestamp, actor (Telegram user), capability, scope, files affected, result
- Logs retained for 90 days minimum
- Logs stored in SQLite with read-only access after write
- Measured by: 100% of operations have corresponding audit log entry

**DR-006: Rate Monitoring & Alerts**
- Telegram bot rate limited to 30 messages/minute (prevents spam loops)
- Brave API soft threshold: 100 searches/day (configurable, user-settable)
- Threshold exceedance triggers notification, not blocking
- File operations: soft monitoring at 50/minute per directory (logs warning if exceeded)
- Measured by: Rate alerts logged, user notified of unusual volume

**Note:** Monitoring and awareness, not hard blocking. User retains operational control.

---

### Privacy & Data Handling

**DR-007: Local-Only Data Processing**
- All file processing occurs locally (no cloud file uploads)
- Git operations local-only (no force push to remotes)
- User data never transmitted except via Telegram (encrypted in transit)
- Measured by: Network traffic monitoring shows no file data egress

**DR-008: No PII Collection**
- System does not collect personally identifiable information
- File paths and contents remain local
- Logs contain operation metadata only (not file contents)
- Measured by: Log audit confirms no PII storage

---

### Compliance Requirements

**DR-009: Open Source Dependency Management**
- All dependencies tracked in requirements.txt / package.json
- Security vulnerability scanning via `npm audit` / `pip-audit`
- No GPL-licensed dependencies (to allow future proprietary use)
- Measured by: Dependency audit passes with zero high-severity vulnerabilities

**DR-010: Data Retention Policy**
- Operation logs: 90 days retention, then auto-delete
- Snapshot branches: 30 days retention, then auto-prune
- Search cache: 7 days retention, then auto-invalidate
- Measured by: Automated cleanup jobs run weekly, confirmed via log review

---

## Functional Requirements

### File Operations

**FR-001: List Files in Scope**
- User can list all files within configured allowed roots (~/Projects, ~/Notes)
- Listing excludes hidden folders (.git, .venv, node_modules)
- Returns: file paths, sizes, modification times
- Traces to: UJ-001, UJ-007
- Depends on: FR-020 (scope validation)

**FR-002: Read File Contents**
- User can read any file within allowed roots
- File size limit: 10MB per file (prevents memory exhaustion)
- Binary files return error (text files only)
- Traces to: UJ-002, UJ-005
- Depends on: FR-020 (scope validation)

**FR-003: Search File Contents**
- User can search for text patterns across all files in scope
- Uses ripgrep for performance
- Returns: file paths, line numbers, matched content
- Regex patterns timeout after 5 seconds (prevents catastrophic backtracking)
- Traces to: UJ-005, UJ-007, UJ-008
- Depends on: FR-020 (scope validation), DR-004 (regex validation)

**FR-004: Apply Patch-Based Edits**
- User can modify files via unified diff patches (no full-file rewrites)
- Patch validation before application (ensures valid diff format)
- Patch size limit: 50KB per patch (prevents large unreviewed changes)
- Traces to: UJ-002, UJ-007
- Depends on: FR-005 (snapshot creation), FR-020 (scope validation)

**FR-005: Automatic Snapshot Creation**
- System creates Git snapshot branch before any file modification
- Snapshot naming: `snapshot/[operation-type]-[timestamp]`
- Snapshots created for: single-file edits, multi-file operations
- Traces to: UJ-002, UJ-007, SC-004
- Depends on: FR-010 (git operations)

**FR-006: Rollback to Previous State**
- User can restore files to any previous snapshot
- Restoration preserves git history (creates new commit, doesn't rewrite history)
- Snapshot browsing: list available restore points with timestamps
- Traces to: UJ-003, SC-004
- Depends on: FR-011 (git checkout)

**FR-007: Multi-File Operation Logging**
- Operations affecting >1 file create automatic snapshot (FR-005)
- Enhanced logging captures: affected files, operation summary, diff size, timestamp
- Post-execution notification sent to Telegram with operation summary
- No pre-execution confirmation required (governed operator model)
- User can rollback via FR-006 if operation was undesired
- Traces to: UJ-007 (multi-file refactoring), SC-004 (recoverability)
- Depends on: FR-004 (patch edits), FR-005 (snapshot creation)

**FR-008: File Size Enforcement**
- Read operations: max 10MB per file
- Write operations: max 50KB patch size
- Exceeding limits returns error with helpful message
- Traces to: SC-002, DR-004
- Depends on: None

**FR-009: Binary File Rejection**
- System detects binary files (images, videos, executables)
- Binary modification attempts return error: "Binary files not supported"
- Exception: .db files (SQLite) readable but not editable
- Traces to: SC-002
- Depends on: None

---

### Git Operations

**FR-010: Git Status**
- User can query git status for any repo in scope
- Returns: modified files, staged files, branch name, commit status
- Works across multiple repos (~/Projects may have many repos)
- Traces to: UJ-001
- Depends on: FR-020 (scope validation)

**FR-011: Git Diff**
- User can view diffs for uncommitted changes
- Supports: staged diff, working tree diff, commit-to-commit diff
- Returns: unified diff format
- Traces to: UJ-001, UJ-002
- Depends on: FR-010 (git status)

**FR-012: Git Commit (Autonomous)**
- Agent can create commits after successful lint/build validation
- Commit message format: "[Type]: [Summary]" (e.g., "Fix: Resolve linting errors")
- Auto-commits triggered by: successful edit + lint + build cycle
- Traces to: UJ-002, UJ-007, SC-001
- Depends on: FR-015 (lint profile), FR-016 (build profile)

**FR-013: Git Checkout (Branch)**
- Agent can checkout snapshot branches for rollback
- Restricted to local branches only (no remote branch checkout)
- Used for: rollback operations, snapshot restoration
- Traces to: UJ-003, FR-006
- Depends on: FR-010 (git status)

**FR-014: Git Snapshot Branch Creation**
- Agent creates lightweight snapshot branches before operations
- Branch naming: `snapshot/[operation]-[YYYY-MM-DD-HHMM]`
- Snapshots auto-pruned after 30 days (configurable)
- Traces to: UJ-002, UJ-007, SC-004
- Depends on: FR-010 (git status)

---

### Command Profiles

**FR-015: Lint Project Profile**
- Executes project linter (eslint, pylint, etc.) on specified files
- Arguments: file path(s) to lint
- Timeout: 60 seconds
- Returns: lint results (errors, warnings, exit code)
- Traces to: UJ-002, UJ-007
- Depends on: DR-004 (argument validation)

**FR-016: Build Project Profile**
- Executes project build command (npm run build, make, etc.)
- Arguments: build target (optional)
- Timeout: 300 seconds (5 minutes)
- Returns: build output, exit code
- Traces to: UJ-002
- Depends on: DR-004 (argument validation)

**FR-017: Run Tests Profile**
- Executes project test suite
- Arguments: test file/pattern (optional, defaults to all tests)
- Timeout: 600 seconds (10 minutes)
- Returns: test results, pass/fail count, exit code
- Traces to: UJ-007
- Depends on: DR-004 (argument validation)

**FR-018: Ripgrep Search Profile**
- Executes ripgrep search within scoped directories
- Arguments: search pattern, file type filters (optional)
- Timeout: 30 seconds
- Returns: matching files, line numbers, content
- Traces to: UJ-007, UJ-008, FR-003
- Depends on: DR-004 (regex validation), FR-020 (scope validation)

**FR-019: Profile Chaining Limit**
- Maximum 5 command profile executions per user request
- Prevents: profile chaining attacks, runaway automation loops
- Exceeding limit returns error: "Profile execution limit reached"
- Traces to: DR-004
- Depends on: None

---

### Scope & Safety

**FR-020: Scope Validation**
- All file operations validate paths are within ~/Projects or ~/Notes
- Path normalization: resolve symlinks, relative paths to absolute
- Path traversal attempts (../, ~, symlinks outside scope) rejected
- Rejection returns error: "Path outside allowed scope"
- Traces to: All file/git FRs, SC-002, DR-002
- Depends on: None (foundational)

**FR-021: Configured Scope Roots**
- User configures allowed directory roots during initial setup
- Default roots: ~/Projects, ~/Notes (Windows: %USERPROFILE%\Projects, %USERPROFILE%\Notes)
- Roots stored in config file, modifiable via /config command
- Traces to: SC-002, DR-002
- Depends on: None

**FR-022: Operation Logging**
- All operations logged to SQLite with: timestamp, Telegram user ID, operation type, file paths, result status
- Log retention: 90 days, then auto-delete
- Logs queryable via /logs command
- Traces to: UJ-006, DR-005
- Depends on: None

**FR-023: Dry-Run Mode**
- User can execute operations in dry-run mode (simulate, don't apply)
- Activated via: /dryrun prefix or --dry-run flag
- Returns: operation preview, affected files, no actual changes
- Traces to: UJ-007 (testing refactors)
- Depends on: All operation FRs

---

### Web Search

**FR-024: Brave Web Search**
- User can perform web searches via Brave Search API
- Search modes: fresh (no cache), static (7-day cache)
- Returns: top 5 results with titles, URLs, snippets
- Traces to: UJ-005, SC-005
- Depends on: FR-026 (soft rate monitoring), DR-003 (API key)

**FR-025: Search Result Caching**
- Static searches cached for 7 days (configurable)
- Cache key: query hash + freshness mode
- Time-sensitive queries bypass cache (dates, "today", "latest")
- Traces to: UJ-005 (cost efficiency)
- Depends on: FR-024 (web search)

**FR-026: Search Volume Monitoring**
- Soft threshold warning at 100 searches per day (configurable)
- Threshold exceedance triggers Telegram notification:
  ```
  ⚠️ Search Volume Alert

  Daily searches: 127 (threshold: 100)
  Monitor Brave API quota to avoid cost overruns.

  Configure threshold: /config search_threshold [number]
  ```
- No hard blocking (user retains control over quota management)
- User can configure alert threshold via config
- Traces to: DR-006 (cost awareness)
- Depends on: FR-024 (web search)

---

### Scheduler

**FR-027: Schedule Job Creation**
- User can create scheduled jobs via natural language or explicit commands
- Job schema: name, cron expression, timezone, action type, enabled status
- Jobs persisted in SQLite, survive system restarts
- Traces to: UJ-001, UJ-004, UJ-006, UJ-008, SC-003
- Depends on: FR-028 (job execution)

**FR-028: Idempotent Job Execution**
- Scheduler uses catch-up logic: run most recent missed slot once (no backlog replay)
- Job tracking: last_completed_slot field prevents duplicates
- Concurrency: max 3 concurrent scheduled jobs
- Traces to: UJ-001, UJ-004, UJ-006, SC-003
- Depends on: FR-027 (job creation)

**FR-029: Timezone-Aware Scheduling**
- All job times stored in UTC internally
- User-facing times displayed in local timezone
- DST handling: jobs scheduled during non-existent hours (2am spring-forward) run at next valid time
- Traces to: UJ-001 (9am local time), UJ-004 (6pm local time), SC-003
- Depends on: FR-027 (job creation)

**FR-030: Job Timeout Enforcement**
- Scheduled jobs timeout after 10 minutes (600 seconds)
- Timeout triggers: job cancellation, error logged, user notified
- Prevents: infinite loops, hung operations
- Traces to: SC-003
- Depends on: FR-028 (job execution)

**FR-031: Job Management Commands**
- User can list jobs: /schedule list
- User can disable job: /schedule disable [name]
- User can delete job: /schedule delete [name]
- User can modify job: /schedule edit [name]
- Traces to: UJ-008 (configure scheduled tasks)
- Depends on: FR-027 (job creation)

---

### Communication & Observability

**FR-032: Telegram Command Interface**
- User sends commands via Telegram chat
- Supports: natural language, explicit /commands
- Explicit commands bypass NLP interpretation (faster, more reliable)
- Traces to: All UJs
- Depends on: FR-033 (auth)

**FR-033: Telegram Authentication**
- Only allowlisted Telegram chat IDs can interact
- Chat ID allowlist stored in config, modifiable via config file only (not runtime)
- Unauthorized chat attempts logged and ignored
- Traces to: DR-001
- Depends on: None (foundational)

**FR-034: Operation Status Notifications**
- All autonomous operations post status to Telegram within 10 seconds
- Notification types: operation started, operation completed, errors, previews
- User can disable notifications: /notify off (logs still captured)
- Traces to: UJ-002, UJ-006, UJ-007
- Depends on: FR-032 (Telegram)

**FR-035: Heartbeat System**
- Configurable recurring status report (default: daily 6pm)
- Heartbeat reports: operations count, errors, scheduled jobs run, uptime
- User can modify heartbeat: /heartbeat configure
- Traces to: UJ-006, SC-001, SC-006
- Depends on: FR-027 (scheduler), FR-034 (notifications)

**FR-036: Postponement for Ambiguous Requests**
- Applies only when agent cannot determine operation intent (ambiguous natural language)
- Agent requests clarification via Telegram: "Did you mean [option A] or [option B]?"
- If no response within 60 seconds: operation postponed
- Retry notification sent after 30 minutes
- If still no response: operation cancelled safely
- Never auto-approve ambiguous operations
- Traces to: NFR-018 (natural language understanding)
- Depends on: FR-032 (Telegram)

**Note:** This is NOT a safety confirmation mechanism. This handles rare cases where the request itself is unclear. Structural safety (snapshots, scope) handles operation safety.

**FR-037: Query Operation Logs**
- User can query recent operations: /logs [hours]
- Returns: timestamp, operation type, files affected, result, errors
- Filterable by: operation type, success/failure, date range
- Traces to: UJ-006, FR-022
- Depends on: FR-022 (logging), FR-032 (Telegram)

### Observability

**FR-038: System Status via Telegram**
- User can query system status: /status
- Returns: uptime, version, supervisor status, last scheduler tick, last broker activity, in-flight operations, notification outbox count, last 10 operation results
- Read-only visibility into system health
- Traces to: SC-001 (autonomous operation), SC-006 (user trust)
- Depends on: FR-022 (logging), FR-032 (Telegram)

**FR-039: Resource Usage Monitoring via Telegram**
- User can query resource usage: /status resources
- Returns: CPU percentage, RAM usage (MB), database size (MB), log size (MB), git snapshot count, event loop lag (ms)
- Read-only visibility into resource consumption
- Traces to: SC-001 (autonomous operation)
- Depends on: FR-032 (Telegram)

**FR-040: Health Checks via Telegram**
- User can query system health: /health
- Returns: overall health status (healthy/degraded/unhealthy) with specific health check results
- Health checks: SQLite writable, scheduler lag, job timeouts, notifier alive, outbox stuck, disk usage (optional)
- Read-only diagnostic capability
- Traces to: SC-001 (autonomous operation), SC-006 (user trust)
- Depends on: FR-032 (Telegram)

**FR-041: Local HTTP Observability Server**
- Read-only HTTP server bound to localhost (127.0.0.1) only
- Endpoints: GET /status (JSON), GET /health (JSON), GET /metrics (JSON)
- No control actions exposed (no POST, PUT, DELETE, PATCH)
- Configurable port (default: 8080)
- Traces to: SC-001 (autonomous operation)
- Depends on: None (independent capability)

**FR-042: HTML Status Page**
- Local HTTP server serves HTML status page: GET / or GET /ui
- Displays: process info, active operations, scheduler next runs, resources, recent errors
- Auto-refreshes every 30 seconds
- Read-only visualization of system state
- Traces to: SC-006 (user trust)
- Depends on: FR-041 (HTTP server)

**FR-043: Runtime Status Snapshot Collection**
- Background task collects runtime status every 10-30 seconds (configurable)
- Non-blocking, independent failure domain
- Snapshot includes: process info, broker activity, scheduler state, notifier state, resource usage, health checks, recent operations
- In-memory cache updated each collection cycle
- Optional persistence to SQLite (disabled by default)
- Traces to: NFR-024 (observability overhead)
- Depends on: None (independent background task)

---

## Non-Functional Requirements

### Performance

**NFR-001: File Read Performance**
- File read operations complete in <200ms for files up to 1MB
- File read operations complete in <500ms for files 1-10MB
- Measured by: Operation latency monitoring over 30-day period
- Target: 95th percentile meets SLA

**NFR-002: Git Operations Performance**
- Git status completes in <500ms for repos up to 100K files
- Git diff completes in <1 second for diffs up to 10K lines
- Measured by: Git operation latency tracking
- Target: 95th percentile meets SLA

**NFR-003: Search Performance**
- Ripgrep search completes in <5 seconds for repos up to 100K files
- Web search (Brave API) completes in <3 seconds (95th percentile)
- Measured by: Search latency monitoring
- Target: 95th percentile meets SLA

**NFR-004: Scheduler Evaluation Frequency**
- Scheduler evaluates job queue every 60 seconds
- Job execution starts within 120 seconds of scheduled time (95th percentile)
- Measured by: Scheduler tick logs, job execution timestamps
- Target: 95% of jobs start within 2-minute window of scheduled time

**NFR-005: Notification Latency**
- Operation notifications delivered to Telegram within 10 seconds of event
- Measured by: Event timestamp vs Telegram delivery timestamp
- Target: 95th percentile <10 seconds

---

### Reliability

**NFR-006: System Uptime**
- System maintains 95% uptime over 30-day periods
- Excludes: planned restarts, user-initiated shutdowns
- Measured by: Process uptime tracking, crash logs
- Target: 95th percentile of 30-day windows meet 95% uptime

**NFR-007: Crash Recovery Time**
- System recovers from crash and restores state within 30 seconds
- State restored from SQLite persistence (jobs, logs, config)
- Measured by: Time from process restart to operational status
- Target: 95% of restarts complete within 30 seconds

**NFR-008: Job Execution Reliability**
- Scheduled jobs execute successfully 99% of the time
- Failures logged with error details
- Measured by: Job success rate over 30-day period
- Target: <1% failure rate

**NFR-009: Data Integrity**
- Zero file corruptions from agent operations
- File integrity verification: pre-operation hash vs post-operation validation
- Measured by: Corruption incident count over 30-day period
- Target: 0 corruptions

---

### Security

**NFR-010: Path Traversal Prevention**
- 100% of path traversal attempts blocked
- Measured by: Security testing with malicious path inputs
- Target: 0% success rate for attacks

**NFR-011: Command Injection Prevention**
- 100% of command injection attempts blocked
- Measured by: Security testing with malicious command inputs
- Target: 0% success rate for attacks

**NFR-012: Scope Violation Prevention**
- Zero successful operations outside configured scope roots
- Measured by: Scope violation attempt logs
- Target: 100% rejection rate for out-of-scope operations

**NFR-013: API Key Security**
- API keys stored in environment variables
- Keys never appear in logs, git history, or console output
- Protected via standard OS file permissions (.env file with appropriate permissions)
- Measured by: Log/repo audit for exposed secrets
- Target: 0 exposed secrets

**NFR-014: Audit Log Completeness**
- 100% of operations have corresponding audit log entry
- Measured by: Operation count vs log entry count
- Target: 1:1 ratio (every operation logged)

---

### Scalability

**NFR-015: Multi-Repo Support**
- System handles up to 50 repos in ~/Projects without performance degradation
- Repo scanning (UJ-001) scales linearly with repo count
- Measured by: Morning summary generation time with varying repo counts
- Target: <5 minutes for 50 repos

**NFR-016: File Count Scalability**
- System handles repos with up to 100K files per repo
- Search and git operations maintain performance (NFR-002, NFR-003)
- Measured by: Performance tests on large repos
- Target: Meets performance SLAs for 100K file repos

**NFR-017: Concurrent Operations**
- System handles up to 3 concurrent scheduled jobs without interference
- Interactive commands prioritized over scheduled jobs
- Measured by: Concurrency testing with overlapping jobs
- Target: No job failures due to concurrency conflicts

---

### Usability

**NFR-018: Natural Language Understanding**
- Agent correctly interprets 90% of natural language commands
- Ambiguous commands prompt clarification (not failed execution)
- Measured by: Command interpretation success rate over 30-day period
- Target: 90% success rate

**NFR-019: Response Time (User Interaction)**
- Interactive commands acknowledge receipt within 2 seconds
- Long-running operations send status updates every 30 seconds
- Measured by: Time to first Telegram response
- Target: 95th percentile <2 seconds to acknowledgment

**NFR-020: Error Message Clarity**
- Error messages include: what failed, why it failed, how to fix
- No technical stack traces sent to user (logged only)
- Measured by: User comprehension survey after 30 days
- Target: 80% of users understand errors without clarification

---

### Maintainability

**NFR-021: Automated Cleanup**
- Snapshot branches auto-pruned after 30 days
- Operation logs auto-deleted after 90 days
- Search cache auto-invalidated after 7 days
- Measured by: Storage usage monitoring, cleanup job logs
- Target: Automated cleanup runs weekly, 0 manual intervention

**NFR-022: Configuration Management**
- All configuration externalized (no hardcoded values)
- Config changes apply without code restart (where possible)
- Measured by: Config audit, restart requirement tracking
- Target: 80% of config changes apply without restart

**NFR-023: Dependency Vulnerability Management**
- Security audit runs weekly (npm audit / pip-audit)
- High-severity vulnerabilities remediated within 7 days
- Measured by: Vulnerability scan results, remediation time
- Target: 0 high-severity vulnerabilities in production

### Observability

**NFR-024: Observability Overhead**
- Snapshot collection consumes <2% CPU on average
- Snapshot collection completes in <100ms per cycle
- No blocking impact on broker, scheduler, or notifier operations
- Measured by: CPU profiling, collection latency tracking
- Target: 95th percentile meets SLA

**NFR-025: HTTP Server Security**
- HTTP server MUST bind to localhost (127.0.0.1 or ::1) only by default
- Binding to non-localhost addresses requires explicit manual configuration edit
- All HTTP routes are GET-only (no POST, PUT, DELETE, PATCH)
- No control actions exposed via HTTP endpoints
- Measured by: Configuration validation, security audit
- Target: 100% compliance with localhost-only binding

**NFR-026: Health Check Reliability**
- Health checks complete within 500ms (95th percentile)
- Health check failures do not block observability queries
- False positive rate <1% over 30-day period
- Measured by: Health check latency, accuracy tracking
- Target: 95th percentile latency, <1% false positives

**NFR-027: Observability Isolation**
- Observability module failures do not crash or block main system
- Independent failure domain with error boundary
- Observability queries are read-only (no writes to broker/scheduler/config state)
- Measured by: Fault injection testing, isolation verification
- Target: 100% isolation compliance

---

## High-Level Architecture

### System Components

```
Telegram Gateway
  ↓
Agent Runtime (Claude SDK)
  ↓
Broker Layer (Policy Enforcement + Capability Routing)
  ↓
Capability Modules:
  - Files Module (FR-001 to FR-009)
  - Git Module (FR-010 to FR-014)
  - Command Profiles (FR-015 to FR-019)
  - Web Search Module (FR-024 to FR-026)
  - Scheduler Module (FR-027 to FR-031)
  - Observability Module (FR-038 to FR-043) [Read-Only]
  ↓
Persistence Layer (SQLite):
  - Operation Logs (FR-022)
  - Scheduled Jobs (FR-027)
  - Search Cache (FR-025)
  - Configuration (FR-021)

Observability Interfaces (Read-Only):
  - Telegram Commands: /status, /health
  - HTTP Server (localhost:8080): /status, /health, /metrics, /ui
```

### Supervision

**Process Management:**
- pm2 (Phase 1: Windows)
- Configurable for other process managers (systemd, launchd)
- Auto-restart on crash
- Logs to file + stdout

**Health Monitoring:**
- Heartbeat system (FR-035)
- Process alive checks via pm2
- Operation logging for debugging (FR-022)
- Observability system (FR-038 to FR-043): /status, /health commands, HTTP server

---

## Capability Modules (Detailed)

### 6.1 Files Module

**Purpose:** Implements FR-001 to FR-009

**Capabilities:**
- list: List files in scope (FR-001)
- read: Read file contents (FR-002)
- search: Search file contents (FR-003)
- apply_patch: Apply unified diff patches (FR-004)
- snapshot: Create Git snapshot (FR-005)
- rollback: Restore from snapshot (FR-006)

**Rules:**
- Patch-only edits (no full-file rewrites) - FR-004
- No binary modification - FR-009
- Auto-snapshot for multi-file changes - FR-007
- File size limit: 10MB read, 50KB patch - FR-008
- No hidden/system folders (.git, node_modules) - FR-001

**Notes folder:**
- Git auto-initialized if not present (ensures FR-005, FR-006 work)
- Same rules as Projects folder

---

### 6.2 Git Module

**Purpose:** Implements FR-010 to FR-014

**Capabilities:**
- status: Query git status (FR-010)
- diff: View diffs (FR-011)
- checkout: Switch branches (FR-013)
- commit: Create commits (FR-012)

**Workflow Rule:**
- Edit → lint (FR-015) → build (FR-016) → commit (FR-012) if successful
- If build fails: retry fix once, abort if still failing

**Snapshot Strategy:**
- Local branch snapshots (FR-014)
- Periodic cleanup: 30-day retention (NFR-021)
- No force push (safety constraint)
- No destructive history rewrite

**Disk Conservation:**
- No full repo duplication
- Use branch pointers, not file copies

---

### 6.3 Web Module (Brave Search)

**Purpose:** Implements FR-024 to FR-026

**Capabilities:**
- search: Perform Brave API search (FR-024)
- optional fetch: Retrieve full page content (future enhancement)

**Modes:**
- fresh: No cache, real-time results (FR-024)
- static: 7-day cached results (FR-025)

**Cache Invalidation:**
- Query hash + freshness mode (FR-025)
- Bypass for time-sensitive terms ("today", "2026", "latest") (FR-025)

**Security:**
- Brave API key stored, loaded from env var (DR-003)
- Rate limiting: 100 searches/day (FR-026, DR-006)

---

### 6.4 Command Profiles

**Purpose:** Implements FR-015 to FR-019

**No arbitrary shell.** Profiles define:
- Executable path
- Allowed arguments schema (validated by broker)
- Scope (which directories allowed)
- Timeout (NFR per profile)
- Network permission (yes/no)
- Output size cap (100KB max to prevent memory exhaustion)

**Initial Profiles:**
- git_status (FR-010 implementation)
- git_diff (FR-011 implementation)
- git_commit (FR-012 implementation)
- lint_project (FR-015)
- build_project (FR-016)
- run_tests (FR-017)
- ripgrep_search (FR-018)

**Cross-Platform Design:**
- Profiles map to OS-specific commands internally (Phase 3)
- Broker abstracts differences
- Phase 1: Windows-only, simplified

**Chaining Protection:**
- Maximum 5 profile executions per request (FR-019)

---

### 6.5 Scheduler Module (Internal)

**Purpose:** Implements FR-027 to FR-031

**Internal scheduler backed by SQLite.**

**Job Schema:**
```
- id (primary key)
- name (user-friendly name)
- cron_expression (standard cron format)
- timezone (user's local timezone, stored as IANA identifier)
- enabled (boolean)
- action_type (search_and_report, repo_summary, heartbeat, etc.)
- action_payload (JSON configuration for action)
- last_completed_slot (timestamp of last successful execution)
- last_run_status (success/failure)
```

**Catch-Up Rule (FR-028):**
- Compute most recent valid slot (based on cron + current time)
- If slot > last_completed_slot: run once
- Else: skip
- **No duplicate execution. No backlog replay beyond most recent slot.**

**Execution:**
- Jobs execute via command profiles or internal actions (FR-028)
- No raw command strings allowed
- Timeout: 10 minutes per job (FR-030)

**Concurrency (NFR-017):**
- Scheduler jobs run in worker pool (max 3 concurrent)
- Git operations serialized per repo
- Write operations scoped per directory

**Timezone Handling (FR-029):**
- All times stored in UTC internally
- Converted to user's local timezone for display
- DST transitions: jobs scheduled during non-existent hours run at next valid time

---

## Heartbeat System

**Purpose:** Implements FR-035, supports SC-001, SC-006

**Configurable heartbeat:**
- Frequency: cron expression (default: daily 6pm)
- Action type: summary, status report, repo digest, etc.
- Modifiable via Telegram: /heartbeat configure

**Heartbeat Examples:**
- Daily system health summary (UJ-006)
- Daily repo change summary (UJ-001)
- Weekly Notes digest (UJ-004)

**Implementation:**
- Heartbeat jobs are normal scheduler jobs with special tag
- Tag: `heartbeat: true` in job metadata

---

## Persistence Model (SQLite)

**Single local database file:** `~/.sohnbot/sohnbot.db`

**Tables:**

**sessions:**
- id, telegram_chat_id, started_at, last_active
- Tracks active user sessions

**jobs:**
- Schema defined in section 6.5
- Scheduled jobs persistence (FR-027)

**execution_log:**
- id, timestamp, user_id, operation_type, file_paths, result_status, error_message
- Operation audit log (FR-022, DR-005)

**search_cache:**
- query_hash, query_text, freshness_mode, cached_results, cached_at, expires_at
- Web search cache (FR-025)

**config:**
- key, value
- System configuration (allowed_roots, API keys, settings)

**Future tables:**
- capability_metrics (operation counts, performance stats)
- failure_counts (error tracking, alerting)

**Design Constraints:**
- All state recoverable after crash (NFR-007)
- Scheduler restores jobs from DB on boot
- No in-memory-only critical state

---

## Concurrency Model

**Supports:**
- Interactive commands (user-initiated via Telegram)
- Background scheduled jobs (scheduler-initiated)

**Controls (NFR-017):**
- Max concurrent tasks: 3 scheduled jobs + 1 interactive command
- Per-scope write mutex (prevents concurrent writes to same directory)
- Git repo operation queue (serializes git ops per repo)
- Execution timeout enforcement (NFR per operation type)

**Priority:**
- Interactive commands > scheduled jobs
- If all workers busy, scheduled jobs wait

**No global lock** (allows parallelism across different scopes)

---

## Telegram UX

**Supports:**

**Natural Language:**
- "Summarize project changes every morning at 9" (UJ-001)
- "Fix the linting errors in auth.js" (UJ-002)
- "How do I fix: ModuleNotFoundError anthropic-sdk" (UJ-005)

**Explicit Commands:**
- /schedule add (create scheduled job)
- /schedule list (list all jobs)
- /git status (query git status)
- /heartbeat configure (modify heartbeat settings)
- /logs [hours] (query operation logs)
- /rollback [file] (restore previous version)
- /dryrun [command] (test operation without applying)
- /notify on|off (toggle notifications)

**Explicit commands bypass NLP:** Faster, more reliable, no interpretation ambiguity.

**Authentication:**
- Allowlisted chat IDs only (FR-033, DR-001)
- Unauthorized attempts logged and ignored

---

## Safety Posture

**Philosophy:** "Paranoid about scope, autonomous within scope"

**Enforced via structural mechanisms:**

**Scope Boundaries (FR-020, FR-021):**
- Strict scope isolation to ~/Projects and ~/Notes
- Path traversal prevention via normalization
- All operations validated against configured roots
- Violations rejected before execution

**Capability Boundaries (FR-015 to FR-019):**
- No arbitrary shell execution
- Profile-based command execution with argument validation
- Profile chaining limited to 5 executions per request
- Regex timeout enforcement (5 seconds)

**Recoverability by Design (FR-005, FR-006, FR-014):**
- Automatic snapshot creation before all file modifications
- Git-based rollback for any operation
- 30-day snapshot retention
- Snapshot restoration completes in <60 seconds

**Autonomous Execution (Core Principle):**
- Tier 0 operations: Execute immediately (read-only)
- Tier 1 operations: Snapshot → Execute → Log (single-file edits)
- Tier 2 operations: Snapshot → Execute → Enhanced log (multi-file edits)
- No routine confirmation prompts
- User intervention only for ambiguous requests (FR-036) or rollback

**Postponement for Ambiguity (FR-036):**
- If agent cannot determine intent: request clarification
- If no response within 60 seconds: postpone operation
- Retry notification after 30 minutes
- Cancel if no response to retry
- Never auto-approve unclear operations

**Observability (FR-022, FR-034, FR-035):**
- All operations logged with timestamp, actor, capability, scope, result
- Post-execution notifications sent to Telegram
- Daily heartbeat status reports
- Operation logs queryable on demand

**Idempotent Scheduling (FR-028):**
- Catch-up logic prevents duplicate job execution
- Scheduled jobs execute once per intended slot
- No backlog replay
- Jobs survive system restarts

**Output & Timeout Controls:**
- Command profile output capped at 100KB
- Timeouts enforced per operation type (NFR-004, NFR-030)
- Long-running operations auto-canceled after timeout

**Core Safety Statement:**
The system does not require routine approvals. Recoverability is the safety valve. Snapshots + Git + scope boundaries + logging provide complete operational safety and undo capability. Users intervene only when they choose to rollback, not before operations execute. This is a governed operator, not a supervised assistant.

---

## Observability

**Every execution logged (FR-022, DR-005):**
- Timestamp
- Actor (Telegram user ID)
- Capability (file read, git commit, search, etc.)
- Scope (file paths affected)
- Summary (operation description)
- Result status (success, failure, timeout)

**Optional notifications (FR-034):**
- Operation started
- Operation completed
- Errors encountered
- Preview requests

**Heartbeat system (FR-035, UJ-006):**
- Daily status summary
- Error digest
- Execution failure escalation threshold (future)

**Query interface (FR-037):**
- /logs command retrieves recent operations
- Filterable by type, status, date range

---

## MVP Definition

**Phase 1 MVP includes:**
- Telegram gateway (FR-032, FR-033)
- Broker core (scope validation, policy enforcement)
- Files module (FR-001 to FR-009)
- Git module (FR-010 to FR-014)
- Brave search (FR-024 to FR-026)
- Internal scheduler (FR-027 to FR-031)
- SQLite persistence
- Basic command profiles (FR-015 to FR-019)
- Heartbeat job (FR-035)
- Operation logging (FR-022)

**MVP Success Criteria:**
- SC-001: 30+ day autonomous operation
- SC-002: Zero scope violations
- SC-003: Zero duplicate job executions
- SC-004: 100% recoverability
- SC-005: 30% task efficiency improvement
- SC-006: User trust rating ≥8/10

**Excludes from Phase 1:**
- UI automation
- Arbitrary shell (by design)
- Network installs (future)
- External deployment (future: home server)
- Cross-platform (Phase 3)

---

## Phase 2 Roadmap

**Additional Capabilities:**
- Configurable permission tiers (allow/warn/block per operation type)
- Limited shell profile (optional, user must explicitly enable)
- Remote deployment to home server (Raspberry Pi, NAS)
- Plugin system for new modules (community contributions)
- Automatic snapshot pruning with size limits
- Structured NLP training (improve natural language understanding)
- Optional read-only "analysis mode" (explore code without edit risk)

**Phase 2 Success Criteria:**
- Plugin ecosystem: 5+ community-contributed modules
- NLP accuracy: 95% command interpretation success
- Remote deployment: Runs on 3+ remote server types

---

## Risk Register

**Risk #1: Model creates overly large patches**
- Impact: Memory exhaustion, review difficulty
- Mitigation: FR-008 (50KB patch size cap)
- Severity: Medium

**Risk #2: Infinite scheduler loops**
- Impact: Duplicate job spam, resource exhaustion
- Mitigation: FR-028 (idempotent slot logic), FR-030 (timeout enforcement)
- Severity: High → Mitigated

**Risk #3: Disk growth via snapshot branches**
- Impact: Storage exhaustion over time
- Mitigation: NFR-021 (30-day snapshot pruning)
- Severity: Medium → Mitigated

**Risk #4: Cross-platform command drift**
- Impact: Different behavior on Windows vs Linux
- Mitigation: Profile abstraction (command profiles map OS-specific internally)
- Severity: Low (Phase 3 only)

**Risk #5: Silent failures**
- Impact: User unaware of errors, trust erosion
- Mitigation: FR-034 (notifications), FR-035 (heartbeat), FR-022 (logging)
- Severity: Medium → Mitigated

**Risk #6: LLM misinterpretation causing unintended operations**
- Impact: Agent executes correct operation for wrong intent (e.g., "delete old files" interpreted too broadly)
- Mitigation:
  - **Primary:** Automatic snapshot before all modifications (FR-005) enables instant rollback
  - **Secondary:** Post-execution logging and notification (FR-034) makes user aware immediately
  - **Tertiary:** Scope boundaries (FR-020) limit blast radius to configured directories
  - **User control:** Rollback capability (FR-006) restores previous state in <60 seconds
  - **Future enhancement:** Dry-run mode (FR-023) allows testing without execution
- Philosophy: Trust structural safety (snapshots, scope, rollback) over prompt-based confirmations
- Severity: Medium → Mitigated via architecture

**Note:** This is NOT mitigated by confirmation prompts (supervision model). This IS mitigated by recoverability architecture (governed operator model). User can undo any operation faster than they could have reviewed it beforehand.

**Risk #7: Git folder corruption**
- Impact: Recoverability system fails
- Mitigation: Future enhancement - .git integrity validation before/after operations
- Severity: Low (rare edge case)

**Risk #8: Profile chaining creates dangerous workflows**
- Impact: Chained profiles bypass individual safety checks
- Mitigation: FR-019 (max 5 profiles per request)
- Severity: Medium → Mitigated

**Risk #9: Timezone/DST edge cases**
- Impact: Missed jobs, duplicate jobs, incorrect scheduling
- Mitigation: FR-029 (UTC storage, DST handling)
- Severity: Medium → Mitigated

**Risk #10: Search cost explosion**
- Impact: Unexpected Brave API charges
- Mitigation: FR-026 (soft threshold monitoring at 100 searches/day, user-configurable alert)
- Severity: Low → Monitored (user retains control)

---

## Traceability Matrix

### Success Criteria → User Journeys

| Success Criterion              | Traced User Journeys           |
| ------------------------------ | ------------------------------ |
| SC-001: Autonomous Operation   | UJ-001, UJ-002, UJ-004, UJ-006 |
| SC-002: Data Integrity         | UJ-002, UJ-007                 |
| SC-003: Scheduling Reliability | UJ-001, UJ-004, UJ-006, UJ-008 |
| SC-004: Recoverability         | UJ-002, UJ-003, UJ-007         |
| SC-005: Task Efficiency        | UJ-001, UJ-002, UJ-005, UJ-007 |
| SC-006: User Trust             | UJ-006                         |

### User Journeys → Functional Requirements

| User Journey                           | Traced Functional Requirements                         |
| -------------------------------------- | ------------------------------------------------------ |
| UJ-001: Morning Repo Summary           | FR-010, FR-011, FR-027, FR-028, FR-029, FR-032, FR-034 |
| UJ-002: Autonomous Lint & Commit       | FR-002, FR-004, FR-005, FR-012, FR-015, FR-032, FR-034 |
| UJ-003: Recovery from Unwanted Changes | FR-006, FR-013, FR-014, FR-032                         |
| UJ-004: Weekly Notes Digest            | FR-001, FR-027, FR-028, FR-032                         |
| UJ-005: Research-Assisted Code Fix     | FR-024, FR-025, FR-032                                 |
| UJ-006: Daily Heartbeat Status         | FR-022, FR-027, FR-034, FR-035                         |
| UJ-007: Safe Multi-File Refactoring    | FR-003, FR-004, FR-005, FR-007, FR-016, FR-017         |
| UJ-008: Configure Scheduled Task       | FR-027, FR-031, FR-032                                 |

### Functional Requirements → Non-Functional Requirements

| FR Category                         | Traced NFRs                        |
| ----------------------------------- | ---------------------------------- |
| File Operations (FR-001 to FR-009)  | NFR-001, NFR-009, NFR-010, NFR-012 |
| Git Operations (FR-010 to FR-014)   | NFR-002, NFR-009                   |
| Command Profiles (FR-015 to FR-019) | NFR-011, NFR-012                   |
| Scope & Safety (FR-020 to FR-023)   | NFR-010, NFR-012, NFR-014          |
| Web Search (FR-024 to FR-026)       | NFR-003, NFR-013                   |
| Scheduler (FR-027 to FR-031)        | NFR-004, NFR-008, NFR-017          |
| Communication (FR-032 to FR-037)    | NFR-005, NFR-018, NFR-019, NFR-020 |
| Observability (FR-038 to FR-043)    | NFR-024, NFR-025, NFR-026, NFR-027 |

---

## Document Change History

**v2.2-observability (2026-02-25):**
- Added Observability capability area (FR-038 to FR-043)
- Added Observability non-functional requirements (NFR-024 to NFR-027)
- System status monitoring via Telegram (/status, /health)
- Resource usage monitoring via Telegram (/status resources)
- Local HTTP observability server (localhost-only, read-only)
- HTML status page with auto-refresh
- Runtime status snapshot collection (background task)
- Health checks for scheduler, notifier, broker, SQLite
- Aligned with governed operator philosophy (read-only, no control backdoors)
- Updated traceability matrix with observability mappings

**v2.1-governed-operator (2026-02-25):**
- **ALIGNMENT WITH GOVERNED OPERATOR PHILOSOPHY**
- Removed supervised operator drift (veto windows, confirmation prompts)
- Added Operation Risk Classification (Tier 0/1/2/3)
- Strengthened Executive Summary with governed operator statement
- Revised FR-007: Multi-File Operation Preview → Multi-File Operation Logging (no pre-approval)
- Revised FR-036: Operation Veto Window → Postponement for Ambiguous Requests (clarification, not safety)
- Revised FR-024/026: Brave Search hard limits → soft threshold monitoring
- Revised DR-003: API key "encrypted at rest" → practical .env storage
- Revised DR-006: Rate limiting → rate monitoring & alerts (no hard blocking)
- Updated UJ-002, UJ-007: Removed confirmation steps, added Tier 1/2 execution flow
- Updated Safety Posture: Comprehensive autonomous execution policy
- Updated Risk #6: Structural safety (snapshots, rollback) over confirmations
- Core principle: "Recoverability is the safety valve" - no babysitting required

**v2.0-enhanced (2026-02-25):**
- Added Executive Summary section (BMAD compliance)
- Added Success Criteria section with SMART objectives
- Added Product Scope section (Phase 1/2/3 roadmap)
- Added 8 User Journeys (UJ-001 to UJ-008)
- Added Domain Requirements section (Security, Privacy, Compliance)
- Restructured Functional Requirements with IDs (FR-001 to FR-037)
- Added Non-Functional Requirements section with measurable values (NFR-001 to NFR-023)
- Added Traceability Matrix (SC→UJ→FR→NFR)
- Removed subjective language ("safe" → specific metrics)
- Added operational gaps identified via validation report
- Formalized all vague requirements with specific values
- Enhanced based on validation report findings

**v1.0 (original):**
- Initial PRD creation
- Basic product overview and architecture
- Capability module descriptions

---

**END OF DOCUMENT**
