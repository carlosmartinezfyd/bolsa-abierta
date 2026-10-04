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

    def test_provisional_without_review_is_archived_without_becoming_incorporated(self):
        values = self.normal()
        values[FEED] = feed(('Lista provisional', PAGE, 'Wed, 23 Sep 2026 09:00:00 +0200', ''))
        values[PAGE] = f'<time datetime="2026-09-23"></time><a href="{DOC}">Lista provisional de admitidos</a>'.encode()
        result = self.collect(values)
        self.assertEqual(result['documents'][0]['status'], 'pending_review')
        self.assertEqual(result['documents'][0]['sha256'], hashlib.sha256(PDF).hexdigest())
        self.assertEqual(result['documents'][0]['downloaded_at'], NOW)

    def test_unsupported_attachment_does_not_abort_valid_same_page_discovery(self):
        values = self.normal()
        values[PAGE] += b'<a href="https://rrhheducacion.carm.es/private-person-title.pdf">Person title</a>'
        result = self.collect(values)
        self.assertEqual(result['documents'][0]['downloaded_at'], NOW)
        self.assertEqual(result['skipped_links'][0]['error_code'], 'unsupported_document_origin')
        self.assertNotIn('Person title', json.dumps(result))
        self.assertNotIn('private-person-title', json.dumps(result))

    def test_budget_deferral_has_no_false_attempt_or_missing_parent_evidence(self):
        first = self.collect(self.normal())
        later = self.collect(self.normal(), previous=first, registry=self.registry(max_requests=1),
                             now='2026-10-03T20:00:00Z')
        doc = later['documents'][0]
        self.assertEqual(doc['status'], 'skipped')
        self.assertEqual(doc['downloaded_at'], NOW)
        self.assertEqual(doc['attempted_at'], NOW)
        self.assertFalse(doc.get('missing_from_index', False))
        skipped_source = next(s for s in later['sources'] if s['id'] == 'rrhh-map')
        self.assertEqual(skipped_source['status'], 'skipped')
        self.assertEqual(skipped_source['attempted_at'], NOW)

    def test_unvisited_article_cannot_mark_prior_attachment_missing(self):
        first = self.collect(self.normal())
        values = self.normal()
        values[FEED] = feed(('Orden definitiva', PAGE, 'Wed, 23 Sep 2026 09:00:00 +0200', ''))
        values[PAGE] = SourceError('challenge', 'access_challenge')
        result = self.collect(values, previous=first)
        self.assertFalse(result['documents'][0].get('missing_from_index', False))

    def test_byte_revisions_preserve_history_and_title_changes_are_separate(self):
        first = self.collect(self.normal())
        values = self.normal()
        values[DOC] = b'%PDF-revision'
        values[PAGE] = f'<a href="{DOC}">Corrección de errores</a>'.encode()
        later = self.collect(values, previous=first, now='2026-10-03T20:00:00Z')
        doc = later['documents'][0]
        self.assertEqual([v['sha256'] for v in doc['content_history']],
                         [hashlib.sha256(PDF).hexdigest(), hashlib.sha256(b'%PDF-revision').hexdigest()])
        self.assertGreater(len(doc['metadata_history']), 1)
        self.assertEqual(first['documents'][0]['sha256'], hashlib.sha256(PDF).hexdigest())
        self.assertEqual(len(first['documents'][0]['content_history']), 1)

    def test_roster_semantics_outrank_incidental_vacancy_wording(self):
        self.assertEqual(inventory.classify('Lista definitiva de interinos que cubren vacantes'), 'baseline')
        self.assertEqual(inventory.classify('Lista complementaria de interinos para vacantes'), 'supplement')

    def test_unclassified_manifest_placeholder_does_not_conflict_with_observed_baseline(self):
        root = 'https://www.carm.es/web/pagina?IDCONTENIDO=75599&IDTIPO=100'
        registry = self.registry()
        registry['sources'] = [{'id': 'annual', 'kind': 'carm_index', 'url': root}]
        result = self.collect({root: f'<a href="{DOC}">Lista definitiva de interinos para vacantes</a>'.encode(),
                               DOC: PDF}, registry=registry,
                              manifest={'source_url': DOC, 'sha256': hashlib.sha256(PDF).hexdigest()})
        self.assertEqual(result['documents'][0]['kind'], 'baseline')

    def test_bounded_carm_pagination_and_detail_coverage(self):
        root = 'https://www.carm.es/web/pagina?IDCONTENIDO=75669&IDTIPO=100'
        page2 = root + '&RESULTADO_INFERIOR=21&RESULTADO_SUPERIOR=40'
        detail = 'https://www.carm.es/web/pagina?IDCONTENIDO=209000&IDTIPO=60'
        registry = self.registry(max_index_pages=2)
        registry['sources'] = [{'id': 'urgent', 'kind': 'carm_index', 'url': root,
                                'family': 'urgent', 'body': 'secondary', 'priority': 1}]
        result = self.collect({root: f'<a href="{page2}">2</a><a href="{detail}">Resolución</a>'.encode(),
                               page2: f'<a href="{DOC}">Admisión definitiva</a>'.encode(),
                               detail: f'<a href="{DOC}">Admisión definitiva</a>'.encode(), DOC: PDF}, registry=registry)
        self.assertEqual(result['sources'][0]['pages'], 2)
        self.assertEqual(result['documents'][0]['downloaded_at'], NOW)
        scope = result['coverage']['sources'][0]
        self.assertEqual(scope['family'], 'urgent')
        self.assertEqual(scope['course'], '2026-2027')
        self.assertEqual(scope['history_complete'], False)

    def test_registry_prioritizes_audited_result_leaves_and_all_requested_families(self):
        registry = json.loads(Path('data/source-registry.json').read_text())
        ids = {s['url'].split('IDCONTENIDO=')[1].split('&')[0] for s in registry['sources']
               if 'IDCONTENIDO=' in s['url']}
        self.assertTrue({'75599', '75501', '24219', '24183', '75669', '45756', '75568',
                         '75757', '75756', '75754', '4254', '27204'} <= ids)
        self.assertTrue(any(s['family'].startswith('habilitations') for s in registry['sources']))

    def test_reviewed_document_survives_one_request_budget(self):
        result = self.collect(self.normal(), registry=self.registry(max_requests=1),
                              manifest={'source_url': DOC, 'sha256': hashlib.sha256(PDF).hexdigest(),
                                        'incorporated': True})
        self.assertEqual(result['documents'][0]['status'], 'incorporated')
        self.assertEqual(result['documents'][0]['verified_at'], NOW)

    def test_unfetched_observed_pagination_is_retained_for_next_run(self):
        root = 'https://www.carm.es/web/pagina?IDCONTENIDO=75669&IDTIPO=100'
        page2 = root + '&RESULTADO_INFERIOR=21&RESULTADO_SUPERIOR=40'
        registry = self.registry(max_requests=1)
        registry['sources'] = [{'id': 'urgent-history', 'kind': 'carm_index', 'url': root,
                                'queue': 'historical'}]
        first = self.collect({root: f'<a href="{page2}">2</a>'.encode()}, registry=registry)
        self.assertEqual(first['sources'][0]['pending_page_urls'], [page2])
        self.assertFalse(first['sources'][0]['scope_complete'])
        second = self.collect({page2: f'<a href="{DOC}">Admisión definitiva</a>'.encode()},
                              registry=registry, previous=first)
        self.assertEqual(second['documents'][0]['content_id'], '900001')
        self.assertEqual(second['documents'][0]['status'], 'skipped')

    def test_habilitations_detail_page_follows_observed_carm_attachment_leaf(self):
        root = 'https://rrhheducacion.carm.es/habilitaciones-para-la-imparticion-de-modulos-atribuidos-a-especialistas/'
        detail = 'https://www.carm.es/web/pagina?IDCONTENIDO=209000&IDTIPO=60'
        registry = self.registry()
        registry['sources'] = [{'id': 'habilitations', 'kind': 'rrhh_page', 'url': root,
                                'family': 'habilitations_modulos'}]
        result = self.collect({root: f'<a href="{detail}">Resolución definitiva</a>'.encode(),
                               detail: f'<a href="{DOC}">Resolución definitiva</a>'.encode(), DOC: PDF}, registry=registry)
        self.assertEqual(result['documents'][0]['downloaded_at'], NOW)

    def test_failed_result_leaf_keeps_source_coverage_partial(self):
        root = 'https://www.carm.es/web/pagina?IDCONTENIDO=75669&IDTIPO=100'
        detail = 'https://www.carm.es/web/pagina?IDCONTENIDO=209000&IDTIPO=60'
        registry = self.registry()
        registry['sources'] = [{'id': 'urgent', 'kind': 'carm_index', 'url': root}]
        result = self.collect({root: f'<a href="{detail}">Resolución definitiva</a>'.encode(),
                               detail: SourceError('blocked', 'access_challenge')}, registry=registry)
        self.assertFalse(result['coverage']['sources'][0]['scope_complete'])
        self.assertEqual(result['coverage']['sources'][0]['pending_details'], 1)

    def test_announcement_follows_bounded_carm_detail_chain_to_all_attachments(self):
        detail = 'https://www.carm.es/web/pagina?IDCONTENIDO=209000&IDTIPO=60'
        leaf = 'https://www.carm.es/web/pagina?IDCONTENIDO=209001&IDTIPO=60'
        values = self.normal()
        values[FEED] = feed(('Resolución definitiva', PAGE, 'Wed, 23 Sep 2026 09:00:00 +0200', ''))
        values[PAGE] = f'<a href="{detail}">Resolución definitiva</a>'.encode()
        values[detail] = f'<a href="{leaf}">Anexos definitivos</a>'.encode()
        values[leaf] = f'<a href="{DOC}">Admisión definitiva</a>'.encode()
        result = self.collect(values)
        self.assertEqual(result['documents'][0]['downloaded_at'], NOW)

    def test_invalid_empty_parent_never_establishes_attachment_disappearance(self):
        root = 'https://www.carm.es/web/pagina?IDCONTENIDO=75599&IDTIPO=100'
        registry = self.registry()
        registry['sources'] = [{'id': 'annual', 'kind': 'carm_index', 'url': root}]
        first = self.collect({root: f'<a href="{DOC}">Lista definitiva</a>'.encode(), DOC: PDF}, registry=registry)
        second = self.collect({root: b'', DOC: PDF}, registry=registry, previous=first, now='2026-10-03T20:00:00Z')
        self.assertEqual(second['sources'][0]['error_code'], 'invalid_index')
        self.assertFalse(second['documents'][0].get('missing_from_index', False))
        self.assertNotIn('missing_parent_ids', second['documents'][0])
        self.assertEqual(second['sources'][0]['first_page_checked_at'], NOW)

    def test_recent_pagination_rotates_beyond_limit_while_refreshing_front_page(self):
        root = 'https://www.carm.es/web/pagina?IDCONTENIDO=24219&IDTIPO=100'
        page2 = root + '&RESULTADO_INFERIOR=21&RESULTADO_SUPERIOR=40'
        page3 = root + '&RESULTADO_INFERIOR=41&RESULTADO_SUPERIOR=60'
        registry = self.registry(max_index_pages=1)
        registry['sources'] = [{'id': 'results', 'kind': 'carm_index', 'url': root, 'queue': 'recent'}]
        values = {root: f'<a href="{page2}">2</a><a href="{page3}">3</a>'.encode(),
                  page2: b'<p>Archive page two</p>', page3: f'<a href="{DOC}">Admisión definitiva</a>'.encode(), DOC: PDF}
        first = self.collect(values, registry=registry)
        exhausted = self.collect(values, registry={**registry, 'limits': {**registry['limits'], 'max_requests': 1}}, previous=first)
        self.assertEqual(exhausted['sources'][0]['pending_page_urls'], first['sources'][0]['pending_page_urls'])
        second = self.collect(values, registry=registry, previous=exhausted)
        third = self.collect(values, registry=registry, previous=second)
        self.assertEqual(third['documents'][0]['downloaded_at'], NOW)
        # A new attachment on the front page must be seen during continuation.
        new_doc = DOC.replace('900001', '900002')
        values[root] += f'<a href="{new_doc}">Admisión definitiva</a>'.encode()
        values[new_doc] = PDF
        refreshed = self.collect(values, registry=registry, previous=third)
        self.assertEqual([d['content_id'] for d in refreshed['documents']], ['900001', '900002'])

    def test_failed_direct_pdf_has_partial_download_coverage_with_complete_traversal(self):
        root = 'https://www.carm.es/web/pagina?IDCONTENIDO=75599&IDTIPO=100'
        registry = self.registry()
        registry['sources'] = [{'id': 'annual', 'kind': 'carm_index', 'url': root, 'family': 'annual_lists'}]
        result = self.collect({root: f'<a href="{DOC}">Lista definitiva</a>'.encode(),
                               DOC: SourceError('blocked', 'access_challenge')}, registry=registry)
        scope = result['coverage']['sources'][0]
        self.assertFalse(scope['scope_complete'])
        self.assertTrue(scope['traversal_complete'])
        self.assertFalse(scope['downloads_complete'])
        self.assertEqual(scope['failed_documents'], 1)
        self.assertEqual(result['coverage']['families'][0]['failed_documents'], 1)

    def test_changed_pdf_bytes_are_downloaded_but_not_verified_for_its_scope(self):
        root = 'https://www.carm.es/web/pagina?IDCONTENIDO=75599&IDTIPO=100'
        registry = self.registry()
        registry['sources'] = [{'id': 'annual', 'kind': 'carm_index', 'url': root}]
        result = self.collect({root: f'<a href="{DOC}">Lista definitiva</a>'.encode(), DOC: b'%PDF-revision'},
                              registry=registry, manifest={'source_url': DOC, 'sha256': hashlib.sha256(PDF).hexdigest()})
        scope = result['coverage']['sources'][0]
        self.assertTrue(scope['downloads_complete'])
        self.assertFalse(scope['verification_complete'])
        self.assertFalse(scope['scope_complete'])
        self.assertEqual(scope['unreviewed_documents'], 1)

    def test_repository_reviewed_metadata_and_maestros_are_verified_before_activation(self):
        baseline = {'source_url': DOC, 'sha256': hashlib.sha256(PDF).hexdigest()}
        award = {'source_url': DOC.replace('900001', '900002'), 'sha256': 'b'*64, 'kind': 'award', 'row_count': 147}
        observation = {'source_url': DOC.replace('900001', '900003'), 'sha256': 'c'*64, 'kind': 'optan_observation'}
        maestros = {'source_url': DOC.replace('900001', '900004'), 'sha256': 'd'*64, 'kind': 'maestros_roster',
                    'amendments': [{'source_url': DOC.replace('900001', '900005'), 'sha256': 'e'*64, 'kind': 'maestros_correction'}]}
        active = {'active_version': 'f'*64, 'documents': [{**award, 'row_count': 132, 'incorporated': True},
                                                          {**{k: v for k, v in maestros.items() if k != 'amendments'}, 'incorporated': True}],
                  'observation_documents': [{**observation, 'incorporated': True}]}
        merged = inventory._merge_reviewed_metadata(baseline, {'documents': [award], 'observation_documents': [observation]}, maestros, active)
        items = inventory._reviewed(merged)
        self.assertEqual(len(items), 5)
        self.assertEqual(items['900002']['row_count'], 147)
        self.assertTrue(items['900002']['incorporated'])
        self.assertFalse(items['900003']['incorporated'])
        self.assertFalse(items['900005']['incorporated'])
        inactive = inventory._merge_reviewed_metadata(baseline, {'documents': [award]}, maestros, {})
        self.assertFalse(any(d.get('incorporated') for d in inventory._reviewed(inactive).values()))

    def test_reviewed_metadata_revision_replaces_prior_classification_at_same_hash(self):
        first = self.collect(self.normal(), manifest={'source_url': DOC, 'sha256': hashlib.sha256(PDF).hexdigest(),
                                                     'kind': 'admission', 'row_count': 132})
        values = {DOC: PDF}
        registry = self.registry()
        registry['sources'] = []
        revised = self.collect(values, registry=registry, previous=first,
                               manifest={'source_url': DOC, 'sha256': hashlib.sha256(PDF).hexdigest(),
                                         'kind': 'baseline', 'row_count': 147})
        self.assertEqual(revised['documents'][0]['kind'], 'baseline')
        self.assertEqual(revised['documents'][0]['row_count'], 147)
        self.assertEqual(revised['documents'][0]['status'], 'pending_review')
        self.assertEqual(len(revised['documents'][0]['content_history']), 1)

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
            active = {'active_version': 'a'*64, 'documents': [], 'references': [{**source, 'content_id': '900001', 'kind': 'admission', 'incorporated': True}]}
            for filename, data in [('source.json', source), ('active.json', active), ('registry.json', self.registry()), ('reviewed.json', {}), ('maestros.json', {})]:
                (directory / filename).write_text(json.dumps(data), encoding='utf8')
            argv = ['source_inventory', '--source', str(directory/'source.json'), '--documents', str(directory/'active.json'),
                    '--reviewed-documents', str(directory/'reviewed.json'), '--maestros', str(directory/'maestros.json'),
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

    def test_cli_reads_repository_and_observation_metadata_before_first_activation(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            digest = hashlib.sha256(PDF).hexdigest()
            source = {'source_url': DOC, 'sha256': digest}
            award = {'source_url': DOC.replace('900001', '900002'), 'sha256': digest, 'kind': 'award', 'row_count': 147}
            observation = {'source_url': DOC.replace('900001', '900003'), 'sha256': digest, 'kind': 'optan_observation'}
            maestros = {'source_url': DOC.replace('900001', '900004'), 'sha256': digest, 'kind': 'maestros_roster',
                        'amendments': [{'source_url': DOC.replace('900001', '900005'), 'sha256': digest, 'kind': 'maestros_correction'}]}
            registry = self.registry()
            registry['sources'] = []
            for filename, data in [('source.json', source), ('registry.json', registry),
                                   ('reviewed.json', {'documents': [award], 'observation_documents': [observation]}),
                                   ('maestros.json', maestros)]:
                (directory/filename).write_text(json.dumps(data), encoding='utf8')
            argv = ['source_inventory', '--source', str(directory/'source.json'),
                    '--documents', str(directory/'not-yet-active.json'), '--registry', str(directory/'registry.json'),
                    '--reviewed-documents', str(directory/'reviewed.json'), '--maestros', str(directory/'maestros.json'),
                    '--state', str(directory/'state.json'), '--private-dir', str(directory/'private')]
            values = {item['source_url']: PDF for item in [source, award, observation, maestros, maestros['amendments'][0]]}
            with patch('sys.argv', argv), patch.object(inventory, 'OfficialClient', return_value=Client(values)), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    inventory.main()
            result = json.loads((directory/'state.json').read_text())
            self.assertEqual(len(result['documents']), 5)
            self.assertTrue(all(d['status'] == 'pending_review' and d['reviewed'] for d in result['documents']))
            self.assertEqual(result['documents'][1]['row_count'], 147)


if __name__ == '__main__':
    unittest.main()
