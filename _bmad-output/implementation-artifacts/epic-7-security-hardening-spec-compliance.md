# Epic 7: Security Hardening & Specification Compliance

**Epic Goal:** Address all findings from the security audit (F-01 through F-12) and PRD/architecture adherence audit (A-01 through A-12), hardening SohnBot against concurrency bugs, subprocess leaks, TOCTOU races, and schema defects while closing specification compliance gaps in the Telegram gateway, configuration system, and observability stack.

**Source Documents:**
- `_bmad-output/implementation-artifacts/security-audit-findings-v1.md` (12 findings)
- `_bmad-output/implementation-artifacts/prd-architecture-adherence-audit-v1.md` (12 findings)

---

## Justified Deviations & Deferrals

Before defining stories, the following findings are assessed as **justified**, **superseded by better decisions**, or **consciously deferred**. These do NOT require implementation in Epic 7.

### A-05: Regex Timeout Protection — JUSTIFIED

**Original finding:** No Python-level regex timeout to prevent catastrophic backtracking (spec requires 5s guard).

**Justification:** All user-facing search (FR-003, FR-018) routes through ripgrep via `profile_executor.py`, which has built-in catastrophic backtracking protection and configurable timeouts. Every `re.compile()` call in the codebase uses pre-compiled constant patterns on controlled internal inputs:
- `web.py:31` — `<[^>]+>` (HTML tag stripping, constant pattern)
- `registry.py:26` — `^[a-zA-Z0-9_./-][\w ./_-]*$` (command validation, constant)
- `git_ops.py:225` — `^[a-zA-Z0-9_][a-zA-Z0-9_/-]*$` (branch validation, constant)
- `patch_editor.py:216` — `^@@ -(\d+)...` (hunk header parsing, constant)

No user-supplied string is ever used as a Python regex pattern. The spec's concern is fully addressed by the ripgrep delegation architecture.

**Action:** Document this as an architectural invariant in CLAUDE.md: "User-facing search MUST route through ripgrep; Python `re` module is permitted only for constant internal patterns on controlled inputs."

---

### A-06: Missing Architecture-Specified Files — PARTIALLY JUSTIFIED

Six files specified in the Architecture Decision Document were never created. Assessment per file:

| File | Verdict | Rationale |
|------|---------|-----------|
| `runtime/conversation_manager.py` | **JUSTIFIED** | Claude Agent SDK manages conversation state internally. A wrapper would duplicate SDK functionality with no safety benefit. Architecture was written before SDK integration details were understood. |
| `runtime/context_loader.py` | **JUSTIFIED** | Claude Agent SDK handles CLAUDE.md loading and context injection natively. Wrapping this adds indirection without value. |
| `scripts/seed_config.py` | **JUSTIFIED** | Config seeding is handled by `ConfigManager.__init__()` which loads TOML defaults on first run. A separate script would add a deployment step for zero benefit. |
| `config/pm2.config.js` | **DEFERRED TO PHASE 3** | Phase 1 runs in development mode. pm2 integration is a Phase 3 (deployment polish) deliverable per PRD scope. |
| `src/sohnbot/__main__.py` | **NEEDED** | Standard Python entry point for `python -m sohnbot`. Trivial to add. Included in Story 7.1. |
| `persistence/models.py` | **DEFERRED** | Feeds into F-09 (typed result models). Both are deferred together as a maintainability investment, not a correctness fix. See F-09 deferral below. |

---

### A-07: Progress Updates for Long-Running Operations — DEFERRED

**Original finding:** Architecture Decision 4 specifies 30s progress updates. Not implemented.

**Justification:** Most SohnBot operations complete in <10 seconds. The three operations that *could* exceed 30 seconds are lint (60s timeout), build (300s), and tests (600s) — all routed through `profile_executor.py` which returns subprocess output on completion. Adding progress updates requires intercepting stdout line-by-line, which changes the subprocess I/O model and introduces complexity disproportionate to the benefit for a single-user system.

**When to revisit:** If users report confusion about long-running build/test operations. Can be addressed by combining A-02 (immediate acknowledgment, included in Story 7.5) with a simple "still running..." ping at 30s intervals — added as a follow-up after the acknowledgment infrastructure lands.

---

### A-09: `max_budget_usd` Not Enforced — DEFERRED

**Original finding:** Config registry defines `runtime.plan_max_budget_usd` but it's never passed to `ClaudeAgentOptions`.

**Justification:** The Claude Agent SDK for Python's `ClaudeAgentOptions` may not yet support `max_budget_usd` as a parameter (the SDK is pre-1.0). `max_turns` (default 10 for Telegram) provides an effective indirect ceiling — at ~$0.01-0.05/turn for Haiku, a 10-turn limit caps individual requests at ~$0.50. The config key exists for forward-compatibility.

**When to revisit:** When the Claude Agent SDK adds budget enforcement support, pass the config value through. This is a 2-line change in `agent_session.py`.

---

### A-11: Module/Tool Naming Divergence — NOT A DEFECT

The architecture specified `mcp__sohnbot__fs__read` but implementation uses `fs__read` because the SDK automatically adds the `mcp__sohnbot__` prefix during MCP server registration. Similarly, `sched` was expanded to `scheduler` for readability. These are implementation details, not architectural violations.

---

### A-12: Capabilities as Sub-Packages — NOT A DEFECT

The architecture recommended single-file capability modules (`capabilities/fs.py`). Implementation uses sub-packages (`capabilities/files/file_ops.py`, `capabilities/files/patch_editor.py`). This was a conscious decision to keep files under 300 lines. Improves maintainability and testability. The module boundaries and public API remain architecturally aligned.

---

### F-09: Untyped `dict[str, Any]` Results — DEFERRED

**Original finding:** All capability results are dictionaries with no compile-time shape guarantees.

**Justification:** This is a maintainability and developer-experience concern, not a runtime correctness issue. The untyped dicts work correctly today. Adding typed dataclasses requires touching every capability module, every test, and the broker router — a large-surface refactoring with low immediate ROI for a single-developer project.

**When to revisit:** When adding a second developer or when a result-shape bug actually occurs. At that point, introduce typed models starting from the most error-prone interfaces (profiles → git → files).

---

## Requirements Traceability

### Findings Addressed in This Epic

| Finding | Severity | Story | FR/NFR/DR Traced |
|---------|----------|-------|------------------|
| A-01 | CRITICAL | 7.1 | DR-010 (retention), NFR-021 (automated cleanup) |
| F-02 | CRITICAL | 7.1 | NFR-009 (data integrity) |
| F-04 | CRITICAL | 7.1 | NFR-009 (data integrity) |
| A-10 | HIGH | 7.1 | Arch Decision 5 (config persistence) |
| F-01 | CRITICAL | 7.2 | NFR-006 (reliability) |
| F-05 | HIGH | 7.2 | NFR-006 (reliability) |
| F-10 | MEDIUM | 7.2 | NFR-006 (reliability) |
| F-03 | CRITICAL | 7.3 | NFR-010 (path traversal), DR-002 (scope isolation) |
| F-06 | HIGH | 7.4 | NFR-011 (command injection), DR-004 |
| F-07 | HIGH | 7.4 | NFR-008 (scheduler reliability), FR-029 (TZ) |
| F-08 | HIGH | 7.4 | NFR-009 (data integrity) |
| A-02 | HIGH | 7.5 | NFR-019 (<2s acknowledgment) |
| A-04 | HIGH | 7.5 | DR-006 (rate limiting) |
| A-03 | HIGH | 7.6 | Arch Decision 5, NFR-022 (hot-reload) |
| F-11 | MEDIUM | 7.7 | NFR-006 (reliability) |
| F-12 | MEDIUM | 7.7 | NFR-027 (observability isolation) |
| A-08 | MEDIUM | 7.7 | Arch Decision 4 (correlation) |

### Findings Justified / Deferred (No Story Required)

| Finding | Severity | Disposition |
|---------|----------|-------------|
| A-05 | HIGH | JUSTIFIED — ripgrep handles user-facing search; Python `re` uses constant patterns only |
| A-06 | MEDIUM | PARTIALLY JUSTIFIED — 3 files superseded by SDK, 1 deferred to Phase 3, `__main__.py` folded into 7.1 |
| A-07 | MEDIUM | DEFERRED — most ops <10s; revisit after A-02 acknowledgment lands |
| A-09 | MEDIUM | DEFERRED — pending SDK support; max_turns provides indirect ceiling |
| A-11 | LOW | NOT A DEFECT — SDK handles naming prefix |
| A-12 | LOW | NOT A DEFECT — improved maintainability |
| F-09 | HIGH | DEFERRED — large refactoring, low immediate ROI; revisit when team grows |

**Totals:** 17 findings addressed across 7 stories. 7 findings justified/deferred with documented rationale.

---

## Epic 7 Stories

---

### Story 7.1: Database & Persistence Hardening

As a developer,
I want all database access to be transactionally safe, schema-correct, and persistent,
So that SohnBot cannot corrupt data under concurrency, fail on valid job types, or lose configuration on restart.

**Addresses:** A-01 (CRITICAL), F-02 (CRITICAL), F-04 (CRITICAL), A-10 (HIGH), A-06/`__main__.py` (MEDIUM)

**Acceptance Criteria:**

**Given** a fresh database with no prior jobs
**When** `initialize_operation_logs_cleanup_job()` runs at startup
**Then** the `cleanup_operation_logs` job is inserted without `IntegrityError`
**And** the `action` CHECK constraint permits `'agent_query'`, `'profile_execute'`, `'heartbeat'`, `'cleanup_operation_logs'`

**Given** two concurrent coroutines (scheduler tick + Telegram handler) both writing to SQLite
**When** both attempt INSERT/UPDATE simultaneously
**Then** writes are serialized via `asyncio.Lock` on the connection
**And** each write uses an explicit `BEGIN IMMEDIATE` transaction
**And** no `OperationalError: database is locked` is raised under normal load

**Given** `capabilities/web.py` needs to read/write search cache
**When** it performs any database operation
**Then** it uses `await get_db()` from `DatabaseManager`, not ad-hoc `aiosqlite.connect()`
**And** all WAL, busy_timeout, and foreign_keys pragmas are applied

**Given** a user changes a dynamic config value via the broker
**When** the process restarts
**Then** the changed value persists in the SQLite `config` table
**And** `load_dynamic_config_from_db()` loads persisted values at startup
**And** persisted values override TOML defaults

**Given** the project is installed
**When** a user runs `python -m sohnbot`
**Then** the `__main__.py` entry point invokes `main.run_main()`

**Implementation Notes:**
- Create migration `0008_widen_jobs_action_check.sql` — recreate `jobs` table with expanded CHECK (SQLite requires table recreation for CHECK changes)
- Add `asyncio.Lock` to `DatabaseManager.get_connection()` in `persistence/db.py`
- Wrap all write operations in `BEGIN IMMEDIATE ... COMMIT` blocks
- Replace 3 `aiosqlite.connect()` calls in `web.py:339, 405, 429` with `await get_db()`
- Implement `ConfigManager._persist_to_database()` and `load_dynamic_config_from_db()` using the existing `config` table from migration `0001_init.sql`
- Create `src/sohnbot/__main__.py` with `from sohnbot.main import run_main; asyncio.run(run_main())`

---

### Story 7.2: Subprocess & Process Lifecycle Hardening

As a developer,
I want all subprocesses to be killed cleanly (including grandchildren) and all async tasks to be tracked,
So that SohnBot cannot leak zombie processes or orphan fire-and-forget coroutines.

**Addresses:** F-01 (CRITICAL), F-05 (HIGH), F-10 (MEDIUM)

**Acceptance Criteria:**

**Given** a command profile spawns a subprocess that itself spawns child processes
**When** the operation times out or is cancelled
**Then** the entire process group is killed (not just the direct child)
**And** `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)` is used on POSIX
**And** `start_new_session=True` is passed to all `create_subprocess_exec` calls

**Given** a git operation is in-flight via `_run_git_command`
**When** the calling coroutine is cancelled (`asyncio.CancelledError`)
**Then** the subprocess is killed before the coroutine exits
**And** the cancellation is re-raised after cleanup
**And** no orphaned `git` process remains

**Given** a scheduler job times out and a notification task is created
**When** `asyncio.create_task()` is used for the timeout notification
**Then** the task reference is stored in a module-level `_background_tasks: set[asyncio.Task]`
**And** a `done_callback` removes completed tasks from the set
**And** no "Task was destroyed but it is pending" warnings appear

**Implementation Notes:**
- Modify `profile_executor.py:50-55, 140-145, 232-237, 306-311` — add `start_new_session=True` (Unix) / `creationflags=CREATE_NEW_PROCESS_GROUP` (Windows) to all `create_subprocess_exec` calls
- Modify all `proc.kill()` calls to use `os.killpg()` with platform guard
- Add `except asyncio.CancelledError` to `git_ops.py:_run_git_command` (around `proc.communicate()`)
- Add `_background_tasks: set[asyncio.Task] = set()` to `executor.py`; update `create_task` call at line 239 with `task.add_done_callback(_background_tasks.discard)`
- Platform consideration: On Windows, `start_new_session` is not supported — use `subprocess.CREATE_NEW_PROCESS_GROUP` flag instead

---

### Story 7.3: Scope Validation TOCTOU Mitigation

As a developer,
I want the scope validator to be resilient against symlink-based TOCTOU attacks,
So that a path cannot pass validation and then be swapped to point outside scope before the file operation executes.

**Addresses:** F-03 (CRITICAL)

**Acceptance Criteria:**

**Given** a path that contains symlink components
**When** scope validation runs
**Then** each path component is checked for symlinks pointing outside scope
**And** the final resolved path is compared against allowed roots
**And** paths with symlinks outside scope are rejected with error code `scope_violation`

**Given** a path that passes initial scope validation
**When** the file operation is about to execute (open/read/write)
**Then** `os.path.realpath()` is called immediately before the I/O call
**And** the real path is re-validated against allowed roots
**And** if the real path is now outside scope (symlink changed between check and use), the operation is rejected

**Given** a symlink chain where `A → B → C` and `C` is outside scope
**When** scope validation is invoked on path `A`
**Then** the full chain is resolved and the final target `C` is validated
**And** the operation is rejected because `C` is outside allowed roots

**Implementation Notes:**
- Modify `broker/scope_validator.py:validate_path()` to call `os.path.realpath()` and validate the resolved path
- Add `_check_symlink_components(path)` helper that walks each component of the path and rejects if any intermediate symlink resolves outside scope
- Modify `capabilities/files/file_ops.py` to re-validate path via `os.path.realpath()` immediately before `open()`/`Path.read_text()`
- Note: This does NOT fully eliminate TOCTOU (that requires `O_NOFOLLOW` at the kernel level) but reduces the race window from unbounded to microseconds
- Add test cases: direct symlink outside scope, nested symlink chains, symlink swap during validation

---

### Story 7.4: Broker Safety & Input Hardening

As a developer,
I want the broker to be safe under concurrent access and restrict command profile inputs to a known-safe allowlist,
So that concurrent Telegram messages cannot corrupt broker state and command profiles cannot be hijacked for arbitrary execution.

**Addresses:** F-06 (HIGH), F-07 (HIGH), F-08 (HIGH)

**Acceptance Criteria:**

**Given** two Telegram messages arrive simultaneously, both triggering profile execution
**When** the broker increments `_profile_counts` for chaining enforcement
**Then** the increment is atomic (protected by `asyncio.Lock`)
**And** the chaining limit of 5 per request is correctly enforced even under concurrency
**And** `_operation_start_times` reads and writes are similarly protected

**Given** a command profile config contains `command: "/usr/bin/malicious-binary"`
**When** the profile executor validates the command
**Then** the command is rejected because it is not in the allowed command allowlist
**And** only known-safe commands are permitted: `pylint`, `flake8`, `ruff`, `eslint`, `mypy`, `pytest`, `npm`, `make`, `cargo`, `go`, `rg`, `tsc`
**And** commands containing `/`, `\`, or `..` are rejected
**And** the rejected command is logged as a security event

**Given** a scheduled job has `timezone: "Invalid/Nonexistent"`
**When** the scheduler evaluates this job's next run slot
**Then** the job is SKIPPED (not executed in UTC fallback)
**And** an error notification is sent to Telegram: "Job [name] skipped: invalid timezone [tz]"
**And** the job is logged as failed with error details
**And** other jobs in the same tick continue executing normally

**Implementation Notes:**
- Add `self._state_lock = asyncio.Lock()` to `BrokerRouter.__init__`; protect `_profile_counts` and `_operation_start_times` access in `_check_and_increment_profile_count()` and `_record_operation_start()`
- Create `ALLOWED_COMMANDS` frozenset in `profile_executor.py`; validate `command.split()[0]` against it; reject paths with `/` or `\`; optionally validate via `shutil.which()` to confirm command exists
- Modify `scheduler/executor.py:96-99` — replace `except Exception: tz = timezone.utc` with `except Exception: log error, send notification, return` (skip the job entirely)
- The timezone validation change means adding a notification enqueue for the timezone error — use existing `enqueue_notification()` from `persistence/notification.py`

---

### Story 7.5: Telegram Gateway UX & Safety

As a user,
I want immediate feedback when I send a message and protection against message floods,
So that I know SohnBot received my request and my Telegram chat doesn't get spammed by a runaway process.

**Addresses:** A-02 (HIGH), A-04 (HIGH)

**Acceptance Criteria:**

**Given** a user sends a message to SohnBot via Telegram
**When** the message passes authentication
**Then** an acknowledgment message ("Processing...") is sent within 2 seconds
**And** the acknowledgment is deleted or edited when the actual response arrives
**And** if processing fails, the acknowledgment is edited to show the error

**Given** SohnBot is sending outbound messages at high volume
**When** the outbound rate exceeds 30 messages per minute
**Then** excess messages are queued and delayed (not dropped)
**And** a structured log warning is emitted at the threshold crossing
**And** the rate limiter uses a sliding-window token bucket

**Given** a scheduled job generates 50 notifications in rapid succession
**When** the notification worker processes the batch
**Then** messages are sent at no more than 30 per minute
**And** remaining messages stay in the outbox with `pending` status
**And** they are delivered in subsequent poll cycles

**Implementation Notes:**
- Modify `gateway/telegram_client.py:handle_message()` — send `await update.message.reply_text("Processing...")` immediately; capture the returned `Message` object; delete or edit on response/error
- Create `gateway/rate_limiter.py` with `RateLimiter` class — sliding-window token bucket, configurable `max_per_minute` (default 30)
- Integrate rate limiter into `send_message()` method on `TelegramClient` — if `acquire()` returns False, `await asyncio.sleep()` until a token is available
- Wire rate limiter into `notification_worker.py:_send_batch()` — each `send_message` call goes through the limiter
- Config key: `telegram.max_messages_per_minute` (dynamic, default 30)

---

### Story 7.6: Configuration System Completion

As a user,
I want to view and modify SohnBot's configuration via Telegram commands,
So that I can tune thresholds, timeouts, and settings without editing files or restarting the process.

**Addresses:** A-03 (HIGH), A-10 (HIGH — DB persistence side shared with Story 7.1)

**Acceptance Criteria:**

**Given** the user sends `/config show` via Telegram
**When** the command is processed
**Then** all config keys are displayed grouped by tier (static/dynamic)
**And** dynamic keys show their current value, default value, and tier
**And** static keys are marked as "requires restart to change"
**And** the response is formatted for Telegram readability (monospace, truncated if >4096 chars)

**Given** the user sends `/config set thresholds.search_volume_daily=200`
**When** the command is processed
**Then** the key is validated against the config registry (type, bounds, tier)
**And** if the key is dynamic, the value is updated in-memory AND persisted to the `config` table
**And** a `config_updated` event is published for subscribing subsystems
**And** the user receives confirmation: "Updated thresholds.search_volume_daily = 200"
**And** if the key is static, the user receives: "Key [key] is static — update config/default.toml and restart"
**And** if validation fails, the user receives the specific error (type mismatch, out of bounds, unknown key)

**Given** the user sends `/config reset thresholds.search_volume_daily`
**When** the command is processed
**Then** the key is reset to its default value (from registry)
**And** the persisted value is removed from the `config` table
**And** a `config_updated` event is published
**And** the user receives confirmation with the restored default value

**Implementation Notes:**
- Create command handler in `gateway/commands.py` for `/config` with subcommands: `show`, `set`, `reset`
- `show`: Call `config_manager.get_all()` → group by tier → format as Telegram message (use `<pre>` or monospace blocks)
- `set`: Parse `key=value`, call `config_manager.update_dynamic_config(key, value)` → validate via registry → persist to DB → publish event
- `reset`: Call `config_manager.reset_dynamic_config(key)` → delete from DB → publish event → return default
- Wire `/config` into Telegram command handler registry (alongside existing `/status`, `/health`, `/schedule`, etc.)
- Note: Story 7.1 implements the DB persistence backend (`_persist_to_database`, `load_dynamic_config_from_db`); this story builds the user-facing commands on top
- Dependency: Story 7.1 must complete first (provides DB persistence)

---

### Story 7.7: Observability Resilience & Traceability

As a developer,
I want the HTTP observability server to self-heal on crash, blocking operations to be async, and operation chains to be traceable,
So that observability survives transient failures and I can trace a user request through all operations it triggers.

**Addresses:** F-11 (MEDIUM), F-12 (MEDIUM), A-08 (MEDIUM)

**Acceptance Criteria:**

**Given** `SnapshotManager.list_snapshots()` is called from the broker router
**When** it executes a git subprocess
**Then** it uses `asyncio.create_subprocess_exec` (not blocking `subprocess.run`)
**And** the event loop is not blocked during snapshot listing
**And** the function is `async def` with `await` on subprocess output

**Given** the HTTP observability server crashes with an unhandled exception
**When** `_safe_http_server_loop` catches the error
**Then** it logs the error and restarts the server after an exponential backoff delay
**And** the backoff sequence is: 2s, 4s, 8s, 16s, 32s (capped at 60s)
**And** after 5 consecutive failures, it sends a critical alert notification to Telegram
**And** it continues attempting restarts (does not silently give up)

**Given** a user sends a Telegram message that triggers a lint → fix → commit chain
**When** the broker handles each operation in the chain
**Then** each operation's `execution_log` entry includes a shared `correlation_id`
**And** the `correlation_id` is generated once per Telegram message in the gateway
**And** structlog context includes `correlation_id` for all log entries in the chain
**And** `correlation_id` is propagated via `structlog.contextvars`

**Implementation Notes:**
- Convert `snapshot_manager.py:list_snapshots()` from `subprocess.run()` to `asyncio.create_subprocess_exec()` + `await proc.communicate()`; update callers to `await`
- Modify `main.py:_safe_http_server_loop()` — add restart counter, exponential backoff (min 2s, max 60s), and critical notification on 5 consecutive failures via `enqueue_notification()`
- Create migration `0009_add_correlation_id.sql` — `ALTER TABLE execution_log ADD COLUMN correlation_id TEXT`; add index `idx_execution_log_correlation_id`
- Modify `gateway/telegram_client.py:handle_message()` — generate `correlation_id = str(uuid.uuid4())`; bind to `structlog.contextvars`; pass through to `route_to_runtime()`
- Modify `broker/router.py:handle()` — read `correlation_id` from structlog context or function parameter; pass to `audit.log_operation_start()`
- Modify `persistence/audit.py:log_operation_start()` — accept and store `correlation_id`

---

## Story Dependency Graph

```
Story 7.1 (Database & Persistence)
  ↓
Story 7.6 (Config Commands) ← depends on 7.1 for DB persistence

Story 7.2 (Subprocess Safety)   ← independent
Story 7.3 (Scope TOCTOU)        ← independent
Story 7.4 (Broker Safety)       ← independent
Story 7.5 (Telegram UX)         ← independent
Story 7.7 (Observability)       ← independent
```

**Recommended Execution Order:**
1. **Story 7.1** — Foundation: fixes 3 CRITICALs and enables 7.6
2. **Story 7.3** — Scope TOCTOU: fixes remaining CRITICAL
3. **Story 7.2** — Subprocess safety: fixes the last CRITICAL + 2 more
4. **Story 7.4** — Broker hardening: 3 HIGHs, all independent
5. **Story 7.5** — Telegram UX: user-facing quality
6. **Story 7.6** — Config commands: depends on 7.1, completes the config story
7. **Story 7.7** — Observability: polish and traceability

---

## Epic 7 Metrics

| Metric | Value |
|--------|-------|
| Findings addressed | 17 of 24 |
| Findings justified/deferred | 7 of 24 |
| Stories | 7 |
| CRITICAL findings fixed | 5 (A-01, F-01, F-02, F-03, F-04) |
| HIGH findings fixed | 7 (A-02, A-03, A-04, A-10, F-05, F-06, F-07, F-08) |
| MEDIUM findings fixed | 5 (A-08, F-10, F-11, F-12, A-06/`__main__.py`) |
| New migrations | 2 (0008_widen_jobs_action_check, 0009_add_correlation_id) |
| New files | ~4 (rate_limiter.py, __main__.py, 2 migrations) |
| Modified files | ~15 |

---

## NFR Compliance Impact

After Epic 7, the NFR compliance scorecard improves from ~71% to ~89%:

| NFR | Before | After | Story |
|-----|--------|-------|-------|
| NFR-009 (Data integrity) | MET | STRENGTHENED | 7.1 (transactions), 7.4 (locks) |
| NFR-010 (Path traversal) | MET WITH CAVEAT | HARDENED | 7.3 (TOCTOU mitigation) |
| NFR-019 (<2s ack) | NOT MET | MET | 7.5 (immediate ack) |
| NFR-021 (Automated cleanup) | BROKEN | MET | 7.1 (CHECK constraint fix) |
| NFR-022 (Hot-reload) | PARTIAL | MET | 7.1 + 7.6 (DB persistence + commands) |
| NFR-027 (Observability isolation) | MET | STRENGTHENED | 7.7 (crash recovery) |
| DR-006 (Rate limiting) | NOT MET | MET | 7.5 (rate limiter) |
