-- 0008_widen_jobs_action_check.sql
-- Widen jobs.action CHECK to include 'cleanup_operation_logs'.
-- SQLite requires table recreation for CHECK constraint changes.

CREATE TABLE jobs_new (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    cron_expr TEXT NOT NULL,
    timezone TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN (
        'agent_query', 'profile_execute', 'heartbeat', 'cleanup_operation_logs'
    )),
    action_params TEXT,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    created_at INTEGER NOT NULL,
    last_completed_slot INTEGER
) STRICT;

INSERT INTO jobs_new SELECT * FROM jobs;
DROP TABLE jobs;
ALTER TABLE jobs_new RENAME TO jobs;
CREATE INDEX IF NOT EXISTS idx_jobs_enabled_name ON jobs(enabled, name);
