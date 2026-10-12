"""Actual Chromium streaming checks; opt in under xvfb on the hosted runner."""
import os
import time
import unittest


@unittest.skipUnless(os.environ.get('RUN_BROWSER_TESTS') == '1', 'requires Chromium and a virtual display')
class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from bolsa_abierta.browser_source import Browser
        cls.browser = Browser(time.monotonic() + 30)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()

    def fetch(self, suffix, limit=32, milliseconds=2000):
        from bolsa_abierta.browser_source import FETCH
        return self.browser.page.evaluate(FETCH, {
            'url': 'https://www.carm.es/' + suffix, 'limit': limit,
            'milliseconds': milliseconds, 'headers': {'Accept': 'application/pdf'}})

    def test_redirect_is_not_followed_even_to_private_address(self):
        for target in ('https://127.0.0.1/secret', 'https://unrelated.example/secret'):
            self.browser.context.route('**/redirect-test', lambda route: route.fulfill(
                status=302, headers={'Location': target}))
            self.assertEqual(self.fetch('redirect-test')['error_code'], 'access_challenge')
            self.browser.context.unroute('**/redirect-test')

    def test_bounded_pdf_bytes_and_oversized_body(self):
        from bolsa_abierta.browser_source import decode_response
        self.browser.context.route('**/bytes-test', lambda route: route.fulfill(
            status=200, content_type='application/pdf', body=b'%PDF-reviewed'))
        result = decode_response(self.fetch('bytes-test'), 32)
        self.assertEqual(b''.join(result.iter_content(32)), b'%PDF-reviewed')
        self.assertEqual(self.fetch('bytes-test', limit=3)['error_code'], 'size_limit')

    def test_no_response_is_aborted(self):
        self.browser.context.route('**/timeout-test', lambda route: None)
        self.assertEqual(self.fetch('timeout-test', milliseconds=50)['error_code'], 'time_limit')
