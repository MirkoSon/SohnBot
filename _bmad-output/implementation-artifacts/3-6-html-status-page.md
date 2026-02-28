# Story 3.6: HTML Status Page

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a developer,
I want an HTML status page with auto-refresh,
So that I can monitor SohnBot in a browser dashboard.

## Acceptance Criteria

**Given** HTTP server is running
**When** I navigate to http://localhost:8080/ or /ui
**Then** HTML page displays: process info, active operations, scheduler next runs, resources, recent errors
**And** page auto-refreshes every 30 seconds
**And** health status is shown with visual indicator (✅ healthy, ⚠️ degraded, ❌ unhealthy)
**And** page uses monospace font and dark theme
**And** page is read-only (no forms or control actions)

## Tasks / Subtasks

- [x] Task 1: Create HTML template file (AC: page displays required info)
  - [x] Create `src/sohnbot/observability/templates/` directory
  - [x] Create `src/sohnbot/observability/templates/status.html` with complete HTML template
  - [x] Use inline CSS (no external dependencies) with dark theme (#1e1e1e background, #d4d4d4 text)
  - [x] Add meta refresh tag: `<meta http-equiv="refresh" content="30">` for 30-second auto-refresh
  - [x] Set monospace font for entire page (font-family: monospace)
  - [x] Include sections: header (health badge + process info), active operations table, scheduler next runs table, resources summary, recent errors table
  - [x] Use emoji indicators for health status: ✅ Healthy, ⚠️ Degraded, ❌ Unhealthy
  - [x] Add color coding: healthy (#4ec9b0 green), degraded (#ce9178 orange), unhealthy (#f48771 red)
  - [x] Keep layout simple and mobile-readable (no JavaScript required)

- [x] Task 2: Implement /ui and / route handlers (AC: all)
  - [x] Update `src/sohnbot/observability/http_server.py` to add `handle_ui` async function
  - [x] Call `get_current_snapshot()` from `capabilities/observe.py`
  - [x] Handle None case gracefully (return HTML with "No snapshot available" message and 503 status)
  - [x] Determine health badge and CSS class from health check results:
    - If any check status is "fail" → "❌ Unhealthy" (unhealthy class)
    - Else if any check status is "warn" → "⚠️ Degraded" (degraded class)
    - Else → "✅ Healthy" (healthy class)
  - [x] Render template with snapshot data:
    - Process: uptime_seconds, version, pid, supervisor
    - Active operations: operation_id (first 8 chars), tool, tier, elapsed_s (from broker.in_flight_operations)
    - Scheduler next runs: job_name, next_run_local (from scheduler.next_jobs, limit to first 5)
    - Resources: cpu_percent, ram_mb, db_size_mb, log_size_mb, snapshot_count, event_loop_lag_ms
    - Recent errors: operation_id (first 8 chars), tool, error_message (first 50 chars), timestamp (from recent_operations where status=='error', limit to 10)
  - [x] Return `web.Response(text=html, content_type="text/html")`
  - [x] Handle empty lists gracefully (show "No active operations", "No scheduled jobs", "No recent errors")

- [x] Task 3: Wire routes into HTTP server (AC: routes accessible)
  - [x] Update `create_observability_app()` in `http_server.py`
  - [x] Add route: `app.router.add_get("/", handle_ui)`
  - [x] Add route: `app.router.add_get("/ui", handle_ui)`
  - [x] Preserve existing /status, /health, /metrics routes (already implemented in Story 3.5)

- [x] Task 4: Testing (AC: all)
  - [x] Update `tests/unit/test_http_server.py`:
    - [x] `/` route returns HTML with Content-Type: text/html
    - [x] `/ui` route returns HTML with Content-Type: text/html
    - [x] HTML contains health badge (✅/⚠️/❌) based on health check results
    - [x] HTML contains process info (uptime, version, PID)
    - [x] HTML contains auto-refresh meta tag
    - [x] HTML gracefully handles no snapshot case (503 status, "No snapshot available" message)
    - [x] HTML gracefully handles empty active operations, scheduled jobs, recent errors
  - [x] Update `tests/integration/test_http_server_integration.py`:
    - [x] Query http://localhost:PORT/ and /ui via httpx client
    - [x] Verify response is valid HTML (content-type check)
    - [x] Verify HTML contains expected sections (active operations, scheduler, resources, errors)
    - [x] Verify health indicator color coding works correctly

## Dev Notes

### Epic 3 Context

**Epic Goal:** Monitor SohnBot's health, resource usage, and operation history through Telegram commands and local observability surfaces.

**Epic 3 Progress (at Story 3.6):**
- Done: Story 3.1 Runtime Status Snapshot Collection
- Done: Story 3.2 Health Checks Implementation
- Done: Story 3.3 System Status via Telegram
- Done: Story 3.4 Health Checks via Telegram
- Done: Story 3.5 Local HTTP Observability Server
- This story: Story 3.6 HTML Status Page
- Next: Epic 3 Retrospective (optional)

This story completes the Epic 3 observability surface by adding a human-readable HTML dashboard.

### Previous Story Intelligence (3.5)

**Story 3.5 Implementation Patterns:**
- HTTP server module already exists at `src/sohnbot/observability/http_server.py`
- Three JSON endpoints already implemented: /status, /health, /metrics
- All endpoints use `get_status_snapshot_data()`, `get_health_snapshot()`, `get_resource_snapshot_data()` from `capabilities/observe.py`
- Graceful None handling pattern: return `{"error": "No snapshot available"}` with 503 status
- CORS headers already included for localhost access
- HTTP server runs in background via `http_server_loop()` launched from `main.py`
- aiohttp dependency already added to `pyproject.toml`

**Key Learnings from Story 3.5:**
- Use `create_observability_app()` to build the aiohttp app with routes
- Return `web.Response(text=html, content_type="text/html")` for HTML responses
- Follow existing pattern: call snapshot accessor functions, check for None, render response
- Keep all logic in `http_server.py` (no separate template loader needed for inline HTML)

### Architecture and Safety Guardrails

1. **Read-Only Dashboard:**
   - HTML page is informational only
   - NO forms, buttons, or interactive controls
   - NO JavaScript required (pure HTML + CSS + meta refresh)
   - All data comes from read-only snapshot cache

2. **Dark Theme and Monospace:**
   - Background: #1e1e1e (dark)
   - Text: #d4d4d4 (light gray)
   - Font: monospace throughout
   - Health colors: healthy (#4ec9b0 green), degraded (#ce9178 orange), unhealthy (#f48771 red)

3. **Auto-Refresh:**
   - Use meta tag: `<meta http-equiv="refresh" content="30">`
   - Browser auto-refreshes every 30 seconds
   - No WebSocket or polling JavaScript needed

4. **Graceful Degradation:**
   - Handle empty lists: show "No active operations", "No scheduled jobs", "No recent errors"
   - Handle no snapshot: show "No snapshot available" with 503 status
   - Format data safely: truncate long strings, handle None values

### File-Level Guidance

**Primary files to modify:**
- `src/sohnbot/observability/http_server.py` (add handle_ui function and routes)

**Primary files to create:**
- `src/sohnbot/observability/templates/status.html` (HTML template with inline CSS)

**Files to reference (do not redesign):**
- `src/sohnbot/capabilities/observe.py` (snapshot data access functions)
- `src/sohnbot/observability/snapshot_collector.py` (snapshot structure reference)
- `_bmad-output/planning-artifacts/architecture.md` (HTML template example at lines 1775-1838)

**Files to update for testing:**
- `tests/unit/test_http_server.py` (add HTML route tests)
- `tests/integration/test_http_server_integration.py` (add HTML integration tests)

### Project Structure Notes

- Templates directory: `src/sohnbot/observability/templates/`
- Keep HTML template simple and self-contained (no template engine needed)
- Use inline CSS to avoid external file dependencies
- Follow existing HTTP server patterns from Story 3.5

### Testing Standards

- Unit tests: Mock snapshot data, verify HTML structure and content
- Integration tests: Start real HTTP server, query with httpx client, verify HTML response
- Verify auto-refresh meta tag is present
- Verify health indicator color coding
- Verify graceful handling of empty data
- Preserve existing async testing patterns (`pytest.mark.asyncio`, lightweight fixtures)

### HTML Template Structure (from Architecture)

The architecture document at lines 1758-1838 provides a complete reference implementation showing:

```html
<!DOCTYPE html>
<html>
<head>
    <title>SohnBot Status</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body { font-family: monospace; margin: 20px; background: #1e1e1e; color: #d4d4d4; }
        .header { margin-bottom: 20px; }
        .health.healthy { color: #4ec9b0; }
        .health.degraded { color: #ce9178; }
        .health.unhealthy { color: #f48771; }
        table { border-collapse: collapse; width: 100%; margin-top: 10px; }
        th, td { border: 1px solid #3e3e3e; padding: 8px; text-align: left; }
        th { background-color: #252526; }
        .section { margin-top: 30px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>SohnBot Status</h1>
        <div class="health {health_class}"><strong>{health_badge}</strong></div>
        <p>Uptime: {uptime}s | Version: {version} | PID: {pid}</p>
    </div>

    <div class="section">
        <h2>Active Operations</h2>
        <table>
            <tr><th>Operation ID</th><th>Tool</th><th>Tier</th><th>Elapsed</th></tr>
            <!-- Dynamically populated from snapshot.broker.in_flight_operations -->
        </table>
    </div>

    <div class="section">
        <h2>Scheduler Next Runs</h2>
        <table>
            <tr><th>Job</th><th>Next Run (Local)</th></tr>
            <!-- Dynamically populated from snapshot.scheduler.next_jobs -->
        </table>
    </div>

    <div class="section">
        <h2>Resources</h2>
        <p>CPU: {cpu}% | RAM: {ram} MB</p>
        <p>DB: {db} MB | Logs: {logs} MB</p>
        <p>Snapshots: {count} | Loop lag: {lag} ms</p>
    </div>

    <div class="section">
        <h2>Latest Errors</h2>
        <table>
            <tr><th>Operation ID</th><th>Tool</th><th>Error</th><th>Timestamp</th></tr>
            <!-- Dynamically populated from recent_operations where status=='error' -->
        </table>
    </div>

    <div class="section">
        <p><em>Auto-refreshes every 30 seconds</em></p>
    </div>
</body>
</html>
```

**Key Implementation Notes:**
- Use Python f-string to inject snapshot data into HTML template
- For tables, use list comprehensions with f-strings to generate rows
- Handle empty lists with conditional rendering: `or "<tr><td colspan='N'>No items</td></tr>"`
- Truncate long strings: `operation_id[:8]`, `error_message[:50]`
- Limit list lengths: `next_jobs[:5]`, `errors[:10]`

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.6: HTML Status Page]
- [Source: _bmad-output/planning-artifacts/architecture.md#Local HTTP Server (lines 1758-1838)]
- [Source: _bmad-output/implementation-artifacts/3-5-local-http-observability-server.md]
- [Source: src/sohnbot/observability/http_server.py]
- [Source: src/sohnbot/capabilities/observe.py]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex (dev-story workflow)

### Debug Log References

- `.venv/bin/pytest -q tests/unit/test_http_server.py tests/integration/test_http_server_integration.py tests/unit/test_commands.py tests/unit/test_telegram_client.py tests/unit/test_mcp_tools.py` (pass, 50 tests)
- `.venv/bin/pytest -q` (fails during collection due to pre-existing legacy import-path issues: tests importing `sohnbot.*` instead of `src.sohnbot.*`)

### Completion Notes List

- Added HTML dashboard template at `src/sohnbot/observability/templates/status.html` with dark monospace theme, 30s meta-refresh, and health badge color variants.
- Added `handle_ui` route handler and rendering helpers in `http_server.py` for `/` and `/ui` using current snapshot cache data.
- Added graceful 503 HTML fallback for no-snapshot startup state.
- Added rendering for active operations, scheduler runs, resource summary, and recent errors with truncation/empty-state rows.
- Updated HTTP app routing to include both `/` and `/ui` while preserving existing JSON routes.
- Extended unit and integration tests to validate HTML routes, content-type, required sections, health badge, and auto-refresh tag.

### File List

- src/sohnbot/observability/templates/status.html (new)
- src/sohnbot/observability/http_server.py (modified)
- tests/unit/test_http_server.py (modified)
- tests/integration/test_http_server_integration.py (modified)
- _bmad-output/implementation-artifacts/3-6-html-status-page.md (modified)

### Change Log

- 2026-02-28: Implemented Story 3.6 HTML status dashboard routes and template with auto-refresh and full test coverage.
