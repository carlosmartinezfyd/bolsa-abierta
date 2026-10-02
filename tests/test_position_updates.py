import hashlib
import tempfile
import unittest
from pathlib import Path
from bolsa_abierta import position_updates as updates
from bolsa_abierta.sources import FetchResult, SourceError


def index(*links):
    return ('<html><div class="bloquemenu"><h2>Cuerpo de enseñanza secundaria y otros '
            '(curso 2026-2027)</h2><ul>' + ''.join(
                f'<li><a href="{url}">{title}</a></li>' for url, title in links
            ) + '</ul></div></html>').encode()


BASE = 'https://www.carm.es/web/descarga?IDCONTENIDO=208095&ARCHIVO=base.pdf'
CORRECTION = 'https://www.carm.es/web/descarga?IDCONTENIDO=208379&ARCHIVO=correction.pdf'
SUPPLEMENT = 'https://www.carm.es/web/descarga?IDCONTENIDO=208249&ARCHIVO=supplement.pdf'


class DiscoveryTests(unittest.TestCase):
    def test_recognizes_definitive_changes_but_not_provisional(self):
        body = index((BASE, '22/07/2026. Relación definitiva'),
                     (CORRECTION, 'CORRECCIÓN DE ERRORES DE LA ORDEN DE 22 DE JULIO DE 2026 RELACIÓN DEFINITIVA'),
                     (SUPPLEMENT, 'Orden complementaria a la relación definitiva'),
                     ('/web/descarga?IDCONTENIDO=207812&ARCHIVO=provisional.pdf', 'Corrección de errores de la relación provisional'))
        docs = updates.discover_documents(body)
        self.assertEqual({d['content_id']: d['kind'] for d in docs},
                         {'208095': 'baseline', '208379': 'correction', '208249': 'supplement', '207812': 'provisional'})
        self.assertEqual(docs[0]['url'], BASE)

    def test_same_id_links_are_deduplicated_and_unknown_pdf_needs_review(self):
        docs = updates.discover_documents(index((BASE, 'Relación definitiva'),
             (BASE+'&RASTRO=other', 'Relación definitiva'),
             ('/web/descarga?IDCONTENIDO=999999&ARCHIVO=new.pdf', 'Nueva resolución')))
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[1]['kind'], 'unclassified')

    def test_rejects_missing_baseline_wrong_course_and_maintenance(self):
        for body in [index((CORRECTION, 'Corrección definitiva')),
                     index((BASE, 'Relación definitiva')).replace(b'2026-2027', b'2025-2026'),
                     b'<h2>Maintenance</h2>', b'<h2>verify you are human</h2>']:
            with self.subTest(body=body), self.assertRaises(SourceError):
                updates.discover_documents(body)

    def test_external_link_cannot_be_collected(self):
        with self.assertRaises(SourceError):
            updates.discover_documents(index((BASE, 'Relación definitiva'),
                ('https://evil.example/doc.pdf', 'Orden complementaria')))

    def test_new_final_document_cannot_hide_behind_baseline_title(self):
        docs = updates.discover_documents(index((BASE, 'Relación definitiva'),
            ('/web/descarga?IDCONTENIDO=999999&ARCHIVO=new.pdf', 'Relación definitiva actualizada')))
        self.assertEqual(docs[1]['kind'], 'unclassified')

    def test_mixed_provisional_and_definitive_title_cannot_be_ignored(self):
        docs = updates.discover_documents(index((BASE, 'Relación definitiva'),
            ('/web/descarga?IDCONTENIDO=999999&ARCHIVO=new.pdf', 'Relación definitiva tras reclamaciones a la relación provisional')))
        self.assertEqual(docs[1]['kind'], 'unclassified')

    def test_over_budget_and_conflicting_identity_fail_closed(self):
        bodies = [index((BASE, 'Relación definitiva'), (BASE, 'Relación provisional')),
                  index((BASE, 'Relación definitiva'), *[(f'/web/descarga?IDCONTENIDO={900000+i}&ARCHIVO=new.pdf', 'Nueva resolución')
                         for i in range(updates.MAX_DOCUMENTS)])]
        for body in bodies:
            with self.assertRaises(SourceError):
                updates.discover_documents(body)

    def test_same_content_id_with_different_download_targets_is_ambiguous(self):
        with self.assertRaises(SourceError):
            updates.discover_documents(index((BASE, 'Relación definitiva'),
                (BASE.replace('base.pdf', 'replacement.pdf'), 'Relación definitiva')))


class CollectionTests(unittest.TestCase):
    def collect(self, bodies, reviewed):
        class Client:
            def fetch(self, url, **kwargs):
                value = bodies[url]
                if isinstance(value, Exception):
                    raise value
                return FetchResult(url, url, value, 'application/pdf' if kwargs.get('kind') == 'pdf' else 'text/html', 200, {})
        with tempfile.TemporaryDirectory() as folder:
            result = updates.collect_documents(Client(), reviewed, Path(folder))
            files = [p.name for p in Path(folder).glob('*.pdf')]
        return result, files

    def test_unknown_correction_is_archived_but_never_applied(self):
        body = b'%PDF-1.4 synthetic correction'
        report, files = self.collect({updates.INDEX_URL: index((BASE, 'Relación definitiva'), (CORRECTION, 'Corrección definitiva')),
                                     BASE: b'%PDF-base', CORRECTION: body}, {'208095': hashlib.sha256(b'%PDF-base').hexdigest()})
        self.assertFalse(report['review_complete'])
        self.assertTrue(report['downloads_complete'])
        self.assertEqual(report['documents'][1]['status'], 'pending_review')
        self.assertIn(hashlib.sha256(body).hexdigest()+'.pdf', files)
        self.assertNotIn('rows', report)

    def test_changed_bytes_and_blocked_download_never_count_as_reviewed(self):
        report, _ = self.collect({updates.INDEX_URL: index((BASE, 'Relación definitiva'), (CORRECTION, 'Corrección definitiva')),
                                 BASE: b'%PDF-new', CORRECTION: SourceError('challenge', 'access_challenge')},
                                {'208095': 'a'*64, '208379': 'b'*64})
        self.assertFalse(report['review_complete'])
        self.assertFalse(report['downloads_complete'])
        self.assertEqual([d['status'] for d in report['documents']], ['changed', 'unavailable'])

    def test_missing_previously_known_document_is_not_complete(self):
        report, _ = self.collect({updates.INDEX_URL: index((BASE, 'Relación definitiva')), BASE: b'%PDF-base'},
                                {'208095': hashlib.sha256(b'%PDF-base').hexdigest(), '208379': 'b'*64})
        self.assertFalse(report['review_complete'])
        self.assertEqual(report['missing_content_ids'], ['208379'])

    def test_blocked_index_is_explicit_and_preserves_known_ids(self):
        report, files = self.collect({updates.INDEX_URL: SourceError('challenge', 'access_challenge')}, {'208095': 'a'*64})
        self.assertFalse(report['index_complete'])
        self.assertFalse(report['review_complete'])
        self.assertEqual(report['error_code'], 'access_challenge')
        self.assertEqual(files, [])

    def test_pending_known_correction_disappearing_does_not_create_success(self):
        report, _ = self.collect({updates.INDEX_URL: index((BASE, 'Relación definitiva')), BASE: b'%PDF-base'},
                                {'208095': hashlib.sha256(b'%PDF-base').hexdigest(), '208379': None})
        self.assertFalse(report['review_complete'])
        self.assertNotIn('checked_at', report)
        self.assertEqual(report['missing_content_ids'], ['208379'])

    def test_all_reviewed_files_are_required_before_success_timestamp(self):
        body = b'%PDF-reviewed'
        report, _ = self.collect({updates.INDEX_URL: index((BASE, 'Relación definitiva')), BASE: body},
                                {'208095': hashlib.sha256(body).hexdigest()})
        self.assertTrue(report['review_complete'])
        self.assertIn('checked_at', report)

    def test_inventory_keeps_known_unreviewed_changes_required(self):
        required = updates.required_documents({'sha256': 'a'*64},
            {'required_content_ids': ['208095', '208379', '208249']})
        self.assertEqual(required, {'208095': 'a'*64, '208379': None, '208249': None})

    def test_required_final_document_cannot_be_downgraded_to_ignored_provisional(self):
        body = b'%PDF-reviewed'
        report, _ = self.collect({updates.INDEX_URL: index((BASE, 'Relación definitiva'),
                                 (CORRECTION, 'Corrección provisional')), BASE: body},
                                {'208095': hashlib.sha256(body).hexdigest(), '208379': None})
        self.assertFalse(report['review_complete'])
        self.assertEqual(report['documents'][1]['status'], 'classification_conflict')
        self.assertNotIn('checked_at', report)
