import unittest
from unittest.mock import patch
from bolsa_abierta import position_sync


class SyncTests(unittest.TestCase):
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
