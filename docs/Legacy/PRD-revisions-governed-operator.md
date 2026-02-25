# PRD Revisions: Governed Operator Alignment

**Date:** 2026-02-25
**Purpose:** Remove supervised operator drift, align with autonomous governed operator philosophy

---

## REVISED SECTION: Executive Summary

**Vision:**
Build a private, autonomous AI agent that operates locally as a trusted development companion—capable of editing code, managing repositories, searching the web, and running scheduled workflows—while remaining structurally safe, observable, and recoverable.

**Differentiator:**
Structural safety over prompt-based safety. Security comes from architectural constraints (scope isolation, capability boundaries, Git recoverability), not from trusting model behavior or frequent human confirmations.

**Governed Operator Philosophy:**
SohnBot is not a supervised assistant. It operates autonomously within strict structural boundaries. Human intervention is exceptional, not routine. Rollback and snapshots are the primary safety mechanisms. Babysitting is not required for normal operation.

**Target Users:**
- Primary: Technically skilled developers operating on local machines
- Comfortable with Git and system tooling
- Want AI assistance without giving up control
- Trust structural safety over prompt-based approvals

**Business Objective:**
Enable safe local AI automation for development workflows, reducing friction in repetitive tasks while maintaining complete recoverability and control through architecture, not supervision.

**Key Innovation:**
Governed, modular local automation system that feels autonomous and operates within structural guardrails—not "an AI with a shell" or "a supervised assistant" but a "controlled operator" that acts independently within defined scope.

---

## NEW SECTION: Operation Risk Classification

**Insert after: Success Criteria section**

### Operation Risk Tiers

SohnBot classifies all operations into risk tiers to determine appropriate structural safety mechanisms. Safety comes from architecture (snapshots, scope boundaries, logging), not from confirmation prompts.

**Tier 0: Read-Only Operations**
- Examples: File read (FR-002), search (FR-003), git status (FR-010), git diff (FR-011)
- Safety mechanism: Scope validation (FR-020)
- Execution policy: Always allowed, no snapshot required
- Logging: Standard operation log (FR-022)

**Tier 1: Single-File Scoped Edits**
- Examples: Single-file patch (FR-004), lint fix on one file
- Safety mechanism: Auto-snapshot before edit (FR-005) + scope validation (FR-020)
- Execution policy: Snapshot → Execute → Log
- User interaction: None required (autonomous execution)
- Rollback: User can restore via FR-006 if needed

**Tier 2: Multi-File Scoped Edits**
- Examples: Multi-file refactoring (UJ-007), batch edits across project
- Safety mechanism: Auto-snapshot before edits (FR-005) + enhanced logging + scope validation
- Execution policy: Snapshot → Execute → Enhanced log with affected files
- User interaction: None required (autonomous execution)
- Notification: Post-execution summary sent to Telegram (FR-034)
- Rollback: User can restore entire operation via FR-006

**Tier 3: Destructive Operations (Future Phase Only)**
- Examples: File deletion, mass rename, repository deletion
- Safety mechanism: Not implemented in Phase 1 MVP
- Execution policy: Requires explicit command syntax (not natural language)
- Future design: Will require user confirmation via explicit destructive command syntax

**Core Principle:**
The system does not require routine approvals. Recoverability is the safety valve. Snapshots + Git + logging provide complete undo capability. Users intervene only when they want to rollback, not before operations execute.

---

## REVISED: FR-007 (was "Multi-File Operation Preview")

**FR-007: Multi-File Operation Logging**
- Operations affecting >1 file create automatic snapshot (FR-005)
- Enhanced logging captures: affected files, operation summary, diff size, timestamp
- Post-execution notification sent to Telegram with operation summary
- No pre-execution confirmation required (governed operator model)
- User can rollback via FR-006 if operation was undesired
- Traces to: UJ-007 (multi-file refactoring), SC-004 (recoverability)
- Depends on: FR-004 (patch edits), FR-005 (snapshot creation)

---

## REVISED: FR-036 (was "Operation Veto Window")

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

---

## REVISED: UJ-002 (Autonomous Lint & Commit)

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

## REVISED: UJ-007 (Safe Multi-File Refactoring)

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

## REVISED: FR-024 to FR-026 (Brave Web Search)

**FR-024: Brave Web Search**
- User can perform web searches via Brave Search API
- Search modes: fresh (no cache), static (7-day cache)
- Returns: top 5 results with titles, URLs, snippets
- Traces to: UJ-005, SC-005
- Depends on: FR-027 (soft rate monitoring), DR-003 (API key)

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

## REVISED: DR-003 (API Key Management)

**DR-003: API Key Management**
- Brave API key stored in environment variable (.env file or system environment)
- Key loaded at startup from environment
- Not logged in operation logs
- Not committed to git (via .gitignore)
- Key rotation supported: update .env, restart process
- Measured by: Keys never appear in logs or git history (manual audit)

**Note:** Practical environment variable storage. No false implication of enterprise-grade encryption or key vaults.

---

## REVISED: DR-006 (Rate Limiting)

**DR-006: Rate Monitoring & Alerts**
- Telegram bot rate limited to 30 messages/minute (prevents spam loops)
- Brave API soft threshold: 100 searches/day (configurable, user-settable)
- Threshold exceedance triggers notification, not blocking
- File operations: soft monitoring at 50/minute per directory (logs warning if exceeded)
- Measured by: Rate alerts logged, user notified of unusual volume

**Note:** Monitoring and awareness, not hard blocking. User retains operational control.

---

## REVISED: Safety Posture Section

### Safety Posture

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

## REVISED: Risk Register (Risk #6 only)

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

---

## SUMMARY OF CHANGES

**Removed:**
- 60-second veto windows for multi-file operations
- "React with ✅ to proceed" language
- Auto-approve on timeout behavior
- Confirmation prompts as routine safety mechanism
- Hard blocking on Brave search quota

**Added:**
- Operation Risk Classification (Tier 0/1/2/3)
- Governed operator philosophy statement in Executive Summary
- Postponement logic for ambiguous requests only (not safety confirmations)
- Soft threshold monitoring for search volume
- Clear statement: "Recoverability is the safety valve"

**Clarified:**
- API key storage is practical (.env), not enterprise-grade encryption
- Multi-file operations execute autonomously with snapshot protection
- User intervention is exceptional, not routine
- Snapshots + rollback provide faster safety than pre-execution approvals

**Philosophy Reinforced:**
- Structural safety > Prompt safety
- Autonomous execution > Supervised operation
- Recoverability > Prevention (via confirmation)
- Architecture > Babysitting

---

**These revisions align the PRD with the core vision: A governed operator that is structurally safe, autonomous, recoverable, and non-babysitting.**
