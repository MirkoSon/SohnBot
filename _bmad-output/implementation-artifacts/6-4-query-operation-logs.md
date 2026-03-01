# Story 6.4: Query Operation Logs

**Epic**: Epic 6 - Research & Web Search
**Story Key**: 6-4-query-operation-logs
**Status**: done
**Created**: 2026-03-01

---

## Story Overview

**As a** user,
**I want** to query recent operations with filtering,
**So that** I can review SohnBot's activity history.

### Business Value
- **Activity Auditing**: Review what SohnBot has done over recent hours/days
- **Debugging Aid**: Quickly find failed operations or errors to understand issues
- **Usage Insights**: Understand operation patterns and frequency
- **Compliance**: Maintain queryable audit trail for operational transparency

---

## Functional Requirements

### FR-037: Query Operation Logs
**Priority**: MEDIUM
**Source**: epics.md lines 1233-1256

The system MUST provide queryable access to operation logs:

1. **Command Interface**
   - Telegram command: `/logs [hours]`
   - Default time range: last 24 hours
   - Optional hours parameter: 1-720 (30 days)
   - Returns formatted operation summary

2. **MCP Tool Interface**
   - Tool name: `observe__logs`
   - Parameters: hours (int, default 24), filters (optional)
   - Returns structured operation log data
   - Integrates with existing observe capability pattern

3. **Log Query Filters**
   - Time range: last N hours (1-720)
   - Operation type: capability filter (fs, git, web, etc.)
   - Status filter: completed, failed, in_progress (plus postponed/cancelled from execution_log schema)
   - Chat ID filter: operations by specific user
   - Tier filter: filter by operation tier (0/1/2/3)

4. **Result Format**
   - Timestamp (ISO 8601 format, local timezone)
   - Operation type: `{capability}__{action}`
   - Files affected: list of file paths (if applicable)
   - Result status: completed/failed/in_progress
   - Duration: milliseconds (if completed)
   - Errors: error details (if failed)
   - Snapshot reference: git snapshot branch (if Tier 1/2)

5. **Data Retention (NFR-021)**
   - Operation logs retained for 90 days
   - Automated cleanup via scheduled job
   - Cleanup runs weekly (every Sunday at 3am UTC)
   - Cleanup is idempotent and safe to run multiple times
   - Cleanup deletes logs older than 90 days

---

## Non-Functional Requirements

### NFR-021: Automated Cleanup
**Priority**: HIGH
**Source**: epics.md line 108

Operation logs MUST auto-delete after 90 days:
- Scheduled job: weekly cleanup (every Sunday 3am UTC)
- Retention period: 90 days from operation timestamp
- Cleanup function: idempotent, safe, non-blocking
- Failed cleanup logged but doesn't halt system

### NFR-037: Log Query Performance
**Priority**: MEDIUM

- Query execution: <500ms for 24-hour window
- Index optimization: timestamp DESC index
- Result limit: max 1000 operations per query
- Pagination: not required for MVP (limit sufficient)

---

## Acceptance Criteria

### AC-037.1: Telegram /logs Command
- [x] Command: `/logs [hours]` implemented in commands.py
- [x] Default hours: 24 if not specified
- [x] Hours range validation: 1-720 (30 days max)
- [x] Formatted output: timestamp, type, status, files, errors
- [x] Empty result: "No operations found in last N hours"

### AC-037.2: MCP observe__logs Tool
- [x] Tool name: `observe__logs` registered in mcp_tools.py
- [x] Parameters: hours (int), filters (optional dict)
- [x] Returns structured log data (list of operation dicts)
- [x] Follows existing observe tool pattern
- [x] Integrates with broker layer (no direct DB access)

### AC-037.3: Query Filtering
- [x] Filter by time range: hours parameter (1-720)
- [x] Filter by capability: `{"capability": "fs"}` filter
- [x] Filter by status: `{"status": "failed"}` filter
- [x] Filter by chat_id: `{"chat_id": "chat-123"}` filter
- [x] Multiple filters combined with AND logic

### AC-037.4: Result Format
- [x] Timestamp: ISO 8601 local time format
- [x] Operation type: `{capability}__{action}` (e.g., "fs__patch")
- [x] Files: JSON array of file paths (empty if none)
- [x] Status: completed/failed/in_progress
- [x] Duration: milliseconds (null if in_progress)
- [x] Error details: error message (null if no error)

### AC-037.5: 90-Day Retention & Cleanup
- [x] Cleanup function: `cleanup_old_operation_logs(db_path, retention_days=90)`
- [x] Scheduled job: weekly (Sunday 3am UTC)
- [x] Job deletes logs older than 90 days
- [x] Cleanup is idempotent (safe to run multiple times)
- [x] Failed cleanup logged but doesn't halt system

---

## Implementation Guidance

### Architecture Context

```
src/sohnbot/persistence/
├── migrations/
│   └── 0001_init.sql             # EXISTING: execution_log table already exists
├── audit.py                       # EXISTING: log_operation_start, log_operation_end
└── operation_logs.py              # NEW: query_operation_logs, cleanup_old_operation_logs

src/sohnbot/gateway/
└── commands.py                    # UPDATE: Add handle_logs_command

src/sohnbot/runtime/
└── mcp_tools.py                   # UPDATE: Add observe__logs tool

src/sohnbot/capabilities/scheduler/
└── scheduler.py                   # UPDATE: Add weekly cleanup job

tests/unit/
├── test_operation_logs.py         # NEW: Unit tests for log queries
└── test_commands.py               # UPDATE: Add /logs command tests

tests/integration/
└── test_logs_query_flow.py        # NEW: Integration test for log query flow
```

### Key Implementation Tasks

#### Task 6.4.1: Create Operation Logs Query Module
**File**: `src/sohnbot/persistence/operation_logs.py` (NEW)

```python
"""Query and cleanup functions for operation execution logs."""

from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite
import structlog

logger = structlog.get_logger(__name__)


async def query_operation_logs(
    db_path: str,
    hours: int = 24,
    capability: Optional[str] = None,
    status: Optional[str] = None,
    chat_id: Optional[str] = None,
    tier: Optional[int] = None,
    limit: int = 1000,
) -> list[dict]:
    """
    Query operation logs from execution_log table.

    Args:
        db_path: Path to SQLite database
        hours: Time range in hours (1-720)
        capability: Filter by capability (fs, git, web, etc.)
        status: Filter by status (completed, failed, in_progress)
        chat_id: Filter by chat ID
        tier: Filter by operation tier (0, 1, 2, 3)
        limit: Maximum results (default 1000)

    Returns:
        List of operation dicts with: operation_id, timestamp, capability, action,
        chat_id, tier, status, file_paths, snapshot_ref, duration_ms, error_details
    """
    # Calculate timestamp cutoff
    cutoff_timestamp = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())

    # Build query with filters
    query = """
        SELECT
            operation_id, timestamp, capability, action, chat_id, tier, status,
            file_paths, snapshot_ref, duration_ms, error_details
        FROM execution_log
        WHERE timestamp >= ?
    """
    params: list = [cutoff_timestamp]

    if capability is not None:
        query += " AND capability = ?"
        params.append(capability)

    if status is not None:
        query += " AND status = ?"
        params.append(status)

    if chat_id is not None:
        query += " AND chat_id = ?"
        params.append(chat_id)

    if tier is not None:
        query += " AND tier = ?"
        params.append(tier)

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    try:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(query, tuple(params)) as cursor:
                rows = await cursor.fetchall()

        # Convert rows to dicts
        results = []
        for row in rows:
            results.append({
                "operation_id": row[0],
                "timestamp": row[1],
                "capability": row[2],
                "action": row[3],
                "chat_id": row[4],
                "tier": row[5],
                "status": row[6],
                "file_paths": row[7],  # JSON string or None
                "snapshot_ref": row[8],
                "duration_ms": row[9],
                "error_details": row[10],  # JSON string or None
            })

        logger.info(
            "operation_logs_query_completed",
            hours=hours,
            capability=capability,
            status=status,
            results_count=len(results),
        )

        return results

    except aiosqlite.Error as exc:
        logger.error("operation_logs_query_error", error=str(exc))
        raise RuntimeError(f"Failed to query operation logs: {exc}") from exc


async def cleanup_old_operation_logs(db_path: str, retention_days: int = 90) -> int:
    """
    Delete operation logs older than retention_days.

    Args:
        db_path: Path to SQLite database
        retention_days: Delete logs older than this (default: 90)

    Returns:
        Number of rows deleted
    """
    cutoff_timestamp = int(
        (datetime.now(timezone.utc) - timedelta(days=retention_days)).timestamp()
    )

    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "DELETE FROM execution_log WHERE timestamp < ?",
                (cutoff_timestamp,),
            )
            await db.commit()
            deleted = cursor.rowcount or 0

        logger.info(
            "operation_logs_cleanup_completed",
            deleted=deleted,
            retention_days=retention_days,
        )

        return deleted

    except aiosqlite.Error as exc:
        logger.error("operation_logs_cleanup_error", error=str(exc))
        return 0
```

#### Task 6.4.2: Add /logs Command Handler
**File**: `src/sohnbot/gateway/commands.py` (UPDATE)

**Add import** (at top):
```python
from ..persistence.operation_logs import query_operation_logs
```

**Add command handler** (after handle_health_command):
```python
async def handle_logs_command(chat_id: str, command_text: str, db_path: str) -> str:
    """
    Handle /logs [hours] command.

    Args:
        chat_id: Telegram chat ID
        command_text: Full command text (e.g., "/logs 48")
        db_path: Path to database

    Returns:
        Formatted log summary string
    """
    # Parse hours parameter
    parts = command_text.strip().split()
    hours = 24  # Default

    if len(parts) > 1:
        try:
            hours = int(parts[1])
            if hours < 1 or hours > 720:
                return "Usage: /logs [hours]\nHours must be between 1 and 720 (30 days)."
        except ValueError:
            return "Usage: /logs [hours]\nHours must be a number."

    # Query logs
    try:
        logs = await query_operation_logs(db_path, hours=hours)
    except Exception as exc:
        return f"Error querying logs: {exc}"

    if not logs:
        return f"No operations found in last {hours} hours."

    # Format results
    lines = [f"📋 Operation Logs (last {hours}h) — {len(logs)} operations\n"]

    for log in logs[:50]:  # Show max 50 in Telegram
        # Format timestamp
        ts = datetime.fromtimestamp(log["timestamp"], tz=timezone.utc)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S UTC")

        # Format operation type
        op_type = f"{log['capability']}__{log['action']}"

        # Format status with emoji
        status = log["status"]
        status_emoji = {
            "completed": "✅",
            "failed": "❌",
            "in_progress": "⏳",
        }.get(status, "❓")

        # Format duration
        duration_ms = log.get("duration_ms")
        duration_str = f"{duration_ms}ms" if duration_ms is not None else "N/A"

        # Format files
        file_paths = log.get("file_paths")
        files_str = ""
        if file_paths:
            import json
            try:
                files = json.loads(file_paths)
                if files:
                    files_str = f"\n  Files: {', '.join(files[:3])}"
                    if len(files) > 3:
                        files_str += f" (+{len(files) - 3} more)"
            except json.JSONDecodeError:
                pass

        # Format errors
        error_details = log.get("error_details")
        error_str = ""
        if error_details and status == "failed":
            import json
            try:
                error = json.loads(error_details)
                error_msg = error.get("message", "Unknown error")
                error_str = f"\n  Error: {error_msg[:80]}"
            except json.JSONDecodeError:
                pass

        lines.append(
            f"{status_emoji} {ts_str} | {op_type} | {duration_str}{files_str}{error_str}"
        )

    if len(logs) > 50:
        lines.append(f"\n... and {len(logs) - 50} more operations")

    return "\n".join(lines)
```

#### Task 6.4.3: Add observe__logs MCP Tool
**File**: `src/sohnbot/runtime/mcp_tools.py` (UPDATE)

**Add import** (at top):
```python
from ..persistence.operation_logs import query_operation_logs
```

**Add tool** (after observe__health tool, around line 900):
```python
@tool(
    "observe__logs",
    "Query recent operation logs with filtering",
    {
        "hours": int,
        "capability": str,  # Optional: fs, git, web, etc.
        "status": str,      # Optional: completed, failed, in_progress
    }
)
async def observe_logs(args):
    """Query operation execution logs from database."""
    hours = args.get("hours", 24)
    capability = args.get("capability")  # Optional filter
    status = args.get("status")          # Optional filter

    # Validate hours
    if hours < 1 or hours > 720:
        return _as_mcp_text("Error: hours must be between 1 and 720 (30 days)")

    # Get database path from config
    db_path = config.get("database.path")

    try:
        logs = await query_operation_logs(
            db_path,
            hours=hours,
            capability=capability,
            status=status,
            limit=100,  # MCP tool returns max 100
        )
    except Exception as exc:
        logger.error("observe_logs_error", error=str(exc))
        return _as_mcp_text(f"Error querying logs: {exc}")

    if not logs:
        return _as_mcp_text(f"No operations found in last {hours} hours")

    # Format as structured text
    lines = [f"Operation Logs (last {hours}h) — {len(logs)} results\n"]

    for log in logs:
        ts = datetime.fromtimestamp(log["timestamp"], tz=timezone.utc)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S UTC")
        op_type = f"{log['capability']}__{log['action']}"
        status_icon = {"completed": "✅", "failed": "❌", "in_progress": "⏳"}.get(log["status"], "❓")
        duration = f"{log['duration_ms']}ms" if log.get("duration_ms") else "N/A"

        lines.append(f"{status_icon} {ts_str} | {op_type} | {log['status']} | {duration}")

    return _as_mcp_text("\n".join(lines))
```

#### Task 6.4.4: Add Weekly Cleanup Scheduled Job
**File**: `src/sohnbot/capabilities/scheduler/scheduler.py` (UPDATE)

**Add import** (at top):
```python
from ...persistence.operation_logs import cleanup_old_operation_logs
```

**Add cleanup job** (in job definitions, around line 200):
```python
# Weekly cleanup job for operation logs (90-day retention)
{
    "name": "cleanup_operation_logs",
    "cron_expr": "0 3 * * 0",  # Every Sunday at 3am UTC
    "timezone": "UTC",
    "action": {
        "type": "python_function",
        "function": cleanup_old_operation_logs,
        "args": {
            "db_path": config.get("database.path"),
            "retention_days": 90,
        },
    },
    "enabled": True,
    "timeout_seconds": 300,  # 5 minutes max
}
```

#### Task 6.4.5: Update message_router to Register /logs Command
**File**: `src/sohnbot/gateway/message_router.py` (UPDATE)

**Import handler** (at top):
```python
from .commands import (
    handle_logs_command,
    handle_notify_command,
    handle_status_command,
    handle_health_command,
    # ... existing imports
)
```

**Register command** (in command routing logic, around line 150):
```python
if command.startswith("/logs"):
    db_path = str(self.config_manager.get("database.path"))
    response_text = await handle_logs_command(chat_id, command, db_path)
    await self.telegram_client.send_message(chat_id, response_text)
    return
```

---

## Testing Strategy

### Unit Tests

**File**: `tests/unit/test_operation_logs.py` (NEW)

```python
"""Unit tests for operation logs query and cleanup."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.persistence.operation_logs import (
    cleanup_old_operation_logs,
    query_operation_logs,
)


@pytest.fixture
def logs_db(tmp_path):
    """Create test database with migrations and sample log data."""
    db_path = tmp_path / "logs-test.db"
    migrations_dir = Path(__file__).parent.parent.parent / "src" / "sohnbot" / "persistence" / "migrations"
    apply_migrations(db_path, migrations_dir)
    return db_path


@pytest.mark.asyncio
async def test_query_operation_logs_last_24_hours(logs_db):
    """Test querying logs from last 24 hours."""
    # Insert test data
    now = int(datetime.now(timezone.utc).timestamp())
    async with aiosqlite.connect(str(logs_db)) as db:
        await db.execute(
            """
            INSERT INTO execution_log (
                operation_id, timestamp, capability, action, chat_id, tier, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("op-1", now - 3600, "fs", "read", "chat-1", 0, "completed"),
        )
        await db.commit()

    # Query logs
    logs = await query_operation_logs(str(logs_db), hours=24)

    assert len(logs) == 1
    assert logs[0]["operation_id"] == "op-1"
    assert logs[0]["capability"] == "fs"
    assert logs[0]["action"] == "read"


@pytest.mark.asyncio
async def test_query_operation_logs_with_capability_filter(logs_db):
    """Test filtering by capability."""
    now = int(datetime.now(timezone.utc).timestamp())
    async with aiosqlite.connect(str(logs_db)) as db:
        await db.execute(
            """
            INSERT INTO execution_log (
                operation_id, timestamp, capability, action, chat_id, tier, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "op-1", now - 3600, "fs", "read", "chat-1", 0, "completed",
                "op-2", now - 1800, "web", "search", "chat-1", 0, "completed",
            ),
        )
        await db.commit()

    # Query only web operations
    logs = await query_operation_logs(str(logs_db), hours=24, capability="web")

    assert len(logs) == 1
    assert logs[0]["capability"] == "web"


@pytest.mark.asyncio
async def test_query_operation_logs_with_status_filter(logs_db):
    """Test filtering by status."""
    now = int(datetime.now(timezone.utc).timestamp())
    async with aiosqlite.connect(str(logs_db)) as db:
        await db.execute(
            """
            INSERT INTO execution_log (
                operation_id, timestamp, capability, action, chat_id, tier, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "op-1", now - 3600, "fs", "read", "chat-1", 0, "completed",
                "op-2", now - 1800, "fs", "patch", "chat-1", 2, "failed",
            ),
        )
        await db.commit()

    # Query only failed operations
    logs = await query_operation_logs(str(logs_db), hours=24, status="failed")

    assert len(logs) == 1
    assert logs[0]["status"] == "failed"
    assert logs[0]["action"] == "patch"


@pytest.mark.asyncio
async def test_cleanup_old_operation_logs(logs_db):
    """Test cleanup deletes logs older than retention period."""
    now = datetime.now(timezone.utc)
    old_timestamp = int((now - timedelta(days=100)).timestamp())
    recent_timestamp = int((now - timedelta(days=30)).timestamp())

    async with aiosqlite.connect(str(logs_db)) as db:
        await db.execute(
            """
            INSERT INTO execution_log (
                operation_id, timestamp, capability, action, chat_id, tier, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "op-old", old_timestamp, "fs", "read", "chat-1", 0, "completed",
                "op-recent", recent_timestamp, "fs", "read", "chat-1", 0, "completed",
            ),
        )
        await db.commit()

    # Run cleanup (90-day retention)
    deleted = await cleanup_old_operation_logs(str(logs_db), retention_days=90)

    assert deleted == 1

    # Verify only old log deleted
    logs = await query_operation_logs(str(logs_db), hours=24 * 365)
    assert len(logs) == 1
    assert logs[0]["operation_id"] == "op-recent"
```

**File**: `tests/unit/test_commands.py` (UPDATE)

```python
"""Add tests for /logs command handler."""

import pytest
from src.sohnbot.gateway.commands import handle_logs_command


@pytest.mark.asyncio
async def test_handle_logs_command_default_hours(logs_db):
    """Test /logs command with default 24 hours."""
    result = await handle_logs_command("chat-1", "/logs", str(logs_db))
    assert "No operations found" in result or "Operation Logs" in result


@pytest.mark.asyncio
async def test_handle_logs_command_custom_hours(logs_db):
    """Test /logs command with custom hours parameter."""
    result = await handle_logs_command("chat-1", "/logs 48", str(logs_db))
    assert "48h" in result or "48 hours" in result


@pytest.mark.asyncio
async def test_handle_logs_command_invalid_hours(logs_db):
    """Test /logs command with invalid hours parameter."""
    result = await handle_logs_command("chat-1", "/logs abc", str(logs_db))
    assert "Usage:" in result


@pytest.mark.asyncio
async def test_handle_logs_command_hours_out_of_range(logs_db):
    """Test /logs command with hours out of range."""
    result = await handle_logs_command("chat-1", "/logs 1000", str(logs_db))
    assert "between 1 and 720" in result
```

### Integration Tests

**File**: `tests/integration/test_logs_query_flow.py` (NEW)

```python
"""Integration tests for operation logs query flow."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.migrate import apply_migrations
from src.sohnbot.broker import BrokerRouter, ScopeValidator
from src.sohnbot.persistence.db import DatabaseManager, set_db_manager


@pytest.fixture
async def setup_database(tmp_path):
    """Setup test database with migrations."""
    db_path = tmp_path / "test.db"
    migrations_dir = Path(__file__).parent.parent.parent / "src" / "sohnbot" / "persistence" / "migrations"
    apply_migrations(db_path, migrations_dir)

    db_manager = DatabaseManager(db_path)
    set_db_manager(db_manager)
    yield db_manager
    await db_manager.close()


@pytest.mark.asyncio
async def test_logs_query_after_file_operations(tmp_path, setup_database):
    """Test /logs command returns operations after file reads."""
    allowed_root = tmp_path / "projects"
    allowed_root.mkdir()
    test_file = allowed_root / "test.txt"
    test_file.write_text("content")

    config = MagicMock()

    def _cfg(key):
        if key == "database.path":
            return str(tmp_path / "test.db")
        if key == "files.max_size_mb":
            return 10
        return None

    config.get.side_effect = _cfg
    router = BrokerRouter(ScopeValidator([str(allowed_root)]), config_manager=config)

    # Execute file read operation
    result = await router.route_operation(
        capability="fs",
        action="read",
        params={"path": str(test_file), "max_size_mb": 10},
        chat_id="chat-1",
    )

    assert result.allowed is True

    # Query logs
    from src.sohnbot.persistence.operation_logs import query_operation_logs

    logs = await query_operation_logs(str(tmp_path / "test.db"), hours=1)

    assert len(logs) >= 1
    assert any(log["capability"] == "fs" and log["action"] == "read" for log in logs)
```

---

## Dependencies

### Required Stories
- ✅ **Story 1.2**: SQLite Persistence Layer (provides execution_log table)
- ✅ **Story 1.8**: Structured Operation Logging (provides log_operation_start/end)
- ✅ **Epic 3**: Observability (provides observe capability pattern)
- ✅ **Epic 4**: Scheduled Jobs (provides scheduler for cleanup job)

### External Dependencies
- **aiosqlite**: Already installed (async SQLite access)
- **datetime**: Standard library (timestamp handling)
- **json**: Standard library (parse file_paths and error_details JSON)

### Configuration Dependencies
- `database.path`: Default "data/sohnbot.db" (already configured)

---

## Migration Plan

### Database Changes
**No migration required** - execution_log table already exists from migration 0001_init.sql

Existing schema:
```sql
CREATE TABLE IF NOT EXISTS execution_log (
    operation_id TEXT PRIMARY KEY,
    timestamp INTEGER NOT NULL,
    capability TEXT NOT NULL,
    action TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    tier INTEGER NOT NULL CHECK(tier IN (0, 1, 2, 3)),
    status TEXT NOT NULL CHECK(status IN ('in_progress', 'completed', 'failed')),
    file_paths TEXT,
    snapshot_ref TEXT,
    duration_ms INTEGER,
    error_details TEXT,
    details TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_execution_log_timestamp
    ON execution_log(timestamp);
```

This schema is perfect for query requirements - no changes needed.

### Deployment Steps
1. Deploy code changes (operation_logs.py, commands.py, mcp_tools.py)
2. Restart SohnBot service
3. Test /logs command via Telegram
4. Test observe__logs MCP tool
5. Wait for weekly cleanup job (or manually trigger for testing)
6. Verify cleanup deletes old logs

---

## Rollback Plan

If log querying causes issues:

1. **Immediate Mitigation**: Comment out /logs command registration in message_router.py
2. **Code Rollback**: Revert to Story 6.3 commit (remove operation_logs.py and command handler)
3. **Cleanup Job**: Disable weekly cleanup job in scheduler.py
4. **Monitoring**: Check logs for query performance issues

---

## Story Intelligence from Previous Stories

### Story 6.3 Learnings (Search Volume Monitoring)
- **Cleanup Pattern**: Use weekly scheduled job (Sunday 3am UTC)
- **Retention Implementation**: Simple DELETE with timestamp comparison
- **Query Pattern**: Use aiosqlite async context manager
- **Error Handling**: Catch aiosqlite.Error specifically, log errors, return gracefully
- **Config Integration**: Read config via config_manager.get()
- **Testing Approach**: Use tmp_path fixture with apply_migrations

Key code patterns from Story 6.3:
```python
# Cleanup function pattern
async def cleanup_old_volume_records(db_path: str, retention_days: int = 30) -> int:
    cutoff_timestamp = ...
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("DELETE FROM ... WHERE date < ?", ...)
        await db.commit()
        deleted = cursor.rowcount or 0
    logger.info("cleanup_completed", deleted=deleted)
    return deleted

# Query function pattern with filters
async def query_function(db_path: str, param1: int, param2: Optional[str] = None):
    query = "SELECT ... WHERE ..."
    params = []
    if param2 is not None:
        query += " AND field = ?"
        params.append(param2)
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
    return rows
```

### Story 3.3 Learnings (System Status via Telegram)
- **Command Handler Pattern**: Parse command parameters with shlex or simple split
- **Validation**: Check parameter ranges, return usage message on invalid input
- **Formatting**: Use emoji for status indicators (✅ ❌ ⏳)
- **Message Length**: Limit results to prevent Telegram message overflow

### Epic 4 Learnings (Scheduled Jobs)
- **Job Definition**: Cron expression, timezone, action dict with function and args
- **Job Timeout**: Set reasonable timeout (300s for cleanup jobs)
- **Idempotency**: Cleanup jobs should be safe to run multiple times

---

## Architecture Compliance

### Query Performance
- **Index Usage**: Existing `idx_execution_log_timestamp` index optimizes time range queries
- **Result Limits**: Max 1000 results prevents memory issues
- **Query Optimization**: Simple WHERE clause with indexed timestamp

### Storage Pattern
- **Existing Table**: Reuse execution_log table (no new tables)
- **Async Access**: Use aiosqlite for non-blocking DB access
- **Error Handling**: Catch specific exceptions, log errors, return gracefully

### Command Interface
- **Telegram Commands**: Follow existing pattern in commands.py
- **Parameter Validation**: Validate hours range (1-720)
- **Error Messages**: Clear, actionable error messages

### MCP Tool Pattern
- **Tool Naming**: Follow observe__* pattern (observe__logs)
- **Tool Schema**: Define parameters with types
- **Result Format**: Use _as_mcp_text() helper for consistent formatting
- **Config Access**: Use config.get() for database path

---

## File Structure Requirements

```
src/sohnbot/persistence/
├── migrations/
│   └── 0001_init.sql             # EXISTING: execution_log table
├── audit.py                       # EXISTING: log_operation_start, log_operation_end
└── operation_logs.py              # NEW: query_operation_logs, cleanup_old_operation_logs

src/sohnbot/gateway/
├── message_router.py              # UPDATE: Register /logs command
└── commands.py                    # UPDATE: Add handle_logs_command

src/sohnbot/runtime/
└── mcp_tools.py                   # UPDATE: Add observe__logs tool

src/sohnbot/capabilities/scheduler/
└── scheduler.py                   # UPDATE: Add weekly cleanup job

tests/unit/
├── test_operation_logs.py         # NEW: Unit tests for query/cleanup
└── test_commands.py               # UPDATE: Add /logs command tests

tests/integration/
└── test_logs_query_flow.py        # NEW: Integration test
```

---

## Testing Requirements

### Unit Test Coverage
- ✅ Query logs with default 24-hour range
- ✅ Query logs with custom hours parameter
- ✅ Query logs with capability filter
- ✅ Query logs with status filter
- ✅ Query logs with chat_id filter
- ✅ Query logs with tier filter
- ✅ Query logs with multiple filters combined
- ✅ Cleanup deletes logs older than retention period
- ✅ Cleanup is idempotent (safe to run multiple times)
- ✅ /logs command with default hours
- ✅ /logs command with custom hours
- ✅ /logs command with invalid hours
- ✅ /logs command with hours out of range

### Integration Test Coverage
- ✅ Execute file operation, query logs, verify operation appears
- ✅ /logs command returns formatted results via Telegram
- ✅ observe__logs MCP tool returns structured data
- ✅ Weekly cleanup job deletes old logs

### Manual Test Checklist
- [ ] Execute `/logs` command via Telegram → verify last 24 hours
- [ ] Execute `/logs 48` command → verify last 48 hours
- [ ] Execute `/logs abc` → verify error message
- [ ] Execute `/logs 1000` → verify range validation error
- [ ] Perform file operations, then `/logs` → verify operations appear
- [ ] Use observe__logs MCP tool via agent session → verify structured output
- [ ] Check execution_log table: `SELECT COUNT(*) FROM execution_log WHERE timestamp < ...` → verify cleanup works

---

## Review Follow-ups (Code Review - 2026-03-01)

### HIGH Priority Issues

- [x] **[AI-Review][HIGH] File List Incomplete - Story 6.3 Fixes Mixed In** `src/sohnbot/config/registry.py, tests/unit/test_config_registry.py`
  - **Issue**: Story File List doesn't include config/registry.py or test_config_registry.py, but both were modified in this commit
  - **Root Cause**: These files contain Story 6.3 code review fixes (search.cache_retention_days max_value 30→90, search.volume_alert_threshold min_value 10→1, max_value 1000→10000)
  - **Impact**: Confusing documentation - Story 6.4 File List doesn't reflect all actual changes. Story 6.3 fixes bundled into Story 6.4 commit.
  - **Fix**: Either add these files to Story 6.4 File List with explanation they're Story 6.3 fixes, OR commit Story 6.3 fixes separately before Story 6.4

### MEDIUM Priority Issues

- [x] **[AI-Review][MEDIUM] Overly Broad Exception Handling in Command Handler** `src/sohnbot/gateway/commands.py:214`
  - **Issue**: `except Exception:  # noqa: BLE001` catches all exceptions including programming errors
  - **Impact**: Could hide bugs like AttributeError, NameError, etc.
  - **Fix**: Change to `except (RuntimeError, ValueError) as exc:` to catch specific exceptions from query_operation_logs

- [x] **[AI-Review][MEDIUM] Overly Broad Exception Handling in Broker Router** `src/sohnbot/broker/router.py:1168-1171`
  - **Issue**: `except Exception:  # noqa: BLE001` when reading database.path config
  - **Impact**: Silently swallows all exceptions, making debugging harder
  - **Fix**: Log specific exception types or at minimum log the error before falling back to default

- [x] **[AI-Review][MEDIUM] Overly Broad Exception Handling in Telegram Client** `src/sohnbot/gateway/telegram_client.py:263-266`
  - **Issue**: `except Exception:  # noqa: BLE001` when reading database.path config
  - **Impact**: Same as above - silently swallows all exceptions
  - **Fix**: Use specific exception types and log warnings for unexpected errors

- [x] **[AI-Review][MEDIUM] Missing Input Validation in Broker** `src/sohnbot/broker/router.py:675-688, 1164-1181`
  - **Issue**: Broker validates hours parameter but doesn't validate tier, status, or capability filter values before passing to query_operation_logs
  - **Impact**: Invalid values reach persistence layer, rely on operation_logs.py validation
  - **Fix**: Add validation for tier (0-3), status (allowed list), capability (non-empty string) in broker before calling query_operation_logs

- [x] **[AI-Review][MEDIUM] MCP Tool Doesn't Validate Filter Value Types** `src/sohnbot/runtime/mcp_tools.py:922-924`
  - **Issue**: Loop extracts filter values without type checking: `params[key] = filters[key]` could pass wrong types
  - **Impact**: Could pass string "2" instead of int 2 for tier, causing validation errors
  - **Fix**: Add type validation/coercion for each filter type (tier=int, status=str, capability=str, chat_id=str)

### LOW Priority Issues

- [x] **[AI-Review][LOW] Inconsistent Status Values Documentation** `src/sohnbot/persistence/operation_logs.py:14-20`
  - **Issue**: ALLOWED_STATUS_FILTERS includes "postponed" and "cancelled", but Story AC-037.4 only mentions "completed", "failed", "in_progress"
  - **Impact**: Minor documentation gap - these statuses ARE valid per execution_log table schema, just not mentioned in story
  - **Fix**: Add note to story that "postponed" and "cancelled" are also supported per table schema

- [x] **[AI-Review][LOW] Error Message Could Be More Helpful** `src/sohnbot/persistence/operation_logs.py:52`
  - **Issue**: Error says "status must be one of: in_progress, completed, failed, postponed, cancelled" - long list
  - **Impact**: Very minor - message is technically correct but could use f-string
  - **Fix**: Change to f-string: `f"status must be one of: {', '.join(_ALLOWED_STATUS_FILTERS)}"`

---

## Definition of Done

- [ ] Code implemented and committed to feature branch
- [x] All acceptance criteria met (AC-037.1 through AC-037.5)
- [x] `operation_logs.py` module created with query and cleanup functions
- [x] `/logs` command handler added to commands.py
- [x] `observe__logs` MCP tool added to mcp_tools.py
- [x] Weekly cleanup job registered in scheduler.py
- [x] Unit tests pass with >90% coverage on new code
- [x] Integration tests verify log query flow
- [ ] Manual testing completed (checklist above)
- [ ] Code review completed
- [ ] All linter checks pass
- [x] Story status updated to 'review' in sprint-status.yaml

---

## Open Questions

### Q1: Should we include "details" field in query results?
**Question**: The execution_log table has a "details" TEXT field. Should this be included in query results?
**Decision**: No - details field is rarely populated and adds bloat. If needed, can be added in future iteration.

### Q2: Should we implement pagination for queries?
**Question**: Should the query support pagination for very large result sets?
**Decision**: Not required for MVP. 1000-result limit is sufficient. Can add pagination in future story if needed.

### Q3: Should cleanup be configurable retention period?
**Question**: Should retention_days be configurable via config, or hardcoded to 90?
**Decision**: Hardcode to 90 days per NFR-021. No config needed - keeps it simple and prevents accidental data loss.

---

## Related Documentation

- `src/sohnbot/persistence/migrations/0001_init.sql`: execution_log table schema
- `src/sohnbot/persistence/audit.py`: Existing log_operation_start and log_operation_end
- `src/sohnbot/gateway/commands.py`: Existing command handlers
- `src/sohnbot/runtime/mcp_tools.py`: Existing MCP tools
- `_bmad-output/planning-artifacts/epics.md`: Epic 6 requirements (lines 1233-1256)

---

## Dev Agent Record

### Agent Model Used
- GPT-5 Codex (CLI)

### Debug Log References
- `.venv/bin/pytest -q tests/unit/test_operation_logs.py tests/unit/test_commands.py tests/unit/test_telegram_client.py tests/unit/test_mcp_tools.py tests/unit/test_main.py tests/unit/test_executor.py tests/unit/test_broker.py tests/integration/test_logs_query_flow.py`

### Completion Notes
- Added `src/sohnbot/persistence/operation_logs.py` with filterable query support (`hours`, `capability`, `status`, `chat_id`, `tier`, `limit`), local ISO timestamp formatting, JSON field decoding, and 90-day cleanup helper.
- Added `/logs [hours]` command handler in `src/sohnbot/gateway/commands.py` with range validation (1-720), empty-state message, and formatted status/error/file output capped to 50 rows.
- Wired Telegram command registration and handler in `src/sohnbot/gateway/telegram_client.py` (`/logs` now available for authorized chats).
- Added `observe__logs` MCP tool in `src/sohnbot/runtime/mcp_tools.py` routing through broker capability `observe/logs` (no direct DB access from tool).
- Extended broker to validate and execute `observe/logs` via persistence query helper.
- Added weekly cleanup scheduling support by:
  - allowing `cleanup_operation_logs` scheduler action (`job_manager.py`)
  - dispatching cleanup action in scheduler executor
  - auto-creating default `"Operation Logs Cleanup"` job on startup in `main.py`.
- Updated SDK allowed tools to include `mcp__sohnbot__observe__logs`.
- Added/updated unit and integration tests for persistence queries/cleanup, `/logs` command, Telegram command handler, MCP tool schema/route, broker route, main startup initialization, scheduler cleanup dispatch, and logs flow integration.
- Addressed AI review action items: narrowed exception handling in `/logs` command, broker config fallback, and Telegram `/logs` DB path lookup; added broker filter validation (`capability`, `status`, `chat_id`, `tier`) and MCP filter type coercion/validation.
- Documented execution_log status support (`postponed`, `cancelled`) and improved status-filter validation error message consistency.

### File List
- src/sohnbot/persistence/operation_logs.py (new)
- src/sohnbot/persistence/__init__.py (updated exports)
- src/sohnbot/gateway/commands.py
- src/sohnbot/gateway/telegram_client.py
- src/sohnbot/broker/router.py
- src/sohnbot/broker/operation_classifier.py
- src/sohnbot/runtime/mcp_tools.py
- src/sohnbot/runtime/agent_session.py
- src/sohnbot/capabilities/scheduler/job_manager.py
- src/sohnbot/capabilities/scheduler/executor.py
- src/sohnbot/main.py
- tests/unit/test_operation_logs.py (new)
- tests/integration/test_logs_query_flow.py (new)
- tests/unit/test_commands.py
- tests/unit/test_telegram_client.py
- tests/unit/test_mcp_tools.py
- tests/unit/test_main.py
- tests/unit/test_executor.py
- tests/unit/test_broker.py
- src/sohnbot/config/registry.py (carried-over Story 6.3 fix, included for commit/file-list completeness)
- tests/unit/test_config_registry.py (carried-over Story 6.3 fix, included for commit/file-list completeness)

---

## Critical Notes for Dev Agent

1. **No Migration Needed**
   - execution_log table already exists from migration 0001_init.sql
   - DO NOT create a new migration for this story

2. **Reuse Existing Table**
   - Use existing execution_log table with current schema
   - All fields needed already exist

3. **Import Pattern**
   - Import from `..persistence.operation_logs` in commands.py
   - Import from `..persistence.operation_logs` in mcp_tools.py
   - Import from `...persistence.operation_logs` in scheduler.py (note: 3 dots)

4. **Query Performance**
   - Existing `idx_execution_log_timestamp` index handles time range queries
   - No new indexes needed
   - Always order by timestamp DESC for latest-first results

5. **Cleanup Job Registration**
   - Add job dict to scheduler job list in scheduler.py
   - Cron: "0 3 * * 0" (Sunday 3am UTC)
   - Timeout: 300 seconds
   - retention_days: 90 (hardcoded per NFR-021)

6. **Error Handling**
   - Catch `aiosqlite.Error` specifically
   - Log errors with structlog
   - Return gracefully (don't crash on DB errors)

7. **Testing Strategy**
   - Use tmp_path fixture with apply_migrations
   - Insert test data directly to execution_log
   - Verify query filters work correctly
   - Verify cleanup deletes only old logs

8. **Message Formatting**
   - Use emoji for status: ✅ completed, ❌ failed, ⏳ in_progress
   - Limit Telegram results to 50 operations
   - Include "... and N more operations" if >50 results
   - Use ISO 8601 timestamp format: YYYY-MM-DD HH:MM:SS UTC

9. **MCP Tool Integration**
   - Follow existing observe tool pattern
   - Use _as_mcp_text() helper for response formatting
   - Limit MCP results to 100 operations
   - Get db_path from config.get("database.path")

10. **Command Registration**
    - Register in message_router.py command routing
    - Pass db_path from config to handler
    - Handle command with and without parameters

