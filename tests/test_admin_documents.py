import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tests.test_position_documents import fixture


class AdminDocumentsTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('bolsa_abierta.admin_documents'), 'Missing administrative intake')
        return importlib.import_module('bolsa_abierta.admin_documents')

    def request(self, body=b'%PDF-1.4 test fixture'):
        return dict(content_id='209126', source_url='https://www.carm.es/web/descarga?IDCONTENIDO=209126',
            sha256=hashlib.sha256(body).hexdigest(), published_at='2026-09-24', kind='award',
            received_at='2026-10-04T12:00:00Z', received_via='local_file', human_seconds=90)

    def test_reviewed_original_uses_strict_adapter_and_duplicate_preserves_administrative_dates(self):
        module = self.module(); pages, pinned = fixture(); request = self.request(); pinned.update(request)
        with TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'source.pdf'; path.write_bytes(b'%PDF-1.4 test fixture')
            with patch('bolsa_abierta.position_documents.pdfplumber.open') as opened:
                opened.return_value.__enter__.return_value = SimpleNamespace(pages=pages)
                first = module.intake_document(path, request, [pinned], private_dir=root / 'private')
                request.update(received_at='2026-10-04T13:00:00Z', human_seconds=10)
                second = module.intake_document(path, request, [pinned], private_dir=root / 'private', state=first['state'])
            self.assertEqual(first['receipt']['status'], 'validated')
            self.assertEqual(first['receipt']['row_count'], 3)
            self.assertTrue(first['receipt']['reviewed_eligible'])
            self.assertFalse(first['receipt']['activated'])
            self.assertEqual(second['receipt']['result'], 'already_received')
            document = second['state']['documents'][0]
            self.assertEqual(document['received_at'], '2026-10-04T12:00:00Z')
            self.assertEqual(document['last_received_at'], '2026-10-04T13:00:00Z')
            self.assertEqual(document['published_at'], '2026-09-24')
            self.assertEqual(second['state']['human_seconds_total'], 100)
            self.assertEqual(second['state']['pending_documents'], 0)
            self.assertEqual(len(list((root / 'private').iterdir())), 1)
            self.assertNotIn('PRUEBA', json.dumps(second))
            self.assertNotIn('checked_at', document)

    def test_unreviewed_changed_or_invalid_original_is_quarantined_without_activation(self):
        module = self.module()
        with TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'source.pdf'; path.write_bytes(b'%PDF-1.4 test fixture')
            request = self.request()
            for reviewed, body, code in (([], b'%PDF-1.4 test fixture', 'unreviewed_document'),
                    ([{**request, 'sha256': 'a' * 64}], b'%PDF-1.4 test fixture', 'manifest_mismatch'),
                    ([request], b'<html>challenge</html>', 'hash_mismatch')):
                path.write_bytes(body)
                with self.subTest(code=code):
                    result = module.intake_document(path, request, reviewed, private_dir=root / 'private')
                    self.assertEqual(result['receipt']['status'], 'quarantined')
                    self.assertEqual(result['receipt']['reason'], code)
                    self.assertFalse(result['receipt']['reviewed_eligible'])
                    self.assertFalse(result['receipt']['activated'])
                    self.assertEqual(result['state']['pending_documents'], 1)

    def test_strict_parser_rejection_is_redacted_and_pending(self):
        module = self.module(); pages, pinned = fixture(); request = self.request(); pinned.update(request)
        pages[1].words.pop()
        with TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'source.pdf'; path.write_bytes(b'%PDF-1.4 test fixture')
            with patch('bolsa_abierta.position_documents.pdfplumber.open') as opened:
                opened.return_value.__enter__.return_value = SimpleNamespace(pages=pages)
                result = module.intake_document(path, request, [pinned], private_dir=root / 'private')
            self.assertEqual(result['receipt']['reason'], 'adapter_rejected')
            self.assertEqual(result['receipt']['status'], 'quarantined')
            self.assertEqual(result['state']['pending_documents'], 1)
            self.assertNotIn('PRUEBA', json.dumps(result))

    def test_controlled_url_timestamp_and_human_time_reject_invalid_metadata_before_file_store(self):
        module = self.module()
        mutations = [{'source_url': 'https://evil.example/web/descarga?IDCONTENIDO=209126'},
            {'source_url': 'https://www.carm.es/web/descarga?IDCONTENIDO=9'},
            {'source_url': 'https://www.carm.es/web/descarga?IDCONTENIDO=209126&IDCONTENIDO=9'},
            {'source_url': 'https://www.carm.es:443/web/descarga?IDCONTENIDO=209126'},
            {'source_url': 'https://www.carm.es/web/descarga?IDCONTENIDO=209126\n'},
            {'received_at': '2026-10-04'}, {'published_at': '2026-02-30'},
            {'sha256': '../escape'}, {'kind': 'unknown'}, {'human_seconds': -1}, {'human_seconds': True}]
        with TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'source.pdf'; path.write_bytes(b'%PDF-1.4 test fixture')
            for mutation in mutations:
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    module.intake_document(path, {**self.request(), **mutation}, [], private_dir=root / 'private')
            self.assertFalse((root / 'private').exists())

    def test_manifest_date_mismatch_does_not_borrow_the_old_publication_date(self):
        module = self.module(); request = self.request()
        with TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'source.pdf'; path.write_bytes(b'%PDF-1.4 test fixture')
            result = module.intake_document(path, request, [{**request, 'published_at': '2026-09-25'}], private_dir=root / 'private')
            self.assertEqual(result['receipt']['reason'], 'manifest_mismatch')
            self.assertEqual(result['receipt']['published_at'], '2026-09-24')

    def test_cli_missing_key_keeps_only_private_original_and_safe_receipt(self):
        from contextlib import redirect_stdout
        import io
        module = self.module(); pages, pinned = fixture(); request = self.request(); pinned.update(request)
        with TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'source.pdf'; path.write_bytes(b'%PDF-1.4 test fixture')
            manifest = root / 'reviewed.json'; manifest.write_text(json.dumps({'documents': [pinned]}))
            state = root / 'state.json'; output = io.StringIO()
            args = ['--file', str(path), '--url', request['source_url'], '--content-id', request['content_id'],
                '--sha256', request['sha256'], '--published-at', request['published_at'], '--kind', 'award',
                '--documents', str(manifest), '--maestros', str(root / 'absent.json'), '--state', str(state),
                '--private-dir', str(root / 'private'), '--archive-dir', str(root / 'archive')]
            with patch.dict('os.environ', {'POSITION_INGEST_TOKEN': 'x' * 50}, clear=True), redirect_stdout(output), patch('bolsa_abierta.position_documents.pdfplumber.open') as opened:
                opened.return_value.__enter__.return_value = SimpleNamespace(pages=pages)
                self.assertEqual(module.main(args), 0)
            receipt = json.loads(output.getvalue())['receipt']
            self.assertEqual(receipt['cache_status'], 'unconfigured')
            self.assertEqual(receipt['status'], 'validated')
            self.assertFalse((root / 'archive').exists())
            self.assertTrue((root / 'private' / (request['sha256'] + '.pdf')).is_file())
            self.assertNotIn('PRUEBA', state.read_text() + output.getvalue())

    def test_optan_uses_non_nominal_observation_adapter(self):
        from tests.test_position_observations import fixture as observation_fixture
        module = self.module(); pages, pinned = observation_fixture()
        request = {**self.request(), 'content_id': '209124', 'kind': 'optan_observation',
                   'source_url': 'https://www.carm.es/web/descarga?IDCONTENIDO=209124'}
        pinned.update({k: request[k] for k in ('sha256', 'source_url')})
        with TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'source.pdf'; path.write_bytes(b'%PDF-1.4 test fixture')
            with patch('bolsa_abierta.position_observations.pdfplumber.open') as opened:
                opened.return_value.__enter__.return_value = SimpleNamespace(pages=pages)
                result = module.intake_document(path, request, [pinned], private_dir=root / 'private')
            self.assertEqual(result['receipt']['status'], 'validated')
            self.assertEqual(result['receipt']['row_count'], 1)
            self.assertEqual(result['receipt']['semantic_status'], 'unconfirmed')
            self.assertNotIn('PRUEBA', json.dumps(result))

    def test_maestros_correction_requires_complete_reviewed_baseline_and_never_exposes_operations(self):
        from tests.test_position_maestros import fixture as maestros_fixture, correction_fixture
        module = self.module(); pages, parent = maestros_fixture(); amendment_pages, correction = correction_fixture(parent)
        body = b'%PDF-1.4 correction fixture'; baseline = b'%PDF-1.4 baseline fixture'
        parent['sha256'] = hashlib.sha256(baseline).hexdigest()
        correction['sha256'] = hashlib.sha256(body).hexdigest(); parent['amendments'] = [correction]
        request = {**self.request(body), 'content_id': correction['content_id'], 'source_url': correction['source_url'],
            'kind': 'maestros_correction', 'published_at': correction['published_at']}
        with TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'correction.pdf'; path.write_bytes(body)
            manifest = root / 'maestros.json'; manifest.write_text(json.dumps(parent))
            awards = root / 'awards.json'; awards.write_text(json.dumps({'documents': []}))
            reviewed = module.load_reviewed(awards, manifest)
            pending = module.intake_document(path, request, reviewed, private_dir=root / 'private')
            self.assertEqual(pending['receipt']['status'], 'quarantined')
            (root / 'private' / (parent['sha256'] + '.pdf')).write_bytes(baseline)
            with patch('bolsa_abierta.position_maestros.pdfplumber.open') as opened:
                opened.return_value.__enter__.side_effect = [SimpleNamespace(pages=pages), SimpleNamespace(pages=amendment_pages)]
                validated = module.intake_document(path, request, reviewed, private_dir=root / 'private', state=pending['state'])
            self.assertEqual(validated['receipt']['status'], 'validated')
            self.assertNotIn('row_count', validated['receipt'])
            self.assertEqual(validated['receipt']['collection_row_count'], 11)
            self.assertEqual(validated['receipt']['source_inclusion_count'], 4)
            self.assertEqual(validated['receipt']['source_operation_count'], 6)
            self.assertEqual(validated['receipt']['pages'], 4)
            self.assertEqual(validated['state']['pending_documents'], 0)
            self.assertNotIn('operations', json.dumps(validated))
            self.assertNotIn('PRUEBA', json.dumps(validated))

    def test_real_malformed_pdf_never_leaks_operand_to_stdout_stderr_or_configured_logger(self):
        import subprocess
        import sys
        marker = 'SYNTHETIC_PRIVATE_MARKER'
        stream = f'({marker}) g'.encode()
        objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
            b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Contents 4 0 R >>',
            b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
        body = b'%PDF-1.4\n'; offsets = []
        for index, value in enumerate(objects, 1):
            offsets.append(len(body)); body += f'{index} 0 obj\n'.encode() + value + b'\nendobj\n'
        xref = len(body)
        body += b'xref\n0 5\n0000000000 65535 f \n'
        body += b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets)
        body += b'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n' + str(xref).encode() + b'\n%%EOF\n'
        request = self.request(body)
        with TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'source.pdf'; source.write_bytes(body)
            manifest = root / 'reviewed.json'; manifest.write_text(json.dumps({'documents': [{**request, 'pages': 1,
                'page_row_counts': [0], 'row_count': 0, 'process_id': '3125',
                'specialties': [{'code': '0590001', 'name': 'FILOSOFIA', 'body': 'SECUNDARIA', 'count': 0}]}]}))
            logfile = root / 'parser.log'
            code = ('import logging,sys; from bolsa_abierta.admin_documents import main; '
                'h=logging.FileHandler(sys.argv[1]); logging.getLogger("pdfminer").addHandler(h); '
                'logging.getLogger("pdfminer").setLevel(logging.WARNING); '
                'status=main(sys.argv[2:]); logging.getLogger("pdfminer").warning("normal logging restored"); '
                'raise SystemExit(status)')
            args = [sys.executable, '-c', code, str(logfile), '--file', str(source), '--url', request['source_url'],
                '--content-id', request['content_id'], '--sha256', request['sha256'], '--published-at', request['published_at'],
                '--kind', request['kind'], '--documents', str(manifest), '--maestros', str(root / 'none'),
                '--state', str(root / 'receipt.json'), '--private-dir', str(root / 'private')]
            completed = subprocess.run(args, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0)
            self.assertNotIn(marker, completed.stdout + completed.stderr + logfile.read_text())
            self.assertIn('normal logging restored', logfile.read_text())
            self.assertEqual(json.loads(completed.stdout)['receipt']['reason'], 'adapter_rejected')

    def test_arbitrary_query_input_is_never_copied_to_public_receipt_or_state(self):
        module = self.module(); pages, pinned = fixture(); clean = self.request(); pinned.update(clean)
        marker = 'SYNTHETIC_PRIVATE_QUERY'
        request = {**clean, 'source_url': clean['source_url'] + '&private=' + marker}
        with TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'source.pdf'; path.write_bytes(b'%PDF-1.4 test fixture')
            with patch('bolsa_abierta.position_documents.pdfplumber.open') as opened:
                opened.return_value.__enter__.return_value = SimpleNamespace(pages=pages)
                reviewed = module.intake_document(path, request, [pinned], private_dir=root / 'private')
            unknown = module.intake_document(path, request, [], private_dir=root / 'private')
            self.assertEqual(reviewed['receipt']['source_url'], clean['source_url'])
            self.assertEqual(unknown['receipt']['source_url'], clean['source_url'])
            self.assertNotIn(marker, json.dumps(reviewed) + json.dumps(unknown))

    def test_encrypted_receipts_preserve_reviewed_cache_provenance_without_claiming_local_origin_check(self):
        import base64
        from contextlib import redirect_stdout
        import io
        from bolsa_abierta.private_archive import restore_bundle
        module = self.module(); pages, pinned = fixture(); request = self.request(); pinned.update(request)
        with TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'source.pdf'; path.write_bytes(b'%PDF-1.4 test fixture')
            manifest = root / 'reviewed.json'; manifest.write_text(json.dumps({'documents': [pinned]}))
            args = ['--file', str(path), '--url', request['source_url'], '--content-id', request['content_id'],
                '--sha256', request['sha256'], '--published-at', request['published_at'], '--kind', 'award',
                '--documents', str(manifest), '--maestros', str(root / 'none'), '--state', str(root / 'state.json'),
                '--private-dir', str(root / 'private'), '--archive-dir', str(root / 'archive')]
            key = base64.b64encode(bytes(range(32))).decode()
            output = io.StringIO()
            with patch.dict('os.environ', {'PRIVATE_ARCHIVE_KEY': key}, clear=True), redirect_stdout(output), patch('bolsa_abierta.position_documents.pdfplumber.open') as opened:
                opened.return_value.__enter__.return_value = SimpleNamespace(pages=pages)
                self.assertEqual(module.main(args), 0)
            restored = restore_bundle(next((root / 'archive').glob('*.baenc')), root / 'restored', key=key)
            receipts = restored['metadata']['receipts']
            self.assertEqual(len(receipts), 1)
            self.assertEqual(receipts[0]['status'], 'validated')
            self.assertTrue(receipts[0]['reviewed_eligible'])
            self.assertEqual(receipts[0]['content_id'], '209126')
            self.assertEqual(receipts[0]['actual_sha256'], request['sha256'])
            self.assertEqual(receipts[0]['source_url'], request['source_url'])
            self.assertEqual(receipts[0]['published_at'], '2026-09-24')
            self.assertEqual(receipts[0]['received_via'], 'local_file')
            self.assertFalse(receipts[0]['origin_check_performed'])
            self.assertNotIn('origin_downloaded_at', receipts[0])
            self.assertEqual(restored['metadata']['receipt_record_count'], 3)
            self.assertEqual(json.loads(output.getvalue())['receipt']['cache_status'], 'encrypted')
