import unittest
from bolsa_abierta.publication_check import matching_publication


class PublicationCheckTests(unittest.TestCase):
    def test_version_count_and_actual_verification_must_agree(self):
        expected = {'active_version': 'a' * 64, 'checked_at': '2026-10-13T00:00:00+00:00', 'record_count': 22}
        api = {'id': 'a' * 64, 'checked_at': '2026-10-13T00:00:00Z', 'row_count': 22}
        self.assertTrue(matching_publication(expected, api, expected))
        for change in ({'id': 'b' * 64}, {'row_count': 21}, {'checked_at': '2026-10-12T00:00:00Z'}):
            self.assertFalse(matching_publication(expected, {**api, **change}, expected))
        self.assertFalse(matching_publication(expected, api, {**expected, 'active_version': 'b' * 64}))
