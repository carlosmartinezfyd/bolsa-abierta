import unittest
import tempfile
from pathlib import Path
import json
import os
from unittest.mock import patch
from bolsa_abierta import position_sync


class SyncTests(unittest.TestCase):
    def test_baseline_course_parser_and_reviewed_scope_change_generation(self):
        source = {'sha256': 'a' * 64, 'row_count': 1, 'course': '2026-2027',
            'parser_revision': 'secondary-lists-v1', 'scope': 'published_list'}
        original = position_sync.build_version(source, '2026-10-04T12:00:00Z')['id']
        for key, changed in [('course', '2027-2028'), ('parser_revision', 'secondary-lists-v2'),
                             ('scope', 'reviewed_list')]:
            with self.subTest(key=key):
                self.assertNotEqual(original, position_sync.build_version({**source, key: changed},
                    '2026-10-04T12:00:00Z')['id'])

    def test_resume_skips_exact_existing_ids_even_when_staging_has_holes(self):
        ids = [f'{n:032x}' for n in range(1, 4)]
        calls = []
        def send(body):
            calls.append(body)
            if body['action'] == 'begin':
                return {'ready': False}
            if body['action'] == 'status':
                return {'existing_ids': [ids[0], ids[2]], 'more': False}
            return {'ready': body['action'] == 'activate'}
        result = position_sync.publish({'id': 'a' * 64, 'row_count': 3},
            lambda: [{'id': identity} for identity in ids], send, resume=True)
        self.assertEqual(result, 'published')
        batches = [call for call in calls if call['action'] == 'rows']
        self.assertEqual(batches[0]['rows'], [{'id': ids[1]}])

    def test_staging_cannot_smuggle_a_record_outside_the_reviewed_generation(self):
        calls = []
        def send(body):
            calls.append(body['action'])
            return {'ready': False} if body['action'] == 'begin' else {
                'existing_ids': ['f' * 32], 'more': False}
        with self.assertRaises(ValueError):
            position_sync.publish({'id': 'a' * 64, 'row_count': 1},
                lambda: [{'id': 'a' * 32}], send, resume=True)
        self.assertNotIn('activate', calls)
        self.assertNotIn('rows', calls)

    def test_failed_configuration_preserves_state_and_reports_previous_success(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            state, summary = Path(directory) / 'state.json', Path(directory) / 'summary.json'
            prior = {'active_version': 'a' * 64, 'checked_at': '2026-10-02T12:00:00Z'}
            state.write_text(json.dumps(prior))
            result = position_sync.main(['--state', str(state), '--summary', str(summary)])
            self.assertEqual(result, 1)
            self.assertEqual(json.loads(state.read_text()), prior)
            status = json.loads(summary.read_text())
            self.assertEqual(status['status'], 'failed')
            self.assertEqual(status['checked_at'], prior['checked_at'])
            self.assertEqual(status['active_version'], prior['active_version'])
            self.assertEqual(status['error_code'], 'not_configured')

    def test_daily_write_pause_never_replaces_the_active_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            state, summary = Path(directory) / 'state.json', Path(directory) / 'summary.json'
            prior = {'active_version': 'c' * 64, 'checked_at': '2026-10-02T12:00:00Z'}
            state.write_text(json.dumps(prior))
            source = {'sha256': 'a' * 64, 'row_count': 1}
            def send(body):
                if body['action'] == 'begin':
                    return {'ready': False}
                if body['action'] == 'status':
                    return {'existing_ids': [], 'more': False}
                raise position_sync.PublicationDeferred('2026-10-05T00:00:00Z')
            with patch.object(position_sync, 'publication_client', return_value=send), \
                    patch.object(position_sync, 'source_collection', return_value=(source, [], 0)), \
                    patch.object(position_sync, 'required_documents', return_value=[]), \
                    patch.object(position_sync, 'fetch_documents', return_value=[]), \
                    patch.object(position_sync, 'read_collection', return_value=[{'id': 'a' * 32}]):
                result = position_sync.main(['--state', str(state), '--summary', str(summary)])
            self.assertEqual(result, 2)
            self.assertEqual(json.loads(state.read_text()), prior)
            status = json.loads(summary.read_text())
            self.assertEqual(status['status'], 'pending_budget')
            self.assertEqual(status['active_version'], prior['active_version'])
            self.assertEqual(status['staged_version'], 'a' * 64)
            self.assertEqual(status['checked_at'], prior['checked_at'])
            self.assertEqual(status['resume_after'], '2026-10-05T00:00:00Z')

    def test_reviewed_metadata_revision_wins_without_changing_original_hash(self):
        previous = {'content_id': '9', 'sha256': 'a' * 64, 'parser_revision': 'v1', 'incorporated': True,
                    'checked_at': '2026-10-02T12:00:00Z'}
        reviewed = {**previous, 'parser_revision': 'v2', 'validated_at': '2026-10-04T12:00:00Z'}
        actual = position_sync.reconcile_documents([reviewed], [previous])
        self.assertEqual(actual[0]['parser_revision'], 'v2')
        self.assertNotIn('incorporated', actual[0])
        self.assertEqual(actual[0]['checked_at'], previous['checked_at'])
        with self.assertRaises(ValueError):
            position_sync.reconcile_documents([{**reviewed, 'sha256': 'b' * 64}], [previous])

    def test_validation_and_download_times_do_not_change_generation_identity(self):
        source = {'sha256': 'a' * 64, 'row_count': 1, 'specialties': [
            {'code': '0590001', 'name': 'Filosofia', 'body': 'Secundaria', 'count': 1}],
            'documents': [{'kind': 'award', 'content_id': '9', 'sha256': 'b' * 64,
                'row_count': 1, 'parser_revision': 'v2', 'validated_at': '2026-10-04T11:00:00Z',
                'specialties': [{'code': '0590001', 'name': 'Filosofia', 'body': 'Secundaria', 'count': 1}]}]}
        one = position_sync.build_version(source, '2026-10-04T12:00:00Z')
        source['documents'][0].update(validated_at='2026-10-04T13:00:00Z', downloaded_at='2026-10-04T12:30:00Z')
        two = position_sync.build_version(source, '2026-10-04T14:00:00Z')
        self.assertEqual(one['id'], two['id'])
        source['documents'][0]['parser_revision'] = 'v3'
        self.assertNotEqual(two['id'], position_sync.build_version(source, '2026-10-04T14:00:00Z')['id'])

    def test_duplicate_local_rows_never_start_row_publication(self):
        calls = []
        def send(body):
            calls.append(body['action'])
            return {'ready': False}
        with self.assertRaises(ValueError):
            position_sync.publish({'id': 'a' * 64, 'row_count': 2},
                lambda: [{'id': 'same'}, {'id': 'same'}], send)
        self.assertEqual(calls, ['begin'])

    def test_changed_revision_requires_explicit_review_of_the_previous_hash(self):
        old = {'content_id': '9', 'sha256': 'a' * 64}
        revised = {'content_id': '9', 'sha256': 'b' * 64, 'supersedes_sha256': 'a' * 64}
        self.assertEqual(position_sync.reconcile_documents([revised], [old])[0]['sha256'], 'b' * 64)

    def test_durable_document_manifest_does_not_drop_prior_publications_or_accept_changed_ids(self):
        self.assertTrue(callable(getattr(position_sync, 'merge_documents', None)))
        one={'content_id':'1','sha256':'a'*64,'incorporated':True}
        two={'content_id':'2','sha256':'b'*64}
        docs=position_sync.merge_documents([one],[two])
        self.assertEqual([d['content_id'] for d in docs],['1','2'])
        self.assertNotIn('incorporated',docs[0])
        with self.assertRaises(ValueError):
            position_sync.merge_documents([one],[{**one,'sha256':'c'*64}])

    def test_extra_documents_are_verified_before_any_publication_can_start(self):
        self.assertTrue(callable(getattr(position_sync, 'fetch_documents', None)))
        class Client:
            def fetch(self, url, kind):
                return type('Fetched', (), {'body': b'%PDF changed'})()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                position_sync.fetch_documents([{'source_url':'https://www.carm.es/web/descarga?IDCONTENIDO=9','sha256':'a'*64}],Client(),Path(folder))
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_multisource_counts_and_identity_include_all_documents_not_check_time(self):
        source={'sha256':'a'*64,'coverage':'baseline_only','row_count':2,
                'specialties':[{'code':'0590001','name':'Filosofia','body':'Secundaria','count':2}],
                'documents':[{'content_id':'209126','sha256':'d'*64,'row_count':1,
                              'specialties':[{'code':'0590I09','name':'Dibujo Ingles','body':'Secundaria','count':1}]}]}
        v=position_sync.build_version(source,'2026-10-02T12:00:00Z')
        self.assertEqual(v['coverage'],'multi_source')
        self.assertEqual(v['row_count'],3)
        self.assertEqual(v['ranked_specialties'],source['specialties'])
        self.assertEqual([x['code'] for x in v['specialties']],['0590001','0590I09'])
        self.assertEqual(v['id'],position_sync.build_version(source,'2026-10-03T12:00:00Z')['id'])
        source['documents'][0]['sha256']='e'*64
        self.assertNotEqual(v['id'],position_sync.build_version(source,'2026-10-03T12:00:00Z')['id'])

    def test_amended_version_identity_changes_with_reviewed_evidence(self):
        source={'sha256':'a'*64,'amendments':[{'content_id':'208249','sha256':'b'*64}]}
        one=position_sync.build_version(source,'2026-10-02T12:00:00Z')
        two=position_sync.build_version({**source,'amendments':[{'content_id':'208249','sha256':'c'*64}]},'2026-10-02T13:00:00Z')
        self.assertNotEqual(one['id'],two['id'])
        self.assertNotEqual(one['id'],source['sha256'])
        self.assertEqual(one['id'],position_sync.build_version(source,'2026-10-03T12:00:00Z')['id'])
        self.assertEqual(position_sync.build_version({'sha256':'a'*64},'2026-10-02T12:00:00Z')['id'],'a'*64)
    def test_unchanged_verified_pdf_updates_check_without_rewriting_rows(self):
        self.assertTrue(callable(getattr(position_sync, 'publish', None)), 'Missing controlled publication')
        calls=[]
        def send(body):
            calls.append(body)
            return {'ready':True}
        result=position_sync.publish({'id':'a'*64,'checked_at':'2026-10-02T12:00:00Z'},lambda:self.fail('Unchanged PDF parsed again'),send)
        self.assertEqual([x['action'] for x in calls],['begin','checked'])
        self.assertEqual(result,'unchanged')

    def test_stage_failure_does_not_attempt_activation(self):
        self.assertTrue(callable(getattr(position_sync, 'publish', None)), 'Missing controlled publication')
        calls=[]
        def send(body):
            calls.append(body['action'])
            if body['action']=='rows':raise RuntimeError('offline')
            return {'ready':False}
        with self.assertRaises(RuntimeError):
            position_sync.publish({'id':'a'*64},lambda:[{'id':'test'}],send)
        self.assertEqual(calls,['begin','rows'])

    def test_unreviewed_pdf_hash_is_not_assigned_an_old_publication_date(self):
        self.assertTrue(callable(getattr(position_sync, 'verify_source', None)), 'Missing source verification')
        with self.assertRaises(ValueError):
            position_sync.verify_source(b'%PDF changed',{'sha256':'a'*64})
