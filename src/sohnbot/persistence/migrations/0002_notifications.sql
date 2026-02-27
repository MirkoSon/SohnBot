-- Notification outbox and per-chat notification preference storage

CREATE TABLE IF NOT EXISTS notification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'sent', 'failed')),
    message_text TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    sent_at INTEGER,
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
    error_details TEXT,
    FOREIGN KEY (operation_id) REFERENCES execution_log(operation_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_notification_outbox_status_created
    ON notification_outbox(status, created_at);
