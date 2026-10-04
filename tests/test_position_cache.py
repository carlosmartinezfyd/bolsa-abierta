"""Recovery behavior uses synthetic originals and real authenticated bundles."""
import base64
import copy
import hashlib
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bolsa_abierta import position_sync
from bolsa_abierta.private_archive import export_bundle
from bolsa_abierta.sources import SourceError


KEY = base64.b64encode(bytes(range(32))).decode()
BODY = b'%PDF-1.7\nsynthetic reviewed original\n%%EOF\n'
DIGEST = hashlib.sha256(BODY).hexdigest()
URL = 'https://www.carm.es/web/descarga?IDCONTENIDO=208095&IDTIPO=60'
OLD = '2026-10-01T09:00:00+00:00'
RECEIVED = '2026-10-03T10:00:00+00:00'


def reviewed(**extra):
    return {'content_id': '208095', 'source_url': URL, 'sha256': DIGEST,
            'kind': 'baseline', 'published_at': '2026-07-22', **extra}


class Origin:
    def __init__(self, body=None):
        self.body = body
        self.attempts = []

    def fetch(self, url, *, kind):
        self.attempts.append((url, kind))
        if self.body is None:
            raise SourceError('Synthetic origin unavailable', 'access_challenge')
        return SimpleNamespace(body=self.body)


def bundle(directory, *, document=None, receipt=False, key=KEY):
    private = directory / 'bundle-source'
    private.mkdir(exist_ok=True)
    (private / (DIGEST + '.pdf')).write_bytes(BODY)
    metadata = {'document_count': 1}
    if receipt:
        metadata['receipts'] = [document]
    else:
        metadata.update(schema=1, purpose='position_source_cache', documents=[
            document or {**reviewed(), 'origin_checked_at': OLD, 'received_at': OLD,
                'received_via': 'official_download'}])
    return export_bundle(private, directory / 'archives', key=key, metadata=metadata)


class CacheTests(unittest.TestCase):
    def collect(self, root, docs, origin, **kwargs):
        self.assertTrue(callable(getattr(position_sync, 'collect_evidence', None)),
                        'Private cache recovery must be implemented before publication')
        return position_sync.collect_evidence(docs, origin, root / 'private',
            archive_dir=root / 'archives', key=kwargs.pop('key', KEY), **kwargs)

    def test_outage_uses_authenticated_reviewed_original_without_renewing_check(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle(root)
            origin = Origin()
            result = self.collect(root, [reviewed()], origin)
            self.assertEqual(origin.attempts, [(URL, 'pdf')])
            self.assertEqual(result['checked_at'], OLD)
            self.assertFalse(result['origin_check_complete'])
            self.assertEqual(result['cached_documents'], 1)
            self.assertEqual(result['origin_failed_documents'], 1)
            self.assertEqual(result['artifacts'][DIGEST].read_bytes(), BODY)
            self.assertEqual(result['evidence'][0]['origin_checked_at'], OLD)
            self.assertEqual(result['evidence'][0]['error_code'], 'access_challenge')
            self.assertNotEqual(result['evidence'][0]['attempted_at'], OLD)

    def test_fresh_original_is_preferred_and_new_checks_do_not_duplicate_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = self.collect(root, [reviewed()], Origin(BODY))
            archives = list((root / 'archives').glob('*.baenc'))
            self.assertEqual(len(archives), 1)
            second = self.collect(root, [reviewed()], Origin(BODY))
            self.assertTrue(first['origin_check_complete'])
            self.assertTrue(second['origin_check_complete'])
            self.assertEqual(second['cached_documents'], 0)
            self.assertEqual(list((root / 'archives').glob('*.baenc')), archives)
            self.assertEqual(second['cache_status'], 'ready')
            self.assertGreaterEqual(second['checked_at'], first['checked_at'])
            self.assertEqual(len(list((root / 'archives').iterdir())), 1)

    def test_mixed_collection_uses_oldest_proven_check_and_keeps_per_document_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle(root)
            other_body = b'%PDF-1.7\nsecond synthetic original\n%%EOF\n'
            other = {**reviewed(), 'content_id': '209126', 'kind': 'award',
                'source_url': 'https://www.carm.es/web/descarga?IDCONTENIDO=209126&IDTIPO=60',
                'sha256': hashlib.sha256(other_body).hexdigest()}
            class MixedOrigin:
                def fetch(self, url, *, kind):
                    if url == URL:
                        raise SourceError('Synthetic unavailable original', 'network_error')
                    return SimpleNamespace(body=other_body)
            result = self.collect(root, [other, reviewed()], MixedOrigin())
            self.assertEqual(result['checked_at'], OLD)
            self.assertEqual(result['origin_verified_documents'], 1)
            self.assertEqual(result['origin_failed_documents'], 1)
            self.assertEqual(result['cached_documents'], 1)
            self.assertEqual(result['evidence'][0]['source_status'], 'fresh')
            self.assertEqual(result['evidence'][1]['error_code'], 'network_error')
            self.assertEqual(len(result['artifacts']), 2)

    def test_changed_origin_hash_never_falls_back_to_old_cached_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle(root)
            with self.assertRaises(ValueError):
                self.collect(root, [reviewed()], Origin(b'%PDF-1.7 changed bytes'))

    def test_without_key_plain_private_files_cannot_authorize_fallback(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            root = Path(folder)
            (root / 'private').mkdir()
            (root / 'private' / (DIGEST + '.pdf')).write_bytes(BODY)
            with self.assertRaises(SourceError):
                self.collect(root, [reviewed()], Origin(), key=None)
            fresh = self.collect(root, [reviewed()], Origin(BODY), key=None)
            self.assertEqual(fresh['cache_status'], 'unconfigured')
            self.assertFalse((root / 'archives').exists())

    def test_wrong_key_cannot_turn_an_outage_into_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle(root)
            with self.assertRaises(SourceError):
                self.collect(root, [reviewed()], Origin(), key=base64.b64encode(b'x' * 32).decode())
            self.assertFalse((root / 'private' / (DIGEST + '.pdf')).exists())

    def test_valid_manual_receipt_keeps_receipt_time_separate_from_unknown_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = {**reviewed(), 'actual_sha256': DIGEST, 'reviewed_eligible': True,
                'status': 'validated', 'received_at': RECEIVED, 'received_via': 'local_file',
                'origin_check_performed': False}
            bundle(root, document=document, receipt=True)
            result = self.collect(root, [reviewed()], Origin())
            self.assertIsNone(result['checked_at'])
            self.assertEqual(result['evidence'][0]['received_at'], RECEIVED)
            self.assertIsNone(result['evidence'][0]['origin_checked_at'])
            self.assertEqual(result['evidence'][0]['received_via'], 'local_file')

    def test_manual_receipt_can_use_reviewed_last_origin_check_but_never_receipt_time(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = {**reviewed(), 'actual_sha256': DIGEST, 'reviewed_eligible': True,
                'status': 'validated', 'received_at': RECEIVED, 'received_via': 'local_file',
                'origin_check_performed': False, 'origin_downloaded_at': RECEIVED}
            bundle(root, document=document, receipt=True)
            result = self.collect(root, [reviewed(checked_at=OLD)], Origin())
            self.assertEqual(result['checked_at'], OLD)

    def test_unreviewed_mismatched_or_unrelated_receipts_fail_closed(self):
        variants = [
            {'reviewed_eligible': False}, {'status': 'quarantined'},
            {'actual_sha256': 'a' * 64}, {'content_id': '999'},
            {'sha256': 'b' * 64}, {'published_at': '2026-07-21'},
        ]
        for changed in variants:
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                document = {**reviewed(), 'actual_sha256': DIGEST, 'reviewed_eligible': True,
                    'status': 'validated', 'received_at': RECEIVED, 'received_via': 'local_file',
                    'origin_check_performed': False, **changed}
                bundle(root, document=document, receipt=True)
                with self.assertRaises(SourceError):
                    self.collect(root, [reviewed()], Origin())

    def test_prior_check_applies_only_to_the_same_recorded_original(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = {**reviewed(), 'received_at': RECEIVED, 'received_via': 'local_file',
                'origin_checked_at': None}
            bundle(root, document=document)
            prior = {'active_version': 'a' * 64, 'checked_at': OLD,
                     'references': [{**reviewed(), 'incorporated': True}]}
            result = self.collect(root, [reviewed()], Origin(), prior=prior)
            self.assertEqual(result['checked_at'], OLD)
            prior['references'][0]['incorporated'] = False
            result = self.collect(root, [reviewed()], Origin(), prior=prior)
            self.assertIsNone(result['checked_at'])
            prior['references'][0]['incorporated'] = True
            prior['references'][0]['sha256'] = 'f' * 64
            result = self.collect(root, [reviewed()], Origin(), prior=prior)
            self.assertIsNone(result['checked_at'])

    def test_fresh_and_cached_evidence_have_the_same_semantic_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = {**reviewed(), 'course': '2026-2027', 'parser_revision': 'test-v1',
                'row_count': 1, 'specialties': []}
            original = copy.deepcopy(source)
            fresh = self.collect(root, [source], Origin(BODY))
            cached = self.collect(root, [source], Origin())
            self.assertEqual(position_sync.build_version(source, fresh['checked_at'])['id'],
                             position_sync.build_version(original, cached['checked_at'])['id'])
            self.assertEqual({k: v for k, v in source.items() if k != 'checked_at'}, original)

    def test_ready_generation_with_unknown_check_does_not_issue_fresh_check_action(self):
        calls = []
        def send(body):
            calls.append(body['action'])
            return {'ready': True}
        result = position_sync.publish({'id': 'a' * 64, 'checked_at': None}, lambda: [], send)
        self.assertEqual(result, 'unchanged')
        self.assertEqual(calls, ['begin'])

    def test_collection_suppresses_parser_diagnostics_before_they_can_reach_public_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / (DIGEST + '.pdf')
            path.write_bytes(BODY)
            out, err = StringIO(), StringIO()
            def parse(stream):
                print('SYNTHETIC PRIVATE PARSER CONTENT')
                import sys
                print('SYNTHETIC PRIVATE PARSER CONTENT', file=sys.stderr)
                return []
            with redirect_stdout(out), redirect_stderr(err), patch.object(position_sync, 'parse_pdf', side_effect=parse):
                rows = position_sync.read_collection({'sha256': DIGEST, 'row_count': 0,
                    'specialties': [], 'documents': []}, {DIGEST: path})
            self.assertEqual(rows, [])
            self.assertEqual(out.getvalue(), '')
            self.assertEqual(err.getvalue(), '')

    def test_rejected_inventory_scan_cannot_emit_pdf_text_before_collection(self):
        from bolsa_abierta import position_documents
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'source.json').write_text(json.dumps(reviewed()))
            (root / 'documents.json').write_text('{"documents": []}')
            (root / (DIGEST + '.pdf')).write_bytes(BODY)
            (root / 'inventory.json').write_text(json.dumps({'documents': [
                {**reviewed(), 'kind': 'award', 'downloaded_at': OLD}]}))
            args = SimpleNamespace(source=root / 'source.json', documents=root / 'documents.json',
                maestros=root / 'absent.json', inventory_state=root / 'inventory.json', inventory_dir=root)
            def reject(*args, **kwargs):
                print('SYNTHETIC PRIVATE SCAN CONTENT')
                raise ValueError('SYNTHETIC PRIVATE SCAN CONTENT')
            out = StringIO()
            with redirect_stdout(out), patch.object(position_documents, 'scan_document', side_effect=reject):
                source, observations, pending = position_sync.source_collection(args, {})
            self.assertEqual(pending, 1)
            self.assertEqual(source['documents'], [])
            self.assertEqual(out.getvalue(), '')


class MainCacheTests(unittest.TestCase):
    def paths(self, root):
        source = root / 'source.json'
        source.write_text(json.dumps({**reviewed(), 'row_count': 1,
            'scope': 'published_list', 'coverage': 'baseline_only',
            'specialties': [{'code': '0590001', 'name': 'Filosofia', 'body': 'Secundaria', 'count': 1}]}))
        documents = root / 'documents.json'
        documents.write_text('{"documents": []}')
        return ['--source', str(source), '--documents', str(documents),
            '--maestros', str(root / 'absent-maestros.json'), '--state', str(root / 'state.json'),
            '--summary', str(root / 'summary.json'), '--private-dir', str(root / 'private'),
            '--archive-dir', str(root / 'archives')]

    def test_full_sync_activates_cached_generation_with_unknown_check_and_degraded_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = {**reviewed(), 'actual_sha256': DIGEST, 'reviewed_eligible': True,
                'status': 'validated', 'received_at': RECEIVED, 'received_via': 'local_file',
                'origin_check_performed': False}
            bundle(root, document=document, receipt=True)
            args = self.paths(root)
            calls = []
            def send(body):
                calls.append(body)
                if body['action'] == 'status':
                    return {'existing_ids': [], 'more': False}
                return {'ready': body['action'] != 'begin', 'active': body['action'] == 'metadata'}
            with patch.dict(os.environ, {'PRIVATE_ARCHIVE_KEY': KEY}, clear=True), \
                    patch.object(position_sync, 'OfficialClient', return_value=Origin()), \
                    patch.object(position_sync, 'publication_client', return_value=send), \
                    patch.object(position_sync, 'read_collection', return_value=[{'id': 'a' * 32}]):
                result = position_sync.main(args)
            self.assertEqual(result, 3)
            state = json.loads((root / 'state.json').read_text())
            summary = json.loads((root / 'summary.json').read_text())
            self.assertIsNone(state['checked_at'])
            self.assertEqual(state['source_evidence'][0]['received_at'], RECEIVED)
            self.assertEqual(state['source_evidence'][0]['source_status'], 'cached')
            self.assertEqual(summary['status'], 'degraded')
            self.assertEqual(summary['cached_documents'], 1)
            self.assertEqual(summary['error_code'], 'origin_unavailable_cached_evidence')
            self.assertIsNone(calls[0]['version']['checked_at'])
            self.assertTrue(any(c['action'] == 'activate' for c in calls))

    def test_publication_rejection_retains_active_state_but_fresh_original_is_already_encrypted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args = self.paths(root)
            prior = {'active_version': 'a' * 64, 'checked_at': OLD}
            (root / 'state.json').write_text(json.dumps(prior))
            def send(body):
                raise RuntimeError('HTTP 403: rejected private token')
            with patch.dict(os.environ, {'PRIVATE_ARCHIVE_KEY': KEY}, clear=True), \
                    patch.object(position_sync, 'OfficialClient', return_value=Origin(BODY)), \
                    patch.object(position_sync, 'publication_client', return_value=send):
                result = position_sync.main(args)
            self.assertEqual(result, 1)
            self.assertEqual(json.loads((root / 'state.json').read_text()), prior)
            self.assertEqual(len(list((root / 'archives').glob('*.baenc'))), 1)
            summary = json.loads((root / 'summary.json').read_text())
            self.assertEqual(summary['status'], 'failed')
            self.assertEqual(summary['checked_at'], OLD)

    def test_budget_pause_after_cached_extraction_keeps_previous_date_and_reports_outage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle(root)
            args = self.paths(root)
            prior = {'active_version': 'a' * 64, 'checked_at': '2026-09-30T10:00:00Z'}
            (root / 'state.json').write_text(json.dumps(prior))
            def send(body):
                if body['action'] == 'begin':
                    return {'ready': False}
                if body['action'] == 'status':
                    return {'existing_ids': [], 'more': False}
                raise position_sync.PublicationDeferred('2026-10-05T00:00:00Z')
            with patch.dict(os.environ, {'PRIVATE_ARCHIVE_KEY': KEY}, clear=True), \
                    patch.object(position_sync, 'OfficialClient', return_value=Origin()), \
                    patch.object(position_sync, 'publication_client', return_value=send), \
                    patch.object(position_sync, 'read_collection', return_value=[{'id': 'a' * 32}]):
                result = position_sync.main(args)
            self.assertEqual(result, 2)
            self.assertEqual(json.loads((root / 'state.json').read_text()), prior)
            summary = json.loads((root / 'summary.json').read_text())
            self.assertEqual(summary['status'], 'pending_budget')
            self.assertEqual(summary['checked_at'], prior['checked_at'])
            self.assertEqual(summary['origin_failed_documents'], 1)
            self.assertEqual(summary['cached_documents'], 1)


if __name__ == '__main__':
    unittest.main()
