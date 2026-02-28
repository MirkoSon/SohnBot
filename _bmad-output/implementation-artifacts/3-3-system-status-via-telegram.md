# Story 3.3: System Status via Telegram

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to query system status via Telegram commands,
So that I can check SohnBot's health and activity.

## Acceptance Criteria

**Given** observability snapshots are being collected
**When** I send `/status` command via Telegram
**Then** response includes: uptime, version, supervisor status, last scheduler tick, last broker activity, in-flight operations, notification outbox count, last 10 operation results
**And** when I send `/status resources`
**Then** response includes: CPU%, RAM (MB), DB size (MB), log size (MB), snapshot count, event loop lag (ms)
**And** all queries are read-only (no system modifications)
**And** response time is <2s (NFR-019)

## Tasks / Subtasks

- [x] Task 1: Add status/resource snapshot read APIs in observability capability (AC: `/status`, `/status resources`, read-only)
  - [x] Update `src/sohnbot/capabilities/observe.py` with read helpers that return latest cached snapshot data for:
    - default status view (`/status`)
    - resource view (`/status resources`)
  - [x] Ensure behavior is safe when no snapshot exists yet (return clear fallback payload/message instead of exceptions)
  - [x] Keep APIs strictly read-only (no DB writes, no side effects)

- [x] Task 2: Implement Telegram status command handling (AC: `/status`, `/status resources`, <2s)
  - [x] Update `src/sohnbot/gateway/commands.py` with `handle_status_command(chat_id: str, command_text: str) -> str`
  - [x] Parse `/status` and `/status resources` modes explicitly
  - [x] Format default status output with all required fields from AC
  - [x] Format resources output with CPU/RAM/DB/log/snapshot/loop-lag fields from AC
  - [x] Ensure formatting is mobile-readable and bounded (trim long in-flight list to a practical size)
  - [x] Return usage guidance for unsupported args (for example, `Usage: /status [resources]`)

- [x] Task 3: Wire `/status` into Telegram command routing (AC: command available via Telegram)
  - [x] Update `src/sohnbot/gateway/telegram_client.py` to register `CommandHandler("status", self.cmd_status)`
  - [x] Implement `cmd_status` with same authorization flow used by other commands (`/help`, `/notify`)
  - [x] Delegate to `handle_status_command(...)` and reply with returned text
  - [x] Keep unauthorized behavior unchanged (silent ignore + warning log)

- [x] Task 4: Expose status/resource MCP tools for agent use (AC: MCP coverage)
  - [x] Update `src/sohnbot/runtime/mcp_tools.py` with `observe__status` and `observe__resources`
  - [x] Return concise text output suitable for agent consumption
  - [x] Add new tools to the server tool list returned by `create_sohnbot_mcp_server(...)`
  - [x] Keep naming aligned with existing convention where runtime tool names are exposed as `mcp__sohnbot__...`

- [x] Task 5: Ensure broker tier classification supports observability reads (AC: read-only guarantee)
  - [x] Update `src/sohnbot/broker/operation_classifier.py` to classify observability reads (`observe.status`, `observe.resources`) as Tier 0 if routed through broker
  - [x] Preserve conservative defaults for unknown operations

- [x] Task 6: Testing (AC: all)
  - [x] Update `tests/unit/test_commands.py`:
    - [x] `/status` returns required status fields
    - [x] `/status resources` returns required resource fields
    - [x] invalid `/status` args return usage text
    - [x] no-snapshot-yet path returns safe fallback
  - [x] Update `tests/unit/test_telegram_client.py`:
    - [x] authorized `/status` command path replies with command output
    - [x] unauthorized `/status` remains blocked
  - [x] Update `tests/unit/test_mcp_tools.py`:
    - [x] server creation still succeeds with observe tools added
    - [x] `mcp__sohnbot__observe__status` and `mcp__sohnbot__observe__resources` covered in allowed-tool list assertions

## Dev Notes

### Epic 3 Context

**Epic Goal:** Monitor SohnBot's health, resource usage, and operation history through Telegram commands and local observability surfaces.

**Epic 3 Progress (at Story 3.3):**
- Done: Story 3.1 Runtime Status Snapshot Collection
- Done: Story 3.2 Health Checks Implementation
- This story: Story 3.3 System Status via Telegram
- Next: Story 3.4 Health Checks via Telegram

This story should consume the snapshot/health foundation from 3.1 and 3.2, not re-implement it.

### Previous Story Intelligence (3.2)

- `StatusSnapshot.health` is now populated via `run_all_health_checks(...)` in `snapshot_collector.py`.
- Scheduler remains a deliberate Epic 4 placeholder (`last_tick_timestamp=0` + "not yet implemented" message) and must be shown gracefully in `/status`.
- Health checks are integrated in snapshot collection already; `/status` should read current cache only.

### Architecture and Safety Guardrails

1. Observability endpoints are read-only.
2. Snapshot cache is the fast path for status requests; avoid re-querying expensive sources in command handlers.
3. Keep output stable and concise for Telegram UX; avoid dumping unbounded payloads.
4. Response path should stay under NFR-019 (<2s), which is achievable when reading in-memory snapshot data.

### File-Level Guidance

**Primary files to modify:**
- `src/sohnbot/capabilities/observe.py`
- `src/sohnbot/gateway/commands.py`
- `src/sohnbot/gateway/telegram_client.py`
- `src/sohnbot/runtime/mcp_tools.py`
- `src/sohnbot/broker/operation_classifier.py` (if observe reads are broker-routed)
- `tests/unit/test_commands.py`
- `tests/unit/test_telegram_client.py`
- `tests/unit/test_mcp_tools.py`

**Files to reference (do not redesign):**
- `src/sohnbot/observability/snapshot_collector.py` (snapshot source of truth)
- `src/sohnbot/capabilities/observe.py` dataclasses and cache functions
- `src/sohnbot/gateway/commands.py` existing command style (`handle_notify_command`)
- `src/sohnbot/gateway/telegram_client.py` auth + command handler patterns

### Project Structure Notes

- Keep observability logic in `capabilities/observe.py` and lightweight command formatting in `gateway/commands.py`.
- Keep Telegram transport concerns in `gateway/telegram_client.py`; do not move business logic there.
- Keep MCP registration centralized in `runtime/mcp_tools.py`.
- Keep story scope limited to status and resources (health command is Story 3.4).

### Testing Standards

- Prefer unit coverage for command parsing/formatting and fallback behaviors.
- Preserve existing async testing patterns (`pytest.mark.asyncio`, lightweight fixtures, mocks for Telegram).
- Ensure any newly added tool names remain compatible with `validate_tool_use` expectations (`mcp__sohnbot__*`).

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.3: System Status via Telegram]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.2: Health Checks Implementation]
- [Source: _bmad-output/planning-artifacts/architecture.md#Observability Architecture]
- [Source: _bmad-output/planning-artifacts/architecture.md#Functional Requirements Mapping]
- [Source: src/sohnbot/capabilities/observe.py]
- [Source: src/sohnbot/observability/snapshot_collector.py]
- [Source: src/sohnbot/gateway/commands.py]
- [Source: src/sohnbot/gateway/telegram_client.py]
- [Source: src/sohnbot/runtime/mcp_tools.py]
- [Source: src/sohnbot/broker/operation_classifier.py]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex (dev-story workflow)

### Debug Log References

- `pytest -q tests/unit/test_commands.py tests/unit/test_telegram_client.py tests/unit/test_mcp_tools.py` (failed: `pytest` not installed in PATH)
- `.venv/bin/pytest -q tests/unit/test_commands.py tests/unit/test_telegram_client.py tests/unit/test_mcp_tools.py` (pass, 33 tests)
- `.venv/bin/pytest -q` (fails during collection due to existing environment/import issues unrelated to this story: missing `sohnbot` module path in some tests, missing `psutil`)

### Completion Notes List

- Added read-only observability snapshot access helpers for status and resource views in `capabilities/observe.py`.
- Implemented `/status [resources]` command handling in `gateway/commands.py` with safe fallback when no snapshot is available.
- Wired Telegram `/status` command registration and handler (`cmd_status`) in `gateway/telegram_client.py`, preserving authorization behavior.
- Added MCP tools `observe__status` and `observe__resources` in `runtime/mcp_tools.py` and registered them in server tool list.
- Extended broker operation classifier to mark observability reads (`observe.status`, `observe.resources`) as Tier 0.
- Added unit coverage for status command output, fallback behavior, Telegram `/status` auth flow, and tool allowlist entries.

### File List

- src/sohnbot/capabilities/observe.py (modified)
- src/sohnbot/gateway/commands.py (modified)
- src/sohnbot/gateway/telegram_client.py (modified)
- src/sohnbot/runtime/mcp_tools.py (modified)
- src/sohnbot/broker/operation_classifier.py (modified)
- tests/unit/test_commands.py (modified)
- tests/unit/test_telegram_client.py (modified)
- tests/unit/test_mcp_tools.py (modified)
- _bmad-output/implementation-artifacts/3-3-system-status-via-telegram.md (modified)

### Change Log

- 2026-02-28: Implemented Story 3.3 system status via Telegram and MCP, added Tier 0 observe classification, and added targeted unit coverage.
