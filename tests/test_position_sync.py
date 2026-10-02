import unittest
import tempfile
from pathlib import Path
import json
from unittest.mock import patch
from bolsa_abierta import position_sync


class SyncTests(unittest.TestCase):
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
