-- Personal rosters are stored privately in D1, never in the Pages snapshot.
CREATE TABLE IF NOT EXISTS position_versions (
  id TEXT PRIMARY KEY,
  metadata TEXT NOT NULL,
  ready INTEGER NOT NULL DEFAULT 0 CHECK (ready IN (0,1))
);

-- Separate table keeps previously deployed generations readable during rollout.
-- A NULL rank is a sourced fact, never an inferred position.
CREATE TABLE IF NOT EXISTS position_entries (
  version_id TEXT NOT NULL REFERENCES position_versions(id),
  id TEXT NOT NULL,
  specialty TEXT NOT NULL,
  list_number TEXT NOT NULL,
  search_name TEXT NOT NULL,
  rank INTEGER CHECK (rank IS NULL OR rank>0),
  payload TEXT NOT NULL,
  PRIMARY KEY (version_id,id),
  UNIQUE (version_id,specialty,rank)
);
CREATE TABLE IF NOT EXISTS position_active (
  singleton INTEGER PRIMARY KEY CHECK (singleton=1),
  version_id TEXT NOT NULL REFERENCES position_versions(id)
);
CREATE TABLE IF NOT EXISTS position_rows (
  version_id TEXT NOT NULL REFERENCES position_versions(id),
  id TEXT NOT NULL,
  specialty TEXT NOT NULL,
  list_number TEXT NOT NULL,
  search_name TEXT NOT NULL,
  rank INTEGER NOT NULL CHECK (rank>0),
  payload TEXT NOT NULL,
  PRIMARY KEY (version_id,id),
  UNIQUE (version_id,specialty,rank)
);

-- Indexed exact list-number lookup and stable scope/name ordering.
CREATE INDEX IF NOT EXISTS position_rows_version ON position_rows(version_id);
CREATE INDEX IF NOT EXISTS position_rows_number ON position_rows(version_id,list_number,specialty,id);
CREATE INDEX IF NOT EXISTS position_rows_scope ON position_rows(version_id,specialty,rank,id);
CREATE INDEX IF NOT EXISTS position_rows_name ON position_rows(version_id,search_name,specialty,rank,id);
-- Names are already accent-folded by the ingestion whitelist.
CREATE VIRTUAL TABLE IF NOT EXISTS position_rows_fts USING fts5(
 search_name,version_id,content='position_rows',content_rowid='rowid',tokenize='trigram'
);
CREATE TABLE IF NOT EXISTS position_rows_search_indexed(row_id INTEGER PRIMARY KEY);
CREATE TRIGGER IF NOT EXISTS position_rows_search_marker AFTER INSERT ON position_rows_search_indexed BEGIN
 INSERT INTO position_rows_fts(rowid,search_name,version_id) SELECT rowid,search_name,version_id FROM position_rows WHERE rowid=new.row_id;
END;
CREATE TRIGGER IF NOT EXISTS position_rows_fts_insert AFTER INSERT ON position_rows BEGIN
 INSERT OR IGNORE INTO position_rows_search_indexed(row_id) VALUES(new.rowid);
END;
CREATE TRIGGER IF NOT EXISTS position_rows_fts_delete AFTER DELETE ON position_rows WHEN EXISTS(SELECT 1 FROM position_rows_search_indexed WHERE row_id=old.rowid) BEGIN
 INSERT INTO position_rows_fts(position_rows_fts,rowid,search_name,version_id) VALUES('delete',old.rowid,old.search_name,old.version_id);
 DELETE FROM position_rows_search_indexed WHERE row_id=old.rowid;
END;

-- Indexed exact list-number lookup and stable scope/name ordering.
CREATE INDEX IF NOT EXISTS position_entries_version ON position_entries(version_id);
CREATE INDEX IF NOT EXISTS position_entries_number ON position_entries(version_id,list_number,specialty,id);
CREATE INDEX IF NOT EXISTS position_entries_scope ON position_entries(version_id,specialty,rank,id);
CREATE INDEX IF NOT EXISTS position_entries_name ON position_entries(version_id,search_name,specialty,rank,id);
-- Names are already accent-folded by the ingestion whitelist.
CREATE VIRTUAL TABLE IF NOT EXISTS position_entries_fts USING fts5(
 search_name,version_id,content='position_entries',content_rowid='rowid',tokenize='trigram'
);
CREATE TABLE IF NOT EXISTS position_entries_search_indexed(row_id INTEGER PRIMARY KEY);
CREATE TRIGGER IF NOT EXISTS position_entries_search_marker AFTER INSERT ON position_entries_search_indexed BEGIN
 INSERT INTO position_entries_fts(rowid,search_name,version_id) SELECT rowid,search_name,version_id FROM position_entries WHERE rowid=new.row_id;
END;
CREATE TRIGGER IF NOT EXISTS position_entries_fts_insert AFTER INSERT ON position_entries BEGIN
 INSERT OR IGNORE INTO position_entries_search_indexed(row_id) VALUES(new.rowid);
END;
CREATE TRIGGER IF NOT EXISTS position_entries_fts_delete AFTER DELETE ON position_entries WHEN EXISTS(SELECT 1 FROM position_entries_search_indexed WHERE row_id=old.rowid) BEGIN
 INSERT INTO position_entries_fts(position_entries_fts,rowid,search_name,version_id) VALUES('delete',old.rowid,old.search_name,old.version_id);
 DELETE FROM position_entries_search_indexed WHERE row_id=old.rowid;
END;

-- Separate application write allowance; account-wide consumption remains external.
CREATE TABLE IF NOT EXISTS position_write_budget(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), day TEXT NOT NULL, writes INTEGER NOT NULL DEFAULT 0 CHECK(writes>=0)
);
INSERT OR IGNORE INTO position_write_budget(singleton,day,writes) VALUES(1,'',0);
CREATE TABLE IF NOT EXISTS position_ingest_metrics(
 version_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, updated_at TEXT NOT NULL, phase TEXT NOT NULL,
 rows_written INTEGER NOT NULL DEFAULT 0, failure_status TEXT
);

CREATE TABLE IF NOT EXISTS position_search_status(
 version_id TEXT PRIMARY KEY REFERENCES position_versions(id),ready INTEGER NOT NULL DEFAULT 0 CHECK(ready IN(0,1)),after_rowid INTEGER NOT NULL DEFAULT 0
);

-- Independent reservation/day allocations prevent stale callers resetting quota.
CREATE TABLE IF NOT EXISTS position_write_reservations(
 id TEXT PRIMARY KEY,day TEXT NOT NULL,reserved INTEGER NOT NULL CHECK(reserved>=0),
 settled INTEGER NOT NULL DEFAULT 0 CHECK(settled IN(0,1))
);
CREATE INDEX IF NOT EXISTS position_write_reservations_pending ON position_write_reservations(settled,day);
CREATE TABLE IF NOT EXISTS position_write_reservation_leases(id TEXT PRIMARY KEY,expires_at INTEGER NOT NULL);
CREATE TRIGGER IF NOT EXISTS position_write_reservation_lease AFTER INSERT ON position_write_reservations BEGIN
 INSERT INTO position_write_reservation_leases(id,expires_at) VALUES(new.id,unixepoch('now')+CASE WHEN new.id LIKE 'ddl:%' THEN 3600 ELSE 120 END);
END;
INSERT OR IGNORE INTO position_write_reservation_leases(id,expires_at)
 SELECT id,unixepoch('now')+CASE WHEN id LIKE 'ddl:%' THEN 3600 ELSE 120 END FROM position_write_reservations WHERE settled=0;

CREATE TABLE IF NOT EXISTS position_write_allocations(
 reservation_id TEXT NOT NULL,day TEXT NOT NULL,charged INTEGER NOT NULL CHECK(charged>=0),
 PRIMARY KEY(reservation_id,day)
);
CREATE INDEX IF NOT EXISTS position_write_allocations_day ON position_write_allocations(day);
DROP VIEW IF EXISTS position_write_usage;
CREATE VIEW position_write_usage AS SELECT date('now') AS day,
 COALESCE((SELECT SUM(charged) FROM position_write_allocations WHERE day=date('now')),0)
 +MAX(0,COALESCE((SELECT writes FROM position_write_budget WHERE singleton=1 AND day=date('now')),0)-COALESCE((SELECT charged FROM position_write_allocations WHERE reservation_id='legacy:'||date('now') AND day=date('now')),0))
 +COALESCE((SELECT SUM(reserved) FROM position_write_reservations r JOIN position_write_reservation_leases l ON l.id=r.id WHERE settled=0 AND r.day<date('now') AND date(l.expires_at,'unixepoch')>=date('now')
 AND NOT EXISTS(SELECT 1 FROM position_write_allocations a WHERE a.reservation_id=r.id AND a.day=date('now'))),0) AS writes;
-- Every accepted staging mutation invalidates an earlier validation snapshot.
CREATE TABLE IF NOT EXISTS position_staging_revisions(version_id TEXT PRIMARY KEY,revision INTEGER NOT NULL DEFAULT 0);
CREATE TRIGGER IF NOT EXISTS position_rows_revision_insert AFTER INSERT ON position_rows BEGIN
 INSERT INTO position_staging_revisions(version_id,revision) VALUES(new.version_id,1)
 ON CONFLICT(version_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER IF NOT EXISTS position_rows_revision_delete AFTER DELETE ON position_rows BEGIN
 INSERT INTO position_staging_revisions(version_id,revision) VALUES(old.version_id,1)
 ON CONFLICT(version_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER IF NOT EXISTS position_entries_revision_insert AFTER INSERT ON position_entries BEGIN
 INSERT INTO position_staging_revisions(version_id,revision) VALUES(new.version_id,1)
 ON CONFLICT(version_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER IF NOT EXISTS position_entries_revision_delete AFTER DELETE ON position_entries BEGIN
 INSERT INTO position_staging_revisions(version_id,revision) VALUES(old.version_id,1)
 ON CONFLICT(version_id) DO UPDATE SET revision=revision+1;
END;
