-- Add correlation_id to execution_log for request chain traceability.
ALTER TABLE execution_log ADD COLUMN correlation_id TEXT;

CREATE INDEX IF NOT EXISTS idx_execution_log_correlation_id
    ON execution_log(correlation_id);
