import base64
import unittest
from unittest.mock import patch, Mock

from bolsa_abierta.sources import OfficialClient, SourceError
from tests.test_sources import public_dns, response, PDF_URL


class BrowserTransportTests(unittest.TestCase):
    def test_browser_denies_subresources_navigations_and_other_origins(self):
        from bolsa_abierta.browser_source import Browser
        browser = Browser.__new__(Browser)
        browser.bootstrapping = False
        for url, method, resource, navigation in (
            ('https://127.0.0.1/secret', 'GET', 'fetch', False),
            ('https://evil.example/', 'GET', 'fetch', False),
            ('https://www.carm.es/script.js', 'GET', 'script', False),
            ('https://www.carm.es/', 'POST', 'fetch', False),
            ('https://www.carm.es/', 'GET', 'document', True),
        ):
            route = Mock()
            route.request = Mock(url=url, method=method, resource_type=resource,
                                 is_navigation_request=Mock(return_value=navigation))
            browser.route(route)
            route.abort.assert_called_once()
            route.continue_.assert_not_called()

    def test_browser_is_explicit_and_still_validates_pdf(self):
        session = Mock()
        with patch.dict('os.environ', {'OFFICIAL_SOURCE_TRANSPORT': 'chromium'}), \
             patch('bolsa_abierta.browser_source.browser_get', return_value=response(
                 b'%PDF-reviewed', headers={'Content-Type': 'application/pdf'})) as get:
            result = OfficialClient(session=session, resolver=public_dns).fetch(PDF_URL, kind='pdf')
            self.assertEqual(result.body, b'%PDF-reviewed')
            self.assertEqual(get.call_args.args[0], PDF_URL)
            session.get.assert_not_called()

    def test_browser_challenge_never_becomes_a_pdf(self):
        with patch.dict('os.environ', {'OFFICIAL_SOURCE_TRANSPORT': 'chromium'}), \
             patch('bolsa_abierta.browser_source.browser_get', return_value=response(b'Radware Captcha Page')):
            with self.assertRaises(SourceError) as caught:
                OfficialClient(resolver=public_dns).fetch(PDF_URL, kind='pdf')
        self.assertEqual(caught.exception.code, 'access_challenge')

    def test_browser_result_rejects_redirect_overflow_and_invalid_encoding(self):
        from bolsa_abierta.browser_source import decode_response
        valid = {'status': 200, 'headers': {'content-type': 'application/pdf'},
                 'body': base64.b64encode(b'%PDF-ok').decode()}
        self.assertEqual(b''.join(decode_response(valid, 20).iter_content(1024)), b'%PDF-ok')
        for value in ({**valid, 'status': 0}, {**valid, 'body': '***'},
                      {**valid, 'body': base64.b64encode(b'x' * 21).decode()},
                      {'error_code': 'size_limit'}, {'error_code': 'time_limit'}):
            with self.subTest(value=value), self.assertRaises(SourceError):
                decode_response(value, 20)

    def test_new_transport_retries_challenge_but_honors_shared_server_cooldown(self):
        import tempfile
        from pathlib import Path
        clock = lambda: 100000
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'retry.json'
            old = OfficialClient(session=Mock(get=Mock(return_value=response(b'Radware Captcha Page'))),
                                 resolver=public_dns, retry_state=state, clock=clock)
            with self.assertRaises(SourceError):
                old.fetch(PDF_URL, kind='pdf')
            with patch.dict('os.environ', {'OFFICIAL_SOURCE_TRANSPORT': 'chromium'}):
                new = OfficialClient(resolver=public_dns, retry_state=state, clock=clock)
                new.check_retry(PDF_URL, 'pdf')
                new._save_retry(PDF_URL, 'pdf', 'temporary_http', 86400)
                with self.assertRaises(SourceError) as caught:
                    new.check_retry(PDF_URL, 'pdf')
                self.assertEqual(caught.exception.code, 'temporary_http')
            with self.assertRaises(SourceError) as caught:
                old.check_retry(PDF_URL, 'pdf')
            self.assertEqual(caught.exception.code, 'temporary_http')


if __name__ == '__main__':
    unittest.main()
