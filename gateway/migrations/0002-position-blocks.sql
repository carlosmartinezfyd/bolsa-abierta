-- Private immutable snapshots; one indexed D1 row per ID-prefix bucket.
CREATE TABLE IF NOT EXISTS position_staging_revisions(version_id TEXT PRIMARY KEY,revision INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS position_search_status(version_id TEXT PRIMARY KEY REFERENCES position_versions(id),ready INTEGER NOT NULL DEFAULT 0 CHECK(ready IN(0,1)),after_rowid INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS position_ingest_metrics(version_id TEXT PRIMARY KEY,started_at TEXT NOT NULL,updated_at TEXT NOT NULL,phase TEXT NOT NULL,rows_written INTEGER NOT NULL DEFAULT 0,failure_status TEXT);
CREATE TABLE IF NOT EXISTS position_block_versions(
 version_id TEXT PRIMARY KEY REFERENCES position_versions(id)
);
CREATE TABLE IF NOT EXISTS position_blocks(
 version_id TEXT NOT NULL REFERENCES position_block_versions(version_id),
 bucket TEXT NOT NULL CHECK(length(bucket)=2 AND bucket NOT GLOB '*[^a-f0-9]*'),
 payload TEXT NOT NULL CHECK(json_valid(payload) AND json_type(payload)='array'),
 PRIMARY KEY(version_id,bucket)
);
CREATE TRIGGER IF NOT EXISTS position_blocks_revision AFTER INSERT ON position_blocks BEGIN
 INSERT INTO position_staging_revisions(version_id,revision) VALUES(new.version_id,1)
 ON CONFLICT(version_id) DO UPDATE SET revision=revision+1;
END;
CREATE VIEW IF NOT EXISTS position_block_rows AS SELECT b.version_id,b.bucket,
 json_extract(j.value,'$.id') AS id,json_extract(j.value,'$.specialty') AS specialty,
 json_extract(j.value,'$.list_number') AS list_number,json_extract(j.value,'$.search_name') AS search_name,
 json_extract(j.value,'$.rank') AS rank,json_remove(j.value,'$.search_name') AS payload
 FROM position_blocks b,json_each(b.payload) j;
CREATE TABLE IF NOT EXISTS position_read_budget(day TEXT PRIMARY KEY,used INTEGER NOT NULL CHECK(used>=0),requests INTEGER NOT NULL DEFAULT 0);
