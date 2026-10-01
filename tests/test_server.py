from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from bolsa_abierta.server import Application
from bolsa_abierta.store import Store
from bolsa_abierta.pipeline import isolated_parse

ROOT = Path(__file__).resolve().parents[1]


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name, ROOT / 'data/seed-state.json')
        self.calls = 0
        self.gate = threading.Event()
        def refresh(store):
            self.calls += 1
            self.gate.wait(3)
            return {'status': 'completed'}
        self.app = Application(self.store, ROOT, refresh=refresh)

    def tearDown(self):
        self.gate.set()
        self.app.close()
        self.temp.cleanup()

    def request(self, path, method='GET', body=b'', **headers):
        env = {'PATH_INFO': path, 'REQUEST_METHOD': method, 'CONTENT_LENGTH': str(len(body)),
               'wsgi.input': io.BytesIO(body), 'CONTENT_TYPE': 'application/json', **headers}
        result = {}
        def start(status, response_headers):
            result.update(status=int(status.split()[0]), headers=dict(response_headers))
        result['body'] = b''.join(self.app(env, start))
        return result

    def test_twenty_public_requests_share_one_job(self):
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda _: self.request('/api/refresh', 'POST', b'{}', HTTP_X_BA_REFRESH='1'), range(20)))
        self.assertEqual({r['status'] for r in results}, {202})
        self.assertEqual(len({json.loads(r['body'])['id'] for r in results}), 1)
        self.gate.set()
        self.app.close()
        self.assertEqual(self.calls, 1)
        job_id = json.loads(results[0]['body'])['id']
        status = json.loads(self.request('/api/refresh/' + job_id)['body'])
        self.assertEqual(status['status'], 'completed')

    def test_rejects_untrusted_input_and_cross_origin_posts(self):
        cases = [({}, b'{}'), ({'HTTP_X_BA_REFRESH': '1'}, b'{"url":"https://example.com"}'),
                 ({'HTTP_X_BA_REFRESH': '1'}, b'[]'),
                 ({'HTTP_X_BA_REFRESH': '1', 'CONTENT_TYPE': 'text/plain'}, b'{}'),
                 ({'HTTP_X_BA_REFRESH': '1', 'HTTP_ORIGIN': 'https://evil.invalid', 'HTTP_HOST': 'localhost'}, b'{}')]
        for headers, body in cases:
            with self.subTest(headers=headers):
                self.assertIn(self.request('/api/refresh', 'POST', body, **headers)['status'], (400, 403, 415))
        self.assertEqual(self.calls, 0)

    def test_serves_state_and_only_explicit_files(self):
        state = json.loads(self.request('/api/state')['body'])
        self.assertEqual(state['capabilities']['source_check'], 'available')
        self.assertEqual(self.request('/')['status'], 200)
        for path in ('/.git/config', '/data/seed-state.json', '/web/../README.md', '/web/%2e%2e/README.md', '/api/documents/../state.sqlite3'):
            self.assertEqual(self.request(path)['status'], 404)

    def test_only_published_hash_verified_pdf_can_be_served(self):
        digest = self.store.archive(b'%PDF-unpublished')
        self.assertEqual(self.request('/api/documents/' + digest + '.pdf')['status'], 404)

    def test_worker_failure_is_terminal(self):
        self.app.close()
        def fail(store):
            raise RuntimeError('test fault')
        self.app = Application(self.store, ROOT, refresh=fail)
        job = json.loads(self.request('/api/refresh', 'POST', b'{}', HTTP_X_BA_REFRESH='1')['body'])
        self.app.close()
        self.assertEqual(self.store.job(job['id'])['status'], 'failed')
        self.assertEqual(self.store.state()['freshness']['status'], 'failed')

    def test_parser_timeout_is_error(self):
        import subprocess
        with patch('bolsa_abierta.pipeline.subprocess.run', side_effect=subprocess.TimeoutExpired('worker', 45)):
            with self.assertRaisesRegex(ValueError, '45 seconds'):
                isolated_parse(b'%PDF-', 'https://www.carm.es/example', '2026-10-01T00:00:00Z')


if __name__ == '__main__':
    unittest.main()
