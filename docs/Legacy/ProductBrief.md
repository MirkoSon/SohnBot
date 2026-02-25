# 🧠 Product Brief

## Project: Local Autonomous Dev Agent (Working Name: “SohnBot”)

---

## 1. Vision

Build a private, autonomous AI agent that operates locally as a trusted development companion — capable of editing code, managing repositories, searching the web, and running scheduled workflows — while remaining structurally safe, observable, and recoverable.

The long-term vision is not “an AI with a shell.”
It is a **governed, modular local automation system** that evolves responsibly.

This agent should:

* Feel autonomous.
* Reduce friction in daily workflows.
* Never require micromanagement.
* Be recoverable when wrong.
* Be extendable over time.

It is not a toy assistant.
It is a controlled operator.

---

## 2. Problem Statement

Developers increasingly want autonomous AI assistance that can:

* Modify files
* Run builds/tests
* Commit changes
* Fetch information
* Schedule recurring tasks

However, giving a language model raw system access introduces:

* Accidental destructive behavior
* Hard-to-reverse state corruption
* Unbounded scheduling errors
* Security risks

The challenge is to design a system that enables autonomy without relying on fragile prompt-based safeguards.

---

## 3. Guiding Principles

### 1. Structural Safety > Prompt Safety

Security must come from architectural constraints, not model behavior.

### 2. Capability-Based Access

The agent can only perform named, schema-bound actions.

### 3. Scope Isolation

The agent operates only within:

* `~/Projects`
* `~/Notes`

Everything else is invisible.

### 4. Recoverability by Design

Git-based snapshots serve as the rollback mechanism.

### 5. Autonomous by Default

No per-action confirmation prompts.
The system must feel fluid and self-directed.

### 6. Observable System

All actions are logged and inspectable.

---

## 4. Target Users

Primary user:

* A technically skilled developer operating on a local machine.
* Comfortable with Git and system tooling.
* Wants AI assistance without giving up control.

Secondary potential future users:

* Power users seeking safe automation frameworks.
* Developers wanting structured AI operators.

---

## 5. Core Capabilities (Phase 1)

### Files

* Read/search files
* Apply structured patches
* Snapshot and rollback via Git

### Git

* Inspect status and diffs
* Commit changes autonomously after successful lint/build
* Use local branches as lightweight snapshots

### Web

* Perform Brave web searches
* Cache static information
* Always allow fresh queries for time-sensitive content

### Scheduler

* Internal cron-like engine
* Catch-up logic (run most recent missed slot once)
* No duplicate executions
* Configurable heartbeat

---

## 6. Non-Goals (Phase 1)

* UI automation
* Arbitrary shell access
* System-wide file access
* Remote hosting
* External multi-user deployment
* Force pushes or destructive Git operations

---

## 7. System Architecture (Conceptual)

Telegram Gateway
→ Agent Runtime (Claude SDK session)
→ Broker Layer (capability enforcement + policy)
→ Modules:

* Files
* Git
* Web
* Scheduler

Persistence:

* SQLite database for state, jobs, logs, and cache

Supervision:

* Always-on process (Windows first)
* Managed by pm2 or equivalent
* Auto-restart and crash resilience

---

## 8. Scheduling Philosophy

The scheduler is internal and idempotent.

Example:

* Daily summary at 9am
* If machine wakes at 12pm → run once
* If machine wakes next day 8:59am → skip yesterday
* If machine wakes 9:01am → run once

No backfill storms.
No duplicate runs.

Jobs are:

* Structured
* Profile-based
* Persistent
* Recoverable

---

## 9. Safety Model

Autonomy without friction is achieved through:

* Strict directory scoping
* Patch-only edits
* Profile-based command execution
* Git-based rollback strategy
* Output size limits
* Execution timeouts
* Concurrency caps
* Execution logging

There are **no manual confirmation prompts** for normal operation.

Risk mitigation happens structurally, not interactively.

---

## 10. UX Philosophy

Dual-mode interaction:

### Natural language

> “Summarize project changes every morning at 9.”

### Explicit commands

* `/schedule add`
* `/git status`
* `/heartbeat configure`

Natural language maps to structured broker calls.
Explicit commands bypass NLP interpretation.

Only allowlisted Telegram users can interact.

---

## 11. Heartbeat Concept

A configurable recurring status report.

Examples:

* Daily system health
* Daily repo change digest
* Weekly notes summary

This keeps the system transparent without requiring manual inspection.

---

## 12. Platform Strategy

### Phase 1

* Windows 11

### Designed for:

* Cross-platform compatibility (Linux/macOS)
* OS abstraction in scheduler and command profiles
* Minimal OS-specific assumptions

---

## 13. Differentiation

This is not:

* A remote shell bot
* A toy chatbot
* A script runner with AI glued on

It is:

* A capability-governed autonomous operator
* A structured automation layer with AI planning
* A recoverable system-first design

---

## 14. Success Criteria (Phase 1)

The product is successful if:

* It runs autonomously for weeks without manual babysitting.
* It never corrupts data outside allowed scopes.
* Scheduled jobs do not duplicate or spiral.
* Git state is always recoverable.
* Web search improves code correctness.
* Logs clearly explain what happened.

---

## 15. Future Expansion

Potential phase 2+ additions:

* Plugin capability modules
* Limited shell profile
* Deployment to home server
* Remote multi-device orchestration
* Configurable permission tiers
* Extended observability dashboards

But expansion must preserve:

> Structural safety + recoverability.

---

## 16. Strategic Intent

This project is not about giving AI more power.

It is about designing a local autonomy framework where power is:

* Scoped
* Governed
* Observable
* Reversible

The ambition is not chaos with intelligence.
It is structured automation with intelligence.