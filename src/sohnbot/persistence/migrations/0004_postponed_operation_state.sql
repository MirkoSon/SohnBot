-- Persist postponed operation state for restart-safe ambiguity handling.

CREATE TABLE IF NOT EXISTS postponed_operation (
    operation_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    original_prompt TEXT NOT NULL,
    option_a TEXT NOT NULL,
    option_b TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('waiting', 'postponed', 'resolved', 'cancelled')),
    clarification_response TEXT,
    retry_enqueued INTEGER NOT NULL DEFAULT 0 CHECK(retry_enqueued IN (0, 1)),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    clarification_deadline_at INTEGER,
    retry_at INTEGER,
    cancel_at INTEGER,
    FOREIGN KEY (operation_id) REFERENCES execution_log(operation_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_postponed_operation_chat_status
    ON postponed_operation(chat_id, status, updated_at);

CREATE INDEX IF NOT EXISTS idx_postponed_operation_status_timing
    ON postponed_operation(status, retry_at, cancel_at);
