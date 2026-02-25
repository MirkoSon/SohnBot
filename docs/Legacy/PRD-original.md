# 📘 PRD v1 – Local Autonomous Telegram Agent

## 1. Product Overview

A locally hosted autonomous agent controlled via Telegram that can:

* Edit files (scoped to Projects and Notes)
* Use Git safely for versioning and rollback
* Perform Brave web search
* Manage scheduled jobs via internal scheduler
* Operate autonomously with strong structural guardrails
* Run on Windows first, cross-platform by design

No UI automation.
No arbitrary shell.
No unrestricted system access.

---

# 2. Target Environment

## Primary OS (Phase 1)

* Windows 11

## Cross-platform goals

* Linux
* macOS

Design requirement:

* No OS-specific scheduling APIs in core logic
* Scheduler abstracted behind interface
* Command profiles adaptable per OS

---

# 3. High-Level Architecture

Telegram Gateway
→ Agent Runtime (Claude SDK)
→ Broker Layer (capabilities + policy enforcement)
→ Modules:

* Files
* Git
* Web (Brave)
* Scheduler (internal)
* Command Profiles

Persistence:

* SQLite (single local DB file)

Supervision:

* pm2 (initial)
* Replaceable by system service later

---

# 4. Core Principles

1. Scope isolation over prompt-based safety.
2. Profiles over raw shell.
3. Git-based recoverability over filesystem duplication.
4. Autonomous execution without per-action confirmations.
5. Idempotent scheduling.
6. Observable + auditable system state.

---

# 5. Scope Boundaries

Allowed roots:

* `~/Projects`
* `~/Notes`

On Windows:

* `%USERPROFILE%\Projects`
* `%USERPROFILE%\Notes`

Broker must:

* Reject access outside these roots
* Normalize paths cross-platform
* Prevent traversal attacks

---

# 6. Capability Modules

## 6.1 Files Module

Capabilities:

* list
* read
* search
* apply_patch
* snapshot (via Git branch)
* rollback

Rules:

* Patch-only edits
* No binary modification
* Auto-snapshot for multi-file changes
* File size limit
* No hidden/system folders

Notes folder may optionally auto-init Git.

---

## 6.2 Git Module

Capabilities:

* status
* diff
* checkout
* commit

Workflow rule:

* Edit → lint/build → commit if successful
* If build fails:

  * Retry fix once
  * Abort if still failing

Snapshot strategy:

* Local branch snapshots
* Periodic cleanup policy
* No force push
* No destructive history rewrite

Disk conservation:

* No full repo duplication
* Use branch pointers, not file copies

---

## 6.3 Web Module (Brave)

Capabilities:

* search
* optional fetch

Modes:

* fresh (no cache)
* static (cached 7 days)

Cache invalidation:

* query hash + freshness mode
* bypass for time-sensitive terms

Brave API key stored only in broker.

---

## 6.4 Command Profiles

No arbitrary shell.

Profiles define:

* Executable
* Allowed args schema
* Scope
* Timeout
* Network permission
* Output cap

Initial profiles:

* git_status
* git_diff
* git_commit
* lint_project
* build_project
* run_tests
* ripgrep_search

Cross-platform design:

* Profiles may map to OS-specific commands internally
* Broker abstracts differences

---

## 6.5 Scheduler Module (Internal)

Internal scheduler backed by SQLite.

Job schema:

* id
* name
* cron_expression
* timezone
* enabled
* action_type
* action_payload
* last_completed_slot
* last_run_status

Catch-up rule:

* Compute most recent valid slot
* If slot > last_completed_slot:

  * Run once
* Else:

  * Skip

No duplicate execution.
No backlog replay beyond most recent slot.

Execution:

* Jobs execute via command profiles or internal actions.
* No raw command strings allowed.

Concurrency:

* Scheduler jobs run in worker pool.
* Git operations serialized per repo.
* Write operations scoped per directory.

---

# 7. Heartbeat System

Purpose:

* Operational visibility
* Health monitoring
* Optional daily summary

Configurable:

* Frequency (cron)
* Action type (summary, status report, repo digest, etc.)
* Can be modified via Telegram

Heartbeat examples:

* Daily system health summary
* Daily repo change summary
* Weekly Notes digest

Heartbeat jobs are normal scheduler jobs with special tag.

---

# 8. Persistence Model (SQLite)

Tables:

sessions
jobs
execution_log
search_cache

Future:

* capability_metrics
* failure_counts

Design constraints:

* All state recoverable after crash
* Scheduler restores jobs from DB on boot
* No in-memory-only critical state

---

# 9. Concurrency Model

Supports:

* Interactive commands
* Background scheduled jobs

Controls:

* Max concurrent tasks configurable
* Per-scope write mutex
* Git repo operation queue
* Execution timeout enforcement

No global lock.

---

# 10. Telegram UX

Supports:

Natural language:

> “Summarize project changes every morning at 9”

Explicit commands:

* /schedule add
* /schedule list
* /git status
* /heartbeat configure

Explicit commands bypass NLP.

Allowlisted chat IDs only.

---

# 11. Safety Posture

You selected: “Paranoid but not annoying.”

Enforced via structure:

* Strict scope boundaries
* No raw shell
* Profile-based execution
* Patch-only edits
* Git snapshots
* No confirmations
* Idempotent scheduling
* Execution logging
* Output caps
* Timeout caps

No interactive “are you sure?” prompts.

---

# 12. Observability

Every execution logged:

* Timestamp
* Actor
* Capability
* Scope
* Summary
* Result status

Optional:

* Daily error digest
* Execution failure escalation threshold

---

# 13. MVP Definition

MVP includes:

* Telegram gateway
* Broker core
* Files module
* Git module
* Brave search
* Internal scheduler
* SQLite persistence
* Basic command profiles
* Heartbeat job

Excludes:

* UI automation
* Arbitrary shell
* Network installs
* External deployment

---

# 14. Phase 2 Roadmap

* Configurable permission tiers
* Limited shell profile (optional)
* Remote deployment (home server)
* Plugin system for new modules
* Automatic snapshot pruning
* Structured natural language → command translation training
* Optional read-only “analysis mode”

---

# 15. Risk Register

1. Model creates overly large patches → mitigated by diff size cap.
2. Infinite scheduler loops → mitigated by idempotent slot logic.
3. Disk growth via snapshot branches → mitigated by cleanup policy.
4. Cross-platform command drift → mitigated by profile abstraction.
5. Silent failures → mitigated by heartbeat + execution logs.

