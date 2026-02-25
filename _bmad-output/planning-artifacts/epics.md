---
stepsCompleted: [1, 2, 3]
inputDocuments:
  - 'E:\GIT\SohnBot\docs\PRD.md'
  - 'E:\GIT\SohnBot\_bmad-output\planning-artifacts\architecture.md'
---

# SohnBot - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for SohnBot, decomposing the requirements from the PRD and Architecture into implementable stories.

## Requirements Inventory

### Functional Requirements

**File Operations:**
- FR-001: List Files in Scope
- FR-002: Read File Contents
- FR-003: Search File Contents
- FR-004: Apply Patch-Based Edits
- FR-005: Automatic Snapshot Creation
- FR-006: Rollback to Previous State
- FR-007: *(merged into FR-022: Structured Operation Logging)*
- FR-008: File Size Enforcement
- FR-009: Binary File Rejection

**Git Operations:**
- FR-010: Git Status
- FR-011: Git Diff
- FR-012: Git Commit (Autonomous)
- FR-013: Git Checkout (Branch)
- FR-014: Git Snapshot Branch Creation

**Command Profiles:**
- FR-015: Lint Project Profile
- FR-016: Build Project Profile
- FR-017: Run Tests Profile
- FR-018: Ripgrep Search Profile
- FR-019: Profile Chaining Limit

**Scope & Safety:**
- FR-020: Scope Validation
- FR-021: Configured Scope Roots
- FR-022: Structured Operation Logging (ALL capabilities: timestamp, user ID, operation type, file paths, result status, errors; includes multi-file operations; persisted to SQLite audit trail)
- FR-023: Dry-Run Mode

**Web Search:**
- FR-024: Brave Web Search
- FR-025: Search Result Caching
- FR-026: Search Volume Monitoring

**Scheduler:**
- FR-027: Schedule Job Creation
- FR-028: Idempotent Job Execution
- FR-029: Timezone-Aware Scheduling
- FR-030: Job Timeout Enforcement
- FR-031: Job Management Commands

**Communication & Observability:**
- FR-032: Telegram Command Interface
- FR-033: Telegram Authentication
- FR-034: Operation Status Notifications
- FR-035: Heartbeat System
- FR-036: Postponement for Ambiguous Requests
- FR-037: Query Operation Logs
- FR-038: System Status via Telegram
- FR-039: Resource Usage Monitoring via Telegram
- FR-040: Health Checks via Telegram
- FR-041: Local HTTP Observability Server
- FR-042: HTML Status Page
- FR-043: Runtime Status Snapshot Collection

### NonFunctional Requirements

**Performance:**
- NFR-001: File Read Performance (<200ms for 1MB, <500ms for 10MB)
- NFR-002: Git Operations Performance (<500ms status, <1s diff)
- NFR-003: Search Performance (<5s ripgrep, <3s Brave API)
- NFR-004: Scheduler Evaluation Frequency (60s tick, 120s execution window)
- NFR-005: Notification Latency (<10s delivery)

**Reliability:**
- NFR-006: System Uptime (95% over 30 days)
- NFR-007: Crash Recovery Time (<30s)
- NFR-008: Scheduler Reliability (99% reliability for correct scheduling + execution orchestration; excludes failures from user code, external APIs, or invalid input)
- NFR-009: Data Integrity (0 file corruptions)

**Security:**
- NFR-010: Path Traversal Prevention (100% blocked)
- NFR-011: Command Injection Prevention (100% blocked)
- NFR-012: Scope Violation Prevention (100% rejected)
- NFR-013: API Key Security (0 exposed secrets)
- NFR-014: Audit Log Completeness (100% operations logged)

**Scalability:**
- NFR-015: Multi-Repo Support (50 repos, <5min scanning)
- NFR-016: File Count Scalability (100K files per repo)
- NFR-017: Concurrent Operations (3 concurrent scheduled jobs)

**Usability:**
- NFR-018: Natural Language Understanding (90% interpretation success)
- NFR-019: Response Time (User Interaction) (<2s acknowledgment)
- NFR-020: Error Message Clarity (80% user comprehension)

**Maintainability:**
- NFR-021: Automated Cleanup (snapshots 30d, logs 90d, cache 7d)
- NFR-022: Configuration Management (80% hot-reload without restart)
- NFR-023: Dependency Vulnerability Management (0 high-severity in prod)

**Observability:**
- NFR-024: Observability Overhead (<2% CPU, <100ms collection)
- NFR-025: HTTP Server Security (localhost-only, GET-only routes)
- NFR-026: Health Check Reliability (<500ms, <1% false positives)
- NFR-027: Observability Isolation (independent failure domain)

**Cost & Runtime Governance:**
- NFR-028: Budget Enforcement (max_budget_usd, max_turns, max_thinking_tokens prevent runaway token spending; requests exceeding budget terminate gracefully; cost governance does not bypass broker enforcement)

### Additional Requirements

**Architecture & Infrastructure:**

1. **Project Initialization:**
   - Custom Architecture-Aligned Structure (no pre-existing starter template)
   - Poetry-based dependency management (Python 3.13+)
   - Complete directory structure with 7 subsystems:
     * Gateway (Telegram integration)
     * Runtime (Claude Agent SDK)
     * Broker (policy enforcement - architectural heart)
     * Capabilities (files, git, profiles, search, scheduler)
     * Persistence (SQLite with WAL mode)
     * Supervision (pm2 process management)
     * Config (two-tier: static/dynamic)

2. **Data Layer (Decision 1):**
   - SQLite with STRICT tables + CHECK constraints
   - Manual SQL (no ORM)
   - Migration runner with SHA-256 checksums
   - WAL mode for concurrency
   - Migration naming: `000N_<description>.sql`

3. **Broker Layer (Decision 2):**
   - Centralized routing for ALL capability execution
   - Operation risk classification (Tier 0/1/2/3)
   - Scope validation + path traversal prevention
   - PreToolUse hooks for Claude Agent SDK
   - Execution logging (start/end) to SQLite audit trail

4. **Scheduler (Decision 3):**
   - Boundary-aligned design (60s tick loop)
   - Idempotent catch-up logic (last_completed_slot tracking)
   - Timezone-aware with zoneinfo (DST handling)
   - asyncio TaskGroup for concurrency (max 3 jobs)

5. **Logging & Observability (Decision 4):**
   - structlog with JSON output
   - Dual logging: file + SQLite audit table
   - Persistent notification outbox (guaranteed delivery)
   - Read-only observability (no control actions)

6. **Configuration (Decision 5):**
   - Two-tier: static (restart required) vs dynamic (hot-reload)
   - TOML primary format + DB-backed for dynamic keys
   - Environment variables for secrets
   - Config registry with validators

7. **Observability System:**
   - HTTP server (aiohttp) bound to localhost only (configurable port, default: 8080; localhost binding enforced via static config)
   - Health checks: SQLite, scheduler lag, job timeouts, notifier, outbox
   - Runtime status snapshots (30s interval, non-blocking)
   - HTML status page with auto-refresh

8. **Model Routing:**
   - Telegram default: claude-haiku (fast, cheap)
   - Dev default: claude-sonnet (balanced)
   - Plan default: claude-opus (deep reasoning)
   - SDK-only controls (no Messages API `effort` parameter)
   - Runtime controls: max_thinking_tokens, max_turns, max_budget_usd

9. **Process Supervision:**
   - pm2 for Windows (Phase 1)
   - Health monitoring and auto-restart
   - Crash recovery within 30 seconds
   - State restoration from SQLite

10. **Implementation Phases:**
    - Phase 1 (Core): Data layer, broker, files, git, configuration
    - Phase 2 (Orchestration): Scheduler, command profiles, web search, notifications
    - Phase 3 (Visibility): Observability HTTP server, health checks, Telegram commands
    - Phase 4 (Polish): Model routing refinement, testing automation, deployment scripts

11. **Deployment:**
    - pm2 ecosystem file configuration
    - Environment variable management (.env file)
    - Initial database migration and seeding
    - Documentation (deployment.md, API docs)

12. **Testing Strategy:**
    - Unit tests: `tests/unit/<module>_test.py` mirroring `src/` structure
    - Integration tests: `tests/integration/test_<workflow>.py`
    - Mocking strategy for Claude SDK, Telegram API, file system
    - Automated test execution

### System Invariants

**Architectural Non-Negotiables:**

These invariants must hold across all implementations and cannot be bypassed:

1. **All state-changing operations pass through the Broker** - No capability can execute modifications without broker routing, validation, and logging
2. **Model selection does not affect safety boundaries** - Switching between Haiku/Sonnet/Opus does not bypass scope validation, tier classification, or snapshot creation
3. **Observability is strictly read-only** - Observability module cannot modify broker state, scheduler jobs, or configuration; no control actions exposed
4. **Secrets are never persisted** - API keys stored in environment variables only; never written to SQLite, logs, or git history
5. **Scheduler never replays historical backlog** - Catch-up logic runs most recent missed slot once; no duplicate job execution
6. **Built-in SDK tools are not exposed unless explicitly allowed** - PreToolUse hooks enforce allowlist; unapproved tools rejected at broker layer

These invariants enforce the **governed operator philosophy** and ensure structural safety cannot be compromised by configuration, natural language requests, or model selection.

### FR Coverage Map

**Epic 1: Autonomous File Management**
- FR-001: List Files in Scope
- FR-002: Read File Contents
- FR-003: Search File Contents
- FR-004: Apply Patch-Based Edits
- FR-005: Automatic Snapshot Creation
- FR-006: Rollback to Previous State
- FR-008: File Size Enforcement
- FR-009: Binary File Rejection
- FR-020: Scope Validation
- FR-021: Configured Scope Roots
- FR-022: Structured Operation Logging (unified from FR-007 + FR-022)
- FR-032: Telegram Command Interface
- FR-033: Telegram Authentication
- FR-034: Operation Status Notifications
- FR-036: Postponement for Ambiguous Requests

**Epic 2: Git Operations & Version Control**
- FR-010: Git Status
- FR-011: Git Diff
- FR-012: Git Commit (Autonomous)
- FR-013: Git Checkout (Branch)
- FR-014: Git Snapshot Branch Creation

**Epic 3: System Observability & Monitoring**
- FR-038: System Status via Telegram
- FR-039: Resource Usage Monitoring via Telegram
- FR-040: Health Checks via Telegram
- FR-041: Local HTTP Observability Server
- FR-042: HTML Status Page
- FR-043: Runtime Status Snapshot Collection

**Epic 4: Scheduled Automation**
- FR-027: Schedule Job Creation
- FR-028: Idempotent Job Execution
- FR-029: Timezone-Aware Scheduling
- FR-030: Job Timeout Enforcement
- FR-031: Job Management Commands
- FR-035: Heartbeat System

**Epic 5: Development Workflow Automation**
- FR-015: Lint Project Profile
- FR-016: Build Project Profile
- FR-017: Run Tests Profile
- FR-018: Ripgrep Search Profile
- FR-019: Profile Chaining Limit
- FR-023: Dry-Run Mode

**Epic 6: Research & Web Search**
- FR-024: Brave Web Search
- FR-025: Search Result Caching
- FR-026: Search Volume Monitoring
- FR-037: Query Operation Logs

**FR Coverage Verification:** ✅ All 43 FRs mapped to epics (FR-007 merged into FR-022)

## Epic List

### Epic 1: Autonomous File Management

**User Outcome:** You can safely read, edit, and manage files in your repositories through Telegram, with automatic snapshots and rollback capability.

**What's Delivered:**
- Complete end-to-end system (Telegram gateway → Runtime → Broker → File capabilities)
- Scope-validated file operations (read, list, search, patch-based edits)
- Automatic git snapshots before modifications
- Rollback to previous state
- Structured operation logging (all capabilities)
- Operation status notifications
- Ambiguous request postponement (clarification workflow when intent unclear)

**FRs Covered:** FR-001, FR-002, FR-003, FR-004, FR-005, FR-006, FR-008, FR-009, FR-020, FR-021, FR-022, FR-032, FR-033, FR-034, FR-036

**Infrastructure Built:** Project structure, SQLite with WAL, broker layer (policy enforcement + tier classification), configuration system, Telegram integration, Claude Agent SDK integration, pm2 supervision

**Why Epic 1:** Delivers immediate, complete value - you can start using SohnBot to manage files autonomously with full safety guarantees (snapshots + rollback) and intelligent ambiguity handling.

---

### Epic 2: Git Operations & Version Control

**User Outcome:** You can query git status, view diffs, and have SohnBot autonomously create commits after successful operations.

**What's Delivered:**
- Git status and diff queries
- Autonomous git commits (after lint/build validation)
- Git checkout for rollback operations
- Enhanced snapshot branch management

**FRs Covered:** FR-010, FR-011, FR-012, FR-013, FR-014

**Builds Upon:** Epic 1 (uses broker, snapshots, Telegram)

**Why Epic 2:** Extends Epic 1's snapshot capability with full git integration and autonomous commit workflow.

---

### Epic 3: System Observability & Monitoring

**User Outcome:** You can monitor SohnBot's health, resource usage, and operation history through Telegram commands and a local HTTP dashboard.

**What's Delivered:**
- System status via Telegram (/status, /status resources)
- Health checks via Telegram (/health)
- Local HTTP observability server (localhost-only, configurable port)
- HTML status page with auto-refresh
- Runtime status snapshot collection (background task)

**FRs Covered:** FR-038, FR-039, FR-040, FR-041, FR-042, FR-043

**Builds Upon:** Epic 1 + Epic 2 (observes broker, file operations, git operations)

**Why Epic 3:** Provides visibility into autonomous system health BEFORE adding advanced automation. Enables safe debugging and evolution. Read-only capability with no blocking dependencies.

---

### Epic 4: Scheduled Automation

**User Outcome:** You can schedule recurring tasks (morning repo summaries, weekly notes digests, daily heartbeats) that run autonomously.

**What's Delivered:**
- Job creation via natural language or explicit commands
- Idempotent job execution with catch-up logic
- Timezone-aware scheduling with DST handling
- Job timeout enforcement
- Job management commands (/schedule list, disable, delete, edit)
- Daily heartbeat system

**FRs Covered:** FR-027, FR-028, FR-029, FR-030, FR-031, FR-035

**Builds Upon:** Epic 1 + Epic 2 + Epic 3 (scheduled jobs trigger file/git operations; observability monitors scheduler health)

**Why Epic 4:** Enables truly autonomous operation - SohnBot runs tasks on your behalf without manual triggers. Observability from Epic 3 ensures scheduler reliability.

---

### Epic 5: Development Workflow Automation

**User Outcome:** You can execute lint, build, test, and search operations through command profiles with execution limits and timeout enforcement.

**What's Delivered:**
- Lint project profile (eslint, pylint, etc.)
- Build project profile (npm run build, make, etc.)
- Run tests profile
- Ripgrep search profile
- Profile chaining limit (max 5 per request)
- Dry-run mode for testing operations

**FRs Covered:** FR-015, FR-016, FR-017, FR-018, FR-019, FR-023

**Builds Upon:** Epic 1 + Epic 2 + Epic 3 (profiles integrated with file edits, autonomous commits; observability monitors profile execution)

**Why Epic 5:** Completes the autonomous lint-edit-commit workflow from your user journeys.

---

### Epic 6: Research & Web Search

**User Outcome:** You can perform web searches via Brave API with intelligent caching and cost monitoring.

**What's Delivered:**
- Brave web search integration (fresh/static modes)
- 7-day search result caching
- Search volume monitoring with soft threshold alerts
- Query operation logs

**FRs Covered:** FR-024, FR-025, FR-026, FR-037

**Builds Upon:** Epic 1 + Epic 3 (uses broker, notifications, logging; observability tracks search volume)

**Why Epic 6:** Enables research-assisted workflows (find solutions, then apply fixes).

## Epic 1: Autonomous File Management

**Epic Goal:** You can safely read, edit, and manage files in your repositories through Telegram, with automatic snapshots and rollback capability.

### Story 1.1: Project Setup & Configuration System

As a developer,
I want a complete project structure with configuration management,
So that I can deploy SohnBot with proper environment setup and dynamic configuration.

**Acceptance Criteria:**

**Given** the Poetry project is initialized with Python 3.13+
**When** I run the setup script
**Then** all directory structure is created (broker, capabilities, gateway, runtime, config, persistence, supervision)
**And** default configuration is loaded from config/default.toml
**And** environment variables are loaded from .env file
**And** configuration registry validates all config keys
**And** hot-reload is supported for dynamic config keys

**Implementation Notes:**
- Creates: pyproject.toml, .env.example, config/default.toml, config/registry.py
- Creates: src/sohnbot/config/manager.py (two-tier config system)
- Creates: all directory structure per architecture
- No database tables yet (created incrementally)

---

### Story 1.2: SQLite Persistence Layer & Broker Foundation

As a developer,
I want SQLite database with WAL mode and the broker layer foundation,
So that all operations are logged and policy enforcement is centralized.

**Acceptance Criteria:**

**Given** the project structure exists
**When** I run the migration script
**Then** SQLite database is initialized with WAL mode enabled
**And** execution_log table is created (STRICT, CHECK constraints)
**And** config table is created for dynamic config storage
**And** migration runner verifies SHA-256 checksums
**And** broker router can classify operations into Tier 0/1/2/3
**And** broker logs operation start/end to execution_log

**Implementation Notes:**
- Creates: migrations/0001_initial_schema.sql (execution_log, config tables only)
- Creates: scripts/migrate.py (checksum verification)
- Creates: src/sohnbot/broker/router.py (operation classification, logging)
- Creates: src/sohnbot/broker/operation_classifier.py (Tier 0/1/2/3 logic)
- Creates: src/sohnbot/persistence/database.py (connection management, WAL mode)

---

### Story 1.3: Telegram Gateway & Claude Agent SDK Integration

As a developer,
I want to receive commands via Telegram and process them through Claude Agent SDK,
So that users can interact with SohnBot through natural language.

**Acceptance Criteria:**

**Given** Telegram bot token is configured in environment
**When** user sends a message to the bot
**Then** message is authenticated against allowlisted chat IDs (FR-033)
**And** message is routed to Claude Agent SDK runtime
**And** agent response is formatted and sent back via Telegram
**And** unauthorized chat IDs are logged and ignored
**And** explicit commands (/) bypass NL interpretation

**Implementation Notes:**
- Creates: src/sohnbot/gateway/telegram_client.py (Bot API integration)
- Creates: src/sohnbot/gateway/message_router.py (route to runtime)
- Creates: src/sohnbot/gateway/formatters.py (format responses for Telegram)
- Creates: src/sohnbot/runtime/agent_session.py (Claude SDK query() wrapper)
- Creates: src/sohnbot/runtime/context_loader.py (load CLAUDE.md, skills)
- Updates: config table with telegram.allowed_chat_ids

---

### Story 1.4: Scope Validation & Path Traversal Prevention

As a user,
I want all file operations restricted to configured scope roots,
So that SohnBot cannot access files outside ~/Projects or ~/Notes.

**Acceptance Criteria:**

**Given** scope roots are configured (~/Projects, ~/Notes)
**When** any file operation is requested with a path
**Then** path is normalized to absolute path (resolve symlinks, relative paths)
**And** path traversal attempts (../, ~, symlinks outside scope) are rejected
**And** rejection returns error: "Path outside allowed scope"
**And** broker validates scope before executing any file capability
**And** 100% of path traversal attempts are blocked (NFR-010)

**Implementation Notes:**
- Creates: src/sohnbot/broker/scope_validator.py (path normalization, traversal prevention)
- Updates: config/default.toml with scope.allowed_roots = ["~/Projects", "~/Notes"]
- Broker calls scope_validator before routing to file capabilities

---

### Story 1.5: File Read Operations (List, Read, Search)

As a user,
I want to list, read, and search files within my configured scope,
So that I can query my repositories and notes.

**Acceptance Criteria:**

**Given** scope validation is enforced
**When** I request to list files in ~/Projects
**Then** all files are returned (excluding .git, .venv, node_modules)
**And** file paths, sizes, modification times are included
**And** file read operations complete in <200ms for 1MB files (NFR-001)
**And** file size limit of 10MB is enforced (FR-008)
**And** binary files return error: "Binary files not supported" (FR-009)
**And** ripgrep search completes in <5s for 100K file repos (NFR-003)
**And** regex patterns timeout after 5s (prevents catastrophic backtracking)

**Implementation Notes:**
- Creates: src/sohnbot/capabilities/files.py (list_files, read_file, search_files)
- MCP tool names: mcp__sohnbot__files__list, mcp__sohnbot__files__read, mcp__sohnbot__files__search
- Broker routes to files capability after scope validation
- All operations logged to execution_log as Tier 0 (read-only)

---

### Story 1.6: Patch-Based File Edit with Snapshot Creation

As a user,
I want to edit files via unified diff patches with automatic snapshots,
So that I can safely modify files with rollback capability.

**Acceptance Criteria:**

**Given** a file exists within scope
**When** I request a patch-based edit
**Then** broker creates git snapshot branch before modification (FR-005)
**And** snapshot branch is named: snapshot/edit-[YYYY-MM-DD-HHMM]
**And** patch is validated (valid unified diff format)
**And** patch size limit of 50KB is enforced (FR-008)
**And** patch is applied to the file
**And** operation is logged to execution_log as Tier 1 (single-file)
**And** notification is sent to Telegram with operation summary (FR-034)

**Implementation Notes:**
- Creates: src/sohnbot/capabilities/files.py (patch_edit function)
- Creates: src/sohnbot/capabilities/git.py (create_snapshot function)
- MCP tool: mcp__sohnbot__files__patch
- Broker classifies as Tier 1, creates snapshot before execution
- Updates: execution_log with snapshot_branch_name column

---

### Story 1.7: Rollback to Previous Snapshot

As a user,
I want to restore files to any previous snapshot,
So that I can recover from unwanted changes.

**Acceptance Criteria:**

**Given** snapshot branches exist (snapshot/*)
**When** I request to rollback to a specific snapshot
**Then** available snapshots are listed with timestamps
**And** selected snapshot is checked out (preserves git history, creates new commit)
**And** rollback operation completes in <30s (NFR-007)
**And** operation is logged to execution_log as Tier 1
**And** notification confirms successful rollback with branch name

**Implementation Notes:**
- Creates: src/sohnbot/capabilities/git.py (list_snapshots, rollback_to_snapshot)
- MCP tools: mcp__sohnbot__git__list_snapshots, mcp__sohnbot__git__rollback
- Uses git checkout + git commit (no history rewriting)
- Broker classifies as Tier 1

---

### Story 1.8: Structured Operation Logging & Notifications

As a user,
I want all operations logged with complete audit trail and status notifications,
So that I can track what SohnBot has done and receive timely updates.

**Acceptance Criteria:**

**Given** any operation is executed (file, git, etc.)
**When** the operation starts
**Then** broker logs: timestamp, chat ID, operation type, file paths, tier to execution_log
**And** when operation completes, broker logs: result status, error details (if any), duration
**And** notification is sent to Telegram within 10s (NFR-005)
**And** notification includes: operation type, files affected, result, snapshot branch (if created)
**And** user can disable notifications: /notify off (logs still captured)
**And** 100% of operations have audit log entry (NFR-014)

**Implementation Notes:**
- Updates: src/sohnbot/broker/router.py (log start/end around capability execution)
- Creates: src/sohnbot/notifier/outbox.py (persistent notification outbox)
- Creates: migrations/0002_notifications.sql (notification_outbox table)
- Background worker polls outbox and sends to Telegram
- Validates: execution_log has complete coverage

---

### Story 1.9: Ambiguous Request Postponement

As a user,
I want SohnBot to request clarification when my request is ambiguous,
So that unclear operations don't fail or execute incorrectly.

**Acceptance Criteria:**

**Given** a natural language request is ambiguous (agent cannot determine intent)
**When** the agent detects ambiguity
**Then** clarification is requested via Telegram: "Did you mean [option A] or [option B]?"
**And** if no response within 60 seconds, operation is postponed
**And** retry notification is sent after 30 minutes
**And** if still no response, operation is cancelled safely
**And** ambiguous operations are never auto-approved

**Implementation Notes:**
- Updates: src/sohnbot/runtime/agent_session.py (ambiguity detection logic)
- Creates: src/sohnbot/runtime/postponement_manager.py (tracks postponed operations)
- Updates: execution_log with postponed status
- Scheduler handles retry after 30 minutes (uses existing scheduler infrastructure)

---

## Epic 2: Git Operations & Version Control

**Epic Goal:** You can query git status, view diffs, and have SohnBot autonomously create commits after successful operations.

### Story 2.1: Git Status & Diff Queries

As a user,
I want to query git status and view diffs for my repositories,
So that I can understand the current state of my code.

**Acceptance Criteria:**

**Given** a git repository exists within scope
**When** I request git status
**Then** modified files, staged files, branch name, commit status are returned
**And** git status completes in <500ms for repos with 100K files (NFR-002)
**And** I can view diffs for uncommitted changes (staged, working tree, commit-to-commit)
**And** diffs are returned in unified diff format
**And** git diff completes in <1s for diffs up to 10K lines (NFR-002)

**Implementation Notes:**
- Updates: src/sohnbot/capabilities/git.py (git_status, git_diff functions)
- MCP tools: mcp__sohnbot__git__status, mcp__sohnbot__git__diff
- Works across multiple repos (user may have many in ~/Projects)
- Broker classifies as Tier 0 (read-only)

---

### Story 2.2: Git Checkout for Rollback Operations

As a user,
I want to checkout snapshot branches for rollback,
So that I can restore previous states during recovery operations.

**Acceptance Criteria:**

**Given** snapshot branches exist locally
**When** I request to checkout a snapshot branch
**Then** branch is checked out (restricted to local branches only, no remote)
**And** operation is logged as Tier 1
**And** checkout is used for rollback operations (FR-013)

**Implementation Notes:**
- Updates: src/sohnbot/capabilities/git.py (git_checkout function)
- MCP tool: mcp__sohnbot__git__checkout
- Validates: only local branches, no remote checkout
- Used by rollback operation from Epic 1

---

### Story 2.3: Autonomous Git Commits

As a user,
I want SohnBot to autonomously create commits after successful operations,
So that changes are tracked in version control automatically.

**Acceptance Criteria:**

**Given** file edits have been successfully applied and validated (lint/build passed)
**When** the edit operation completes
**Then** a git commit is created autonomously
**And** commit message follows format: "[Type]: [Summary]" (e.g., "Fix: Resolve linting errors")
**And** commit includes all modified files from the operation
**And** operation is logged as Tier 1
**And** notification confirms commit with SHA and message

**Implementation Notes:**
- Updates: src/sohnbot/capabilities/git.py (git_commit function)
- MCP tool: mcp__sohnbot__git__commit
- Triggered after successful lint/build validation (integration with Epic 5)
- Broker classifies as Tier 1

---

### Story 2.4: Enhanced Snapshot Branch Management

As a user,
I want automatic snapshot pruning and enhanced snapshot tracking,
So that snapshot branches don't accumulate indefinitely.

**Acceptance Criteria:**

**Given** snapshot branches accumulate over time
**When** snapshots are older than 30 days (configurable)
**Then** snapshots are auto-pruned weekly
**And** pruning is logged to execution_log
**And** snapshot naming follows: snapshot/[operation]-[YYYY-MM-DD-HHMM]
**And** snapshot count is tracked for observability (NFR-021)

**Implementation Notes:**
- Updates: src/sohnbot/capabilities/git.py (prune_snapshots function)
- Scheduled job runs weekly (uses scheduler from Epic 4)
- Configuration: snapshot.retention_days (default: 30)
- Validates: NFR-021 automated cleanup

---

## Epic 3: System Observability & Monitoring

**Epic Goal:** You can monitor SohnBot's health, resource usage, and operation history through Telegram commands and a local HTTP dashboard.

### Story 3.1: Runtime Status Snapshot Collection

As a developer,
I want background status snapshot collection every 30 seconds,
So that current system state is always available for queries.

**Acceptance Criteria:**

**Given** SohnBot is running
**When** the snapshot collector runs every 30 seconds (configurable)
**Then** snapshot includes: process info, broker activity, scheduler state, notifier state, resources, health checks
**And** snapshot collection is non-blocking (independent failure domain)
**And** snapshot collection completes in <100ms (NFR-024)
**And** snapshot collection consumes <2% CPU (NFR-024)
**And** in-memory cache is updated each cycle
**And** optional persistence to SQLite (disabled by default)

**Implementation Notes:**
- Creates: src/sohnbot/observability/snapshot_collector.py (background task)
- Creates: src/sohnbot/capabilities/observe.py (StatusSnapshot dataclass)
- Background task runs in asyncio TaskGroup
- Reads from broker/scheduler/notifier state (read-only)
- Configuration: observability.collection_interval_seconds (default: 30)

---

### Story 3.2: Health Checks Implementation

As a user,
I want automated health checks for critical subsystems,
So that I can detect issues before they cause failures.

**Acceptance Criteria:**

**Given** the system is running
**When** health checks execute (part of snapshot collection)
**Then** SQLite writable check verifies database write capability
**And** scheduler lag check detects if scheduler is behind (threshold: 5 minutes)
**And** job timeout check identifies jobs exceeding timeout
**And** notifier alive check verifies notification worker is active
**And** outbox stuck check identifies pending notifications older than 1 hour
**And** disk usage check (optional) monitors DB + log size against configured cap
**And** health checks complete within 500ms (NFR-026)
**And** false positive rate <1% over 30 days (NFR-026)

**Implementation Notes:**
- Creates: src/sohnbot/observability/health_checks.py (all health check functions)
- Health checks return: HealthCheckResult (name, status: pass/fail/warn, message, details)
- Configuration: observability.scheduler_lag_threshold, notifier_lag_threshold, outbox_stuck_threshold
- Validates: NFR-026 reliability

---

### Story 3.3: System Status via Telegram

As a user,
I want to query system status via Telegram commands,
So that I can check SohnBot's health and activity.

**Acceptance Criteria:**

**Given** observability snapshots are being collected
**When** I send /status command via Telegram
**Then** response includes: uptime, version, supervisor status, last scheduler tick, last broker activity, in-flight operations, notification outbox count, last 10 operation results
**And** when I send /status resources
**Then** response includes: CPU%, RAM (MB), DB size (MB), log size (MB), snapshot count, event loop lag (ms)
**And** all queries are read-only (no system modifications)
**And** response time <2s (NFR-019)

**Implementation Notes:**
- Updates: src/sohnbot/capabilities/observe.py (get_status_snapshot, get_resource_snapshot)
- Updates: src/sohnbot/gateway/commands.py (handle_status command)
- MCP tools: mcp__sohnbot__observe__status, mcp__sohnbot__observe__resources
- Reads from in-memory snapshot cache (fast)

---

### Story 3.4: Health Checks via Telegram

As a user,
I want to query system health via Telegram,
So that I can diagnose issues remotely.

**Acceptance Criteria:**

**Given** health checks are running
**When** I send /health command via Telegram
**Then** overall health status is returned (healthy/degraded/unhealthy)
**And** specific health check results are listed (pass/fail/warn)
**And** failing checks include error details
**And** response is formatted clearly for mobile reading

**Implementation Notes:**
- Updates: src/sohnbot/capabilities/observe.py (run_health_checks)
- Updates: src/sohnbot/gateway/commands.py (handle_health command)
- MCP tool: mcp__sohnbot__observe__health
- Reads from latest snapshot health checks

---

### Story 3.5: Local HTTP Observability Server

As a developer,
I want a local HTTP server with read-only observability endpoints,
So that I can monitor SohnBot from a web browser.

**Acceptance Criteria:**

**Given** HTTP server is enabled in configuration
**When** the server starts
**Then** it binds to localhost only (127.0.0.1, configurable port, default: 8080)
**And** GET /status returns status snapshot as JSON
**And** GET /health returns health check results as JSON
**And** GET /metrics returns minimal metrics as JSON (not Prometheus format)
**And** all routes are GET-only (no POST, PUT, DELETE, PATCH)
**And** no control actions are exposed
**And** localhost-only binding is enforced (NFR-025)

**Implementation Notes:**
- Creates: src/sohnbot/observability/http_server.py (aiohttp server)
- Configuration: observability.http_enabled, observability.http_port (static config)
- Validator enforces: lambda v: v in ("127.0.0.1", "::1")
- Runs in background asyncio task
- Validates: NFR-025 security

---

### Story 3.6: HTML Status Page

As a developer,
I want an HTML status page with auto-refresh,
So that I can monitor SohnBot in a browser dashboard.

**Acceptance Criteria:**

**Given** HTTP server is running
**When** I navigate to http://localhost:8080/ or /ui
**Then** HTML page displays: process info, active operations, scheduler next runs, resources, recent errors
**And** page auto-refreshes every 30 seconds
**And** health status is shown with visual indicator (✅ healthy, ⚠️ degraded, ❌ unhealthy)
**And** page uses monospace font and dark theme
**And** page is read-only (no forms or control actions)

**Implementation Notes:**
- Updates: src/sohnbot/observability/http_server.py (handle_ui route)
- Creates: src/sohnbot/observability/templates/status.html (simple HTML template)
- Uses inline CSS (no external dependencies)
- Auto-refresh via meta tag: <meta http-equiv="refresh" content="30">

---

## Epic 4: Scheduled Automation

**Epic Goal:** You can schedule recurring tasks (morning repo summaries, weekly notes digests, daily heartbeats) that run autonomously.

### Story 4.1: Job Creation & Persistence

As a user,
I want to create scheduled jobs via natural language or explicit commands,
So that recurring tasks run automatically.

**Acceptance Criteria:**

**Given** I want to schedule a recurring task
**When** I request job creation (e.g., "Run morning summary daily at 9am")
**Then** job is created with: name, cron expression, timezone, action type, enabled status
**And** job is persisted to SQLite (survives system restarts)
**And** job schema includes: id, name, cron_expr, timezone, action, enabled, created_at, last_completed_slot
**And** jobs are stored in local timezone (converted to UTC internally)
**And** confirmation is sent via Telegram with job details

**Implementation Notes:**
- Creates: migrations/0003_scheduler.sql (jobs table with STRICT, CHECK constraints)
- Creates: src/sohnbot/scheduler/job_manager.py (create_job, list_jobs, delete_job)
- MCP tools: mcp__sohnbot__sched__create, mcp__sohnbot__sched__list
- Validates: cron expression format, timezone with zoneinfo

---

### Story 4.2: Idempotent Job Execution with Catch-Up

As a user,
I want scheduled jobs to execute reliably with idempotent catch-up,
So that missed jobs run once without duplicate execution.

**Acceptance Criteria:**

**Given** scheduled jobs exist in the jobs table
**When** the scheduler evaluates the job queue (60s tick loop)
**Then** jobs due for execution are identified
**And** catch-up logic runs most recent missed slot once (no historical backlog replay)
**And** last_completed_slot field prevents duplicate execution
**And** max 3 concurrent jobs execute (asyncio TaskGroup)
**And** job execution starts within 120 seconds of scheduled time (NFR-004, 95th percentile)
**And** scheduler reliability is 99% (NFR-008, excludes user code failures)

**Implementation Notes:**
- Creates: src/sohnbot/scheduler/executor.py (boundary-aligned tick loop, idempotent execution)
- Scheduler runs as background asyncio task
- Uses last_completed_slot to track execution (idempotency key)
- Concurrent limit: max 3 jobs via TaskGroup
- Validates: NFR-004, NFR-008

---

### Story 4.3: Timezone-Aware Scheduling with DST Handling

As a user,
I want jobs scheduled in my local timezone with correct DST handling,
So that jobs run at the expected local time.

**Acceptance Criteria:**

**Given** jobs are created with local timezone
**When** the job is stored
**Then** job time is converted to UTC internally (storage)
**And** user-facing times are displayed in local timezone (queries)
**And** DST transitions are handled correctly (non-existent hours run at next valid time)
**And** jobs during spring-forward (2am → 3am) run at 3am
**And** jobs during fall-back (2am → 1am) run once at first occurrence

**Implementation Notes:**
- Updates: src/sohnbot/scheduler/executor.py (zoneinfo for DST handling)
- Uses Python zoneinfo for timezone conversion
- Stores: UTC epoch timestamps + timezone name
- Displays: local timezone for user queries
- Validates: FR-029

---

### Story 4.4: Job Timeout Enforcement

As a user,
I want scheduled jobs to timeout after 10 minutes,
So that hung operations don't block the scheduler.

**Acceptance Criteria:**

**Given** a scheduled job is executing
**When** job execution exceeds 10 minutes (600 seconds)
**Then** job is cancelled
**And** timeout is logged to execution_log with error details
**And** user is notified via Telegram: "Job [name] timed out after 10 minutes"
**And** scheduler continues processing other jobs (timeout doesn't block scheduler)

**Implementation Notes:**
- Updates: src/sohnbot/scheduler/executor.py (asyncio timeout wrapper)
- Uses asyncio.wait_for(job_task, timeout=600)
- Configuration: scheduler.job_timeout_seconds (default: 600)
- Validates: FR-030

---

### Story 4.5: Job Management Commands

As a user,
I want to list, disable, delete, and edit scheduled jobs,
So that I can manage my automation.

**Acceptance Criteria:**

**Given** scheduled jobs exist
**When** I send /schedule list
**Then** all jobs are listed with: name, cron, timezone, enabled status, last run
**And** when I send /schedule disable [name]
**Then** job is disabled (enabled=false) but not deleted
**And** when I send /schedule delete [name]
**Then** job is permanently deleted from database
**And** when I send /schedule edit [name]
**Then** I can modify job parameters (cron, timezone, action)

**Implementation Notes:**
- Updates: src/sohnbot/scheduler/job_manager.py (disable_job, delete_job, edit_job)
- Updates: src/sohnbot/gateway/commands.py (handle_schedule command)
- MCP tools: mcp__sohnbot__sched__disable, mcp__sohnbot__sched__delete, mcp__sohnbot__sched__edit
- Validates: FR-031

---

### Story 4.6: Daily Heartbeat System

As a user,
I want a configurable recurring heartbeat report,
So that I receive daily status summaries automatically.

**Acceptance Criteria:**

**Given** heartbeat is configured (default: daily 6pm)
**When** the heartbeat job executes
**Then** report includes: operations count, errors, scheduled jobs run, uptime
**And** report is sent to Telegram
**And** user can modify heartbeat schedule: /heartbeat configure
**And** heartbeat uses scheduler infrastructure (created as a scheduled job)

**Implementation Notes:**
- Creates: src/sohnbot/capabilities/heartbeat.py (generate_heartbeat_report)
- Default job created during initial setup: "Daily Heartbeat" cron="0 18 * * *"
- Uses scheduler from this epic
- Validates: FR-035

---

## Epic 5: Development Workflow Automation

**Epic Goal:** You can execute lint, build, test, and search operations through command profiles with execution limits and timeout enforcement.

### Story 5.1: Lint Project Profile

As a user,
I want to execute project linter on specified files,
So that code quality is validated before commits.

**Acceptance Criteria:**

**Given** a project with linter configured (eslint, pylint, etc.)
**When** I request lint execution on specific files
**Then** linter runs with file path arguments
**And** timeout is enforced at 60 seconds
**And** lint results are returned (errors, warnings, exit code)
**And** operation is logged as Tier 0 (read-only execution)
**And** results are sent to Telegram

**Implementation Notes:**
- Creates: src/sohnbot/capabilities/profiles.py (execute_lint_profile)
- MCP tool: mcp__sohnbot__profiles__lint
- Uses subprocess with timeout
- Configuration: profiles.lint.command (e.g., "pylint"), profiles.lint.timeout (default: 60)
- Validates: FR-015

---

### Story 5.2: Build Project Profile

As a user,
I want to execute project build command,
So that I can verify builds succeed before committing.

**Acceptance Criteria:**

**Given** a project with build command (npm run build, make, etc.)
**When** I request build execution
**Then** build command runs with optional target argument
**And** timeout is enforced at 300 seconds (5 minutes)
**And** build output and exit code are returned
**And** operation is logged as Tier 0
**And** results are sent to Telegram

**Implementation Notes:**
- Updates: src/sohnbot/capabilities/profiles.py (execute_build_profile)
- MCP tool: mcp__sohnbot__profiles__build
- Configuration: profiles.build.command, profiles.build.timeout (default: 300)
- Validates: FR-016

---

### Story 5.3: Run Tests Profile

As a user,
I want to execute project test suite,
So that I can verify tests pass before committing.

**Acceptance Criteria:**

**Given** a project with test suite
**When** I request test execution
**Then** test command runs with optional test file/pattern argument
**And** timeout is enforced at 600 seconds (10 minutes)
**And** test results are returned (pass/fail count, exit code)
**And** operation is logged as Tier 0
**And** results are sent to Telegram

**Implementation Notes:**
- Updates: src/sohnbot/capabilities/profiles.py (execute_test_profile)
- MCP tool: mcp__sohnbot__profiles__test
- Configuration: profiles.test.command, profiles.test.timeout (default: 600)
- Validates: FR-017

---

### Story 5.4: Ripgrep Search Profile

As a user,
I want to execute ripgrep search within scoped directories,
So that I can find patterns across my codebase.

**Acceptance Criteria:**

**Given** ripgrep is installed
**When** I request search with pattern
**Then** ripgrep executes within scope-validated directories
**And** timeout is enforced at 30 seconds
**And** results include: matching files, line numbers, content
**And** file type filters are supported (optional)
**And** operation is logged as Tier 0
**And** scope validation prevents searches outside allowed roots

**Implementation Notes:**
- Updates: src/sohnbot/capabilities/profiles.py (execute_ripgrep_profile)
- MCP tool: mcp__sohnbot__profiles__ripgrep
- Uses broker scope validation before execution
- Configuration: profiles.ripgrep.timeout (default: 30)
- Validates: FR-018

---

### Story 5.5: Profile Chaining Limit & Dry-Run Mode

As a user,
I want profile execution limits and dry-run testing,
So that I can prevent runaway automation and test operations safely.

**Acceptance Criteria:**

**Given** multiple profile executions are requested
**When** profile count exceeds 5 per user request
**Then** execution is rejected with error: "Profile execution limit reached"
**And** when I prefix command with /dryrun or --dry-run flag
**Then** operation preview is returned (affected files, no actual changes)
**And** dry-run mode works for all operation types (file edits, commits, profiles)

**Implementation Notes:**
- Updates: src/sohnbot/broker/router.py (track profile count per request, enforce limit)
- Updates: src/sohnbot/runtime/agent_session.py (dry-run mode detection)
- All capabilities check dry_run flag before execution
- Validates: FR-019, FR-023

---

## Epic 6: Research & Web Search

**Epic Goal:** You can perform web searches via Brave API with intelligent caching and cost monitoring.

### Story 6.1: Brave Web Search Integration

As a user,
I want to perform web searches via Brave Search API,
So that I can find solutions and documentation.

**Acceptance Criteria:**

**Given** Brave API key is configured
**When** I request a web search
**Then** search query is sent to Brave Search API
**And** search modes are supported: fresh (no cache), static (7-day cache)
**And** top 5 results are returned with titles, URLs, snippets
**And** web search completes in <3 seconds (NFR-003, 95th percentile)
**And** API key is never exposed in logs or responses
**And** operation is logged as Tier 0

**Implementation Notes:**
- Creates: src/sohnbot/capabilities/web.py (brave_search function)
- Creates: migrations/0004_search_cache.sql (search_cache table)
- MCP tool: mcp__sohnbot__web__search
- Configuration: web.brave_api_key (environment variable)
- Validates: FR-024, NFR-003, NFR-013

---

### Story 6.2: Search Result Caching

As a user,
I want static search results cached for 7 days,
So that repeated searches don't consume API quota.

**Acceptance Criteria:**

**Given** a search query has been executed in static mode
**When** the same query is requested within 7 days
**Then** cached results are returned (no API call)
**And** cache key is: query hash + freshness mode
**And** time-sensitive queries bypass cache (detected keywords: dates, "today", "latest")
**And** cache expiration is configurable (default: 7 days)
**And** cache auto-invalidates after configured period (NFR-021)

**Implementation Notes:**
- Updates: src/sohnbot/capabilities/web.py (check cache before API call)
- search_cache table includes: query_hash, mode, results_json, created_at, expires_at
- Configuration: web.cache_days (default: 7)
- Validates: FR-025, NFR-021

---

### Story 6.3: Search Volume Monitoring

As a user,
I want soft threshold alerts for search volume,
So that I can monitor API quota without hard blocking.

**Acceptance Criteria:**

**Given** search volume is tracked daily
**When** daily searches exceed 100 (configurable threshold)
**Then** Telegram notification is sent: "⚠️ Search Volume Alert: 127 searches (threshold: 100)"
**And** notification advises: "Monitor Brave API quota to avoid cost overruns"
**And** no hard blocking occurs (user retains control)
**And** threshold is configurable: /config search_threshold [number]
**And** search count resets daily at midnight UTC

**Implementation Notes:**
- Updates: src/sohnbot/capabilities/web.py (track daily search count)
- Creates: daily_metrics table or use config table for counter
- Configuration: web.search_threshold (default: 100)
- Notification triggered when threshold exceeded
- Validates: FR-026

---

### Story 6.4: Query Operation Logs

As a user,
I want to query recent operations with filtering,
So that I can review SohnBot's activity history.

**Acceptance Criteria:**

**Given** operations are logged to execution_log
**When** I send /logs [hours] command
**Then** recent operations are returned (default: last 24 hours)
**And** results include: timestamp, operation type, files affected, result, errors
**And** filtering is supported by: operation type, success/failure, date range
**And** logs are queryable via Telegram
**And** operation logs are retained for 90 days (NFR-021)
**And** logs auto-delete after 90 days

**Implementation Notes:**
- Updates: src/sohnbot/gateway/commands.py (handle_logs command)
- MCP tool: mcp__sohnbot__observe__logs (reuses observe capability)
- Queries execution_log table with filters
- Scheduled cleanup job (weekly) deletes logs >90 days old
- Validates: FR-037, NFR-021
