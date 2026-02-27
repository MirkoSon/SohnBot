-- Extend execution_log status enum with postponed/cancelled lifecycle states.

CREATE TABLE IF NOT EXISTS execution_log_new (
    operation_id TEXT PRIMARY KEY,
    timestamp INTEGER NOT NULL,
    capability TEXT NOT NULL,
    action TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    tier INTEGER NOT NULL CHECK(tier IN (0, 1, 2, 3)),
    status TEXT NOT NULL CHECK(status IN ('in_progress', 'completed', 'failed', 'postponed', 'cancelled')),
    file_paths TEXT,
    snapshot_ref TEXT,
    duration_ms INTEGER,
    error_details TEXT,
    details TEXT
) STRICT;

INSERT INTO execution_log_new (
    operation_id, timestamp, capability, action, chat_id, tier, status, file_paths, snapshot_ref, duration_ms, error_details, details
)
SELECT
    operation_id, timestamp, capability, action, chat_id, tier, status, file_paths, snapshot_ref, duration_ms, error_details, details
FROM execution_log;

DROP TABLE execution_log;
ALTER TABLE execution_log_new RENAME TO execution_log;

CREATE INDEX IF NOT EXISTS idx_execution_log_status_timestamp
    ON execution_log(status, timestamp);

CREATE INDEX IF NOT EXISTS idx_execution_log_operation_id
    ON execution_log(operation_id);

CREATE INDEX IF NOT EXISTS idx_execution_log_timestamp
    ON execution_log(timestamp);
