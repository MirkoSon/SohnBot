-- Daily search volume tracking for soft alerting.
-- Story 6.3: Search Volume Monitoring

CREATE TABLE IF NOT EXISTS daily_search_volume (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE, -- YYYY-MM-DD (UTC)
    search_count INTEGER NOT NULL DEFAULT 0 CHECK(search_count >= 0),
    alert_sent INTEGER NOT NULL DEFAULT 0 CHECK(alert_sent IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_daily_search_volume_date
ON daily_search_volume(date DESC);
