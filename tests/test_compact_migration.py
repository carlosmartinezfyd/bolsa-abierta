import sqlite3
import unittest
from pathlib import Path
from bolsa_abierta.operations import prepare_compact_gateway


class CompactMigrationTests(unittest.TestCase):
    def test_exact_deployment_schema_applies_and_is_idempotent(self):
        root = Path(__file__).resolve().parents[1] / 'gateway'
        source = '\n'.join([(root / 'schema.sql').read_text(),
            (root / 'positions.sql').read_text().split('-- Indexed exact')[0],
            (root / 'migrations/0002-position-blocks.sql').read_text()])
        with sqlite3.connect(':memory:') as db:
            db.executescript((root / 'migrations/budget-bootstrap.sql').read_text())
            def execute(sql):
                if sql.lstrip().upper().startswith('SELECT'):
                    cursor = db.execute(sql)
                else:
                    db.executescript(sql)
                    if '\nSELECT r.id AS id' not in sql:
                        return [{'results': []}]
                    cursor = db.execute(sql[sql.index('\nSELECT r.id AS id'):].strip())
                return [{'results': [dict(zip([d[0] for d in cursor.description], row)) for row in cursor.fetchall()]}]
            self.assertEqual(prepare_compact_gateway(execute, source, 'ddl:40:1')['status'], 'ready')
            count = db.execute('SELECT COUNT(*) FROM position_write_allocations').fetchone()[0]
            self.assertEqual(prepare_compact_gateway(execute, source, 'ddl:41:1')['status'], 'ready')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM position_write_allocations').fetchone()[0], count)
            self.assertIn('position_block_rows', {r[0] for r in db.execute('SELECT name FROM sqlite_schema')})
            self.assertNotIn('position_entries_fts', {r[0] for r in db.execute('SELECT name FROM sqlite_schema')})
