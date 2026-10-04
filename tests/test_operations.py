import importlib.util
import json
import os
import subprocess
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


class OperationsTests(unittest.TestCase):
    def operations(self):
        self.assertIsNotNone(importlib.util.find_spec('bolsa_abierta.operations'),
                             'metadata-only operations implementation is required')
        from bolsa_abierta import operations
        return operations

    def test_native_schedule_has_intervals_but_no_invented_causal_lag(self):
        operations = self.operations()
        state = operations.start_run({}, run_id='1', code_sha='a' * 40,
                                     trigger='schedule', now='2026-10-04T00:17:00Z')
        state = operations.finish_run(state, '1', status='success', now='2026-10-04T00:18:00Z')
        state = operations.start_run(state, run_id='2', code_sha='a' * 40,
                                     trigger='schedule', now='2026-10-04T02:47:00Z')
        public = operations.public_summary(state)
        self.assertEqual(public['cadence']['median_run_interval_seconds'], 9000)
        self.assertIsNone(public['cadence']['median_scheduled_lag_seconds'])
        self.assertEqual(public['cadence']['known_scheduled_runs'], 0)
        self.assertIsNone(state['runs'][0]['scheduled_at'])
        self.assertEqual(public['trial']['nominal_windows'], 672)
        self.assertEqual(public['trial']['status'], 'collecting')
        self.assertIsNone(public['trial']['acceptance_met'])

    def test_known_worker_schedule_is_preserved_and_lag_is_computed(self):
        operations = self.operations()
        state = operations.start_run({}, run_id='8', code_sha='b' * 40,
            trigger='worker_cron', now='2026-10-04T00:18:00Z',
            scheduled_at='2026-10-04T00:17:00Z', clock_received_at='2026-10-04T00:17:01Z',
            dispatch_at='2026-10-04T00:17:02Z', request_id='c' * 32)
        self.assertEqual(operations.public_summary(state)['cadence']['median_scheduled_lag_seconds'], 60)
        self.assertEqual(state['runs'][0]['request_id'], 'c' * 32)

    def test_worker_subsecond_start_does_not_drop_known_schedule(self):
        operations = self.operations()
        state = operations.start_run({}, run_id='9', trigger='worker_cron',
            now='2026-10-04T00:17:00.250Z', scheduled_at='2026-10-04T00:17:00Z')
        cadence = operations.public_summary(state)['cadence']
        self.assertEqual(cadence['known_scheduled_runs'], 1)
        self.assertEqual(cadence['median_scheduled_lag_seconds'], 0.25)

    def test_retention_remains_bounded_without_resetting_trial_start(self):
        operations = self.operations()
        state = {}
        origin = datetime(2026, 10, 4, tzinfo=timezone.utc)
        for i in range(operations.MAX_RUNS + 3):
            state = operations.start_run(state, run_id=str(i), code_sha='a' * 40,
                trigger='schedule', now=(origin + timedelta(minutes=30 * i)).isoformat())
        self.assertLessEqual(len(state['runs']), operations.MAX_RUNS)
        self.assertEqual(state['trial']['started_at'], '2026-10-04T00:00:00Z')
        self.assertGreater(state['retention']['discarded_runs'], 0)
        self.assertEqual(operations.public_summary(state)['trial']['status'], 'evaluation_pending')
        self.assertIsNone(operations.public_summary(state)['trial']['acceptance_met'])

    def test_public_summary_drops_untrusted_text_nested_rows_and_tokens(self):
        operations = self.operations()
        state = operations.start_run({}, run_id='3', code_sha='a' * 40, trigger='schedule', now='2026-10-04T00:17:00Z')
        state['secret'] = 'PRIVATE_VALUE'
        state['runs'][0]['exception'] = 'PRIVATE_VALUE'
        state['runs'][0]['phases'] = {'inventory': {'status': 'PRIVATE_VALUE', 'rows': [{'name': 'PRIVATE_VALUE'}]}}
        state['trial']['notes'] = 'PRIVATE_VALUE'
        text = json.dumps(operations.public_summary(state))
        self.assertNotIn('PRIVATE_VALUE', text)
        self.assertNotIn('rows', text)
        self.assertNotIn('exception', text)

    def test_phase_wrapper_records_start_end_and_actual_failure_without_output(self):
        self.operations()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'operations.json'
            env = {**os.environ, 'GITHUB_RUN_ID': '55', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a' * 40, 'GITHUB_EVENT_NAME': 'workflow_dispatch'}
            result = subprocess.run([sys.executable, '-m', 'bolsa_abierta.operations', '--state', str(path),
                'run', '--phase', 'positions', '--', sys.executable, '-c',
                'import sys; print("PRIVATE_NOMINAL_ROW"); print("SECRET", file=sys.stderr); sys.exit(2)'],
                env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('PRIVATE_NOMINAL_ROW', result.stdout + result.stderr)
            self.assertNotIn('SECRET', result.stdout + result.stderr)
            state = json.loads(path.read_text())
            phase = state['runs'][0]['phases']['positions']
            self.assertEqual(phase['status'], 'pending_budget')
            self.assertEqual(phase['exit_code'], 2)
            self.assertIsNotNone(phase['started_at'])
            self.assertIsNotNone(phase['ended_at'])
            self.assertGreaterEqual(phase['elapsed_seconds'], 0)
            self.assertNotIn('PRIVATE_NOMINAL_ROW', json.dumps(state))

    def test_populated_btree_migration_plan_preserves_core_and_allows_progress(self):
        operations = self.operations()
        self.assertTrue(hasattr(operations, 'split_migration_indexes'), 'bounded per-index migration is required')
        source = (Path(__file__).resolve().parents[1] / 'gateway/migrations/0001-search-and-evidence.sql').read_text()
        core, indexes = operations.split_migration_indexes(source)
        self.assertEqual(len(indexes), 8)
        with sqlite3.connect(':memory:') as db:
            db.executescript(core)
            names = {row[0] for row in db.execute('SELECT name FROM sqlite_schema')}
            self.assertIn('position_entries_fts', names)
            self.assertFalse(any(index['name'] in names for index in indexes))
            db.executescript(indexes[0]['sql'])
            names = {row[0] for row in db.execute('SELECT name FROM sqlite_schema')}
            self.assertIn(indexes[0]['name'], names)
            self.assertFalse(any(index['name'] in names for index in indexes[1:]))

    def test_per_index_migration_resumes_next_day_without_dropping_generations(self):
        operations = self.operations()
        self.assertTrue(hasattr(operations, 'prepare_gateway_migration'), 'daily resumable migration runner is required')
        source = (Path(__file__).resolve().parents[1] / 'gateway/migrations/0001-search-and-evidence.sql').read_text()
        core, indexes = operations.split_migration_indexes(source)
        with sqlite3.connect(':memory:') as db:
            db.executescript(core)
            db.execute("INSERT INTO position_versions(id,metadata) VALUES('retained','{}')")
            for table in ('position_rows', 'position_entries'):
                db.executemany(f'INSERT INTO {table}(version_id,id,specialty,list_number,search_name,rank,payload) VALUES(?,?,?,?,?,?,?)',
                    [('retained', str(i), '0597', '2000000', 'synthetic', i+1, '{}') for i in range(500)])
            def execute(sql):
                if sql.lstrip().upper().startswith('SELECT'):
                    cursor = db.execute(sql)
                    return [{'results': [dict(zip([d[0] for d in cursor.description], row)) for row in cursor.fetchall()]}]
                db.executescript(sql)
                if '\nSELECT r.id AS id' in sql:
                    cursor = db.execute(sql[sql.index('\nSELECT r.id AS id'):].strip())
                    return [{'results': [dict(zip([d[0] for d in cursor.description], row)) for row in cursor.fetchall()]}]
                return [{'results': []}]
            first = operations.prepare_gateway_migration(execute, source, 'ddl:3:1', limit=1500)
            self.assertEqual(first['status'], 'pending_budget')
            self.assertGreater(first['created_indexes'], 0)
            self.assertGreater(first['remaining_indexes'], 0)
            before = first['remaining_indexes']
            db.execute("UPDATE position_write_allocations SET day=date('now','-1 day')")
            db.execute("UPDATE position_write_reservations SET day=date('now','-1 day')")
            second = operations.prepare_gateway_migration(execute, source, 'ddl:4:1', limit=1500)
            self.assertLess(second['remaining_indexes'], before)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM position_rows').fetchone()[0], 500)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM position_entries').fetchone()[0], 500)

    def correlated_run(self, operations, request_id='a' * 32):
        evidence = operations.start_run({}, run_id='1', request_id=request_id, now='2026-10-04T00:17:00Z')
        run = evidence['runs'][0]
        run.update(status='success', ended_at='2026-10-04T00:19:00Z')
        run['phases'] = {phase: {'status': 'success', 'started_at': '2026-10-04T00:17:20Z',
                                'ended_at': '2026-10-04T00:18:00Z'} for phase in operations.PHASES}
        return evidence

    def test_gateway_completion_correlation_does_not_acknowledge_partial_source_phases(self):
        operations = self.operations()
        state = {'freshness': {'request_id': 'a' * 32, 'status': 'completed',
                              'last_attempt_at': '2026-10-04T00:17:30Z'},
                 'documents': [{'name': 'PRIVATE_NOMINAL_ROW'}]}
        evidence = self.correlated_run(operations)
        evidence['runs'][0]['status'] = 'partial'
        result = operations.gateway_status(state, evidence)
        self.assertEqual(result['freshness']['status'], 'partial')
        self.assertNotIn('PRIVATE_NOMINAL_ROW', json.dumps(result))
        evidence['runs'][0]['status'] = 'success'
        self.assertEqual(operations.gateway_status(state, evidence)['freshness']['status'], 'completed')

    def test_gateway_correlation_rejects_missing_different_and_stale_request_evidence(self):
        operations = self.operations()
        state = {'freshness': {'request_id': 'a' * 32, 'status': 'completed',
                              'last_attempt_at': '2026-10-04T00:17:30Z'}}
        for identifier, attempt in ((None, '2026-10-04T00:17:30Z'),
                                    ('b' * 32, '2026-10-04T00:17:30Z'),
                                    ('a' * 32, '2026-10-04T00:16:59Z'),
                                    ('a' * 32, '2026-10-04T00:17:02Z'),
                                    ('a' * 32, '2026-10-04T00:20:00Z')):
            with self.subTest(identifier=identifier, attempt=attempt):
                evidence = self.correlated_run(operations, request_id=identifier)
                state['freshness']['last_attempt_at'] = attempt
                result = operations.gateway_status(state, evidence)['freshness']
                self.assertNotEqual(result['status'], 'completed')
                self.assertIsNone(result['request_id'], 'unrelated runs must not publish old terminal request IDs')

    def test_migration_reservation_respects_legacy_usage_carry_and_future_day(self):
        operations = self.operations()
        self.assertTrue(hasattr(operations, 'migration_reservation_sql'), 'DB UTC migration reservations are required')
        bootstrap = (Path(__file__).resolve().parents[1] / 'gateway/migrations/budget-bootstrap.sql').read_text()
        for obstruction in ('legacy', 'carry', 'future'):
            with self.subTest(obstruction=obstruction), sqlite3.connect(':memory:') as db:
                db.executescript(bootstrap)
                if obstruction == 'legacy':
                    db.execute("UPDATE position_write_budget SET day=date('now'),writes=66000 WHERE singleton=1")
                elif obstruction == 'carry':
                    db.execute("INSERT INTO position_write_reservations VALUES('old',date('now','-1 day'),66000,0)")
                else:
                    db.execute("INSERT INTO position_write_allocations VALUES('future',date('now','+1 day'),1)")
                db.executescript(operations.migration_reservation_sql('ddl:1:1', 5000, 70000))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM position_write_reservations WHERE id='ddl:1:1'").fetchone()[0], 0)

    def test_expired_migration_cannot_resume_or_charge_full_estimate_to_today(self):
        operations = self.operations()
        bootstrap = (Path(__file__).resolve().parents[1] / 'gateway/migrations/budget-bootstrap.sql').read_text()
        with sqlite3.connect(':memory:') as db:
            db.executescript(bootstrap)
            db.executescript(operations.migration_reservation_sql('ddl:8:1', 15000))
            db.execute("UPDATE position_write_reservation_leases SET expires_at=unixepoch('now')-86400")
            db.execute("UPDATE position_write_reservations SET day=date('now','-2 day')")
            db.execute("UPDATE position_write_allocations SET day=date('now','-2 day')")
            sql = operations.migration_reservation_sql('ddl:8:1', 15000)
            db.executescript(sql)
            select = 'SELECT ' + sql.rsplit('\nSELECT ', 1)[1].strip()
            self.assertIsNone(db.execute(select).fetchone(), 'expired DDL must never resume')
            db.executescript(operations.migration_settlement_sql('ddl:8:1'))
            self.assertLessEqual(db.execute('SELECT writes FROM position_write_usage').fetchone()[0], 100)
            self.assertEqual(db.execute("SELECT charged FROM position_write_allocations WHERE day=date('now','-1 day')").fetchone()[0], 15000)

    def test_migration_reservation_is_idempotent_and_settles_without_refund(self):
        operations = self.operations()
        self.assertTrue(hasattr(operations, 'migration_reservation_sql'), 'DB UTC migration reservations are required')
        bootstrap = (Path(__file__).resolve().parents[1] / 'gateway/migrations/budget-bootstrap.sql').read_text()
        with sqlite3.connect(':memory:') as db:
            db.executescript(bootstrap)
            db.execute("UPDATE position_write_budget SET day=date('now'),writes=35000 WHERE singleton=1")
            sql = operations.migration_reservation_sql('ddl:2:1', 15000, 70000)
            db.executescript(sql)
            db.executescript(sql)
            self.assertEqual(db.execute('SELECT writes FROM position_write_usage').fetchone()[0], 50000)
            db.executescript(operations.migration_settlement_sql('ddl:2:1'))
            self.assertEqual(db.execute('SELECT writes FROM position_write_usage').fetchone()[0], 50000)
            self.assertEqual(db.execute("SELECT settled FROM position_write_reservations WHERE id='ddl:2:1'").fetchone()[0], 1)

    def test_cached_position_evidence_exit_three_is_partial_and_propagated(self):
        self.operations()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'operations.json'
            result = subprocess.run([sys.executable, '-m', 'bolsa_abierta.operations', '--state', str(path),
                'run', '--phase', 'positions', '--', sys.executable, '-c', 'raise SystemExit(3)'],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 3)
            phase = json.loads(path.read_text())['runs'][0]['phases']['positions']
            self.assertEqual(phase['status'], 'partial')
            self.assertEqual(phase['exit_code'], 3)

    def test_archive_allowlist_authenticates_bundles_and_never_returns_plaintext(self):
        operations = self.operations()
        self.assertTrue(hasattr(operations, 'validated_archive_paths'), 'authenticated persistence allowlist is required')
        from bolsa_abierta.private_archive import export_bundle
        import base64, hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / 'private'
            private.mkdir()
            content = b'%PDF-synthetic PRIVATE_NOMINAL_ROW'
            (private / (hashlib.sha256(content).hexdigest() + '.pdf')).write_bytes(content)
            key = base64.b64encode(b'k' * 32).decode()
            archive = root / 'archive'
            exported = export_bundle(private, archive, key=key)
            (archive / 'plaintext.pdf').write_bytes(content)
            (archive / 'metadata.json').write_text('PRIVATE_NOMINAL_ROW')
            paths = operations.validated_archive_paths(archive, key=key)
            self.assertEqual(paths, [Path(exported['path'])])
            self.assertTrue(all(path.suffix == '.baenc' for path in paths))
            bundle = paths[0]
            encrypted = bytearray(bundle.read_bytes())
            encrypted[-1] ^= 1
            bundle.write_bytes(encrypted)
            with self.assertRaises(ValueError):
                operations.validated_archive_paths(archive, key=key)

    def test_zero_exit_partial_vacancy_capture_is_partial_without_publishing_rows(self):
        self.operations()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / 'operations.json'
            database = Path(directory) / 'state.sqlite3'
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE state(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
                db.execute('INSERT INTO state VALUES(1, ?)', (json.dumps({
                    'freshness': {'status': 'partial'}, 'documents': [{'name': 'PRIVATE_NOMINAL_ROW'}],
                    'current_id': 'previous_good_generation'}),))
            before = database.read_bytes()
            env = {**os.environ, 'GITHUB_RUN_ID': '56', 'GITHUB_RUN_ATTEMPT': '1'}
            result = subprocess.run([sys.executable, '-m', 'bolsa_abierta.operations', '--state', str(state_path),
                'run', '--phase', 'vacancies', '--freshness-db', str(database), '--',
                sys.executable, '-c', 'pass'], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, 'the command actual exit must still propagate')
            phase = json.loads(state_path.read_text())['runs'][0]['phases']['vacancies']
            self.assertEqual(phase['exit_code'], 0)
            self.assertEqual(phase['status'], 'partial')
            self.assertEqual(database.read_bytes(), before, 'diagnostic read must preserve usable source state')
            self.assertNotIn('PRIVATE_NOMINAL_ROW', state_path.read_text() + result.stdout + result.stderr)

    def test_failed_start_and_interrupted_run_do_not_claim_success(self):
        operations = self.operations()
        state = operations.start_run({}, run_id='1', code_sha='a' * 40, trigger='schedule', now='2026-10-04T00:17:00Z')
        self.assertEqual(state['runs'][0]['status'], 'running')
        self.assertIsNone(state['runs'][0]['ended_at'])
        self.assertEqual(operations.public_summary(state)['run_counts']['success'], 0)


if __name__ == '__main__':
    unittest.main()
