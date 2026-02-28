# Story 3.4: Health Checks via Telegram

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to query system health via Telegram,
So that I can diagnose issues remotely.

## Acceptance Criteria

**Given** health checks are running
**When** I send `/health` command via Telegram
**Then** overall health status is returned (healthy/degraded/unhealthy)
**And** specific health check results are listed (pass/fail/warn)
**And** failing checks include error details
**And** response is formatted clearly for mobile reading

## Tasks / Subtasks

- [x] Task 1: Add health snapshot read API in observability capability (AC: health data access)
  - [x] Update `src/sohnbot/capabilities/observe.py` with `get_health_snapshot() -> dict` helper
  - [x] Return health check results from latest cached snapshot
  - [x] Calculate overall health status: "healthy" (all pass), "degraded" (any warn), "unhealthy" (any fail)
  - [x] Ensure behavior is safe when no snapshot exists yet (return clear fallback message)
  - [x] Keep API strictly read-only (no DB writes, no side effects)

- [x] Task 2: Implement Telegram health command handling (AC: `/health`, formatted output)
  - [x] Update `src/sohnbot/gateway/commands.py` with `handle_health_command(chat_id: str) -> str`
  - [x] Format output with overall status prominently displayed
  - [x] List all health check results with status indicators (✅ pass, ⚠️ warn, ❌ fail)
  - [x] Include error details for failing/warning checks
  - [x] Ensure formatting is mobile-readable and concise
  - [x] Return clear message when no health data available yet

- [x] Task 3: Wire `/health` into Telegram command routing (AC: command available via Telegram)
  - [x] Update `src/sohnbot/gateway/telegram_client.py` to register `CommandHandler("health", self.cmd_health)`
  - [x] Implement `cmd_health` with same authorization flow used by `/status`
  - [x] Delegate to `handle_health_command(...)` and reply with returned text
  - [x] Keep unauthorized behavior unchanged (silent ignore + warning log)

- [x] Task 4: Expose health MCP tool for agent use (AC: MCP coverage)
  - [x] Update `src/sohnbot/runtime/mcp_tools.py` with `observe__health` tool
  - [x] Return health check results in text format suitable for agent consumption
  - [x] Add tool to the server tool list returned by `create_sohnbot_mcp_server(...)`
  - [x] Keep naming aligned with existing convention: `mcp__sohnbot__observe__health`

- [x] Task 5: Ensure broker tier classification supports health reads (AC: read-only guarantee)
  - [x] Update `src/sohnbot/broker/operation_classifier.py` to classify `observe.health` as Tier 0 if routed through broker
  - [x] Consistent with `observe.status` and `observe.resources` from Story 3.3

- [x] Task 6: Testing
  - [x] Update `tests/unit/test_commands.py`:
    - `/health` returns overall status
    - `/health` lists all health check results
    - `/health` shows error details for failing checks
    - `/health` handles no-snapshot-yet gracefully
  - [x] Update `tests/unit/test_telegram_client.py`:
    - Authorized `/health` command replies with health output
    - Unauthorized `/health` remains blocked
  - [x] Update `tests/unit/test_mcp_tools.py`:
    - `mcp__sohnbot__observe__health` covered in tool list
    - Server creation succeeds with health tool added

## Dev Notes

### Epic 3 Context

**Epic Goal:** Monitor SohnBot's health, resource usage, and operation history through Telegram commands and a local HTTP dashboard.

**Epic 3 Progress:**
- ✅ Story 3.1: Runtime Status Snapshot Collection (COMPLETED)
- ✅ Story 3.2: Health Checks Implementation (COMPLETED)
- ✅ Story 3.3: System Status via Telegram (COMPLETED)
- 🔄 Story 3.4: Health Checks via Telegram (THIS STORY)
- ⏳ Story 3.5: Local HTTP Observability Server
- ⏳ Story 3.6: HTML Status Page

**Why Story 3.4:**
This story exposes the health check engine (Story 3.2) via Telegram commands. It follows the same pattern as Story 3.3 (which exposed status/resources) but for health diagnostics. This enables remote health monitoring and issue diagnosis.

### Architecture Context

**Governed Operator Spine:**
- Health queries are **Tier 0** operations (read-only, no state modification)
- Route through Broker for consistency but no policy enforcement needed
- No snapshot creation (reading existing snapshots)
- Operations logged to `execution_log` for audit trail

**Read-Only Observability (NFR-014):**
- All observability queries are strictly read-only
- No system modifications allowed via observability commands
- Reads from in-memory snapshot cache (fast, no DB contention)
- Health checks run in background (Story 3.2), not triggered by queries

**Integration with Previous Stories:**

Story 3.1 implemented snapshot collection:
```python
# Story 3.1: Background collection every 30 seconds
snapshot = await collect_snapshot()  # Includes health checks
```

Story 3.2 implemented health checks:
```python
# Story 3.2: Health checks integrated into snapshots
health = await run_all_health_checks(scheduler_state, notifier_state, resources)
# Returns: list[HealthCheckResult(name, status, message, timestamp, details)]
```

Story 3.3 implemented `/status` command pattern:
```python
# Story 3.3: Telegram command handling pattern
def handle_status_command(chat_id: str, command_text: str) -> str:
    snapshot = get_latest_snapshot()
    return format_status_output(snapshot)
```

Story 3.4 implements `/health` command following same pattern:
```python
# Story 3.4: Health command (THIS STORY)
def handle_health_command(chat_id: str) -> str:
    health_data = get_health_snapshot()
    return format_health_output(health_data)
```

### Critical Implementation Patterns

**1. Follow Story 3.3 Command Pattern (EXACTLY)**

Story 3.3 established the Telegram command pattern for observability queries. Story 3.4 MUST follow the exact same pattern:

**File Structure from Story 3.3:**
- `src/sohnbot/capabilities/observe.py` - Read helper functions
- `src/sohnbot/gateway/commands.py` - Command handling logic
- `src/sohnbot/gateway/telegram_client.py` - Command registration
- `src/sohnbot/runtime/mcp_tools.py` - MCP tool exposure
- `src/sohnbot/broker/operation_classifier.py` - Tier 0 classification

**Story 3.4 follows same structure:**
- Add `get_health_snapshot()` to `observe.py` (like `get_status_snapshot()`)
- Add `handle_health_command()` to `commands.py` (like `handle_status_command()`)
- Register `cmd_health` in `telegram_client.py` (like `cmd_status`)
- Add `observe__health` to `mcp_tools.py` (like `observe__status`)
- Classify `observe.health` as Tier 0 (like `observe.status`)

**2. Health Status Calculation Pattern**

Health check results have three statuses: `pass`, `warn`, `fail`.

Overall health status calculation:
```python
def calculate_overall_health(health_checks: list[HealthCheckResult]) -> str:
    """
    Calculate overall health status from individual check results.

    Returns:
        "healthy" - All checks pass
        "degraded" - Any checks warn (none fail)
        "unhealthy" - Any checks fail
    """
    if not health_checks:
        return "unknown"

    has_fail = any(check.status == "fail" for check in health_checks)
    has_warn = any(check.status == "warn" for check in health_checks)

    if has_fail:
        return "unhealthy"
    elif has_warn:
        return "degraded"
    else:
        return "healthy"
```

**3. Mobile-Friendly Formatting Pattern**

Health output should be concise and mobile-readable:
```
🏥 System Health: HEALTHY

Health Checks:
✅ sqlite_writable: pass
✅ scheduler_lag: pass (not yet implemented)
✅ notifier_alive: pass (last attempt: 3s ago)
⚠️ outbox_stuck: warn (12 pending notifications)
✅ disk_usage: pass (disabled)

Last check: 5 seconds ago
```

Or if unhealthy:
```
🚨 System Health: UNHEALTHY

Health Checks:
✅ sqlite_writable: pass
❌ scheduler_lag: fail (scheduler lag 320s > threshold 300s)
✅ notifier_alive: pass
✅ outbox_stuck: pass
✅ disk_usage: pass

⚠️ Action Required: scheduler_lag is failing

Last check: 2 seconds ago
```

**Status Indicators:**
- ✅ = pass (green metaphor)
- ⚠️ = warn (yellow metaphor)
- ❌ = fail (red metaphor)

**4. MCP Tool Pattern (from Story 3.3)**

Follow Story 3.3's MCP tool pattern:
```python
# mcp_tools.py
{
    "type": "function",
    "function": {
        "name": "mcp__sohnbot__observe__health",
        "description": "Query system health checks and overall health status",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
}
```

No parameters needed (just return health snapshot).

**5. Authorization Pattern (from Story 3.3)**

Follow Story 3.3's authorization pattern:
```python
# telegram_client.py
async def cmd_health(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /health command."""
    chat_id = str(update.effective_chat.id)

    # Authorization check
    if not self._is_authorized(chat_id):
        logger.warning("unauthorized_health_attempt", chat_id=chat_id)
        # Silent ignore (no response to unauthorized users)
        return

    # Authorized - process command
    try:
        response = handle_health_command(chat_id)
        await update.message.reply_text(response)
    except Exception as exc:
        logger.error("health_command_failed", chat_id=chat_id, error=str(exc))
        await update.message.reply_text("❌ Health check query failed")
```

### Project Structure Notes

**Files to Modify:**
```
src/sohnbot/capabilities/observe.py (add get_health_snapshot helper)
src/sohnbot/gateway/commands.py (add handle_health_command)
src/sohnbot/gateway/telegram_client.py (register /health command)
src/sohnbot/runtime/mcp_tools.py (add observe__health tool)
src/sohnbot/broker/operation_classifier.py (add observe.health Tier 0)
tests/unit/test_commands.py (add health command tests)
tests/unit/test_telegram_client.py (add health authorization tests)
tests/unit/test_mcp_tools.py (add health tool tests)
```

**Files to Reference (DO NOT MODIFY):**
```
src/sohnbot/observability/health_checks.py (reference for HealthCheckResult structure)
src/sohnbot/observability/snapshot_collector.py (reference for snapshot collection)
```

**Module Structure After Story 3.4:**
```
src/sohnbot/capabilities/observe.py (add get_health_snapshot)
src/sohnbot/gateway/commands.py (add handle_health_command)
src/sohnbot/gateway/telegram_client.py (add cmd_health handler)
src/sohnbot/runtime/mcp_tools.py (add observe__health tool)
```

### Technical Constraints

**Performance Requirements (NFR-019):**
- Response time < 2 seconds (same as `/status`)
- Read from in-memory cache (no DB queries)
- Formatting should be fast (simple string operations)

**Mobile Readability:**
- Use emojis for visual status indicators
- Keep lines short (< 80 characters)
- Group related information
- Prioritize most important info at top (overall status)

**Error Handling:**
- Graceful handling when no snapshot available yet
- Clear error messages (not stack traces)
- Always return valid response (never raise to user)

### Previous Story Intelligence

**From Story 3.3 (System Status via Telegram - JUST COMPLETED):**

Key learnings from Story 3.3:
- Telegram command pattern established and working
- Authorization flow tested and secure
- MCP tool integration pattern proven
- Mobile-friendly formatting validated
- Read-only observability pattern confirmed

**Code from Story 3.3 to reuse:**
```python
# observe.py pattern
def get_status_snapshot() -> dict:
    """Get latest status snapshot."""
    snapshot = _get_latest_snapshot()
    if not snapshot:
        return {"status": "no_data", "message": "No snapshot data available yet"}
    return {...}

# commands.py pattern
def handle_status_command(chat_id: str, command_text: str) -> str:
    """Handle /status command."""
    snapshot = get_status_snapshot()
    return format_output(snapshot)

# telegram_client.py pattern
async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    if not self._is_authorized(chat_id):
        logger.warning("unauthorized_status_attempt", chat_id=chat_id)
        return
    response = handle_status_command(chat_id, command_text)
    await update.message.reply_text(response)
```

**Apply same patterns to Story 3.4:**
- Same file structure
- Same authorization flow
- Same error handling
- Same MCP integration
- Same testing approach

**From Story 3.2 (Health Checks Implementation):**

Story 3.2 defined the `HealthCheckResult` structure:
```python
@dataclass
class HealthCheckResult:
    name: str  # "sqlite_writable", "scheduler_lag", etc.
    status: str  # "pass", "warn", "fail"
    message: str  # Human-readable message
    timestamp: int  # Unix timestamp
    details: dict[str, Any]  # Additional context
```

Health checks implemented:
1. **sqlite_writable** - Database write capability
2. **scheduler_lag** - Scheduler behind threshold (returns "pass" if Epic 4 not implemented)
3. **job_timeouts** - Jobs exceeding timeout (returns "pass" if jobs table doesn't exist)
4. **notifier_alive** - Notification worker active
5. **outbox_stuck** - Pending notifications > threshold
6. **disk_usage** - Disk space monitoring (optional, disabled by default)

Story 3.4 formats these results for Telegram display.

**From Story 3.1 (Runtime Status Snapshot Collection):**

Story 3.1 established the snapshot cache pattern:
- Background collection every 30 seconds (configurable)
- In-memory cache updated each cycle
- Snapshots include health checks (populated by Story 3.2)
- Read from cache (fast, no DB queries)

Story 3.4 reads health data from this cache.

### Health Check Output Format Specification

**Overall Status Display:**
- 🏥 = healthy (all green)
- ⚠️ = degraded (some yellow, no red)
- 🚨 = unhealthy (any red)

**Individual Check Status:**
- ✅ = pass
- ⚠️ = warn
- ❌ = fail

**Example Outputs:**

**Healthy System:**
```
🏥 System Health: HEALTHY

Health Checks:
✅ sqlite_writable: pass
✅ scheduler_lag: pass
✅ notifier_alive: pass
✅ outbox_stuck: pass
✅ disk_usage: disabled

Last check: 3 seconds ago
```

**Degraded System:**
```
⚠️ System Health: DEGRADED

Health Checks:
✅ sqlite_writable: pass
✅ scheduler_lag: pass
✅ notifier_alive: pass
⚠️ outbox_stuck: warn (15 pending notifications > threshold 10)
✅ disk_usage: disabled

Last check: 1 second ago
```

**Unhealthy System:**
```
🚨 System Health: UNHEALTHY

Health Checks:
✅ sqlite_writable: pass
❌ scheduler_lag: fail (lag 380s > threshold 300s)
✅ notifier_alive: pass
⚠️ outbox_stuck: warn (12 pending notifications)
✅ disk_usage: disabled

⚠️ Action Required: scheduler_lag

Last check: 2 seconds ago
```

**No Data Available:**
```
⏳ System Health: UNKNOWN

No health data available yet. Health checks are collected every 30 seconds.

Please wait for the first health check cycle to complete.
```

### Latest Tech Information

**Telegram Bot Best Practices (2026):**
- Use emoji for visual status indicators (mobile-friendly)
- Keep messages concise (< 4096 characters - Telegram limit)
- Group related information together
- Prioritize critical info at top
- Use clear action items for failures

**Python asyncio Command Handlers:**
- Use async/await for Telegram handlers
- Handle exceptions gracefully (don't raise to user)
- Log all errors for debugging
- Reply with user-friendly error messages

**Health Check Standards:**
- Overall health: healthy/degraded/unhealthy (industry standard)
- Individual checks: pass/warn/fail (common pattern)
- Include timestamps for staleness detection
- Error details for diagnostics

### References

**Epic & Story Source:**
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 3: System Observability & Monitoring]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.4: Health Checks via Telegram]

**Story 3.3 Patterns (JUST COMPLETED):**
- [Source: src/sohnbot/capabilities/observe.py] - get_status_snapshot pattern
- [Source: src/sohnbot/gateway/commands.py] - handle_status_command pattern
- [Source: src/sohnbot/gateway/telegram_client.py] - cmd_status handler pattern
- [Source: _bmad-output/implementation-artifacts/3-3-system-status-via-telegram.md] - Complete implementation details

**Story 3.2 Context (Health Checks Engine):**
- [Source: src/sohnbot/observability/health_checks.py] - HealthCheckResult structure, run_all_health_checks
- [Source: _bmad-output/implementation-artifacts/3-2-health-checks-implementation.md] - Health checks implementation

**Story 3.1 Context (Snapshot Collection):**
- [Source: src/sohnbot/observability/snapshot_collector.py] - Background collection pattern
- [Source: src/sohnbot/capabilities/observe.py] - StatusSnapshot structure

**Broker & MCP Integration:**
- [Source: src/sohnbot/broker/operation_classifier.py] - Tier classification
- [Source: src/sohnbot/runtime/mcp_tools.py] - MCP tool registration

**Testing Patterns:**
- [Source: tests/unit/test_commands.py] - Command handler tests from Story 3.3
- [Source: tests/unit/test_telegram_client.py] - Authorization tests from Story 3.3

## Dev Agent Record

### Agent Model Used

GPT-5 Codex (dev-story workflow)

### Debug Log References

- `.venv/bin/pytest -q tests/unit/test_commands.py tests/unit/test_telegram_client.py tests/unit/test_mcp_tools.py` (pass, 39 tests)
- `.venv/bin/pytest -q` (fails during collection due to pre-existing environment/import issues: missing `sohnbot` module path in some tests, missing `psutil`)

### Completion Notes List

- Added `get_health_snapshot()` in observability capability to expose cached health checks and computed overall health (`healthy`/`degraded`/`unhealthy`/`unknown`) in read-only form.
- Added `handle_health_command(chat_id)` in gateway commands with mobile-readable output, per-check status icons, and warn/fail detail surfacing.
- Added Telegram `/health` command registration and `cmd_health` handler with existing authorization flow and silent unauthorized handling.
- Added MCP tool `observe__health` and registered it in MCP server tool list with text output for agent consumption.
- Added Tier-0 classification for `observe.health` in broker operation classifier.
- Extended unit tests for command output, Telegram `/health` authorization path, and MCP allowlist.

### File List

- src/sohnbot/capabilities/observe.py (modified)
- src/sohnbot/gateway/commands.py (modified)
- src/sohnbot/gateway/telegram_client.py (modified)
- src/sohnbot/runtime/mcp_tools.py (modified)
- src/sohnbot/broker/operation_classifier.py (modified)
- tests/unit/test_commands.py (modified)
- tests/unit/test_telegram_client.py (modified)
- tests/unit/test_mcp_tools.py (modified)
- _bmad-output/implementation-artifacts/3-4-health-checks-via-telegram.md (modified)

### Change Log

- 2026-02-28: Implemented Story 3.4 `/health` command and MCP exposure, added Tier 0 classification, and added targeted unit test coverage.
