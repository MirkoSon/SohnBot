-- Search cache table for Brave web search responses.
-- Story 6.1 foundation for cache + volume monitoring.

CREATE TABLE IF NOT EXISTS search_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_hash TEXT NOT NULL,
    query TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('fresh', 'static')),
    results_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_search_cache_query_hash
ON search_cache(query_hash);

CREATE INDEX IF NOT EXISTS idx_search_cache_expires_at
ON search_cache(expires_at);
