-- Derived, versioned index; references cannot outlive their immutable source.
CREATE TABLE IF NOT EXISTS position_search_blocks(
 version_id TEXT NOT NULL, bucket TEXT NOT NULL,
 payload TEXT NOT NULL CHECK(json_valid(payload) AND json_type(payload)='object'),
 PRIMARY KEY(version_id,bucket),
 FOREIGN KEY(version_id,bucket) REFERENCES position_blocks(version_id,bucket) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS position_search_complete(
 version_id TEXT PRIMARY KEY REFERENCES position_versions(id) ON DELETE CASCADE,
 format INTEGER NOT NULL DEFAULT 1 CHECK(format=1)
);
CREATE TABLE IF NOT EXISTS position_client_budget(
 day TEXT NOT NULL,client TEXT NOT NULL,requests INTEGER NOT NULL,
 PRIMARY KEY(day,client)
);
