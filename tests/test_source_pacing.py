import unittest
from unittest.mock import Mock, patch

from bolsa_abierta.sources import OfficialClient, SourceError
from tests.test_sources import public_dns, response, PDF_URL


class SourcePacingTests(unittest.TestCase):
    def test_carm_requests_are_spaced_but_rrhh_remains_independent(self):
        now = [1000.0]
        waits = []
        def sleep(seconds):
            waits.append(seconds)
            now[0] += seconds
        session = Mock()
        session.get.side_effect = [
            response(b'%PDF-first', headers={'Content-Type': 'application/pdf'}),
            response(b'<html>news</html>', headers={'Content-Type': 'text/html'}),
            response(b'%PDF-second', headers={'Content-Type': 'application/pdf'}),
        ]
        with patch('bolsa_abierta.sources.time.monotonic', side_effect=lambda: now[0]):
            client = OfficialClient(session=session, resolver=public_dns, sleep=sleep,
                                    carm_interval=2)
            client.fetch(PDF_URL, kind='pdf')
            client.fetch('https://rrhheducacion.carm.es/feed/')
            self.assertEqual(waits, [])
            client.fetch(PDF_URL, kind='pdf')
        self.assertEqual(waits, [2])
        self.assertEqual(session.get.call_count, 3)

    def test_pacing_respects_the_request_deadline(self):
        session = Mock(get=Mock(return_value=response(b'%PDF-ok',
                       headers={'Content-Type': 'application/pdf'})))
        with patch('bolsa_abierta.sources.time.monotonic', return_value=1000):
            client = OfficialClient(session=session, resolver=public_dns,
                                    carm_interval=2, max_seconds=1)
            client.fetch(PDF_URL, kind='pdf')
            with self.assertRaises(SourceError) as caught:
                client.fetch(PDF_URL, kind='pdf')
        self.assertEqual(caught.exception.code, 'time_limit')
        self.assertEqual(session.get.call_count, 1)

    def test_invalid_pacing_configuration_fails_operationally(self):
        for interval in (-1, 11, float('nan'), float('inf'), 'bad'):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                OfficialClient(carm_interval=interval)

    def test_delayed_wakeup_cannot_start_an_expired_request(self):
        now = [1000.0]
        def delayed_wakeup(seconds):
            now[0] += seconds + 40
        session = Mock(get=Mock(return_value=response(b'%PDF-ok',
                       headers={'Content-Type': 'application/pdf'})))
        with patch('bolsa_abierta.sources.time.monotonic', side_effect=lambda: now[0]):
            client = OfficialClient(session=session, resolver=public_dns,
                                    carm_interval=2, sleep=delayed_wakeup)
            client.fetch(PDF_URL, kind='pdf')
            with self.assertRaises(SourceError):
                client.fetch(PDF_URL, kind='pdf')
        self.assertEqual(session.get.call_count, 1)
