---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
inputDocuments:
  - 'E:/GIT/SohnBot/docs/PRD.md'
  - 'E:/GIT/SohnBot/docs/Resources/Agent SDK Overview.md'
  - 'E:/GIT/SohnBot/docs/Resources/Claude Agent SDK for Python.md'
  - 'E:/GIT/SohnBot/docs/Resources/Claude Agent SDK CLI Chat Demo.md'
workflowType: 'architecture'
project_name: 'SohnBot'
user_name: 'Mirko'
date: '2026-02-25'
lastStep: 8
status: 'complete'
completedAt: '2026-02-25'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**

SohnBot implements **37 functional requirements** organized into 6 capability modules:

1. **File Operations (FR-001 to FR-009)**: Read, search, patch-based edits, snapshot creation, rollback, size enforcement, binary rejection
2. **Git Operations (FR-010 to FR-014)**: Status, diff, commit, checkout, snapshot branch management
3. **Command Profiles (FR-015 to FR-019)**: Lint, build, test, ripgrep search, execution limits
4. **Scope & Safety (FR-020 to FR-023)**: Path validation, configured scope roots, operation logging, dry-run mode
5. **Web Search (FR-024 to FR-026)**: Brave API integration, caching, volume monitoring
6. **Scheduler (FR-027 to FR-037)**: Job creation, idempotent execution, timezone awareness, timeout enforcement, heartbeat monitoring

**Core Architectural Requirements:**

- **Governed Operator Philosophy**: Autonomous execution within structural boundaries. Human intervention is exceptional, not routine. Recoverability is the primary safety mechanism.
- **Operation Risk Classification**: Tier 0 (read-only), Tier 1 (single-file), Tier 2 (multi-file), Tier 3 (destructive/future). Execution proceeds autonomously; user notified post-operation with snapshot references.
- **Broker-Enforced Policy**: All agent capabilities route through a centralized broker layer that enforces scope validation, operation limits, and safety constraints architecturally—not via prompts or confirmations.
- **Snapshot-First Recoverability**: Git snapshots created before all modification operations. Rollback is the recovery mechanism, not prevention.

**Non-Functional Requirements:**

**23 NFRs** define system behavior across:

- **Performance (NFR-001 to NFR-005)**: File reads <500ms, git ops <1s, searches <5s, scheduler ±2min precision, notifications <10s
- **Reliability (NFR-006 to NFR-009)**: 95% uptime, <30s crash recovery, 99% job execution success, zero file corruptions
- **Security (NFR-010 to NFR-014)**: 100% path traversal prevention, command injection blocking, scope violation rejection, API key protection, complete audit logging
- **Scalability (NFR-015 to NFR-017)**: 50 repos, 100K files/repo, 3 concurrent jobs
- **Usability (NFR-018 to NFR-020)**: 90% NL understanding, <2s response acknowledgment, clear error messages
- **Maintainability (NFR-021 to NFR-023)**: Automated cleanup (snapshots, logs, cache), hot config reloading, vulnerability management

**Scale & Complexity:**

- **Primary domain**: Policy-enforced local autonomous execution system (not just "local automation")
- **Complexity level**: Medium-High
  - 37 functional requirements with sophisticated workflow orchestration
  - Safety-critical operations requiring structural enforcement
  - Multi-module coordination (Files, Git, Scheduler, Search, Command Profiles)
  - Idempotent scheduler with timezone-aware catch-up logic
  - Patch-based editing with automatic snapshot orchestration
- **Estimated architectural components**: 7 major subsystems
  1. Telegram Gateway (message routing, user interface)
  2. Agent Runtime (Claude SDK integration, conversation management)
  3. **Broker Layer** (policy enforcement, capability routing, operation classification) ← **Architectural heart**
  4. Capability Modules (Files, Git, Command Profiles, Web Search, Scheduler)
  5. Persistence Layer (SQLite: jobs, logs, cache, config)
  6. Process Supervision (pm2, health monitoring, auto-restart)
  7. Configuration Management (scope roots, API keys, thresholds)

### Technical Constraints & Dependencies

**Local-First Constraints:**
- Runs entirely on user's local machine (Windows Phase 1)
- No cloud dependencies for core functionality
- Private API keys (Anthropic, Brave) stored in environment variables
- User owns all data (SQLite databases, git repos, logs)

**Technology Mandates:**
- Python 3.10+ (Claude Agent SDK requirement)
- SQLite (persistence, no external database)
- Git (snapshot/rollback mechanism, must be installed)
- Telegram Bot API (user interface)
- Process manager (pm2 for Windows, configurable for others)

**Integration Requirements:**
- Claude Agent SDK for Python (agent runtime foundation)
- Brave Search API (web search capability)
- ripgrep (fast file content search)
- Standard git CLI (snapshot/rollback operations)

**Safety Boundaries:**
- File operations restricted to configured scope roots (~/Projects, ~/Notes)
- Path normalization and traversal prevention (architectural, not prompt-based)
- Command profile execution limits (5 per request, prevents chaining attacks)
- Timeout enforcement (lint: 60s, build: 300s, tests: 600s, scheduled jobs: 600s)
- Regex timeout protection (5s max, prevents catastrophic backtracking)

**Performance Constraints:**
- File size limits (10MB read, 50KB patch)
- Repository scalability targets (50 repos, 100K files each)
- Concurrent execution limits (3 scheduled jobs max)
- Scheduler evaluation frequency (60s tick rate)

### Cross-Cutting Concerns Identified

1. **Structural Safety (Primary)**
   - Broker layer enforces all capability boundaries
   - Agent is replaceable; safety model is architectural
   - Scope isolation, path validation, operation classification
   - No reliance on model behavior for safety

2. **Recoverability by Design**
   - Git snapshots before all modifications
   - Snapshot retention (30 days, auto-pruned)
   - Rollback mechanism with user-browsable restore points
   - Idempotent operations (scheduler catch-up, no duplicate execution)

3. **Observability**
   - Complete operation logging (SQLite audit trail, 90-day retention)
   - Post-operation Telegram notifications with snapshot references
   - Status updates for long-running operations (every 30s)
   - Heartbeat system for liveness monitoring
   - Soft monitoring (search volume alerts) without hard blocking

4. **Performance Management**
   - Timeout enforcement across all blocking operations
   - Caching strategy (search results: 7 days)
   - Size limits prevent memory exhaustion
   - Concurrency controls prevent resource contention

5. **Security Boundaries**
   - Path traversal prevention (100% blocking target)
   - Command injection prevention (100% blocking target)
   - API key protection (environment variables, never logged)
   - Audit completeness (100% of operations logged)

6. **Timezone & Scheduling Correctness**
   - All times stored UTC internally, displayed in local TZ
   - DST handling (spring-forward non-existent hours)
   - Idempotent catch-up logic (run most recent missed slot once)
   - Last-completed-slot tracking prevents duplicates across restarts

## Starter Template Evaluation

### Primary Technology Domain

**Policy-Enforced Local Autonomous Execution System** (Python agent/daemon)

- Python 3.10+ (Claude Agent SDK requirement)
- Telegram bot interface layer
- Background service/daemon architecture
- Multi-module broker orchestration

### Starter Options Considered

**1. Cookiecutter-Poetry Template**
- Generic Python package scaffolding with modern tooling
- **Verdict:** Good base, but lacks specialized patterns for agent/bot/broker architecture

**2. Claude Agent SDK Demos**
- Official examples (88.4% TypeScript, 9.4% Python)
- Simple single-file patterns
- **Verdict:** Useful for SDK usage patterns, but explicitly not production-grade

**3. Custom Architecture-Aligned Structure** ✓
- **Verdict:** Required—no existing template combines Python agent + Telegram + broker architecture + daemon service

### Selected Starter: Custom Architecture-Aligned Structure

**Rationale for Selection:**

SohnBot's requirements are unique:
- **Broker layer as architectural heart** (not standard in Python packages)
- **7 distinct subsystems** requiring explicit organization
- **Production NFRs** (95% uptime, crash recovery, monitoring)
- **Governed operator model** (structural safety, not prompt-based)

No existing template combines: Claude Agent SDK + Telegram Bot + Policy Broker + Daemon Service + Modular Capabilities

**Recommended Project Structure:**

```
sohnbot/
├── src/
│   └── sohnbot/
│       ├── __init__.py
│       ├── __main__.py              # Entry point for daemon
│       │
│       ├── gateway/                  # Telegram Gateway (Subsystem 1)
│       │   ├── __init__.py
│       │   ├── telegram_client.py   # Telegram Bot API integration
│       │   ├── message_router.py    # Route messages to agent runtime
│       │   └── formatters.py        # Format agent responses for Telegram
│       │
│       ├── runtime/                  # Agent Runtime (Subsystem 2)
│       │   ├── __init__.py
│       │   ├── agent_session.py     # Claude SDK query() wrapper
│       │   ├── conversation_manager.py  # Multi-turn conversation state
│       │   └── context_loader.py    # Load CLAUDE.md, skills, etc.
│       │
│       ├── broker/                   # Broker Layer (Subsystem 3) ← HEART
│       │   ├── __init__.py
│       │   ├── policy_enforcer.py   # Scope validation, operation classification
│       │   ├── capability_router.py # Route requests to capability modules
│       │   ├── operation_classifier.py  # Tier 0/1/2/3 classification
│       │   └── hooks.py             # PreToolUse hook implementations
│       │
│       ├── capabilities/             # Capability Modules (Subsystem 4)
│       │   ├── __init__.py
│       │   ├── files/               # FR-001 to FR-009
│       │   │   ├── __init__.py
│       │   │   ├── file_ops.py      # Read, list, search
│       │   │   ├── patch_editor.py  # Unified diff application
│       │   │   └── snapshot_manager.py  # Git snapshot creation
│       │   ├── git/                 # FR-010 to FR-014
│       │   │   ├── __init__.py
│       │   │   ├── git_ops.py       # Status, diff, commit, checkout
│       │   │   └── snapshot_strategy.py
│       │   ├── command_profiles/    # FR-015 to FR-019
│       │   │   ├── __init__.py
│       │   │   ├── profile_executor.py
│       │   │   └── profiles.py      # Lint, build, test, ripgrep
│       │   ├── search/              # FR-024 to FR-026
│       │   │   ├── __init__.py
│       │   │   ├── brave_client.py
│       │   │   └── search_cache.py
│       │   └── scheduler/           # FR-027 to FR-037
│       │       ├── __init__.py
│       │       ├── job_manager.py   # Create, list, delete jobs
│       │       ├── executor.py      # Idempotent execution with catch-up
│       │       └── timezone_handler.py
│       │
│       ├── persistence/              # Persistence Layer (Subsystem 5)
│       │   ├── __init__.py
│       │   ├── database.py          # SQLite connection management
│       │   ├── models.py            # Job, Log, Config models
│       │   └── migrations/          # Schema migration scripts
│       │
│       ├── supervision/              # Process Supervision (Subsystem 6)
│       │   ├── __init__.py
│       │   ├── health_monitor.py    # Heartbeat, liveness checks
│       │   └── crash_recovery.py    # State restoration after crash
│       │
│       └── config/                   # Configuration Management (Subsystem 7)
│           ├── __init__.py
│           ├── settings.py          # Load from env vars, config files
│           ├── scope_config.py      # Allowed roots configuration
│           └── defaults.py          # Default thresholds, timeouts
│
├── tests/
│   ├── unit/
│   │   ├── test_broker/
│   │   ├── test_capabilities/
│   │   └── test_gateway/
│   ├── integration/
│   └── fixtures/
│
├── config/
│   ├── sohnbot.example.toml        # Example configuration file
│   └── pm2.config.js                # pm2 process manager config
│
├── scripts/
│   ├── setup.sh                     # Initial setup script
│   └── migrate.py                   # Database migration runner
│
├── docs/
│   ├── architecture.md              # (This file, from _bmad-output/)
│   ├── deployment.md
│   └── api/
│
├── .env.example                     # Example environment variables
├── pyproject.toml                   # Poetry dependencies, project metadata
├── poetry.lock
├── README.md
├── CLAUDE.md                        # Claude Code instructions
└── .gitignore
```

**Initialization Approach:**

**Step 1:** Initialize with Poetry
```bash
poetry init --name sohnbot --python "^3.10" --dependency claude-agent-sdk --dependency python-telegram-bot --dependency aiosqlite
```

**Step 2:** Create directory structure manually
```bash
mkdir -p src/sohnbot/{gateway,runtime,broker,capabilities/{files,git,command_profiles,search,scheduler},persistence,supervision,config}
mkdir -p tests/{unit,integration,fixtures}
mkdir -p config scripts docs
```

**Step 3:** Initialize each module with `__init__.py`
```bash
find src/sohnbot -type d -exec touch {}/__init__.py \;
```

**Architectural Decisions Provided by This Structure:**

**Language & Runtime:**
- Python 3.10+ (Claude SDK requirement)
- Poetry for dependency management (reproducible builds, lockfile)
- asyncio-based architecture (Claude SDK is async-native)

**Code Organization:**
- **src/ layout** (prevents accidental imports, clean packaging)
- **Subsystem-aligned modules** (maps 1:1 to PRD's 7 subsystems)
- **Broker as first-class citizen** (dedicated top-level module, not buried in utils/)
- **Capability modules separated** (Files, Git, Scheduler, Search, Command Profiles isolated)

**Testing Framework:**
- pytest (Python standard for async testing)
- Unit tests per subsystem
- Integration tests for cross-subsystem workflows
- Fixtures for test data

**Development Experience:**
- Poetry virtual environment isolation
- pyproject.toml centralizes all configuration (dependencies, tools, metadata)
- CLAUDE.md provides AI agent instructions
- .env for secrets management

**Configuration Management:**
- TOML config files (user-editable, human-readable)
- Environment variables for secrets (API keys)
- Defaults in code, overridable via config

**Process Management:**
- pm2 for daemon supervision (Phase 1: Windows)
- Configurable for systemd, launchd (future)
- Health monitoring and auto-restart built-in

**Note:** Project initialization using this structure should be **Story 1** in the implementation plan.


## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
- Broker & Policy Enforcement Pattern (affects all capability execution)
- Data Architecture & Persistence (foundation for all state)
- Configuration Management (affects initialization and runtime behavior)

**Important Decisions (Shape Architecture):**
- Scheduler Architecture (affects autonomous operation reliability)
- Logging & Observability (affects debugging and audit compliance)

**Deferred Decisions (Post-MVP):**
- Multi-user support (PRD specifies single user Phase 1)
- Cloud deployment patterns (local-first Phase 1)
- Advanced monitoring/alerting (basic observability sufficient for MVP)

### Decision 1: Data Architecture & Persistence

**Choice:** Manual SQL + Migration Runner + DB-Level Governance (STRICT + CHECK) + WAL

**Rationale:**
- Aligns with governed operator philosophy (explicit, auditable, structural safety)
- No ORM abstraction hiding SQL behavior
- STRICT tables + CHECK constraints enforce invariants at database level
- WAL mode enables safe concurrency (scheduler + interactive commands)
- Migration checksums detect tampering
- Full transparency for security auditing

**Implementation Requirements:**

**Migration Directory:** `src/sohnbot/persistence/migrations/` with versioned SQL files (0001_init.sql, 0002_indexes.sql, etc.)

**Migration Application:** Lexical order, transactional, checksum validation prevents tampering

**Connection Pragmas:** `foreign_keys=ON, journal_mode=WAL, synchronous=NORMAL, busy_timeout=5000, temp_store=MEMORY`

**Core Tables (STRICT):** jobs, execution_log, search_cache, config, notification_outbox with CHECK constraints

**Retention:** 90-day execution logs, 7-day search cache, 30-day sent notifications

**API:** `get_connection()`, `apply_migrations()`, `init_db()`, retention helpers

**Affects:** All subsystems (Jobs, Logging, Cache, Config, Notifications)

---

### Decision 2: Broker & Policy Enforcement

**Choice:** Centralized Broker Routing Layer + Minimal PreToolUse Guardrail Hook

**Architectural Invariant:**
> **All state-changing capability execution MUST pass through the Broker.**

**Rationale:**
- Broker layer is the architectural heart
- Single source of truth for policy (no duplication)
- Impossible to bypass (PreToolUse blocks non-broker tools)
- Clean separation: hook=guardrail, broker=policy, capabilities=domain
- Complete audit trail

**Implementation Pattern:**

**PreToolUse Hook:** Blocks any tool NOT matching `mcp__sohnbot__*`, returns `permissionDecision: deny`

**MCP Tools:** In-process server with tools: `mcp__sohnbot__fs_read`, `mcp__sohnbot__fs_apply_patch`, `mcp__sohnbot__git_commit`, `mcp__sohnbot__sched_add_job`, `mcp__sohnbot__web_search`

**Broker Responsibilities:**
1. Scope validation (path normalization, traversal prevention)
2. Operation classification (Tier 0/1/2/3)
3. Command profile limits (max 5 per request)
4. Timeout assignment
5. Audit logging (pre + post execution)
6. Capability routing

**Flow:** Agent → PreToolUse hook → MCP tool → Broker (validate/classify/log) → Capability module → Result

**Invariants:**
- No bypass possible (hook enforcement)
- Single policy source (broker only)
- Complete audit (pre + post logging)
- Scope isolation (path validation)
- Timeout enforcement (all operations)
- Snapshot-first (Tier 1/2 operations)

**Affects:** All capability execution, audit logging, operation classification

---

### Decision 3: Scheduler Architecture

**Choice:** Boundary-Aligned Loop + asyncio.TaskGroup + zoneinfo + Idempotent Catch-Up

**Rationale:**
- Boundary alignment prevents drift over 30+ days
- zoneinfo provides correct DST handling
- TaskGroup ensures structured concurrency
- Idempotent catch-up (most recent slot only, no backlog)
- Native Python 3.13, no external libraries

**Implementation Pattern:**

**Tick Loop:** Compute next 60s boundary, sleep until boundary, evaluate jobs, recompute

**Slot Computation:** croniter + zoneinfo for timezone-aware cron evaluation, convert to UTC

**Idempotent Logic:** Compare most_recent_slot > last_completed_slot, execute once only

**Concurrency:** TaskGroup + Semaphore(3) for max 3 concurrent jobs

**Timeout:** `asyncio.timeout(600)` wraps each job execution

**DST Handling:** Spring-forward skips non-existent hours, fall-back deduplicates via last_completed_slot

**Failure Resilience:** Job exceptions don't crash scheduler, temporary DB errors retry next tick

**Invariants:**
- No cumulative drift (boundary realignment)
- Idempotent execution (no duplicates)
- Correct timezone/DST (zoneinfo IANA)
- Concurrency isolation (TaskGroup)
- Timeout enforcement (10 min hard limit)
- Continuous operation (survives job failures)

**Affects:** All scheduled jobs (morning summary, weekly digest, heartbeat, retention)

---

### Decision 4: Logging & Observability

**Choice:** structlog + Dual Logging (File + SQLite) + Persistent Notification Outbox

**Rationale:**
- structlog enables structured JSON logs (machine-parseable)
- Dual logging serves different needs (files: debug, SQLite: audit)
- Persistent outbox guarantees delivery (survives crashes/outages)
- Operations never block on logging/notifications
- Independent failure domains

**Implementation Pattern:**

**structlog Config:** JSON processors, contextvars for correlation, console pretty-print (dev), file JSON (prod)

**File Logs:** Rotated JSON files for debugging, 30-day retention

**SQLite Audit:** `execution_log` table for operation-level events (start, classification, completion, failure), 90-day retention

**Notification Outbox:** `notification_outbox` table with pending/sent/failed status, background worker polls + sends, exponential backoff on retry

**Progress Updates:** Every 30s for long-running operations

**Heartbeat:** Scheduled job logging uptime, active jobs, memory usage

**Correlation:** operation_id + correlation_id tie together logs/audit/notifications

**Invariants:**
- Operations never block (async logging/notifications)
- Guaranteed delivery (persistent outbox + retries)
- Complete audit (all operations logged to SQLite)
- Machine-parseable (JSON structured logs)
- Independent failures (logging ≠ audit ≠ notification ≠ operation)
- 30+ day support (structured logs + retention)

**Affects:** All subsystems (debugging, audit, notifications)

---

### Decision 5: Configuration & Secrets Management

**Choice:** TOML + DB-backed Dynamic Config + Environment Variables for Secrets

**Rationale:**
- Two-tier separates security boundaries (static) from operations (dynamic)
- 80%+ hot reload via SQLite + event system
- Secrets in environment only (never files, never logged)
- Config registry provides strong validation
- Windows-first (event-based reload, no SIGHUP)

**Implementation Pattern:**

**Static Config (Restart Required):** Scope roots, database path, API key env names, log paths — loaded from `config/sohnbot.toml` + environment

**Dynamic Config (Hot Reloadable):** Thresholds, timeouts, retention periods, scheduler settings — seeded from TOML, authoritative in SQLite `config` table

**Config Registry:** Code-defined registry with tier (static/dynamic), type, default, bounds, validators

**Precedence:**
- Static: code defaults < TOML < env overrides
- Dynamic: code defaults < TOML seed < SQLite (authoritative)

**/config Commands:**
- `/config show` - Display all config
- `/config set <key>=<value>` - Update dynamic config (validates, updates SQLite, publishes event)
- `/config reset <key>` - Reset to default

**Hot Reload:** Event system (`config_updated` event), subsystems subscribe and apply changes

**Secrets:** ANTHROPIC_API_KEY, BRAVE_API_KEY, TELEGRAM_BOT_TOKEN from environment only, never stored in TOML/SQLite, never logged

**Invariants:**
- 80%+ hot reload (dynamic config)
- Security boundaries protected (static restart required)
- Secrets never leak (env only, redacted in logs)
- Strong validation (registry types/bounds)
- Windows-compatible (event-based, no SIGHUP)

**Affects:** All subsystems (initialization, hot reload, security)

---

### Decision Impact Analysis

**Implementation Sequence:**

1. **Database Schema** → Foundation for all persistence
2. **Configuration Management** → Required for initialization
3. **Logging & Observability** → Required before operations
4. **Broker & Policy Enforcement** → Core safety layer
5. **Scheduler Architecture** → Autonomous operation

**Cross-Component Dependencies:**

```
Database (foundation)
  ├→ Config (settings for all subsystems)
  ├→ Logging (audit/debug for all subsystems)
  ├→ Broker (routes all capability execution)
  │   ├→ Files Module
  │   ├→ Git Module
  │   ├→ Command Profiles
  │   ├→ Search Module
  │   └→ Scheduler Module
  └→ Notification Outbox (user notifications)
```

**Critical Path:** Database → Config → Logging → Broker → Capabilities

**Hot Reload Capability (80%+ Requirement):**

**Hot Reloadable (No Restart):** Thresholds, timeouts, retention periods, scheduler settings, logging verbosity, notification settings (~85% of config keys)

**Restart Required:** Scope roots, database path, API keys, logging file path (~15% of config keys)

**Percentage:** ~85% hot-reloadable ✓

## Implementation Patterns & Consistency Rules

### Pattern Philosophy

SohnBot follows **Python-centric patterns** aligned with:
- **PEP 8** (Python style guide)
- **Explicit over implicit** (structural safety philosophy)
- **Governed operator spine** (non-negotiable validation sequence)

These patterns are **MANDATORY** for all AI agents implementing SohnBot code.

---

### Naming Patterns

**Database:** Plural snake_case tables, snake_case columns
- Tables: `jobs`, `execution_log`, `notification_outbox`, `schema_migrations`
- Columns: `operation_id`, `last_completed_slot`, `created_at`
- Indexes: `idx_<table>_<columns>` (e.g., `idx_jobs_enabled_schedule`)
- Foreign Keys: `<referenced_table>_id` (e.g., `job_id`, `user_id`)

**MCP Tools:** `mcp__sohnbot__<module>__<verb>`
- `mcp__sohnbot__fs__read`, `mcp__sohnbot__fs__apply_patch`
- `mcp__sohnbot__git__commit`, `mcp__sohnbot__git__status`
- `mcp__sohnbot__sched__add_job`, `mcp__sohnbot__sched__list_jobs`
- `mcp__sohnbot__web__search`
- `mcp__sohnbot__profiles__lint`

**Modules:** snake_case abbreviations
- `fs` (Files), `git` (Git), `sched` (Scheduler), `web` (Web search), `profiles` (Command profiles)

**Code:**
- Files/Modules: `snake_case.py` (e.g., `broker.py`, `policy_enforcer.py`)
- Functions: `snake_case()` (e.g., `create_snapshot()`, `validate_scope()`)
- Classes: `PascalCase` (e.g., `BrokerResult`, `ConfigLoader`)
- Constants: `SCREAMING_SNAKE_CASE` (e.g., `MAX_CONCURRENT_JOBS`, `DEFAULT_TIMEOUT_SECONDS`)
- Private: `_leading_underscore()` (e.g., `_validate_internal()`)

**Config Keys:** Dotted snake_case
- `thresholds.search_volume_daily`, `timeouts.lint_timeout`, `retention.logs_days`

**structlog Fields:** snake_case
- `operation_id`, `correlation_id`, `duration_ms`, `snapshot_ref`

---

### Structure Patterns

**Package:** `src/sohnbot/`

**Subsystems:**
```
src/sohnbot/
├── broker.py              ← Single file (DO NOT rename)
├── gateway/               ← Telegram interface
├── runtime/               ← Agent SDK integration
├── capabilities/          ← Single-file modules
│   ├── fs.py             ← Files (FR-001 to FR-009)
│   ├── git.py            ← Git (FR-010 to FR-014)
│   ├── profiles.py       ← Command profiles (FR-015 to FR-019)
│   ├── web.py            ← Web search (FR-024 to FR-026)
│   └── sched.py          ← Scheduler (FR-027 to FR-037)
├── persistence/
│   ├── db.py
│   ├── models.py
│   └── migrations/
│       ├── 0001_init.sql
│       ├── 0002_indexes.sql
│       └── 0003_constraints.sql
├── supervision/
└── config/
```

**Tests:** Keep OUT of src
```
tests/
├── unit/
│   ├── test_broker.py
│   ├── test_capabilities_fs.py
│   └── test_persistence.py
├── integration/
│   ├── test_broker_integration.py
│   └── test_scheduler_integration.py
└── fixtures/
```

**Migrations:** `<sequence>_<description>.sql` (e.g., `0001_init.sql`, `0002_indexes.sql`)
- Zero-padded 4 digits

---

### Format Patterns

**Timestamps:** UTC Unix epoch **integer seconds** in DB
```python
✓ int(datetime.now(timezone.utc).timestamp())
✗ datetime.now().isoformat()  # Convert only at UI edges
```

**JSON in SQLite:** Compact (no pretty print)
```python
✓ json.dumps(data)
✗ json.dumps(data, indent=2)
```

**JSON Fields:** snake_case
```json
✓ {"operation_id": "...", "snapshot_ref": "..."}
✗ {"operationId": "...", "snapshotRef": "..."}
```

**Error Structure:** Stable dict shape
```python
{
    "code": "scope_violation",           # snake_case
    "message": "Path outside allowed scope",
    "details": {"path": "/etc/passwd"},
    "retryable": False
}
```

**Telegram Notifications:** 1 emoji per message max
- ✅ Success, ❌ Error, ⚠️ Warning, 🔄 In progress, 💓 Heartbeat, 📊 Report

---

### Communication Patterns

**Events:** snake_case naming
```
✓ config_updated, job_completed, snapshot_created
✗ ConfigUpdated, config.updated
```

**Event Payload:**
```python
{
    "event": "config_updated",
    "timestamp": 1709571234,
    "data": {"keys": ["thresholds.search_volume_daily"]}
}
```

**BrokerResult:**
```python
@dataclass
class BrokerResult:
    allowed: bool
    operation_id: str
    tier: int | None = None
    snapshot_ref: str | None = None
    error: dict | None = None
```

---

### Process Patterns

**Error Handling:**
- Log + continue: Expected operational errors (file not found)
- Log + raise: Unexpected errors, contract violations
- Raise without log: Input validation (let caller log)

**Async:**
- Use `TaskGroup` for structured concurrency
- `create_task()` ONLY for long-lived daemons (scheduler, notifier worker)
- Always `await` capability calls

**Transactions:** Per operation (one transaction per logical operation)
```python
def create_job(conn, job_data):
    conn.execute("INSERT INTO jobs ...")
    conn.commit()  # Commit per operation
```

**Retries:** Exponential backoff with jitter, constants in config registry
```python
base_delay = 2 ** attempt
jitter = random.uniform(0, 0.1 * base_delay)
delay = base_delay + jitter
```

---

### Validation Order (Non-Negotiable)

**Governed-Operator Spine:**

```
1. Hook Allowlist Gate
   └─ Check: tool name matches mcp__sohnbot__*

2. Broker Validation + Classification + Log Start
   ├─ Generate operation_id
   ├─ Classify tier (0/1/2/3)
   ├─ Validate scope
   ├─ Check limits
   └─ Log start

3. Capability Domain Validation
   └─ Domain-specific validation (e.g., patch format)

4. Execute
   ├─ Create snapshot (if Tier 1/2)
   ├─ Apply timeout
   └─ Execute logic

5. Broker Log End + Snapshot Ref + Enqueue Notification
   ├─ Log completion
   ├─ Include snapshot_ref, duration_ms
   ├─ Enqueue notification (non-blocking)
   └─ Return BrokerResult
```

**This sequence MUST NOT be reordered or bypassed.**

---

### Enforcement

**All AI Agents MUST:**
1. Follow naming patterns exactly (snake_case, plural tables, dotted config)
2. Respect module structure (broker.py stays broker.py, capabilities single-file)
3. Use Unix epoch timestamps (no ISO strings in SQLite)
4. Maintain validation order (Hook → Broker → Capability → Execute → Log)
5. Commit per operation (one transaction per operation)
6. Use TaskGroup for concurrency (no orphaned tasks)
7. Follow error structure ({code, message, details, retryable})
8. Log with structured fields (operation_id, correlation_id)

**Verification:**
- `ruff check src/` (PEP 8, snake_case)
- `mypy src/` (type annotations)
- `pytest tests/` (before commit)
- Migration checksum (tamper detection)

**These patterns are MANDATORY. No exceptions.**

## Project Structure & Boundaries

### Complete Project Directory Structure

```
sohnbot/
├── README.md
├── pyproject.toml                    # Poetry dependencies, project metadata
├── poetry.lock
├── .env.example                      # Example environment variables
├── .gitignore
├── CLAUDE.md                         # Claude Code instructions
│
├── config/
│   ├── sohnbot.example.toml         # Example configuration
│   └── pm2.config.js                # pm2 process manager config
│
├── scripts/
│   ├── setup.sh                     # Initial setup script
│   ├── migrate.py                   # Database migration runner CLI
│   └── seed_config.py               # Seed dynamic config on first run
│
├── data/                            # Runtime data (gitignored)
│   ├── sohnbot.db                   # SQLite database
│   └── .gitkeep
│
├── logs/                            # Log files (gitignored)
│   ├── sohnbot.log                  # JSON structured logs
│   └── .gitkeep
│
├── docs/
│   ├── PRD.md                       # Product Requirements Document
│   ├── architecture.md              # This document (from _bmad-output/)
│   ├── deployment.md                # Deployment instructions
│   ├── development.md               # Development guide
│   ├── api/
│   │   ├── broker.md                # Broker API documentation
│   │   ├── capabilities.md          # Capability modules API
│   │   └── mcp_tools.md             # MCP tool definitions
│   └── Resources/                   # Technical resources
│       ├── Agent SDK Overview.md
│       ├── Claude Agent SDK for Python.md
│       └── Claude Agent SDK CLI Chat Demo.md
│
├── src/
│   └── sohnbot/
│       ├── __init__.py
│       ├── __main__.py              # Entry point: python -m sohnbot
│       │
│       ├── broker.py                # ← HEART: Policy enforcement, routing, classification
│       │
│       ├── gateway/                 # Subsystem 1: Telegram Gateway
│       │   ├── __init__.py
│       │   ├── telegram_client.py   # python-telegram-bot integration
│       │   ├── message_router.py    # Route messages to agent runtime
│       │   ├── formatters.py        # Format agent responses for Telegram
│       │   ├── commands.py          # /config, /status, /rollback commands
│       │   └── notification_worker.py  # Background worker for outbox
│       │
│       ├── runtime/                 # Subsystem 2: Agent Runtime
│       │   ├── __init__.py
│       │   ├── agent_session.py     # Claude SDK query() wrapper
│       │   ├── conversation_manager.py  # Multi-turn state
│       │   ├── context_loader.py    # Load CLAUDE.md, skills
│       │   ├── mcp_tools.py         # MCP tool registration
│       │   └── hooks.py             # PreToolUse guardrail hook
│       │
│       ├── capabilities/            # Subsystem 4: Capability Modules
│       │   ├── __init__.py
│       │   ├── fs.py                # FR-001 to FR-009: Files
│       │   ├── git.py               # FR-010 to FR-014: Git
│       │   ├── profiles.py          # FR-015 to FR-019: Command Profiles
│       │   ├── web.py               # FR-024 to FR-026: Web Search
│       │   └── sched.py             # FR-027 to FR-037: Scheduler
│       │
│       ├── persistence/             # Subsystem 5: Persistence Layer
│       │   ├── __init__.py
│       │   ├── db.py                # Connection, migrations, pragmas
│       │   ├── models.py            # Domain models (NOT ORM)
│       │   ├── audit.py             # Audit log insert/query helpers
│       │   ├── migrations/
│       │   │   ├── 0001_init.sql    # Core tables (STRICT + CHECK)
│       │   │   ├── 0002_indexes.sql # Performance indexes
│       │   │   └── 0003_constraints.sql  # Additional constraints
│       │   └── retention.py         # Retention cleanup queries
│       │
│       ├── supervision/             # Subsystem 6: Process Supervision
│       │   ├── __init__.py
│       │   ├── health_monitor.py    # Heartbeat, liveness checks
│       │   └── crash_recovery.py    # State restoration after crash
│       │
│       └── config/                  # Subsystem 7: Configuration
│           ├── __init__.py
│           ├── settings.py          # Config loader (TOML + SQLite + env)
│           ├── registry.py          # Config key registry + validation
│           ├── scope_config.py      # Scope roots validation
│           ├── defaults.py          # Default values for all config keys
│           └── events.py            # Config update event system
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                  # pytest configuration, fixtures
│   │
│   ├── unit/
│   │   ├── test_broker.py           # Broker policy enforcement tests
│   │   ├── test_config.py           # Config registry, loader tests
│   │   ├── test_capabilities_fs.py  # Files capability unit tests
│   │   ├── test_capabilities_git.py # Git capability unit tests
│   │   ├── test_capabilities_sched.py  # Scheduler unit tests
│   │   ├── test_persistence.py      # DB, migrations, models tests
│   │   └── test_gateway.py          # Telegram gateway tests
│   │
│   ├── integration/
│   │   ├── test_broker_integration.py  # End-to-end broker flow
│   │   ├── test_scheduler_integration.py  # Scheduler tick + execution
│   │   ├── test_notification_flow.py  # Outbox → worker → Telegram
│   │   └── test_snapshot_recovery.py  # Snapshot creation + rollback
│   │
│   └── fixtures/
│       ├── sample_jobs.json         # Test job definitions
│       ├── sample_patches.txt       # Test unified diffs
│       ├── test_config.toml         # Test configuration
│       └── test.db                  # In-memory test database
│
└── _bmad-output/                    # BMAD planning artifacts (not in src)
    └── planning-artifacts/
        └── architecture.md          # This document
```

---

### Architectural Boundaries

**MCP Tools Interface:**
- `mcp__sohnbot__fs__read`, `mcp__sohnbot__fs__apply_patch`
- `mcp__sohnbot__git__commit`, `mcp__sohnbot__git__status`
- `mcp__sohnbot__sched__add_job`, `mcp__sohnbot__web__search`
- `mcp__sohnbot__profiles__lint`
- All route through `broker.handle()`

**Component Boundaries:**
- Telegram Gateway ↔ Agent Runtime (message passing)
- Agent Runtime ↔ Broker (MCP tools call broker)
- Broker ↔ Capabilities (validated requests, domain execution)
- Capabilities ↔ Persistence (SQLite queries/inserts)
- Gateway ↔ Persistence (notification outbox polling)

**Service Boundaries:**
- Scheduler Loop (continuous 60s ticks)
- Notification Worker (continuous 5s polls)
- Main Process (pm2 managed, auto-restart)

**Data Boundaries:**
- SQLite: `jobs`, `execution_log`, `search_cache`, `config`, `notification_outbox`, `schema_migrations`
- File System: Scope-validated `~/Projects`, `~/Notes` only
- Git: Snapshot branches in `.git/refs`

---

### Requirements to Structure Mapping

**Capability Modules:**
- FR-001 to FR-009 → `capabilities/fs.py`
- FR-010 to FR-014 → `capabilities/git.py`
- FR-015 to FR-019 → `capabilities/profiles.py`
- FR-024 to FR-026 → `capabilities/web.py`
- FR-027 to FR-037 → `capabilities/sched.py`

**Cross-Cutting:**
- FR-020 to FR-023 (Scope & Safety) → `broker.py`
- All logging → `persistence/audit.py` + structlog
- All config → `config/` subsystem
- All notifications → `gateway/notification_worker.py` + outbox

---

### Integration Points

**Internal Communication:**
- Synchronous: `await` for direct calls (Gateway → Runtime → Broker → Capability)
- Asynchronous: Event system (`config_updated`), outbox pattern (notifications)
- Background: `create_task()` for scheduler + notification worker only

**External Integrations:**
- Telegram Bot API (bidirectional, HTTPS, `gateway/telegram_client.py`)
- Claude Agent SDK (outbound, HTTPS, `runtime/agent_session.py`)
- Brave Search API (outbound, HTTPS, `capabilities/web.py`)
- Local Git CLI (subprocess, `capabilities/git.py`)
- Local ripgrep CLI (subprocess, `capabilities/profiles.py`)

**Data Flow:**
```
User → Gateway → Runtime → Claude SDK → MCP Tool → PreToolUse Hook
  → Broker (validate + classify + log start)
    → Capability (execute)
      → Broker (log end + enqueue notification)
        → Runtime → Gateway → User

Async: Broker enqueues → Outbox table → Worker polls → Telegram
```

---

### Development Workflow

**Setup:**
```bash
poetry install
cp .env.example .env  # Add API keys
python scripts/migrate.py
python scripts/seed_config.py
```

**Run:**
```bash
poetry run python -m sohnbot
# Or: pm2 start config/pm2.config.js
```

**Deploy:**
```bash
poetry install --no-dev
python scripts/migrate.py
pm2 start config/pm2.config.js
```

## Observability Capability (Architecture Addition)

### Observability Philosophy

SohnBot's observability aligns with the **governed operator philosophy**:
- **Read-only by design:** Observability provides visibility, not control
- **Local-first:** No cloud services, Prometheus, or Grafana required
- **Non-blocking:** Metrics collection never blocks broker, scheduler, or notifier
- **Minimal overhead:** <2% CPU, simple in-memory snapshots

**Key Principle:** Observability reports on system state but cannot modify it.

---

### Observability Architecture

#### Components

```
┌──────────────────────────────────────────────────────────────┐
│                   Observability Module                        │
│                  (Read-Only Capability)                       │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │         Runtime Status Snapshot (In-Memory)          │    │
│  │  - Process info, broker activity, scheduler state    │    │
│  │  - Resource usage, health checks, operation history  │    │
│  │  - Updated every 10-30s (non-blocking background)    │    │
│  └────────┬────────────────────────────────────────────┘    │
│           │                                                   │
│           ├──→ Telegram Commands (/status, /health)          │
│           │                                                   │
│           └──→ Local HTTP Server (localhost-only)            │
│                 - GET /status (JSON)                          │
│                 - GET /health (JSON)                          │
│                 - GET /metrics (JSON)                         │
│                 - GET / or /ui (HTML status page)            │
└──────────────────────────────────────────────────────────────┘
           ↑
           │ (Reads from, never writes to)
           │
    ┌──────┴──────────────────────────────────┐
    │                                          │
    │  Broker       Scheduler     Notifier    │
    │  Persistence  Gateway       Config      │
    │                                          │
    └──────────────────────────────────────────┘
```

---

### Functional Requirements Mapping

**Observability Capability** (`capabilities/observe.py`):
- FR-038: Telegram `/status` → `get_status_snapshot()` + `format_telegram_status()`
- FR-039: Telegram `/status resources` → `get_resource_snapshot()` + `format_telegram_resources()`
- FR-040: Telegram `/health` → `run_health_checks()` + `format_telegram_health()`
- FR-041: HTTP Endpoints → `http_server.py` routes (GET /status, /health, /metrics)
- FR-042: HTTP Status Page → `http_server.py` route (GET /) + static HTML template
- FR-043: Runtime Status Snapshot → `snapshot_collector.py` background task

---

### Implementation Specification

#### Module Structure

```
src/sohnbot/capabilities/observe.py     # Observability capability (FR-038 to FR-043)
  ├─ get_status_snapshot()              # FR-038: Telegram /status
  ├─ get_resource_snapshot()            # FR-039: Telegram /status resources
  ├─ run_health_checks()                # FR-040: Telegram /health
  ├─ HealthCheck dataclass              # Health check result model
  └─ StatusSnapshot dataclass           # Runtime status model

src/sohnbot/observability/              # Observability subsystem (new)
  ├─ __init__.py
  ├─ snapshot_collector.py              # FR-043: Background snapshot updater
  ├─ http_server.py                     # FR-041/042: Local HTTP server
  ├─ health_checks.py                   # FR-040: Health check implementations
  ├─ metrics.py                         # Metric collection helpers
  └─ templates/
      └─ status.html                    # FR-042: HTML status page template
```

#### Runtime Status Snapshot Model

```python
# src/sohnbot/capabilities/observe.py

from dataclasses import dataclass
from datetime import datetime

@dataclass
class ProcessInfo:
    pid: int
    uptime_seconds: int
    version: str                        # From pyproject.toml or git hash
    supervisor: str | None              # "pm2" | "systemd" | "none"
    supervisor_status: str | None       # pm2 status if available
    restart_count: int | None

@dataclass
class BrokerActivity:
    last_operation_timestamp: int      # Unix epoch
    in_flight_operations: list[dict]   # [{operation_id, tool, tier, elapsed_s}]
    last_10_results: dict               # {"ok": 8, "error": 1, "timeout": 1}

@dataclass
class SchedulerState:
    last_tick_timestamp: int            # Unix epoch
    last_tick_local: str                # ISO format in local TZ
    next_jobs: list[dict]               # [{job_name, next_run_utc, next_run_local}]
    active_jobs_count: int

@dataclass
class NotifierState:
    last_attempt_timestamp: int         # Unix epoch
    pending_count: int
    oldest_pending_age_seconds: int | None

@dataclass
class ResourceUsage:
    cpu_percent: float                  # Instant CPU %
    cpu_1m_avg: float | None            # 1-min average if available
    ram_mb: int                         # RSS in MB
    db_size_mb: float
    log_size_mb: float
    snapshot_count: int                 # Total git snapshot branches
    event_loop_lag_ms: float | None     # Event loop lag estimate

@dataclass
class HealthCheckResult:
    name: str                           # "sqlite_writable", "scheduler_lag", etc.
    status: str                         # "pass" | "fail" | "warn"
    message: str
    timestamp: int                      # Unix epoch
    details: dict | None                # Additional context

@dataclass
class StatusSnapshot:
    timestamp: int                      # Snapshot creation time (UTC epoch)
    process: ProcessInfo
    broker: BrokerActivity
    scheduler: SchedulerState
    notifier: NotifierState
    resources: ResourceUsage
    health: list[HealthCheckResult]
    recent_operations: list[dict]       # Last 100 operations (trimmed)
```

#### Snapshot Collector (Background Task)

```python
# src/sohnbot/observability/snapshot_collector.py

import asyncio
from datetime import datetime, timezone
import psutil

async def snapshot_collector_loop(interval_seconds: int = 30):
    """
    Background task that collects runtime status snapshot every N seconds.
    Non-blocking, independent failure domain.
    """
    while True:
        try:
            snapshot = await collect_snapshot()

            # Update in-memory cache (global or injected dependency)
            update_snapshot_cache(snapshot)

            # Optionally persist to SQLite
            if config.get("observability.persist_snapshots"):
                persist_snapshot(snapshot)

            logger.debug(
                "Snapshot collected",
                timestamp=snapshot.timestamp,
                in_flight_ops=len(snapshot.broker.in_flight_operations)
            )

        except Exception as e:
            logger.error(
                "Snapshot collection failed",
                error=str(e),
                exc_info=True
            )

        await asyncio.sleep(interval_seconds)

async def collect_snapshot() -> StatusSnapshot:
    """
    Collect current runtime status from all subsystems.
    Non-blocking, read-only queries.
    """
    return StatusSnapshot(
        timestamp=int(datetime.now(timezone.utc).timestamp()),
        process=collect_process_info(),
        broker=collect_broker_activity(),
        scheduler=collect_scheduler_state(),
        notifier=collect_notifier_state(),
        resources=collect_resource_usage(),
        health=run_all_health_checks(),
        recent_operations=query_recent_operations(limit=100)
    )

def collect_process_info() -> ProcessInfo:
    """Collect process and supervisor information."""
    import os
    process = psutil.Process(os.getpid())

    # Attempt to detect supervisor
    supervisor, supervisor_status, restart_count = detect_supervisor()

    return ProcessInfo(
        pid=os.getpid(),
        uptime_seconds=int(time.time() - process.create_time()),
        version=get_version(),  # From pyproject.toml or git
        supervisor=supervisor,
        supervisor_status=supervisor_status,
        restart_count=restart_count
    )

def collect_broker_activity() -> BrokerActivity:
    """Query broker for current activity (read-only)."""
    # Query execution_log for in-flight operations
    conn = get_connection()
    in_flight = conn.execute("""
        SELECT operation_id, capability, action, tier,
               (unixepoch() - timestamp) as elapsed_seconds
        FROM execution_log
        WHERE status = 'in_progress'
        ORDER BY timestamp DESC
        LIMIT 20
    """).fetchall()

    # Query last 10 operation results
    last_10 = conn.execute("""
        SELECT status, COUNT(*) as count
        FROM (
            SELECT status FROM execution_log
            WHERE status != 'in_progress'
            ORDER BY timestamp DESC
            LIMIT 10
        )
        GROUP BY status
    """).fetchall()

    last_operation_ts = conn.execute("""
        SELECT MAX(timestamp) FROM execution_log
    """).fetchone()[0] or 0

    return BrokerActivity(
        last_operation_timestamp=last_operation_ts,
        in_flight_operations=[
            {
                "operation_id": row[0],
                "tool": f"{row[1]}__{row[2]}",
                "tier": row[3],
                "elapsed_s": row[4]
            }
            for row in in_flight
        ],
        last_10_results=dict(last_10)
    )

def collect_scheduler_state() -> SchedulerState:
    """Query scheduler for current state (read-only)."""
    conn = get_connection()

    # Get last tick timestamp (from heartbeat or scheduler state table)
    last_tick = get_last_scheduler_tick()  # Implementation-specific

    # Get next scheduled jobs
    next_jobs = conn.execute("""
        SELECT name, last_completed_slot
        FROM jobs
        WHERE enabled = 1
        ORDER BY last_completed_slot ASC
        LIMIT 5
    """).fetchall()

    # Get active jobs count (jobs currently running)
    active_jobs_count = len(get_active_scheduler_jobs())  # From scheduler state

    return SchedulerState(
        last_tick_timestamp=last_tick,
        last_tick_local=format_local_time(last_tick),
        next_jobs=[
            {
                "job_name": row[0],
                "next_run_utc": row[1],  # Computed from cron
                "next_run_local": format_local_time(row[1])
            }
            for row in next_jobs
        ],
        active_jobs_count=active_jobs_count
    )

def collect_notifier_state() -> NotifierState:
    """Query notification outbox for current state (read-only)."""
    conn = get_connection()

    pending_count = conn.execute("""
        SELECT COUNT(*) FROM notification_outbox WHERE status = 'pending'
    """).fetchone()[0]

    oldest_pending = conn.execute("""
        SELECT MIN(created_at) FROM notification_outbox WHERE status = 'pending'
    """).fetchone()[0]

    last_attempt = conn.execute("""
        SELECT MAX(created_at) FROM notification_outbox
    """).fetchone()[0] or 0

    oldest_age = None
    if oldest_pending:
        oldest_age = int(time.time()) - oldest_pending

    return NotifierState(
        last_attempt_timestamp=last_attempt,
        pending_count=pending_count,
        oldest_pending_age_seconds=oldest_age
    )

def collect_resource_usage() -> ResourceUsage:
    """Collect process resource usage (non-blocking)."""
    import os
    process = psutil.Process(os.getpid())

    # Database size
    db_path = config.get("database.path")
    db_size = os.path.getsize(db_path) / (1024 * 1024) if os.path.exists(db_path) else 0

    # Log directory size
    log_dir = "logs"
    log_size = sum(
        os.path.getsize(os.path.join(log_dir, f))
        for f in os.listdir(log_dir)
        if os.path.isfile(os.path.join(log_dir, f))
    ) / (1024 * 1024) if os.path.exists(log_dir) else 0

    # Snapshot count (count git branches matching snapshot/*)
    snapshot_count = count_git_snapshots()

    # Event loop lag (measure time between scheduled callbacks)
    event_loop_lag = measure_event_loop_lag()  # Simple estimate

    return ResourceUsage(
        cpu_percent=process.cpu_percent(interval=0.1),
        cpu_1m_avg=None,  # Requires tracking over time
        ram_mb=int(process.memory_info().rss / (1024 * 1024)),
        db_size_mb=db_size,
        log_size_mb=log_size,
        snapshot_count=snapshot_count,
        event_loop_lag_ms=event_loop_lag
    )
```

#### Health Checks

```python
# src/sohnbot/observability/health_checks.py

def run_all_health_checks() -> list[HealthCheckResult]:
    """
    Run all health checks and return results.
    Each check is independent and non-blocking.
    """
    checks = [
        check_sqlite_writable(),
        check_scheduler_lag(),
        check_job_timeouts(),
        check_notifier_alive(),
        check_outbox_stuck(),
        check_disk_usage()  # Optional
    ]
    return checks

def check_sqlite_writable() -> HealthCheckResult:
    """Verify SQLite is writable and WAL enabled."""
    try:
        conn = get_connection()

        # Test write + rollback
        conn.execute("BEGIN")
        conn.execute("UPDATE config SET value = value WHERE key = '__test__'")
        conn.execute("ROLLBACK")

        # Verify WAL mode
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

        if journal_mode.upper() != "WAL":
            return HealthCheckResult(
                name="sqlite_writable",
                status="warn",
                message=f"SQLite writable but not in WAL mode (current: {journal_mode})",
                timestamp=int(time.time()),
                details={"journal_mode": journal_mode}
            )

        return HealthCheckResult(
            name="sqlite_writable",
            status="pass",
            message="SQLite writable and WAL enabled",
            timestamp=int(time.time()),
            details=None
        )

    except Exception as e:
        return HealthCheckResult(
            name="sqlite_writable",
            status="fail",
            message=f"SQLite write test failed: {str(e)}",
            timestamp=int(time.time()),
            details={"error": str(e)}
        )

def check_scheduler_lag() -> HealthCheckResult:
    """Check if scheduler is running and not lagging."""
    last_tick = get_last_scheduler_tick()
    now = int(time.time())
    lag_seconds = now - last_tick

    threshold = config.get("observability.scheduler_lag_threshold", 300)  # 5 min default

    if lag_seconds > threshold:
        return HealthCheckResult(
            name="scheduler_lag",
            status="fail",
            message=f"Scheduler lag {lag_seconds}s exceeds threshold {threshold}s",
            timestamp=now,
            details={"lag_seconds": lag_seconds, "threshold": threshold}
        )
    elif lag_seconds > threshold * 0.5:
        return HealthCheckResult(
            name="scheduler_lag",
            status="warn",
            message=f"Scheduler lag {lag_seconds}s approaching threshold {threshold}s",
            timestamp=now,
            details={"lag_seconds": lag_seconds, "threshold": threshold}
        )
    else:
        return HealthCheckResult(
            name="scheduler_lag",
            status="pass",
            message=f"Scheduler healthy (lag: {lag_seconds}s)",
            timestamp=now,
            details=None
        )

def check_job_timeouts() -> HealthCheckResult:
    """Check if any jobs are exceeding timeout."""
    conn = get_connection()

    # Query in-flight operations older than 10 minutes (job timeout)
    timeout_threshold = config.get("timeouts.job_timeout", 600)

    timed_out_jobs = conn.execute("""
        SELECT operation_id, capability, action,
               (unixepoch() - timestamp) as elapsed_seconds
        FROM execution_log
        WHERE status = 'in_progress'
          AND capability = 'sched'
          AND (unixepoch() - timestamp) > ?
    """, (timeout_threshold,)).fetchall()

    if timed_out_jobs:
        return HealthCheckResult(
            name="job_timeouts",
            status="fail",
            message=f"{len(timed_out_jobs)} job(s) exceeding timeout {timeout_threshold}s",
            timestamp=int(time.time()),
            details={"timed_out_count": len(timed_out_jobs)}
        )
    else:
        return HealthCheckResult(
            name="job_timeouts",
            status="pass",
            message="No jobs exceeding timeout",
            timestamp=int(time.time()),
            details=None
        )

def check_notifier_alive() -> HealthCheckResult:
    """Check if notifier worker is making progress."""
    last_attempt = get_last_notification_attempt()  # From NotifierState
    now = int(time.time())
    lag = now - last_attempt

    threshold = config.get("observability.notifier_lag_threshold", 120)  # 2 min

    if lag > threshold:
        return HealthCheckResult(
            name="notifier_alive",
            status="fail",
            message=f"Notifier last attempt {lag}s ago (threshold: {threshold}s)",
            timestamp=now,
            details={"lag_seconds": lag, "threshold": threshold}
        )
    else:
        return HealthCheckResult(
            name="notifier_alive",
            status="pass",
            message="Notifier active",
            timestamp=now,
            details=None
        )

def check_outbox_stuck() -> HealthCheckResult:
    """Check if notification outbox has stuck messages."""
    oldest_pending_age = get_oldest_pending_notification_age()  # From NotifierState

    if oldest_pending_age is None:
        return HealthCheckResult(
            name="outbox_stuck",
            status="pass",
            message="Outbox empty",
            timestamp=int(time.time()),
            details=None
        )

    threshold = config.get("observability.outbox_stuck_threshold", 3600)  # 1 hour

    if oldest_pending_age > threshold:
        return HealthCheckResult(
            name="outbox_stuck",
            status="warn",
            message=f"Oldest pending notification age {oldest_pending_age}s (threshold: {threshold}s)",
            timestamp=int(time.time()),
            details={"oldest_age_seconds": oldest_pending_age, "threshold": threshold}
        )
    else:
        return HealthCheckResult(
            name="outbox_stuck",
            status="pass",
            message=f"Outbox healthy (oldest: {oldest_pending_age}s)",
            timestamp=int(time.time()),
            details=None
        )

def check_disk_usage() -> HealthCheckResult:
    """Optional: Check if disk usage exceeds configured cap."""
    if not config.get("observability.disk_cap_enabled", False):
        return HealthCheckResult(
            name="disk_usage",
            status="pass",
            message="Disk cap check disabled",
            timestamp=int(time.time()),
            details=None
        )

    # Check DB + logs size against cap
    resources = collect_resource_usage()
    total_mb = resources.db_size_mb + resources.log_size_mb
    cap_mb = config.get("observability.disk_cap_mb", 1000)

    if total_mb > cap_mb:
        return HealthCheckResult(
            name="disk_usage",
            status="warn",
            message=f"Disk usage {total_mb:.1f}MB exceeds cap {cap_mb}MB",
            timestamp=int(time.time()),
            details={"total_mb": total_mb, "cap_mb": cap_mb}
        )
    else:
        return HealthCheckResult(
            name="disk_usage",
            status="pass",
            message=f"Disk usage {total_mb:.1f}MB within cap {cap_mb}MB",
            timestamp=int(time.time()),
            details=None
        )
```

#### Local HTTP Server

```python
# src/sohnbot/observability/http_server.py

from aiohttp import web
import json

async def start_http_server(host: str = "127.0.0.1", port: int = 8080):
    """
    Start local HTTP server for observability (localhost-only).
    Runs in background, non-blocking.
    """
    app = web.Application()

    # Read-only routes
    app.router.add_get("/status", handle_status)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/metrics", handle_metrics)
    app.router.add_get("/", handle_ui)
    app.router.add_get("/ui", handle_ui)

    # Static files for UI (if needed)
    # app.router.add_static("/static", "src/sohnbot/observability/static")

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host, port)
    await site.start()

    logger.info(
        "HTTP observability server started",
        host=host,
        port=port,
        routes=["/status", "/health", "/metrics", "/", "/ui"]
    )

async def handle_status(request):
    """GET /status - Return status snapshot as JSON."""
    snapshot = get_current_snapshot()  # From in-memory cache

    return web.json_response({
        "timestamp": snapshot.timestamp,
        "process": {
            "pid": snapshot.process.pid,
            "uptime_seconds": snapshot.process.uptime_seconds,
            "version": snapshot.process.version,
            "supervisor": snapshot.process.supervisor,
            "restart_count": snapshot.process.restart_count
        },
        "broker": {
            "last_operation_timestamp": snapshot.broker.last_operation_timestamp,
            "in_flight_operations": snapshot.broker.in_flight_operations,
            "last_10_results": snapshot.broker.last_10_results
        },
        "scheduler": {
            "last_tick_timestamp": snapshot.scheduler.last_tick_timestamp,
            "last_tick_local": snapshot.scheduler.last_tick_local,
            "next_jobs": snapshot.scheduler.next_jobs,
            "active_jobs_count": snapshot.scheduler.active_jobs_count
        },
        "notifier": {
            "last_attempt_timestamp": snapshot.notifier.last_attempt_timestamp,
            "pending_count": snapshot.notifier.pending_count,
            "oldest_pending_age_seconds": snapshot.notifier.oldest_pending_age_seconds
        },
        "resources": {
            "cpu_percent": snapshot.resources.cpu_percent,
            "ram_mb": snapshot.resources.ram_mb,
            "db_size_mb": snapshot.resources.db_size_mb,
            "log_size_mb": snapshot.resources.log_size_mb,
            "snapshot_count": snapshot.resources.snapshot_count,
            "event_loop_lag_ms": snapshot.resources.event_loop_lag_ms
        }
    })

async def handle_health(request):
    """GET /health - Return health check results as JSON."""
    snapshot = get_current_snapshot()

    # Determine overall health
    statuses = [check.status for check in snapshot.health]
    if "fail" in statuses:
        overall = "unhealthy"
    elif "warn" in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    return web.json_response({
        "status": overall,
        "checks": [
            {
                "name": check.name,
                "status": check.status,
                "message": check.message,
                "timestamp": check.timestamp,
                "details": check.details
            }
            for check in snapshot.health
        ]
    })

async def handle_metrics(request):
    """GET /metrics - Return minimal metrics as JSON (NOT Prometheus format)."""
    snapshot = get_current_snapshot()

    # Query operation counts from DB
    conn = get_connection()
    operation_counts = conn.execute("""
        SELECT status, COUNT(*) as count
        FROM execution_log
        GROUP BY status
    """).fetchall()

    scheduler_stats = conn.execute("""
        SELECT COUNT(*) as total FROM jobs WHERE enabled = 1
    """).fetchone()

    return web.json_response({
        "uptime_seconds": snapshot.process.uptime_seconds,
        "operations_total": sum(dict(operation_counts).values()),
        "operations_ok": dict(operation_counts).get("ok", 0),
        "operations_error": dict(operation_counts).get("error", 0),
        "operations_timeout": dict(operation_counts).get("timeout", 0),
        "operations_denied": dict(operation_counts).get("denied", 0),
        "scheduler_enabled_jobs": scheduler_stats[0] if scheduler_stats else 0,
        "notification_outbox_pending": snapshot.notifier.pending_count,
        "cpu_percent": snapshot.resources.cpu_percent,
        "ram_mb": snapshot.resources.ram_mb,
        "db_size_mb": snapshot.resources.db_size_mb
    })

async def handle_ui(request):
    """GET / or /ui - Return HTML status page."""
    snapshot = get_current_snapshot()

    # Determine health indicator
    health_statuses = [check.status for check in snapshot.health]
    if "fail" in health_statuses:
        health_badge = "❌ Unhealthy"
        health_class = "unhealthy"
    elif "warn" in health_statuses:
        health_badge = "⚠️ Degraded"
        health_class = "degraded"
    else:
        health_badge = "✅ Healthy"
        health_class = "healthy"

    # Render HTML (simple template)
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>SohnBot Status</title>
        <meta http-equiv="refresh" content="30">
        <style>
            body {{ font-family: monospace; margin: 20px; background: #1e1e1e; color: #d4d4d4; }}
            .header {{ margin-bottom: 20px; }}
            .health.healthy {{ color: #4ec9b0; }}
            .health.degraded {{ color: #ce9178; }}
            .health.unhealthy {{ color: #f48771; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
            th, td {{ border: 1px solid #3e3e3e; padding: 8px; text-align: left; }}
            th {{ background-color: #252526; }}
            .section {{ margin-top: 30px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>SohnBot Status</h1>
            <div class="health {health_class}"><strong>{health_badge}</strong></div>
            <p>Uptime: {snapshot.process.uptime_seconds}s | Version: {snapshot.process.version} | PID: {snapshot.process.pid}</p>
        </div>

        <div class="section">
            <h2>Active Operations</h2>
            <table>
                <tr><th>Operation ID</th><th>Tool</th><th>Tier</th><th>Elapsed</th></tr>
                {"".join(f"<tr><td>{op['operation_id'][:8]}</td><td>{op['tool']}</td><td>{op['tier']}</td><td>{op['elapsed_s']}s</td></tr>" for op in snapshot.broker.in_flight_operations) or "<tr><td colspan='4'>No active operations</td></tr>"}
            </table>
        </div>

        <div class="section">
            <h2>Scheduler Next Runs</h2>
            <table>
                <tr><th>Job</th><th>Next Run (Local)</th></tr>
                {"".join(f"<tr><td>{job['job_name']}</td><td>{job['next_run_local']}</td></tr>" for job in snapshot.scheduler.next_jobs[:5]) or "<tr><td colspan='2'>No scheduled jobs</td></tr>"}
            </table>
        </div>

        <div class="section">
            <h2>Resources</h2>
            <p>CPU: {snapshot.resources.cpu_percent:.1f}% | RAM: {snapshot.resources.ram_mb} MB</p>
            <p>DB: {snapshot.resources.db_size_mb:.1f} MB | Logs: {snapshot.resources.log_size_mb:.1f} MB</p>
            <p>Snapshots: {snapshot.resources.snapshot_count} | Loop lag: {snapshot.resources.event_loop_lag_ms or 'N/A'} ms</p>
        </div>

        <div class="section">
            <h2>Latest Errors</h2>
            <table>
                <tr><th>Operation ID</th><th>Tool</th><th>Error</th><th>Timestamp</th></tr>
                {"".join(f"<tr><td>{op['operation_id'][:8]}</td><td>{op['tool']}</td><td>{op['error_message'][:50]}</td><td>{op['timestamp']}</td></tr>" for op in [o for o in snapshot.recent_operations if o['status'] == 'error'][:10]) or "<tr><td colspan='4'>No recent errors</td></tr>"}
            </table>
        </div>

        <div class="section">
            <p><em>Auto-refreshes every 30 seconds</em></p>
        </div>
    </body>
    </html>
    """

    return web.Response(text=html, content_type="text/html")
```

#### Telegram Commands Integration

```python
# src/sohnbot/gateway/commands.py (additions)

async def handle_status(chat_id: str, args: list[str] = None):
    """Handle /status [resources] command."""
    if args and args[0] == "resources":
        # FR-039: /status resources
        snapshot = get_current_snapshot()

        message = f"""📊 **Resource Usage**

**CPU:** {snapshot.resources.cpu_percent:.1f}%
**RAM:** {snapshot.resources.ram_mb} MB
**Database:** {snapshot.resources.db_size_mb:.1f} MB
**Logs:** {snapshot.resources.log_size_mb:.1f} MB
**Snapshots:** {snapshot.resources.snapshot_count}
**Event Loop Lag:** {snapshot.resources.event_loop_lag_ms or 'N/A'} ms
"""
    else:
        # FR-038: /status (default)
        snapshot = get_current_snapshot()

        uptime_str = format_uptime(snapshot.process.uptime_seconds)
        last_tick_ago = format_time_ago(snapshot.scheduler.last_tick_timestamp)
        last_broker_ago = format_time_ago(snapshot.broker.last_operation_timestamp)

        message = f"""⚙️ **System Status**

**Uptime:** {uptime_str}
**Version:** {snapshot.process.version}
**Supervisor:** {snapshot.process.supervisor or 'none'} (PID: {snapshot.process.pid})

**Last scheduler tick:** {last_tick_ago}
**Last broker activity:** {last_broker_ago}

**In-flight operations:** {len(snapshot.broker.in_flight_operations)}
{"".join(f"  - {op['tool']} (Tier {op['tier']}, {op['elapsed_s']}s)" for op in snapshot.broker.in_flight_operations[:5])}

**Notification outbox:** {snapshot.notifier.pending_count} pending

**Last 10 operations:**
{"  - ".join(f"{status}: {count}" for status, count in snapshot.broker.last_10_results.items())}
"""

    await telegram_client.send_message(chat_id, message)

async def handle_health(chat_id: str):
    """Handle /health command."""
    snapshot = get_current_snapshot()

    # Determine overall health
    statuses = [check.status for check in snapshot.health]
    if "fail" in statuses:
        indicator = "❌ Unhealthy"
    elif "warn" in statuses:
        indicator = "⚠️ Degraded"
    else:
        indicator = "✅ Healthy"

    # Get top issues (failures + warnings)
    issues = [
        check for check in snapshot.health
        if check.status in ("fail", "warn")
    ]

    if not issues:
        message = f"""{indicator}

All systems operational.
"""
    else:
        message = f"""{indicator}

{"".join(f"- {check.message}" for check in issues)}
"""

    await telegram_client.send_message(chat_id, message)
```

---

### Configuration Keys

Add to `config/registry.py`:

```python
# Observability configuration
"observability.http_enabled": ConfigKey(
    tier="dynamic",
    value_type="bool",
    default=True,
    restart_required=False
),
"observability.http_port": ConfigKey(
    tier="static",  # Binding requires restart
    value_type="int",
    default=8080,
    min_value=1024,
    max_value=65535,
    restart_required=True
),
"observability.http_host": ConfigKey(
    tier="static",  # MUST be localhost, not configurable via NL
    value_type="str",
    default="127.0.0.1",
    restart_required=True,
    validator=lambda v: v in ("127.0.0.1", "::1")  # Localhost only
),
"observability.refresh_seconds": ConfigKey(
    tier="dynamic",
    value_type="int",
    default=30,
    min_value=10,
    max_value=300
),
"observability.collection_interval_seconds": ConfigKey(
    tier="dynamic",
    value_type="int",
    default=30,
    min_value=10,
    max_value=300
),
"observability.persist_snapshots": ConfigKey(
    tier="dynamic",
    value_type="bool",
    default=False  # In-memory only by default
),
"observability.scheduler_lag_threshold": ConfigKey(
    tier="dynamic",
    value_type="int",
    default=300,  # 5 minutes
    min_value=60,
    max_value=3600
),
"observability.notifier_lag_threshold": ConfigKey(
    tier="dynamic",
    value_type="int",
    default=120,  # 2 minutes
    min_value=30,
    max_value=600
),
"observability.outbox_stuck_threshold": ConfigKey(
    tier="dynamic",
    value_type="int",
    default=3600,  # 1 hour
    min_value=300,
    max_value=86400
),
"observability.disk_cap_enabled": ConfigKey(
    tier="dynamic",
    value_type="bool",
    default=False
),
"observability.disk_cap_mb": ConfigKey(
    tier="dynamic",
    value_type="int",
    default=1000,  # 1 GB
    min_value=100,
    max_value=100000
)
```

---

### Security Notes

**Localhost-Only Binding (Critical):**
- HTTP server MUST bind to `127.0.0.1` (and `::1`) only by default
- `observability.http_host` is a **static** config key (requires restart)
- Validator enforces localhost values only: `lambda v: v in ("127.0.0.1", "::1")`
- Changing binding to `0.0.0.0` or public IPs requires **explicit manual config edit** (not via natural language or `/config set`)
- **Rationale:** Prevents accidental exposure of observability endpoints to network

**Read-Only Enforcement:**
- All HTTP routes are GET only (no POST, PUT, DELETE, PATCH)
- No control actions exposed (no `/restart`, `/stop`, `/execute`, etc.)
- Observability module has **no write access** to broker, scheduler, or configuration
- Snapshot collection is read-only queries against SQLite and process state

**No Authentication (Localhost Assumption):**
- Phase 1: No authentication required if binding is localhost-only
- Future: If binding ever widened beyond localhost, MUST add authentication (token-based or basic auth)
- **Explicitly out of scope for Phase 1**

---

### Testing

**Unit Tests:**
- `tests/unit/test_observability_snapshot.py` - Snapshot collection
- `tests/unit/test_observability_health.py` - Health check logic
- `tests/unit/test_observability_http.py` - HTTP route handlers (mock aiohttp)

**Integration Tests:**
- `tests/integration/test_observability_telegram.py` - `/status`, `/health` commands end-to-end
- `tests/integration/test_observability_http_server.py` - Start HTTP server, query endpoints, verify localhost binding

**Smoke Tests:**
- Start SohnBot, verify HTTP server binds to localhost:8080
- Query `/status`, `/health`, `/metrics`, `/ui` via curl
- Verify Telegram `/status` and `/health` commands return valid data

---

### Implementation Priority

**Story Order:**
1. **Snapshot Collector** (FR-043) - Foundation for all observability
2. **Health Checks** (FR-040) - Critical for autonomous operation monitoring
3. **Telegram Commands** (FR-038, FR-039, FR-040) - Primary UX
4. **HTTP Server** (FR-041, FR-042) - Secondary UX

**Dependencies:**
- Requires `aiohttp` (HTTP server)
- Requires `psutil` (process resource monitoring)
- Requires broker, scheduler, notifier to expose state for snapshot collection


---

## Model & Runtime Controls

This section defines SohnBot's model selection and runtime control policies, strictly aligned with the **Claude Agent SDK for Python** (not Messages API).

**Reference:** `docs/Resources/Agent SDK Reference.md`

**CRITICAL:** This project uses the Claude Agent SDK. We do NOT use the Messages API `effort` parameter. All runtime controls must use SDK-supported fields from `ClaudeAgentOptions`.

---

### Model Routing Policy

SohnBot defines three explicit model profiles for different execution contexts:

| Profile             | Model                | Use Case                                  |
| ------------------- | -------------------- | ----------------------------------------- |
| `telegram_default`  | `claude-haiku-*`     | Telegram conversations (low-latency)      |
| `dev_default`       | `claude-sonnet-*`    | Development / local execution (balanced)  |
| `plan_default`      | `claude-opus-*`      | Planning mode (high-reasoning)            |

**Routing Rules:**
- Telegram conversations default to `telegram_default` model
- Development/local execution defaults to `dev_default` model
- `/plan` command escalates to `plan_default` model
- **Natural language CANNOT change models** (governed operator principle)
- Only explicit commands (e.g., `/model set sonnet`) may change model profile
- Fallback model configured via `fallback_model` in `ClaudeAgentOptions`

**Implementation:**
```python
# runtime/agent_session.py

def get_model_for_context(context: str) -> str:
    """Return model based on execution context."""
    profiles = {
        "telegram": config.get("models.telegram_default"),
        "dev": config.get("models.dev_default"),
        "plan": config.get("models.plan_default")
    }
    return profiles.get(context, profiles["dev"])

options = ClaudeAgentOptions(
    model=get_model_for_context(current_context),
    fallback_model=config.get("models.fallback_model"),
    # ... other options
)
```

---

### Permission Mode Policy

SohnBot uses `permission_mode` to control execution behavior in different contexts.

**Supported Permission Modes** (from Agent SDK):
- `"default"` - Standard permission behavior
- `"acceptEdits"` - Auto-accept file edits (use with caution)
- `"plan"` - Planning mode, no execution (read-only exploration)
- `"bypassPermissions"` - Bypass all permission checks (NOT USED in SohnBot)

**Permission Mode Mapping:**

| Context               | Permission Mode | Execution Allowed | Rationale                                |
| --------------------- | --------------- | ----------------- | ---------------------------------------- |
| Telegram (normal)     | `"default"`     | ✅ Yes            | Standard governed operator execution     |
| `/plan` command       | `"plan"`        | ❌ No             | Read-only exploration, no modifications  |
| Development (local)   | `"default"`     | ✅ Yes            | Standard execution with broker oversight |

**Policy:**
- `/plan` command sets `permission_mode="plan"` to prevent execution and produce plan-only responses
- Normal Telegram interactions use `permission_mode="default"`
- Execution escalation must be **explicit** (command-based), not triggered via natural language
- `"bypassPermissions"` mode is **prohibited** (bypasses broker layer, violates governed operator architecture)

**Implementation:**
```python
# gateway/commands.py

async def handle_plan_command(chat_id: str, prompt: str):
    """Execute /plan command with planning mode."""
    options = ClaudeAgentOptions(
        model=config.get("models.plan_default"),  # Opus for planning
        permission_mode="plan",  # No execution, plan only
        max_thinking_tokens=config.get("models.runtime.plan_max_thinking_tokens"),
        max_turns=config.get("models.runtime.plan_max_turns"),
    )

    async for message in query(prompt, options=options):
        # Stream plan-only response (no execution)
        yield message
```

---

### Thinking & Token Controls

Since the Agent SDK does not expose `output_config.effort` (Messages API only), SohnBot controls reasoning behavior using SDK-supported runtime controls:

**Supported Controls** (from `ClaudeAgentOptions`):
- `max_thinking_tokens` (int | None) - Maximum tokens for thinking blocks
- `max_turns` (int | None) - Maximum conversation turns
- `max_budget_usd` (float | None) - Maximum budget in USD for the session

**Profile-Specific Controls:**

| Profile     | `max_thinking_tokens` | `max_turns` | `max_budget_usd` | Rationale                                 |
| ----------- | --------------------- | ----------- | ---------------- | ----------------------------------------- |
| Telegram    | 4000                  | 10          | None             | Fast responses, cost control              |
| Dev         | 8000                  | 25          | None             | Balanced reasoning, moderate complexity   |
| Plan (Opus) | 16000                 | 50          | 5.00             | Deep reasoning, budget cap for safety     |

**Configuration:**
```toml
[models.runtime]
telegram_max_thinking_tokens = 4000
dev_max_thinking_tokens = 8000
plan_max_thinking_tokens = 16000
telegram_max_turns = 10
dev_max_turns = 25
plan_max_turns = 50
plan_max_budget_usd = 5.00  # Optional safety cap for Opus planning
```

**Implementation:**
```python
# runtime/agent_session.py

def get_runtime_controls(context: str) -> dict:
    """Return runtime control parameters for context."""
    return {
        "max_thinking_tokens": config.get(f"models.runtime.{context}_max_thinking_tokens"),
        "max_turns": config.get(f"models.runtime.{context}_max_turns"),
        "max_budget_usd": config.get(f"models.runtime.{context}_max_budget_usd"),
    }

options = ClaudeAgentOptions(
    model=get_model_for_context(context),
    **get_runtime_controls(context)
)
```

**Note:** Do NOT introduce unsupported parameters like `effort`, `temperature`, or `top_p`. All runtime control must use fields defined in `ClaudeAgentOptions` per Agent SDK documentation.

---

### Tool Governance Invariants

**CRITICAL:** Model choice and runtime controls MUST NOT affect broker enforcement.

Model selection affects **quality, latency, and cost only**. The following remain **invariant** across all models:

| Architectural Boundary          | Enforcement Layer | Invariant Across Models |
| ------------------------------- | ----------------- | ----------------------- |
| **Broker enforcement**          | Broker Layer      | ✅ Always enforced      |
| **Scope validation**            | Broker Layer      | ✅ Always enforced      |
| **Tier classification**         | Broker Layer      | ✅ Always enforced      |
| **Logging (execution_log)**     | Broker Layer      | ✅ Always enforced      |
| **Snapshot creation (Tier 1+)** | Broker Layer      | ✅ Always enforced      |
| **Scheduler behavior**          | Scheduler Module  | ✅ Always enforced      |
| **Notification delivery**       | Notifier Module   | ✅ Always enforced      |

**Why This Matters:**
- Switching from Haiku → Sonnet → Opus does not bypass safety boundaries
- A cheaper model cannot "escape" scope restrictions
- A more capable model cannot skip snapshot creation
- Broker policy enforcement is **architectural, not model-dependent**

**Example:**
```python
# Even if using Opus with permission_mode="plan", broker still logs the operation:
await broker.route_operation(
    capability="files",
    action="read",
    params={"path": "/path/to/file"}
)
# → Broker classifies as Tier 0 (read-only)
# → Broker logs operation start
# → Capability executes (read-only, safe in plan mode)
# → Broker logs operation end
# → No snapshot created (Tier 0)
```

---

### Configuration Integration

Add the following configuration keys to `config/registry.py`:

```python
# Model Selection Configuration
"models.telegram_default": ConfigKey(
    tier="dynamic",
    value_type="str",
    default="claude-haiku-4-5-20251001",
    restart_required=False,
    validator=lambda v: v.startswith("claude-")
),
"models.dev_default": ConfigKey(
    tier="dynamic",
    value_type="str",
    default="claude-sonnet-4-6",
    restart_required=False,
    validator=lambda v: v.startswith("claude-")
),
"models.plan_default": ConfigKey(
    tier="dynamic",
    value_type="str",
    default="claude-opus-4-6",
    restart_required=False,
    validator=lambda v: v.startswith("claude-")
),
"models.fallback_model": ConfigKey(
    tier="dynamic",
    value_type="str",
    default="claude-sonnet-4-6",
    restart_required=False,
    validator=lambda v: v.startswith("claude-")
),

# Runtime Control Configuration
"models.runtime.telegram_max_thinking_tokens": ConfigKey(
    tier="dynamic",
    value_type="int",
    default=4000,
    min_value=1000,
    max_value=32000,
    restart_required=False
),
"models.runtime.dev_max_thinking_tokens": ConfigKey(
    tier="dynamic",
    value_type="int",
    default=8000,
    min_value=1000,
    max_value=32000,
    restart_required=False
),
"models.runtime.plan_max_thinking_tokens": ConfigKey(
    tier="dynamic",
    value_type="int",
    default=16000,
    min_value=1000,
    max_value=32000,
    restart_required=False
),
"models.runtime.telegram_max_turns": ConfigKey(
    tier="dynamic",
    value_type="int",
    default=10,
    min_value=1,
    max_value=100,
    restart_required=False
),
"models.runtime.dev_max_turns": ConfigKey(
    tier="dynamic",
    value_type="int",
    default=25,
    min_value=1,
    max_value=100,
    restart_required=False
),
"models.runtime.plan_max_turns": ConfigKey(
    tier="dynamic",
    value_type="int",
    default=50,
    min_value=1,
    max_value=100,
    restart_required=False
),
"models.runtime.plan_max_budget_usd": ConfigKey(
    tier="dynamic",
    value_type="float",
    default=5.00,
    min_value=0.10,
    max_value=100.00,
    restart_required=False
)
```

**Tier Classification:**
- **All model/runtime keys are DYNAMIC** (can be changed without restart)
- Changing model defaults does not affect static boundaries (broker enforcement, scope validation)
- Hot-reload supported via config event system

**TOML Representation** (`config/default.toml`):
```toml
[models]
telegram_default = "claude-haiku-4-5-20251001"
dev_default = "claude-sonnet-4-6"
plan_default = "claude-opus-4-6"
fallback_model = "claude-sonnet-4-6"

[models.runtime]
telegram_max_thinking_tokens = 4000
dev_max_thinking_tokens = 8000
plan_max_thinking_tokens = 16000
telegram_max_turns = 10
dev_max_turns = 25
plan_max_turns = 50
plan_max_budget_usd = 5.00
```

---

### Design Alignment

**Governed Operator Philosophy:**
- Model routing is **explicit and policy-driven**, not natural-language controllable
- Natural language cannot escalate to more expensive models (prevents cost manipulation)
- `/plan` command explicitly requests planning mode (Opus + no execution)
- Broker layer remains the **single source of truth** for safety enforcement

**No Messages API Dependency:**
- This project uses **Claude Agent SDK for Python**
- We do NOT use Messages API `effort` parameter (not exposed in SDK)
- All runtime controls use SDK-supported fields: `max_thinking_tokens`, `max_turns`, `max_budget_usd`
- Reference: `docs/Resources/Agent SDK Reference.md`

**Cost & Latency Optimization:**
- Telegram → Haiku (fast, cheap, sufficient for most interactions)
- Dev → Sonnet (balanced, general-purpose)
- `/plan` → Opus (deep reasoning, budget-capped)
- Fallback model provides resilience if primary model unavailable

---


---

## Architecture Validation Results

### Coherence Validation ✅

**Decision Compatibility:**

All architectural decisions are fully compatible and work together without conflicts:
- Python 3.13 + SQLite STRICT + Claude Agent SDK + asyncio + structlog integrate seamlessly
- Manual SQL (Decision 1) supports broker logging (Decision 4) and configuration (Decision 5)
- Scheduler boundary-aligned design (Decision 3) uses SQLite persistence (Decision 1)
- Observability read-only architecture integrates with broker/scheduler/notifier state
- Model routing (Model Controls) leverages two-tier configuration system (Decision 5)
- No version conflicts across the technology stack

**Pattern Consistency:**

Implementation patterns fully support architectural decisions:
- snake_case naming enforced everywhere (prevents AI agent drift)
- Validation order (Hook→Broker→Capability→Execute→Log) non-negotiable across all capabilities
- Async/await patterns consistent (TaskGroup, no fire-and-forget)
- MCP tool naming follows strict pattern: `mcp__sohnbot__<module>__<verb>`
- Error handling uniform across all modules (try/except/finally + structlog context)
- Style constitution prevents implementation inconsistencies across AI agents

**Structure Alignment:**

Project structure fully supports the architecture:
- Broker layer centralized in `src/sohnbot/broker/` (architectural heart)
- Capabilities isolated in single-file modules (`src/sohnbot/capabilities/<module>.py`)
- Observability independent failure domain (`src/sohnbot/observability/`)
- Configuration registry centralized (`config/registry.py`)
- Clear data flow: Telegram → Runtime → Broker → Capabilities
- No bypass paths around broker enforcement

### Requirements Coverage Validation ✅

**Functional Requirements Coverage:**

All 43 functional requirements are architecturally supported:

| Capability Area | FRs | Implementation Support |
|----------------|-----|----------------------|
| File Operations | FR-001 to FR-009 | `capabilities/files.py` + broker tier classification |
| Git Operations | FR-010 to FR-014 | `capabilities/git.py` + snapshot branch management |
| Command Profiles | FR-015 to FR-019 | `capabilities/profiles.py` + execution limits |
| Scope & Safety | FR-020 to FR-023 | `broker/scope_validator.py` + audit logging |
| Web Search | FR-024 to FR-026 | `capabilities/web.py` + cache + monitoring |
| Scheduler | FR-027 to FR-031 | `scheduler/` subsystem + jobs table + idempotent slots |
| Communication | FR-032 to FR-037 | `gateway/telegram_client.py` + `notifier/` outbox |
| Observability | FR-038 to FR-043 | `capabilities/observe.py` + `observability/` HTTP server |

**Non-Functional Requirements Coverage:**

All 27 non-functional requirements are addressed:

- **Performance (NFR-001 to NFR-005):** Timeout enforcement, async I/O, scheduler precision
- **Reliability (NFR-006 to NFR-009):** pm2 supervision, WAL mode, CHECK constraints
- **Security (NFR-010 to NFR-014):** Scope validator, path normalization, env secrets, audit log
- **Scalability (NFR-015 to NFR-017):** Multi-repo support, concurrent limits (TaskGroup)
- **Usability (NFR-018 to NFR-020):** Natural language via Claude SDK, Telegram notifications
- **Maintainability (NFR-021 to NFR-023):** Automated cleanup, hot reload, vulnerability management
- **Observability (NFR-024 to NFR-027):** <2% overhead, localhost-only, health checks, isolation

**Cross-Cutting Concerns:**

- ✅ Governed operator philosophy enforced via broker layer (architectural heart)
- ✅ Operation risk classification (Tier 0/1/2/3) implemented in broker
- ✅ Snapshot-first recoverability handled before Tier 1+ operations
- ✅ Model routing explicit and policy-driven (no natural language control)

### Implementation Readiness Validation ✅

**Decision Completeness:**

- All 5 core architectural decisions documented with specific versions
- Observability architecture complete (aiohttp, psutil, localhost-only binding enforced)
- Model controls complete (Claude Agent SDK only, no Messages API `effort` parameter)
- Rationale provided for every major choice
- Implementation code snippets provided for critical patterns

**Structure Completeness:**

- Every file and directory specified in Project Structure section
- All 43 functional requirements mapped to specific implementation files
- Component boundaries clearly defined (broker, capabilities, scheduler, observability, runtime)
- Integration points specified (gateway → runtime → broker → capabilities)
- No ambiguous or undefined structural elements

**Pattern Completeness:**

- Naming conventions comprehensive (snake_case, MCP tool pattern, module structure)
- Validation order non-negotiable (5-step enforcement sequence)
- Async patterns specified (TaskGroup, context managers, no fire-and-forget)
- Error handling patterns defined (try/except/finally + structlog)
- Configuration tier classification (static vs dynamic, restart_required flag)
- AI agent conflict prevention (style constitution, manual SQL, single-file capabilities)

### Gap Analysis Results

**Critical Gaps:** ❌ None identified

**Important Gaps:** ⚠️ None blocking implementation, but consider during development:

1. **Testing Strategy** - Architecture defines structure but not test organization:
   - Suggest: `tests/unit/<module>_test.py` mirroring `src/` structure
   - Suggest: `tests/integration/test_<workflow>.py` for end-to-end scenarios
   - Mocking strategy for Claude SDK, Telegram API, file system to be defined
   - **Not blocking:** Can be defined during implementation

2. **Migration Runner Details** - Decision 1 specifies "minimal migration runner":
   - Suggest: SHA-256 checksums for migration integrity verification
   - Suggest: `000N_<description>.sql` naming convention
   - Migration table tracks applied versions
   - **Not blocking:** Standard migration patterns well-established

3. **Error Recovery Workflows** - Snapshot/rollback defined but not recovery UX:
   - User-facing rollback command (e.g., `/rollback <operation_id>`)
   - Manual rollback only (no automatic triggers)
   - Partial failure handling approach (best-effort completion)
   - **Not blocking:** FR-006 specifies rollback capability, details flexible

**Nice-to-Have Gaps:** ℹ️ Future enhancements (not required for Phase 1):

- Development workflow optimization (hot reload, debug logging, CLI mode)
- Deployment automation (pm2 templates, config seeding, health endpoints)
- Documentation templates (module docstrings, MCP tool docs, config key docs)

**Overall Assessment:** Architecture is **implementation-ready** with no critical or blocking gaps.

### Validation Issues Addressed

**No critical issues found during validation.**

**No important issues found during validation.**

**Minor observations:**
- Observability and Model Controls sections added after initial architecture creation
- Both sections integrate seamlessly and follow all established patterns
- No conflicts or inconsistencies introduced

### Architecture Completeness Checklist

**✅ Requirements Analysis**

- [x] Project context thoroughly analyzed (37→43 FRs, 23→27 NFRs, governed operator philosophy)
- [x] Scale and complexity assessed (Medium-High, 7 subsystems, policy-enforced autonomous execution)
- [x] Technical constraints identified (Python 3.13, SQLite 3.45+, local-first, Windows Phase 1)
- [x] Cross-cutting concerns mapped (broker enforcement, snapshot/rollback, observability, model routing)

**✅ Architectural Decisions**

- [x] 5 critical decisions documented with specific versions (Data, Broker, Scheduler, Logging, Config)
- [x] Technology stack fully specified (Python 3.13, SQLite STRICT, Claude Agent SDK, structlog, asyncio)
- [x] Integration patterns defined (Telegram → Runtime → Broker → Capabilities data flow)
- [x] Performance considerations addressed (timeout enforcement, async I/O, TaskGroup concurrency)
- [x] Observability architecture defined (read-only, localhost HTTP server, Telegram commands, health checks)
- [x] Model routing policy defined (Haiku/Sonnet/Opus profiles, SDK-only controls, permission modes)

**✅ Implementation Patterns**

- [x] Naming conventions established (snake_case everywhere, MCP tool pattern, single-file capabilities)
- [x] Structure patterns defined (broker-centric routing, capability isolation, config registry)
- [x] Communication patterns specified (validation order, async patterns, error handling)
- [x] Process patterns documented (broker routing, snapshot creation, health checks, model selection)

**✅ Project Structure**

- [x] Complete directory structure defined (every file and directory specified with purpose)
- [x] Component boundaries established (broker, capabilities, scheduler, observability, runtime, gateway)
- [x] Integration points mapped (gateway → runtime → broker → capabilities, observability read-only)
- [x] Requirements to structure mapping complete (all 43 FRs mapped to specific implementation files)

### Architecture Readiness Assessment

**Overall Status:** ✅ **READY FOR IMPLEMENTATION**

**Confidence Level:** **HIGH**

Architecture is coherent, complete, and provides comprehensive guidance for consistent AI agent implementation.

**Key Strengths:**

1. **Broker-Centric Enforcement:** All capability execution routes through centralized policy enforcement (architectural invariant)
2. **Governed Operator Philosophy:** Autonomous execution within structural boundaries, recoverability as safety valve
3. **AI Agent Conflict Prevention:** Style constitution, non-negotiable validation order, manual SQL prevent implementation drift
4. **Complete Requirements Coverage:** All 43 FRs and 27 NFRs architecturally supported with specific implementation mappings
5. **Technology Stack Coherence:** Python 3.13 + SQLite STRICT + Claude Agent SDK + asyncio integrate seamlessly
6. **Observability Integration:** Read-only visibility (Telegram + HTTP) with independent failure domain
7. **Model Routing Policy:** Explicit, policy-driven model selection (Haiku/Sonnet/Opus) aligned with SDK capabilities

**Areas for Future Enhancement:**

1. **Testing Automation:** Add CI/CD pipeline with automated test execution (Phase 2)
2. **Multi-Platform Support:** Extend beyond Windows to Linux/macOS (Phase 2)
3. **Advanced Observability:** Optional Prometheus/Grafana integration for power users (Phase 3)
4. **Dry-Run Mode:** FR-023 deferred to future phase (preview without execution)
5. **Rollback UX:** Enhanced rollback command with interactive confirmation (refinement)

### Implementation Handoff

**AI Agent Guidelines:**

1. **Follow architectural decisions exactly as documented** - No deviation from specified versions, patterns, or structure
2. **Use implementation patterns consistently** - snake_case, validation order, async patterns, error handling
3. **Respect broker-centric architecture** - ALL capability execution MUST route through broker layer
4. **Refer to this document for all architectural questions** - Single source of truth for implementation decisions
5. **Validate against style constitution** - Prevent AI agent drift by following non-negotiable rules

**First Implementation Priority:**

1. **Initialize Project Structure:**
   ```bash
   mkdir -p src/sohnbot/{broker,capabilities,scheduler,observability,runtime,gateway,notifier,config}
   mkdir -p config migrations scripts tests/{unit,integration}
   touch src/sohnbot/__init__.py
   ```

2. **Set Up Data Layer** (Decision 1):
   - Create `migrations/0001_initial_schema.sql` with STRICT tables
   - Implement `scripts/migrate.py` (checksum verification)
   - Initialize SQLite with WAL mode

3. **Implement Broker Layer** (Decision 2):
   - `src/sohnbot/broker/router.py` - Central routing + tier classification
   - `src/sohnbot/broker/scope_validator.py` - Path validation + traversal prevention
   - `src/sohnbot/broker/operation_log.py` - Execution logging start/end

4. **Build Core Capabilities:**
   - `src/sohnbot/capabilities/files.py` - File operations (FR-001 to FR-009)
   - `src/sohnbot/capabilities/git.py` - Git operations + snapshot management (FR-010 to FR-014)
   - `src/sohnbot/runtime/agent_session.py` - Claude Agent SDK integration + model routing

5. **Establish Configuration System** (Decision 5):
   - `config/registry.py` - ConfigKey definitions (static/dynamic tier classification)
   - `config/default.toml` - Default configuration values
   - `src/sohnbot/config/manager.py` - Hot reload + event system

**Implementation Phase Sequence:**

- **Phase 1 (Core):** Data layer, broker, files capability, git capability, configuration
- **Phase 2 (Orchestration):** Scheduler, command profiles, web search, notifications
- **Phase 3 (Visibility):** Observability HTTP server, health checks, Telegram commands
- **Phase 4 (Polish):** Model routing refinement, testing automation, deployment scripts

**Reference Documents:**

- Architecture: `_bmad-output/planning-artifacts/architecture.md` (this document)
- Requirements: `docs/PRD.md` (43 FRs, 27 NFRs, user journeys, success criteria)
- Claude SDK: `docs/Resources/Agent SDK Reference.md` (API reference, ClaudeAgentOptions)

---

**Architecture validated and ready for implementation.**

*Generated: 2026-02-25*
*Validation Status: PASSED*
*Next Step: Begin implementation following First Implementation Priority sequence*

