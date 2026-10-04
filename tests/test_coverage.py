import json
import unittest
import tempfile
from pathlib import Path

from bolsa_abierta.coverage import inventory_summary, position_summary
from bolsa_abierta.store import Store, export_static


class CoverageTests(unittest.TestCase):
    def test_scope_course_and_successful_check_state_are_preserved_without_inference(self):
        public = inventory_summary({'course': '2026-2027', 'coverage': {'sources': [
            {'source_id': 'historical', 'course': 'unknown', 'status': 'checked'},
            {'source_id': 'previous', 'course': '2025-2026', 'status': 'checked'},
            {'source_id': 'undated', 'status': 'checked'}]}})
        scopes = public['coverage']['sources']
        self.assertEqual([scope['course'] for scope in scopes], ['unknown', '2025-2026', None])
        self.assertEqual([scope['status'] for scope in scopes], ['checked'] * 3)

    def test_cached_generation_discloses_incomplete_origin_check_and_unknown_date(self):
        public = position_summary({'status': 'degraded', 'attempted_at': '2026-10-04T12:00:00Z',
            'checked_at': None, 'active_version': 'a' * 64, 'cache_status': 'ready',
            'origin_check_complete': False, 'origin_verified_documents': 5,
            'origin_failed_documents': 2, 'cached_documents': 2,
            'error_code': 'origin_unavailable_cached_evidence', 'source_evidence': [{'name': 'PRIVATE PERSON'}]})
        self.assertEqual(public['status'], 'degraded')
        self.assertIsNone(public['checked_at'])
        self.assertFalse(public['origin_check_complete'])
        self.assertEqual(public['cached_documents'], 2)
        self.assertEqual(public['origin_failed_documents'], 2)
        self.assertEqual(public['origin_verified_documents'], 5)
        self.assertEqual(public['cache_status'], 'ready')
        self.assertNotIn('PRIVATE', json.dumps(public))

    def test_traversal_and_verified_download_coverage_remain_distinct(self):
        scope = {'source_id': 'awards', 'scope_complete': False, 'traversal_complete': True,
            'downloads_complete': False, 'verification_complete': False,
            'document_count': 5, 'pending_documents': 2, 'failed_documents': 1,
            'skipped_documents': 1, 'unreviewed_documents': 3}
        public = inventory_summary({'course': '2026-2027', 'coverage': {'sources': [scope]}})
        result = public['coverage']['sources'][0]
        for key, expected in scope.items():
            self.assertEqual(result[key], expected)

    def test_static_export_publishes_only_whitelisted_operational_summaries(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'runtime', root / 'data/seed-state.json')
            output = Path(folder) / 'site'
            export_static(store, output, inventory={'course': '2026-2027', 'documents': [
                {'kind': 'award', 'status': 'pending_review', 'name': 'PRIVATE PERSON'}]},
                positions={'status': 'failed', 'rows': [{'name': 'PRIVATE PERSON'}]})
            public = (output / 'data/state.json').read_text()
            self.assertNotIn('PRIVATE PERSON', public)
            state = json.loads(public)
            self.assertEqual(state['source_inventory']['document_count'], 1)
            self.assertEqual(state['position_status']['status'], 'failed')

    def test_public_inventory_contains_aggregates_but_no_document_or_announcement_names(self):
        private = {'course': '2026-2027', 'attempted_at': '2026-10-04T12:00:00Z',
            'checked_at': '2026-10-02T12:00:00Z', 'index_complete': False,
            'documents': [{'kind': 'award', 'status': 'incorporated', 'sha256': 'a' * 64,
                'title': 'PRIVATE PERSON', 'name': 'PRIVATE PERSON', 'source_url': 'https://invalid.test/PRIVATE_PERSON'},
                {'kind': 'baseline', 'status': 'skipped', 'work_status': 'skipped'}],
            'announcements': [{'title': 'PRIVATE PERSON'}],
            'sources': [{'id': 'awards', 'family': 'awards', 'status': 'partial',
                'checked_at': '2026-10-02T12:00:00Z', 'private_body': 'PRIVATE PERSON'}]}
        public = inventory_summary(private)
        self.assertEqual(public['status_counts'], {'incorporated': 1, 'skipped': 1})
        self.assertEqual(public['kinds'], {'award': 1, 'baseline': 1})
        self.assertEqual(public['document_count'], 2)
        self.assertFalse(public['index_complete'])
        self.assertEqual(public['checked_at'], '2026-10-02T12:00:00Z')
        self.assertNotIn('PRIVATE', json.dumps(public))
        self.assertNotIn('documents', public)

    def test_missing_checks_never_become_complete_or_current(self):
        public = inventory_summary({'course': '2026-2027'})
        self.assertFalse(public['index_complete'])
        self.assertFalse(public['downloads_complete'])
        self.assertFalse(public['review_complete'])
        self.assertIsNone(public['checked_at'])

    def test_failed_position_attempt_preserves_active_generation_date(self):
        public = position_summary({'status': 'failed', 'attempted_at': '2026-10-04T12:00:00Z',
            'checked_at': '2026-10-02T12:00:00Z', 'active_version': 'a' * 64,
            'exception': 'PRIVATE PERSON', 'error_code': 'access_challenge',
            'rows': [{'name': 'PRIVATE PERSON'}]})
        self.assertEqual(public['active_version'], 'a' * 64)
        self.assertEqual(public['checked_at'], '2026-10-02T12:00:00Z')
        self.assertEqual(public['status'], 'failed')
        self.assertNotIn('PRIVATE', json.dumps(public))
