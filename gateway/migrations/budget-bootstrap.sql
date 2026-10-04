-- Small additive bootstrap, before reserving large DDL.
CREATE TABLE IF NOT EXISTS position_write_budget(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), day TEXT NOT NULL, writes INTEGER NOT NULL DEFAULT 0 CHECK(writes>=0)
);
INSERT OR IGNORE INTO position_write_budget(singleton,day,writes) VALUES(1,'',0);
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
