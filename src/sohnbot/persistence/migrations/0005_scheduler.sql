-- Scheduler foundation for recurring autonomous jobs.
-- Adds durable job definitions with strict validation for safe execution.

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    cron_expr TEXT NOT NULL,
    timezone TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('agent_query', 'profile_execute', 'heartbeat')),
    action_params TEXT,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    created_at INTEGER NOT NULL,
    last_completed_slot INTEGER
) STRICT;

-- Optimize common lookups for enabled jobs and deterministic listing by name.
CREATE INDEX IF NOT EXISTS idx_jobs_enabled_name ON jobs(enabled, name);
