import unittest
from unittest.mock import Mock, patch
import requests
from bolsa_abierta import position_sync as sync


class PublicationRetryTests(unittest.TestCase):
    def client(self, session):
        with patch.object(sync.requests, 'Session', return_value=session):
            return sync.publication_client('https://bolsa-abierta-gateway.cmartinezmtez.workers.dev', 'x' * 48)

    @patch('time.sleep')
    def test_lost_ack_then_transient_error_retries_identical_idempotent_request(self, sleep):
        session = Mock()
        session.post.side_effect = [requests.Timeout(), Mock(status_code=503),
                                   Mock(status_code=200, json=lambda: {'ready': True})]
        body = {'action': 'activate', 'id': 'a' * 64}
        self.assertTrue(self.client(session)(body)['ready'])
        self.assertEqual(session.post.call_count, 3)
        self.assertTrue(all(c.kwargs['json'] == body for c in session.post.call_args_list))
        self.assertEqual(sleep.call_count, 2)

    @patch('time.sleep')
    def test_auth_conflict_and_budget_are_not_retried(self, sleep):
        for code in (403, 409, 429):
            session = Mock()
            session.post.return_value = Mock(status_code=code, json=lambda: {'pending_budget': True})
            with self.assertRaises(RuntimeError):
                self.client(session)({'action': 'block'})
            self.assertEqual(session.post.call_count, 1)
        sleep.assert_not_called()

    @patch('time.sleep')
    def test_transient_failure_stops_at_three_attempts(self, sleep):
        session = Mock()
        session.post.side_effect = requests.ConnectionError()
        with self.assertRaises(RuntimeError):
            self.client(session)({'action': 'begin'})
        self.assertEqual(session.post.call_count, 3)
