CREATE TABLE IF NOT EXISTS gateway_watchdog(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),lease_until INTEGER NOT NULL DEFAULT 0,
 observed_at INTEGER, status TEXT NOT NULL DEFAULT 'unobserved',issues TEXT NOT NULL DEFAULT '[]',
 first_failure INTEGER,last_good INTEGER,next_retry INTEGER NOT NULL DEFAULT 0,
 day TEXT NOT NULL DEFAULT '',retries INTEGER NOT NULL DEFAULT 0,request_id TEXT,
 dispatch_status TEXT NOT NULL DEFAULT 'none'
);
INSERT OR IGNORE INTO gateway_watchdog(singleton) VALUES(1);
