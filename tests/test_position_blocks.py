import unittest
from bolsa_abierta.position_sync import publish


class CompactPublicationTests(unittest.TestCase):
    def test_resume_revalidates_stored_blocks_and_updates_actual_check_after_activation(self):
        calls = []
        def send(body):
            calls.append(body)
            return {'storage': 'blocks-v1', 'ready': False,
                    'buckets': ['00'], 'search_pending': ['00']}
        version = {'id': 'a' * 64, 'row_count': 2, 'checked_at': '2026-10-13T00:00:00Z'}
        publish(version, lambda: [{'id': '00' + '1' * 30}, {'id': 'aa' + '1' * 30}], send, resume=True)
        self.assertEqual([c['bucket'] for c in calls if c['action'] == 'block'], ['00', 'aa'])
        self.assertEqual(calls[-1], {'action': 'checked', 'id': version['id'], 'checked_at': version['checked_at']})

    def test_ready_generation_backfills_index_without_reextracting(self):
        calls = []
        def send(body):
            calls.append(body)
            return {'storage': 'blocks-v1', 'ready': True, 'search_pending': ['00', 'ff']}
        publish({'id': 'a' * 64}, lambda: self.fail('no re-extraction'), send)
        self.assertEqual([c['action'] for c in calls], ['begin', 'search-block', 'search-block'])

    def test_negotiated_blocks_group_stable_ids_and_activate_only_after_upload(self):
        rows = [{'id': 'aa' + '1' * 30}, {'id': '00' + '2' * 30}, {'id': '00' + '1' * 30}]
        calls = []
        def send(body):
            calls.append(body)
            return {'storage': 'blocks-v1', 'ready': False}
        self.assertEqual(publish({'id': 'a' * 64, 'row_count': 3}, lambda: rows, send, resume=True), 'published')
        self.assertEqual([c['action'] for c in calls], ['begin', 'block', 'block', 'activate'])
        self.assertEqual(calls[1]['bucket'], '00')
        self.assertEqual([r['id'] for r in calls[1]['rows']], sorted(r['id'] for r in rows if r['id'].startswith('00')))

    def test_oversized_bucket_is_rejected_before_any_block_is_sent(self):
        rows = [{'id': 'aa' + f'{n:030x}'} for n in range(257)]
        calls = []
        def send(body):
            calls.append(body)
            return {'storage': 'blocks-v1', 'ready': False}
        with self.assertRaises(ValueError):
            publish({'id': 'a' * 64, 'row_count': 257}, lambda: rows, send)
        self.assertEqual(len(calls), 1)
