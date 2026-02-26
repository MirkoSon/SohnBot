-- Initial schema migration for SohnBot
-- Creates execution_log, config, and schema_migrations tables
-- All tables use STRICT mode for type safety

-- execution_log: Audit trail for all operations (90-day retention)
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

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_execution_log_status_timestamp
    ON execution_log(status, timestamp);

CREATE INDEX IF NOT EXISTS idx_execution_log_operation_id
    ON execution_log(operation_id);

CREATE INDEX IF NOT EXISTS idx_execution_log_timestamp
    ON execution_log(timestamp);

-- config: Dynamic configuration storage (hot-reloadable settings)
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL,
    updated_by TEXT,
    tier TEXT CHECK(tier IN ('static', 'dynamic'))
) STRICT;

-- schema_migrations: Track applied migrations with checksums
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_name TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at INTEGER NOT NULL
) STRICT;
