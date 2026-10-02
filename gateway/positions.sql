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
