-- All timestamps are UTC epoch milliseconds. A single row serializes dispatch quota.
CREATE TABLE IF NOT EXISTS gateway_gate (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    job_id TEXT,
    created_at INTEGER NOT NULL DEFAULT 0,
    lease_until INTEGER NOT NULL DEFAULT 0,
    cooldown_until INTEGER NOT NULL DEFAULT 0,
    day TEXT NOT NULL DEFAULT '',
    dispatches INTEGER NOT NULL DEFAULT 0 CHECK (dispatches >= 0)
);
INSERT OR IGNORE INTO gateway_gate (singleton) VALUES (1);

CREATE TABLE IF NOT EXISTS gateway_jobs (
    id TEXT PRIMARY KEY CHECK (length(id) = 32 AND id NOT GLOB '*[^a-f0-9]*'),
    created_at INTEGER NOT NULL,
    deadline INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','completed','partial','failed')),
    message TEXT NOT NULL,
    poll_until INTEGER NOT NULL DEFAULT 0,
    completed_at INTEGER
);
CREATE INDEX IF NOT EXISTS gateway_jobs_created_at ON gateway_jobs(created_at);
