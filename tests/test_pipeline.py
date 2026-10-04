import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from bolsa_abierta.store import Store, export_static
from bolsa_abierta.pipeline import run_refresh

SEED = Path(__file__).resolve().parents[1] / 'data/seed-state.json'
URL = 'https://www.carm.es/web/descarga?IDCONTENIDO=209318'


class Client:
    def __init__(self, body=b'%PDF-one', fail=False):
        self.body, self.fail = body, fail

    def fetch(self, url, **kwargs):
        if self.fail:
            raise ValueError('challenge')
        from types import SimpleNamespace
        return SimpleNamespace(body=self.body, final_url=url, status=200, headers={})


def discovery(client, known_notices=()):
    return {'complete': True, 'checks': [{'id': 'rss', 'success': True}],
            'notices': [{'id': 'notice', 'url': 'https://rrhheducacion.carm.es/example/',
                         'title': 'Vacantes', 'date': '2026-09-30', 'kind': 'vacancies', 'pdf_urls': [URL]}]}


def parse(body, source_url, retrieved_at):
    doc = copy.deepcopy(json.loads(SEED.read_text(encoding='utf-8'))['documents'][0])
    doc.update(id=hashlib.sha256(body).hexdigest(), sha256=hashlib.sha256(body).hexdigest(),
               published_at='2026-09-30T14:35:00+02:00', process_id='3133',
               source_url=source_url, retrieved_at=retrieved_at, provenance='official_download')
    return doc


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'runtime', SEED)

    def run_it(self, client=None, discover=discovery, parser=parse):
        return run_refresh(self.store, client=client or Client(), discover=discover, parser=parser)

    def test_valid_bytes_archived_and_idempotent(self):
        first = self.run_it()
        self.assertEqual(first['status'], 'completed')
        state = self.store.state()
        self.assertEqual(len(state['documents']), 3)
        self.assertIsNotNone(state['freshness']['last_success_at'])
        doc = state['documents'][0]
        self.assertEqual(self.store.artifact(doc['id']).read_bytes(), b'%PDF-one')
        self.run_it()
        self.assertEqual(len(self.store.state()['documents']), 3)

    def test_failure_preserves_rows_and_success_timestamp(self):
        self.run_it()
        before = self.store.state()
        result = self.run_it(Client(fail=True))
        after = self.store.state()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(after['documents'], before['documents'])
        self.assertEqual(after['freshness']['last_success_at'], before['freshness']['last_success_at'])
        self.assertEqual(after['catalog']['notices'][0]['status'], 'fetch_failed')

    def test_html_and_parse_failure_not_published(self):
        before = self.store.state()['current_id']
        self.run_it(Client(b'<html>challenge</html>'))
        self.assertEqual(self.store.state()['current_id'], before)
        def reject(*args):
            raise ValueError('template changed')
        self.run_it(parser=reject)
        self.assertEqual(self.store.state()['current_id'], before)
        digest = hashlib.sha256(b'%PDF-one').hexdigest()
        notice = self.store.state()['catalog']['notices'][0]
        self.assertEqual(notice['failed_document_id'], digest)
        self.assertEqual(notice['status'], 'extraction_failed')
        self.assertFalse(self.store.artifact(digest).exists())
        self.assertEqual(self.store.private_artifact(digest).read_bytes(), b'%PDF-one')
        self.assertNotIn(digest, [d['id'] for d in self.store.state()['documents']])

    def test_reopening_moves_old_unapproved_bytes_out_of_the_public_archive(self):
        digest = self.store.archive(b'%PDF-unapproved-legacy')
        self.assertTrue(self.store.artifact(digest).exists())
        reopened = Store(self.store.root, SEED)
        self.assertFalse(reopened.artifact(digest).exists())
        self.assertEqual(reopened.private_artifact(digest).read_bytes(), b'%PDF-unapproved-legacy')

    def test_parser_output_cannot_leak_names_into_public_diagnostics(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from bolsa_abierta.pipeline import isolated_parse
        with patch('bolsa_abierta.pipeline.subprocess.run', return_value=SimpleNamespace(
                returncode=1, stderr=b'Invalid row: PRIVATE PERSON ***1234**')):
            with self.assertRaises(ValueError) as caught:
                isolated_parse(b'%PDF-test', URL, '2026-10-04T12:00:00Z')
        self.assertNotIn('PRIVATE', str(caught.exception))
        self.assertNotIn('1234', str(caught.exception))

    def test_same_url_new_bytes_retains_both_revisions(self):
        self.run_it()
        first = self.store.state()['current_id']
        self.run_it(Client(b'%PDF-two'))
        state = self.store.state()
        self.assertEqual(len(state['documents']), 4)
        self.assertNotEqual(state['current_id'], first)
        self.assertEqual(state['previous_id'], json.loads(SEED.read_text(encoding='utf-8'))['current_id'])
        self.assertIn(first, [d['id'] for d in state['documents']])

    def test_partial_discovery_never_advances_complete_success(self):
        def partial(client, known_notices=()):
            value = discovery(client)
            value['complete'] = False
            return value
        self.assertEqual(self.run_it(discover=partial)['status'], 'partial')
        self.assertIsNone(self.store.state()['freshness']['last_success_at'])
        self.assertEqual(len(self.store.state()['documents']), 3)

    def test_discovery_exception_preserves_seed(self):
        def bad(*args, **kwargs):
            raise RuntimeError('offline')
        self.assertEqual(self.run_it(discover=bad)['status'], 'failed')
        self.assertEqual(len(self.store.state()['documents']), 2)

    def test_export_links_only_verified_archives(self):
        self.run_it()
        out = Path(self.temp.name) / 'site'
        export_static(self.store, out)
        state = json.loads((out / 'data/state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['capabilities']['source_check'], 'snapshot_only')
        self.assertTrue((out / state['documents'][0]['artifact_url']).exists())
        self.assertNotIn('artifact_url', state['documents'][-1])
        self.store.artifact(state['current_id']).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            export_static(self.store, out)

    def test_concurrent_job_claim_is_single_and_durable(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=20) as pool:
            values = list(pool.map(lambda _: self.store.claim_job(), range(20)))
        self.assertEqual(len({v[0]['id'] for v in values}), 1)
        self.assertEqual(sum(v[1] for v in values), 1)
        job = values[0][0]
        self.store.finish_job(job['id'], {'status': 'completed'})
        same, claimed = Store(self.store.root, SEED).claim_job()
        self.assertFalse(claimed)
        self.assertEqual(same['id'], job['id'])

    def test_new_runtime_bootstraps_exact_bundled_snapshot(self):
        self.run_it()
        out = Path(self.temp.name) / 'site'
        exported = export_static(self.store, out)
        restored = Store(Path(self.temp.name) / 'restored', out / 'data/state.json')
        self.assertEqual(restored.state()['current_id'], exported['current_id'])
        self.assertEqual(restored.verified_artifact(exported['current_id']).read_bytes(), b'%PDF-one')
        self.assertEqual(restored.state()['freshness'], exported['freshness'])

    def test_missing_approved_archive_blocks_export(self):
        self.run_it()
        self.store.artifact(self.store.state()['current_id']).unlink()
        with self.assertRaises(ValueError):
            export_static(self.store, Path(self.temp.name) / 'site')

    def test_known_historical_hash_must_still_be_parsed(self):
        state = self.store.state()
        digest = hashlib.sha256(b'%PDF-one').hexdigest()
        state['documents'][0]['id'] = digest
        state['documents'][0]['sha256'] = digest
        self.store.publish(state)
        called = []
        def reject(*args):
            called.append(True)
            raise ValueError('Untrusted historical extraction')
        self.run_it(parser=reject)
        self.assertEqual(called, [True])
        self.assertEqual(self.store.state()['documents'][0]['evidence_status'], 'original_unavailable')

    def test_seed_diff_matches_existing_totals(self):
        from bolsa_abierta.store import compare
        docs = self.store.state()['documents']
        changes = compare(docs[0], docs[1])
        self.assertEqual(len(changes), 54)
        self.assertEqual(sum(c['delta'] for c in changes), -30)

    def test_real_pdf_pipeline_in_isolated_process_and_snapshot_restore(self):
        body = (SEED.parent.parent / 'tests/fixtures/carm-2026-09-30.pdf').read_bytes()
        result = run_refresh(self.store, client=Client(body), discover=discovery)
        self.assertEqual(result['status'], 'completed')
        state = self.store.state()
        doc = state['documents'][0]
        self.assertEqual((doc['row_count'], doc['places'], doc['process_id']), (77, 85, '3133'))
        self.assertEqual(doc['extraction_status'], 'validated')
        self.assertEqual(self.store.verified_artifact(doc['id']).read_bytes(), body)
        out = Path(self.temp.name) / 'site'
        export_static(self.store, out)
        restored = Store(Path(self.temp.name) / 'restored', out / 'data/state.json')
        self.assertEqual(restored.state()['documents'][0]['rows'], doc['rows'])
        self.run_it(Client(fail=True))
        self.assertEqual(self.store.state()['current_id'], doc['id'])

    def test_public_snapshot_budget_retains_current_previous_and_archives(self):
        from bolsa_abierta.store import public_state
        self.run_it()
        state = self.store.state()
        state['documents'][-1]['padding'] = 'x' * 400000
        visible = public_state(state, byte_budget=400000)
        self.assertEqual({d['id'] for d in visible['documents']}, {state['current_id'], state['previous_id']})
        self.assertEqual(visible['history_window']['omitted_documents'], 1)
        self.assertEqual(len(state['documents']), 3)
        self.assertIn(state['documents'][-1]['id'], [d['id'] for d in visible['history_documents']])
        repeated = public_state(visible)
        self.assertEqual(repeated['history_window']['omitted_documents'], 1)
        self.assertEqual(repeated['history_documents'], visible['history_documents'])


if __name__ == '__main__':
    unittest.main()
