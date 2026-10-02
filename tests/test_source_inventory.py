import hashlib
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bolsa_abierta import source_inventory as inventory
from bolsa_abierta.sources import FetchResult, SourceError


FEED = 'https://rrhheducacion.carm.es/feed/'
MAP = 'https://rrhheducacion.carm.es/mapa-web/'
PAGE = 'https://rrhheducacion.carm.es/procedimiento-docente/'
DOC = 'https://www.carm.es/web/descarga?IDCONTENIDO=900001&ARCHIVO=documento.pdf'
NOW = '2026-10-02T20:00:00Z'
PDF = b'%PDF-1.4 synthetic non-personal document'


def feed(*items):
    return ('<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>' + ''.join(
        f'<item><title>{title}</title><link>{url}</link><pubDate>{date}</pubDate>'
        f'<content:encoded><![CDATA[{body}]]></content:encoded></item>'
        for title, url, date, body in items) + '</channel></rss>').encode()


def sitemap(*urls):
    return ('<ul>' + ''.join(f'<li><a class="rank-math-html-sitemap__link" href="{url}">'
                           'Resolución de una persona</a></li>' for url in urls) + '</ul>').encode()


class Client:
    def __init__(self, values):
        self.values = values
    def fetch(self, url, **kwargs):
        value = self.values[url]
        if isinstance(value, Exception):
            raise value
        return FetchResult(url, url, value, 'application/pdf' if kwargs.get('kind') == 'pdf' else 'text/html', 200, {})


class InventoryTests(unittest.TestCase):
    def registry(self, **limits):
        return {'course': '2026-2027', 'since': '2026-06-01', 'limits': {'max_undated_details': 0, **limits},
                'sources': [{'id': 'rrhh-feed', 'kind': 'rss', 'url': FEED},
                            {'id': 'rrhh-map', 'kind': 'map', 'url': MAP}]}

    def collect(self, values, *, registry=None, previous=None, manifest=None, now=NOW):
        with tempfile.TemporaryDirectory() as directory:
            return inventory.collect_inventory(registry or self.registry(), manifest or {},
                previous=previous, client=Client(values), now=now, private_dir=Path(directory))

    def normal(self):
        return {FEED: feed(('Resolución definitiva de admisión Dibujo Inglés', PAGE,
                           'Wed, 23 Sep 2026 09:00:00 +0200', f'<a href="{DOC}">Orden definitiva</a>')),
                FEED+'?paged=2': feed(('Lista antigua', PAGE+'antigua/',
                                      'Thu, 21 May 2026 09:00:00 +0200', '')),
                MAP: sitemap(PAGE), PAGE: f'<time datetime="2026-09-23"></time><a href="{DOC}">Orden definitiva de admisión</a>'.encode(),
                DOC: PDF}

    def test_paginated_feed_reaches_window_without_twenty_item_cutoff(self):
        values = self.normal()
        values[FEED] = feed(*[(f'Resolución definitiva {i}', PAGE+str(i),
             'Wed, 23 Sep 2026 09:00:00 +0200', f'<a href="{DOC}">Admisión definitiva</a>') for i in range(25)])
        for i in range(25):
            values[PAGE+str(i)] = values[PAGE]
        values[MAP] = sitemap(*(PAGE+str(i) for i in range(25)))
        result = self.collect(values)
        self.assertTrue(result['index_complete'])
        self.assertEqual(result['sources'][0]['pages'], 2)
        self.assertEqual(len(result['announcements']), 25)
        self.assertEqual(result['documents'][0]['status'], 'pending_review')
        self.assertFalse(result['review_complete'])

    def test_repeated_page_and_budget_cannot_claim_complete_catalogue(self):
        for values, registry in [(self.normal(), self.registry(max_feed_pages=1)),
                                 (self.normal(), self.registry())]:
            values[FEED+'?paged=2'] = values[FEED]
            result = self.collect(values, registry=registry)
            self.assertFalse(result['index_complete'])
            self.assertFalse(result['review_complete'])

    def test_unknown_map_date_is_retained_without_exposing_slug_or_title(self):
        values = self.normal()
        secret = 'https://rrhheducacion.carm.es/resolucion-de-persona-ficticia/'
        values[MAP] = sitemap(PAGE, secret)
        result = self.collect(values)
        unknown = [a for a in result['announcements'] if a.get('published_at') is None]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]['status'], 'discovered')
        self.assertFalse(result['review_complete'])
        public = json.dumps(result)
        self.assertNotIn('persona-ficticia', public)
        self.assertNotIn('Resolución de una persona', public)

    def test_changed_or_unavailable_preserves_last_verified_time(self):
        manifest = {'content_id': '900001', 'source_url': DOC, 'sha256': hashlib.sha256(PDF).hexdigest(), 'incorporated': True}
        first = self.collect(self.normal(), manifest=manifest)
        self.assertEqual(first['documents'][0]['status'], 'incorporated')
        for body, status in [(b'%PDF-revision', 'changed'), (SourceError('blocked', 'access_challenge'), 'unavailable')]:
            values = self.normal()
            values[DOC] = body
            later = self.collect(values, previous=first, manifest=manifest, now='2026-10-03T20:00:00Z')
            self.assertEqual(later['documents'][0]['status'], status)
            self.assertEqual(later['documents'][0]['verified_at'], NOW)
            self.assertEqual(later.get('checked_at'), first.get('checked_at'))
            self.assertFalse(later['review_complete'])

    def test_disappeared_documents_and_sources_survive_failed_check(self):
        first = self.collect(self.normal())
        values = {FEED: SourceError('blocked', 'access_challenge'), MAP: SourceError('blocked', 'network_error'), DOC: SourceError('blocked', 'access_challenge')}
        later = self.collect(values, previous=first, now='2026-10-03T20:00:00Z')
        self.assertEqual([d['content_id'] for d in later['documents']], ['900001'])
        self.assertEqual(len(later['announcements']), 1)
        self.assertFalse(later['index_complete'])
        self.assertEqual(later['sources'][0]['checked_at'], NOW)

    def test_external_download_never_enters_inventory(self):
        values = self.normal()
        values[PAGE] = b'<a href="https://evil.example/file.pdf">Orden definitiva</a>'
        values[FEED] = feed(('Orden definitiva', PAGE, 'Wed, 23 Sep 2026 09:00:00 +0200', ''))
        result = self.collect(values)
        self.assertFalse(result['downloads_complete'])
        self.assertEqual(result['documents'], [])
        self.assertIn('unsupported_document_origin', [a.get('error_code') for a in result['announcements']])

    def test_classification_never_applies_provisional_or_unknown_document(self):
        expected = {'Relación provisional de admitidos': 'provisional',
                    'Corrección de errores de lista definitiva': 'correction',
                    'Adjudicación definitiva de destinos': 'award',
                    'Resolución definitiva de admisión': 'admission',
                    'Procedimiento urgente declarado desierto': 'closed_procedure',
                    'Apertura de listas de interinos': 'opening',
                    'Reactivación de aspirantes': 'reactivation',
                    'Ceses de personal interino': 'cessation',
                    'Nuevo documento': 'unclassified',
                    'Relación definitiva tras reclamaciones a la provisional': 'unclassified'}
        for title, kind in expected.items():
            self.assertEqual(inventory.classify(title), kind)

    def test_carm_index_downloads_all_families_not_just_vacancies(self):
        url = 'https://www.carm.es/web/pagina?IDCONTENIDO=75599&IDTIPO=100'
        registry = self.registry()
        registry['sources'] = [{'id': 'annual', 'kind': 'carm_index', 'url': url}]
        values = {url: f'<h2>Curso 2026-2027</h2><a href="{DOC}">Nueva resolución definitiva</a>'.encode(), DOC: PDF}
        result = self.collect(values, registry=registry)
        self.assertTrue(result['index_complete'])
        self.assertEqual(result['documents'][0]['status'], 'pending_review')

    def test_failed_or_missing_source_cannot_be_forgotten_by_registry_change(self):
        first = self.collect(self.normal())
        registry = self.registry()
        registry['sources'] = [{'id': 'rrhh-map', 'kind': 'map', 'url': MAP}]
        result = self.collect({MAP: sitemap(PAGE), DOC: PDF, PAGE: self.normal()[PAGE]}, previous=first, registry=registry)
        self.assertEqual(len(result['sources']), 2)
        self.assertFalse(result['index_complete'])

    def test_provisional_without_review_does_not_download_or_become_incorporated(self):
        values = self.normal()
        values[FEED] = feed(('Lista provisional', PAGE, 'Wed, 23 Sep 2026 09:00:00 +0200', ''))
        values[PAGE] = f'<time datetime="2026-09-23"></time><a href="{DOC}">Lista provisional de admitidos</a>'.encode()
        values.pop(DOC)
        result = self.collect(values)
        self.assertEqual(result['documents'][0]['status'], 'not_applicable')

    def test_detail_budget_is_explicit_without_losing_previous_checks(self):
        values = self.normal()
        values[FEED] = feed(*[('Orden definitiva', PAGE+str(i), 'Wed, 23 Sep 2026 09:00:00 +0200', '') for i in range(2)])
        values[MAP] = sitemap(PAGE+'0', PAGE+'1')
        values[PAGE+'0'] = values[PAGE]
        values[PAGE+'1'] = values[PAGE]
        result = self.collect(values, registry=self.registry(max_details=1))
        self.assertFalse(result['downloads_complete'])
        self.assertEqual(result['pending_announcements'], 1)

    def test_map_only_article_date_is_resolved_and_old_history_is_outside_window(self):
        values = self.normal()
        unknown = PAGE+'archive/'
        values[MAP] = sitemap(PAGE, unknown)
        values[unknown] = b'<meta property="article:published_time" content="2025-09-23T10:00:00+02:00"><article>Old publication</article>'
        result = self.collect(values, registry=self.registry(max_undated_details=1))
        older = [a for a in result['announcements'] if a.get('published_at') == '2025-09-23']
        self.assertEqual(len(older), 1)
        self.assertEqual(older[0]['status'], 'not_applicable')
        self.assertEqual(result['unresolved_catalogue_dates'], 0)

    def test_manifest_hash_recovery_does_not_remain_changed(self):
        manifest = {'source_url': DOC, 'sha256': hashlib.sha256(PDF).hexdigest(), 'incorporated': True}
        values = self.normal()
        values[DOC] = b'%PDF-unreviewed'
        first = self.collect(values, manifest=manifest)
        recovered = self.collect(self.normal(), manifest=manifest, previous=first)
        self.assertEqual(recovered['documents'][0]['status'], 'incorporated')

    def test_reviewed_final_cannot_be_downgraded_by_provisional_label(self):
        values = self.normal()
        values[FEED] = feed(('Lista provisional', PAGE, 'Wed, 23 Sep 2026 09:00:00 +0200', ''))
        values[PAGE] = f'<a href="{DOC}">Lista provisional</a>'.encode()
        result = self.collect(values, manifest={'source_url': DOC, 'sha256': hashlib.sha256(PDF).hexdigest()})
        self.assertFalse(result['review_complete'])
        self.assertEqual(result['documents'][0]['status'], 'pending_review')
        self.assertEqual(result['documents'][0]['error_code'], 'classification_conflict')

    def test_matching_reviewed_manifest_does_not_claim_api_activation(self):
        result = self.collect(self.normal(), manifest={'source_url': DOC, 'sha256': hashlib.sha256(PDF).hexdigest()})
        self.assertEqual(result['documents'][0]['status'], 'pending_review')
        self.assertTrue(result['documents'][0]['reviewed'])
        self.assertFalse(result['review_complete'])

    def test_active_document_is_checked_before_article_backlog_consumes_budget(self):
        result = self.collect(self.normal(), registry=self.registry(max_requests=4),
            manifest={'source_url': DOC, 'sha256': hashlib.sha256(PDF).hexdigest(), 'incorporated': True})
        self.assertEqual(result['documents'][0]['status'], 'incorporated')
        self.assertEqual(result['documents'][0]['verified_at'], NOW)
        self.assertFalse(result['review_complete'])

    def test_dated_map_only_article_is_revisited_and_new_attachment_is_retained(self):
        registry = self.registry(max_undated_details=1)
        registry['sources'] = [{'id': 'rrhh-map', 'kind': 'map', 'url': MAP}]
        values = {MAP: sitemap(PAGE), DOC: PDF,
                  PAGE: f'<time datetime="2026-09-23"></time><a href="{DOC}">Admisión definitiva</a>'.encode()}
        first = self.collect(values, registry=registry)
        self.assertEqual([d['content_id'] for d in first['documents']], ['900001'])
        replacement = DOC.replace('900001', '900002')
        values[replacement] = b'%PDF-1.4 replacement document'
        values[PAGE] = f'<time datetime="2026-09-23"></time><a href="{replacement}">Admisión definitiva</a>'.encode()
        second = self.collect(values, registry=registry, previous=first, now='2026-10-03T20:00:00Z')
        self.assertEqual([d['content_id'] for d in second['documents']], ['900001', '900002'])
        self.assertEqual(second['documents'][1]['downloaded_at'], '2026-10-03T20:00:00Z')
        self.assertTrue(second['documents'][0]['missing_from_index'])

    def test_failed_article_does_not_starve_accessible_article_under_detail_budget(self):
        inaccessible, accessible = sorted([PAGE+'0', PAGE+'1'], key=lambda url: hashlib.sha256(url.encode()).hexdigest())
        values = self.normal()
        values[FEED] = feed(*[('Orden definitiva', url, 'Wed, 23 Sep 2026 09:00:00 +0200', '')
                             for url in (inaccessible, accessible)])
        values[MAP] = sitemap(inaccessible, accessible)
        values[inaccessible] = SourceError('Blocked page', 'access_challenge')
        values[accessible] = values[PAGE]
        first = self.collect(values, registry=self.registry(max_details=1))
        self.assertEqual(first['documents'], [])
        skipped = next(a for a in first['announcements'] if a.get('error_code') == 'detail_limit')
        self.assertNotIn('attempted_at', skipped)
        second = self.collect(values, registry=self.registry(max_details=1), previous=first, now='2026-10-03T20:00:00Z')
        self.assertEqual([d['content_id'] for d in second['documents']], ['900001'])
        self.assertEqual(second['documents'][0]['downloaded_at'], '2026-10-03T20:00:00Z')

    def test_definitive_adjudicatarios_title_is_an_award(self):
        self.assertEqual(inventory.classify('Listado Definitivo de Adjudicatarios Con Plaza en Secundaria'), 'award')
        self.assertEqual(inventory.classify('Listado Provisional de Adjudicatarios Con Plaza en Secundaria'), 'provisional')

    def test_cli_reads_activated_references_alongside_documents(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = {'source_url': DOC, 'sha256': hashlib.sha256(PDF).hexdigest()}
            active = {'documents': [], 'references': [{**source, 'content_id': '900001', 'kind': 'admission', 'incorporated': True}]}
            for filename, data in [('source.json', source), ('active.json', active), ('registry.json', self.registry())]:
                (directory / filename).write_text(json.dumps(data), encoding='utf8')
            argv = ['source_inventory', '--source', str(directory/'source.json'), '--documents', str(directory/'active.json'),
                    '--registry', str(directory/'registry.json'), '--state', str(directory/'state.json'),
                    '--private-dir', str(directory/'private')]
            with patch('sys.argv', argv), patch.object(inventory, 'OfficialClient', return_value=Client(self.normal())), contextlib.redirect_stdout(io.StringIO()):
                try:
                    inventory.main()
                except SystemExit as error:
                    self.assertEqual(error.code, 1)
            state = json.loads((directory/'state.json').read_text(encoding='utf8'))
            self.assertEqual(state['documents'][0]['status'], 'incorporated')
            self.assertTrue(state['review_complete'])


if __name__ == '__main__':
    unittest.main()
