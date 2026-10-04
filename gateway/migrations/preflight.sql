-- Read-only preflight BEFORE applying 0001-search-and-evidence.sql.
-- This is an estimate, never an account-wide quota reading or billing promise.
SELECT 'position_rows' AS source_table,COUNT(*) AS nominal_rows,
 COUNT(*)*4 AS planned_btree_index_entries,COUNT(*)*32 AS conservative_fts_backfill_allowance
 FROM position_rows
UNION ALL
SELECT 'position_entries',COUNT(*),COUNT(*)*4,COUNT(*)*32 FROM position_entries;
SELECT name FROM sqlite_schema WHERE type='index' AND name LIKE 'position_%';
