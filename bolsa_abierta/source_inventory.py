"""Durable, metadata-only inventory of official teaching-list publications.

Discovery is not incorporation. Only bytes matching the reviewed ingestion
manifest can be marked incorporated; this module never changes a person's rank.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from .sources import OfficialClient, SourceError, _allowed_url, _challenge, _fold, canonical_url


STATES = frozenset({'discovered', 'unavailable', 'changed', 'pending_review',
                    'incorporated', 'not_applicable', 'skipped'})


def classify(title):
    value = _fold(title)
    if 'provisional' in value and 'definitiv' in value:
        return 'unclassified'
    if 'provisional' in value:
        return 'provisional'
    if 'correccion' in value or 'rectificacion' in value:
        return 'correction'
    if 'desiert' in value:
        return 'closed_procedure'
    if 'reactivacion' in value or 'reincorporacion' in value:
        return 'reactivation'
    if re.search(r'\b(ceses?|bajas?|exclusion)\b', value):
        return 'cessation'
    if any(word in value for word in ('adjudicacion', 'adjudicados', 'adjudicatarios')) and 'definitiv' in value:
        return 'award'
    if 'complementaria' in value:
        return 'supplement'
    if 'list' in value and 'interin' in value and 'definitiv' in value:
        return 'baseline'
    if 'vacantes' in value:
        return 'vacancies'
    if 'abiert' in value or 'apertura' in value:
        return 'opening'
    if 'definitiv' in value and any(v in value for v in ('admision', 'admitid', 'convocatoria')):
        return 'admission'
    if 'list' in value and 'interin' in value and 'definitiv' in value:
        return 'baseline'
    if 'urgente' in value or 'convocatoria' in value:
        return 'procedure'
    return 'unclassified'


def _opaque(url):
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()


def _html(body):
    if _challenge(body):
        raise SourceError('Official source requires verification', 'access_challenge')
    return BeautifulSoup(body.decode('utf-8', errors='replace'), 'html.parser')


def _document_url(url):
    value = _allowed_url(url)
    query = parse_qs(value.query)
    ids = query.get('IDCONTENIDO', [])
    if value.hostname != 'www.carm.es' or value.path != '/web/descarga' or len(ids) != 1 or not ids[0].isdigit():
        raise SourceError('Unsupported official document identity', 'unsupported_document_origin')
    return ids[0]


def _document_links(body, base_url, title='', *, skipped=None):
    result = []
    for anchor in _html(body).select('a[href]'):
        url = urljoin(base_url, anchor['href'])
        path = urlsplit(url).path.lower()
        if path != '/web/descarga' and not path.endswith('.pdf'):
            continue
        try:
            identity = _document_url(url)
        except SourceError:
            if skipped is not None:
                # Unsupported URLs and titles may name people. Store only
                # irreversible identities and safe host/error metadata.
                skipped.append({'url_id': hashlib.sha256(url.encode()).hexdigest(),
                                'parent_id': _opaque(base_url),
                                'error_code': 'unsupported_document_origin'})
            continue
        label = anchor.get_text(' ', strip=True)
        kind = classify(label)
        if kind == 'unclassified':
            kind = classify(title)
        result.append({'content_id': identity, 'source_url': url, 'kind': kind,
                       'classification_status': 'uncertain' if kind == 'unclassified' else 'title_only',
                       'title_sha256': hashlib.sha256(label.encode()).hexdigest()})
    return result


def _feed(body):
    if _challenge(body):
        raise SourceError('Official feed requires verification', 'access_challenge')
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
        raise SourceError('Unsupported feed entities', 'invalid_feed')
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise SourceError('Unrecognized official feed', 'invalid_feed') from error
    if root.tag != 'rss' or root.find('channel') is None:
        raise SourceError('Unrecognized official feed', 'invalid_feed')
    entries = []
    for item in root.findall('./channel/item'):
        try:
            url = item.findtext('link', '').strip()
            value = _allowed_url(url)
            if value.hostname != 'rrhheducacion.carm.es':
                raise ValueError('foreign feed link')
            stamp = parsedate_to_datetime(item.findtext('pubDate', ''))
            if stamp.tzinfo is None:
                raise ValueError('undated feed item')
        except (SourceError, ValueError, TypeError) as error:
            raise SourceError('Invalid official feed item', 'invalid_feed_item') from error
        entries.append({'id': _opaque(url), 'url': url, 'published_at': stamp.date().isoformat(),
                        'title': item.findtext('title', ''),
                        'body': item.findtext('{http://purl.org/rss/1.0/modules/content/}encoded', '').encode()})
    return entries


def _map(body, base_url):
    anchors = _html(body).select('a.rank-math-html-sitemap__link[href]')
    if not anchors:
        raise SourceError('Official catalogue has no recognized entries', 'invalid_catalogue')
    result = {}
    for anchor in anchors:
        url = urljoin(base_url, anchor['href'])
        value = _allowed_url(url)
        if value.hostname != 'rrhheducacion.carm.es':
            raise SourceError('Official catalogue contains a foreign entry', 'invalid_catalogue')
        result[_opaque(url)] = {'id': _opaque(url), 'url': url, 'title': anchor.get_text(' ', strip=True)}
    return result


def _manifest_entries(source, *, inherited_active=False, observation=False):
    observation = observation or source.get('kind') == 'optan_observation'
    active = bool(source.get('incorporated', inherited_active)) and not observation
    if source.get('source_url'):
        item = {k: deepcopy(v) for k, v in source.items()
                if k not in ('amendments', 'documents', 'references', 'observation_documents')}
        item['incorporated'] = active
        if observation:
            item['observation_only'] = True
        yield item
    for key in ('amendments', 'documents', 'references', 'observation_documents'):
        for item in source.get(key, []):
            yield from _manifest_entries(item, inherited_active=active,
                                         observation=observation or key == 'observation_documents')


def _reviewed(source):
    result = {}
    for item in _manifest_entries(source):
        identity = _document_url(item['source_url'])
        if item.get('content_id', identity) != identity or not re.fullmatch('[a-f0-9]{64}', item.get('sha256', '')):
            raise ValueError('Invalid reviewed document manifest')
        if identity in result and result[identity]['sha256'] != item['sha256']:
            raise ValueError('Conflicting reviewed document hashes')
        result[identity] = item
    return result


def _merge_reviewed_metadata(source, repository, maestros, active):
    """Code-reviewed interpretations win; activation requires prior evidence."""
    active_items = _reviewed(active) if active.get('active_version') else {}
    reviewed_items = _reviewed({'documents': [source, repository, maestros]})
    merged = dict(active_items)
    merged.update(reviewed_items)
    for identity, item in merged.items():
        prior = active_items.get(identity, {})
        item['incorporated'] = bool(prior.get('incorporated') is True and
            prior.get('sha256') == item['sha256'] and not item.get('observation_only'))
    return {'documents': list(merged.values())}


def _apply_reviewed_metadata(doc, known, now):
    # Do not copy document titles or arbitrary response fields into public state.
    fields = ('kind', 'source_url', 'published_at', 'course', 'parser_revision',
              'rank_scope', 'row_count', 'pages', 'process_id', 'signed_at')
    snapshot = {key: known[key] for key in fields if key in known}
    if known.get('title'):
        snapshot['title_sha256'] = hashlib.sha256(known['title'].encode()).hexdigest()
    snapshot.update(evidence_type='reviewed_definition', reviewed_sha256=known['sha256'])
    history = doc.setdefault('metadata_history', [])
    if not any({k: v for k, v in old.items() if k != 'observed_at'} == snapshot for old in history):
        history.append({**snapshot, 'observed_at': now})
    doc.update({key: known[key] for key in fields if key in known})
    if known.get('kind'):
        doc['reviewed_kind'] = known['kind']
        doc['classification_status'] = 'reviewed_metadata'
    doc['observation_only'] = bool(known.get('observation_only'))


def _published_date(body):
    soup = _html(body)
    values = [item.get('content', '') for item in soup.select('meta[property="article:published_time"]')]
    values += [item.get('datetime', '') for item in soup.select('time[datetime]')]
    dates = set()
    for value in values:
        try:
            dates.add(date.fromisoformat(value[:10]).isoformat())
        except ValueError:
            continue
    return next(iter(dates)) if len(dates) == 1 else None


def _defer(item, code, now):
    if item.get('status') != 'skipped':
        item['prior_status'] = item.get('status', 'discovered')
    item.update(status='skipped', work_status='deferred', error_code=code, queued_at=now)


def _verify_document(doc, known, fetch, now):
    expected = known.get('sha256')
    doc.pop('error_code', None)
    try:
        body = fetch(doc['source_url'], 'pdf')
        doc['attempted_at'] = now
        if not body.startswith(b'%PDF-'):
            raise SourceError('Not a PDF document', 'invalid_pdf')
        digest, prior = hashlib.sha256(body).hexdigest(), doc.get('sha256')
        history = doc.setdefault('content_history', [])
        if prior and not any(v['sha256'] == prior for v in history):
            history.append({key: doc[key] for key in ('sha256', 'bytes', 'downloaded_at') if key in doc})
        if not any(v['sha256'] == digest for v in history):
            history.append({'sha256': digest, 'bytes': len(body), 'downloaded_at': now})
        doc.update(sha256=digest, bytes=len(body), downloaded_at=now)
        doc['work_status'] = 'checked'
        if expected and digest == expected and (doc['kind'] == 'provisional' or doc.get('provisional_observed')):
            doc.update(status='pending_review', error_code='classification_conflict', reviewed=False)
        elif expected and digest == expected:
            doc.update(status='incorporated' if known.get('incorporated') is True else 'pending_review',
                       verified_at=now, reviewed=True)
        elif (expected and digest != expected) or (prior and digest != prior) or doc.get('status') == 'changed':
            doc.update(status='changed', reviewed=False)
        else:
            doc['status'] = 'pending_review'
        return True
    except SourceError as error:
        if error.code == 'traversal_limit':
            _defer(doc, error.code, now)
        else:
            doc.update(status='unavailable', work_status='failed', error_code=error.code, attempted_at=now)
        return False


def _page_links(body, base_url):
    """Bounded observed navigation only; never fabricate pagination URLs."""
    pages, details = {}, {}
    base = urlsplit(base_url)
    base_query = parse_qs(base.query)
    for anchor in _html(body).select('a[href]'):
        url = urljoin(base_url, anchor['href'])
        try:
            parsed = _allowed_url(url)
        except SourceError:
            continue
        if parsed.path != '/web/pagina' or parsed.hostname != 'www.carm.es':
            continue
        query = parse_qs(parsed.query)
        if len(query.get('IDCONTENIDO', [])) != 1 or not query['IDCONTENIDO'][0].isdigit():
            continue
        identity = _opaque(url)
        label = anchor.get_text(' ', strip=True)
        if parsed.hostname == base.hostname and query.get('IDCONTENIDO') == base_query.get('IDCONTENIDO'):
            if any(key in query for key in ('RESULTADO_INFERIOR', 'RESULTADO_SUPERIOR', 'paged', 'pagina', 'page')):
                pages[identity] = url
        elif query.get('IDTIPO', [''])[0] in ('100', '60'):
            details[identity] = {'id': identity, 'url': url, 'title': label}
    return pages, details


def collect_inventory(registry, manifest, *, previous=None, client=None, now=None, private_dir=None):
    """Reconcile bounded official discovery while preserving prior evidence.

    Completeness is scoped to configured pages/course windows, never the entire
    historical archive. Public queues use opaque identities, without post titles
    or slugs. Original bytes are written only to the caller's private directory.
    """
    previous = deepcopy(previous or {})
    since = date.fromisoformat(registry['since']).isoformat()
    now = now or datetime.now(timezone.utc).isoformat()
    limits = {'max_feed_pages': 80, 'max_requests': 160, 'max_seconds': 240, 'max_details': 50,
              'max_undated_details': 5, 'max_index_pages': 3, 'max_historical_details': 3,
              'download_reserve': 12, 'max_detail_depth': 2}
    limits.update(registry.get('limits', {}))
    optional_zero = {'max_undated_details', 'max_historical_details', 'download_reserve'}
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or
           (v == 0 and k not in optional_zero) for k, v in limits.items()):
        raise ValueError('Inventory budgets must be positive')
    reviewed = _reviewed(manifest)
    client = client or OfficialClient(max_pdf_bytes=60_000_000, retries=0, max_seconds=20)
    private_dir = Path(private_dir) if private_dir is not None else None
    if private_dir:
        private_dir.mkdir(parents=True, exist_ok=True)
    deadline, requests_used = time.monotonic()+limits['max_seconds'], 0
    sources = {s['id']: s for s in previous.get('sources', [])}
    announcements = {a['id']: a for a in previous.get('announcements', [])}
    documents = {d['content_id']: d for d in previous.get('documents', [])}
    report = {'schema_version': 2, 'course': registry['course'], 'since': since, 'attempted_at': now,
              'index_complete': True, 'downloads_complete': True, 'review_complete': False,
              'skipped_links': []}
    if previous.get('checked_at'):
        report['checked_at'] = previous['checked_at']
    candidates, catalogue, observed, parent_documents = {}, {}, set(), {}
    complete_catalogues, catalogue_members = set(), {}
    source_ids = {s['id'] for s in registry['sources']}
    reserve = min(int(limits['download_reserve']), int(limits['max_requests'])//5)
    verified_this_run = set()

    def fetch(url, kind='html', *, reserve_requests=0):
        nonlocal requests_used
        if requests_used >= limits['max_requests']-reserve_requests or time.monotonic() >= deadline:
            raise SourceError('Inventory traversal budget exhausted', 'traversal_limit')
        requests_used += 1
        fetched = client.fetch(url, kind=kind)
        if fetched.status != 200 or _challenge(fetched.body):
            raise SourceError('Unverified official response', 'invalid_response')
        if private_dir:
            digest = hashlib.sha256(fetched.body).hexdigest()
            (private_dir / (digest + ('.pdf' if kind == 'pdf' else '.html'))).write_bytes(fetched.body)
        return fetched.body

    def failure(item, error):
        if error.code == 'traversal_limit':
            _defer(item, error.code, now)
        else:
            item.update(status='unavailable', work_status='failed', error_code=error.code, attempted_at=now)

    def record_document(item, parent_id, definition=None):
        identity = item['content_id']
        observed.add(identity)
        doc = documents.setdefault(identity, {'content_id': identity, 'status': 'discovered', 'first_seen_at': now})
        old_kind = doc.get('kind')
        if old_kind == 'unclassified' and not any(h.get('title_sha256') for h in doc.get('metadata_history', [])):
            old_kind = None
        if identity in reviewed and reviewed[identity].get('kind'):
            doc.update(kind=reviewed[identity]['kind'], classification_status='reviewed_metadata')
        elif old_kind and old_kind != item['kind']:
            doc.update(kind='unclassified', classification_status='uncertain')
        else:
            doc.update(kind=item['kind'], classification_status=item.get('classification_status', 'title_only'))
        if item['kind'] == 'provisional':
            doc['provisional_observed'] = True
        doc.update(source_url=item['source_url'], last_seen_at=now)
        doc['source_ids'] = sorted(set(doc.get('source_ids', [])) | {parent_id})
        doc['parent_ids'] = sorted(set(doc.get('parent_ids', doc['source_ids'])) | {parent_id})
        metadata = {'parent_id': parent_id, 'source_url': item['source_url'], 'kind': item['kind'],
                    'title_sha256': item.get('title_sha256'),
                    'classification_status': item.get('classification_status', 'uncertain'),
                    'published_at': item.get('published_at')}
        if definition:
            metadata.update(family=definition.get('family', 'unspecified'), body=definition.get('body', 'unspecified'),
                            course=definition.get('course', registry['course']))
            doc['family'] = metadata['family']
            doc['body'] = metadata['body']
            doc['priority'] = definition.get('priority', 50)
            doc['registry_source_ids'] = sorted(set(doc.get('registry_source_ids', [])) | {definition['id']})
        history = doc.setdefault('metadata_history', [])
        if not any({k: v for k, v in version.items() if k != 'observed_at'} == metadata for version in history):
            history.append({**metadata, 'observed_at': now})
        doc.pop('missing_from_index', None)
        doc.pop('missing_parent_ids', None)

    def links(body, url, parent_id, title='', definition=None, published=None):
        before = len(report['skipped_links'])
        docs = _document_links(body, url, title, skipped=report['skipped_links'])
        for doc in docs:
            doc['published_at'] = published
            record_document(doc, parent_id, definition)
        return docs, len(report['skipped_links']) != before

    def verify(doc, known):
        if not _verify_document(doc, known, fetch, now):
            report['downloads_complete'] = False
        verified_this_run.add(doc['content_id'])

    # Active evidence always receives the first request slots, even with a tiny
    # budget; discovery cannot prevent checking an incorporated original.
    for identity, item in reviewed.items():
        doc = documents.setdefault(identity, {'content_id': identity, 'source_url': item['source_url'],
            'kind': item.get('kind', 'unclassified'), 'status': 'discovered', 'first_seen_at': now, 'source_ids': []})
        _apply_reviewed_metadata(doc, item, now)
        verify(doc, item)

    for identity, source in sources.items():
        if identity not in source_ids:
            source.update(status='unavailable', error_code='source_removed')
            report['index_complete'] = False

    definitions = sorted(registry['sources'], key=lambda s: (s.get('queue') == 'historical', s.get('priority', 50)))
    for definition in definitions:
        identity, kind, url = definition['id'], definition['kind'], definition['url']
        if not re.fullmatch('[a-z0-9_-]+', identity):
            raise ValueError('Source IDs must be non-personal identifiers')
        _allowed_url(url)
        current = sources.setdefault(identity, {'id': identity, 'kind': kind})
        current.update(pages=0, scope_complete=False, pending_pages=0, pending_details=0,
                       unsupported_links=0,
                       family=definition.get('family', 'unspecified'), body=definition.get('body', 'unspecified'),
                       course=definition.get('course', registry['course']), history_complete=False)
        current.pop('error_code', None)
        try:
            if kind == 'rss':
                reached_window, digests, last_date = False, set(), None
                members = set()
                for page in range(1, int(limits['max_feed_pages'])+1):
                    page_url = url if page == 1 else url+('&' if '?' in url else '?')+urlencode({'paged': page})
                    body = fetch(page_url, 'rss', reserve_requests=reserve)
                    current['attempted_at'] = now
                    digest = hashlib.sha256(body).hexdigest()
                    if digest in digests:
                        raise SourceError('Official feed repeated a page', 'repeated_page')
                    digests.add(digest)
                    entries = _feed(body)
                    current['pages'] += 1
                    if not entries:
                        if page == 1:
                            raise SourceError('Empty official feed', 'empty_feed')
                        reached_window = True
                        break
                    for entry in entries:
                        if last_date and entry['published_at'] > last_date:
                            raise SourceError('Official feed is not chronologically continuous', 'unordered_feed')
                        last_date = entry['published_at']
                        if entry['published_at'] < since:
                            reached_window = True
                            continue
                        members.add(entry['id'])
                        candidates[entry['id']] = {**entry, 'definition': definition}
                        item = announcements.setdefault(entry['id'], {'id': entry['id'], 'first_seen_at': now})
                        item.update(published_at=entry['published_at'], kind=classify(entry['title']),
                                    last_seen_at=now, source_ids=sorted(set(item.get('source_ids', [])) | {identity}))
                        item.pop('missing_from_index', None)
                        for doc in _document_links(entry['body'], entry['url'], entry['title'], skipped=report['skipped_links']):
                            doc['published_at'] = entry['published_at']
                            record_document(doc, entry['id'], definition)
                    if reached_window:
                        break
                if not reached_window:
                    raise SourceError('Feed pagination limit reached before course boundary', 'traversal_limit')
                catalogue_members[identity] = members
                complete_catalogues.add(identity)
            elif kind == 'map':
                body = fetch(url, reserve_requests=reserve)
                current['attempted_at'] = now
                entries = _map(body, url)
                current.update(pages=1, entries=len(entries))
                catalogue_members[identity] = set(entries)
                complete_catalogues.add(identity)
                for entry in entries.values():
                    entry['definition'] = definition
                    catalogue[entry['id']] = entry
                    item = announcements.setdefault(entry['id'], {'id': entry['id'], 'first_seen_at': now,
                        'status': 'discovered', 'kind': classify(entry['title'])})
                    item.update(last_seen_at=now, source_ids=sorted(set(item.get('source_ids', [])) | {identity}))
                    item.pop('missing_from_index', None)
            elif kind in ('carm_index', 'rrhh_page'):
                pending = [(identity, url)]
                seen_pages = set()
                # Previously deferred observed pages are resumable and rotated
                # before re-reading the first historical page on every run.
                retained_pages = [(_opaque(u), u) for u in current.get('pending_page_urls', [])
                                  if canonical_url(u) != canonical_url(url)]
                if definition.get('queue') == 'historical':
                    pending = retained_pages + pending
                else:
                    # Refresh the live front page, then rotate previously
                    # observed continuations before newly repeated links.
                    pending += retained_pages
                page_limit = int(definition.get('max_pages', limits['max_index_pages']))
                if retained_pages and definition.get('queue') != 'historical':
                    page_limit = max(2, page_limit)
                while pending and current['pages'] < page_limit:
                    parent_id, page_url = pending[0]
                    if canonical_url(page_url) in seen_pages:
                        pending.pop(0)
                        continue
                    current['pending_page_urls'] = list(dict.fromkeys(u for _, u in pending))
                    current['pending_pages'] = len(current['pending_page_urls'])
                    body = fetch(page_url, reserve_requests=reserve)
                    current['attempted_at'] = now
                    _html(body)
                    page_definition = definition
                    continuation = canonical_url(page_url) != canonical_url(url)
                    if continuation and definition.get('queue') != 'historical':
                        # Undated continuation pages can contain older courses.
                        # Keep their evidence in bounded archive work; never
                        # infer a current-course date from the live root.
                        page_definition = {**definition, 'queue': 'historical', 'course': 'unknown',
                                           'priority': definition.get('priority', 50)+60}
                    docs, unsupported = links(body, page_url, parent_id, definition=page_definition)
                    next_pages, details = _page_links(body, page_url)
                    if not docs and not details and not next_pages and not _html(body).get_text(strip=True):
                        raise SourceError('Official index is empty', 'invalid_index')
                    if canonical_url(page_url) == canonical_url(url):
                        current['first_page_checked_at'] = now
                    # Publish disappearance evidence only after every check on
                    # this actual parent has succeeded.
                    parent_documents[parent_id] = {d['content_id'] for d in docs}
                    if unsupported:
                        current['unsupported_links'] = current.get('unsupported_links', 0) + 1
                        report['downloads_complete'] = False
                    seen_pages.add(canonical_url(page_url))
                    pending.pop(0)
                    current['pages'] += 1
                    pending.extend((key, value) for key, value in next_pages.items()
                                   if canonical_url(value) not in seen_pages)
                    for entry in details.values():
                        item = announcements.setdefault(entry['id'], {'id': entry['id'], 'first_seen_at': now,
                            'status': 'discovered', 'kind': classify(entry['title'])})
                        item.update(last_seen_at=now, source_ids=sorted(set(item.get('source_ids', [])) | {identity}))
                        candidates[entry['id']] = {**entry, 'definition': page_definition,
                            'queue': page_definition.get('queue', 'recent'), 'parent_source': identity}
                # CARM numeric query URLs contain no nominal post slugs.
                current['pending_page_urls'] = list(dict.fromkeys(u for _, u in pending if canonical_url(u) not in seen_pages))
                current['pending_pages'] = len(current['pending_page_urls'])
                if current['pending_pages']:
                    raise SourceError('Index pagination budget reached', 'traversal_limit')
            else:
                raise ValueError('Unsupported registry source kind')
            current.update(status='checked', work_status='checked', checked_at=now, scope_complete=True)
        except SourceError as error:
            failure(current, error)
            report['index_complete'] = False

    for entry in catalogue.values():
        published = announcements[entry['id']].get('published_at')
        if published and published >= since and entry['id'] not in candidates:
            candidates[entry['id']] = {**entry, 'published_at': published}
        elif published and published < since:
            candidates.setdefault(entry['id'], {**entry, 'published_at': published, 'queue': 'historical'})

    unknown = sorted((e for e in catalogue.values() if not announcements[e['id']].get('published_at')),
                     key=lambda e: (announcements[e['id']].get('attempted_at', ''), e['id']))
    # Undated and historical queues have independent caps; recent result leaves
    # are processed first, and archive work preserves download capacity.
    for entry in unknown[:int(limits['max_undated_details'])]:
        candidates.setdefault(entry['id'], {**entry, 'queue': 'undated'})
    ordered = sorted(candidates.values(), key=lambda e: (
        {'recent': 0, 'historical': 1, 'undated': 2}.get(e.get('queue', 'recent'), 0),
        e.get('definition', {}).get('priority', 50),
        announcements[e['id']].get('attempted_at', ''),
        -date.fromisoformat(e['published_at']).toordinal() if e.get('published_at') else 0, e['id']))
    detail_budget = min(int(limits['max_details']), max(0, (int(limits['max_requests'])-requests_used)//2))
    detail_count, history_count = 0, 0
    for offset, entry in enumerate(ordered):
        item = announcements[entry['id']]
        queue_kind = entry.get('queue', 'recent')
        if detail_count >= detail_budget or (queue_kind == 'historical' and history_count >= limits['max_historical_details']):
            _defer(item, 'detail_limit', now)
            report['downloads_complete'] = False
            continue
        try:
            body = fetch(entry['url'], reserve_requests=reserve if queue_kind != 'recent' else 0)
            item['attempted_at'] = now
            detail_count += 1
            history_count += queue_kind == 'historical'
            published = entry.get('published_at') or _published_date(body)
            if published:
                item['published_at'] = published
            docs, unsupported = links(body, entry['url'], entry['id'], entry['title'], entry.get('definition'), published)
            _, children = _page_links(body, entry['url'])
            if not docs and not children and not _html(body).get_text(strip=True):
                raise SourceError('Official detail is empty', 'invalid_announcement')
            parent_documents[entry['id']] = {d['content_id'] for d in docs}
            child_work = []
            for child in children.values():
                if child['id'] in candidates or child['id'] == entry['id']:
                    continue
                child_item = announcements.setdefault(child['id'], {'id': child['id'], 'first_seen_at': now,
                                                      'status': 'discovered', 'kind': classify(child['title'])})
                definition = entry.get('definition', {})
                child_item.update(last_seen_at=now, source_ids=sorted(set(child_item.get('source_ids', [])) |
                    ({definition['id']} if definition.get('id') else set())), parent_id=entry['id'])
                child.update(definition=definition, queue=queue_kind, depth=entry.get('depth', 0)+1)
                candidates[child['id']] = child
                if child['depth'] > limits['max_detail_depth']:
                    _defer(child_item, 'detail_depth_limit', now)
                    report['downloads_complete'] = False
                else:
                    child_work.append(child)
            # Result attachment leaves keep their parent's recent-work priority.
            ordered[offset+1:offset+1] = sorted(child_work, key=lambda e: e['id'])
            item.update(checked_at=now, status='discovered' if docs or children else 'pending_review', work_status='checked',
                        document_ids=sorted({d['content_id'] for d in docs}))
            if queue_kind == 'undated' and not published:
                item.update(status='pending_review', error_code='unknown_publication_date')
                report['downloads_complete'] = False
            elif queue_kind == 'undated' and published < since:
                item['status'] = 'not_applicable'
            else:
                item.pop('error_code', None)
            if unsupported:
                item['error_code'] = 'unsupported_document_origin'
                report['downloads_complete'] = False
        except SourceError as error:
            # A failed real request rotates the queue; a budget omission does not.
            if error.code != 'traversal_limit':
                detail_count += 1
            failure(item, error)
            report['downloads_complete'] = False

    for identity, item in announcements.items():
        parents = set(item.get('source_ids', []))
        if parents and parents <= complete_catalogues and all(identity not in catalogue_members[p] for p in parents):
            item['missing_from_index'] = True
            report['index_complete'] = False
    for identity, doc in documents.items():
        parents = set(doc.get('parent_ids', doc.get('source_ids', [])))
        missing = sorted(p for p in parents if p in parent_documents and identity not in parent_documents[p])
        if missing:
            doc['missing_parent_ids'] = missing
        if identity not in observed and parents and parents <= parent_documents.keys() and len(missing) == len(parents):
            doc['missing_from_index'] = True
            report['index_complete'] = False
    queue = sorted(documents.values(), key=lambda d: (d['content_id'] not in reviewed,
        d.get('priority', 50), d.get('attempted_at', ''), d['content_id']))
    for doc in queue:
        if doc['content_id'] in verified_this_run:
            # A conflicting label discovered after the active-byte check still
            # prevents that title from silently activating a provisional list.
            if doc.get('provisional_observed') and doc.get('reviewed'):
                doc.update(status='pending_review', error_code='classification_conflict', reviewed=False)
            continue
        verify(doc, {})

    unknown_dates = sum(not a.get('published_at') for a in announcements.values())
    pending_announcements = sum(bool((a.get('published_at', '') >= since or not a.get('published_at')) and (
        a.get('status') in ('pending_review', 'unavailable', 'skipped') or a.get('error_code')))
        for a in announcements.values())
    report['review_complete'] = bool(documents) and report['index_complete'] and report['downloads_complete'] and not pending_announcements and not unknown_dates and all(
        d['status'] in ('incorporated', 'not_applicable') and not d.get('missing_from_index') for d in documents.values())
    if report['review_complete']:
        report['checked_at'] = now
    scopes = []
    families = {}
    document_scopes = {}
    for doc in documents.values():
        origins = set(doc.get('registry_source_ids', [])) | (set(doc.get('source_ids', [])) & source_ids)
        for parent in doc.get('parent_ids', doc.get('source_ids', [])):
            origins.update(announcements.get(parent, {}).get('source_ids', []))
        document_scopes[doc['content_id']] = origins
    for definition in definitions:
        source = sources[definition['id']]
        pending_details = sum(
            a.get('status') in ('skipped', 'unavailable', 'pending_review') or not a.get('checked_at')
            for a in announcements.values() if definition['id'] in a.get('source_ids', []))
        source['pending_details'] = pending_details
        scoped_docs = [d for d in documents.values() if definition['id'] in document_scopes[d['content_id']]]
        failed_documents = sum(d.get('status') == 'unavailable' for d in scoped_docs)
        skipped_documents = sum(d.get('status') == 'skipped' for d in scoped_docs)
        pending_documents = sum(d.get('work_status') != 'checked' or d.get('downloaded_at') != now
                                for d in scoped_docs)
        unreviewed_documents = sum(d.get('reviewed') is not True for d in scoped_docs)
        source.update(document_count=len(scoped_docs), failed_documents=failed_documents,
                      skipped_documents=skipped_documents, pending_documents=pending_documents,
                      unreviewed_documents=unreviewed_documents,
                      traversal_complete=bool(source.get('scope_complete') and not pending_details),
                      downloads_complete=bool(not pending_documents and not source.get('unsupported_links')),
                      verification_complete=bool(not pending_documents and not unreviewed_documents and
                                                 not source.get('unsupported_links')))
        source['scope_complete'] = source['traversal_complete'] and source['verification_complete']
        scope = {key: source.get(key) for key in ('family', 'body', 'course', 'status', 'pages',
            'scope_complete', 'history_complete', 'pending_pages', 'pending_details', 'checked_at', 'attempted_at',
            'traversal_complete', 'downloads_complete', 'document_count', 'failed_documents',
            'skipped_documents', 'pending_documents', 'verification_complete', 'unreviewed_documents')}
        scope['source_id'] = definition['id']
        scopes.append(scope)
        key = (scope['family'], scope['body'], scope['course'])
        family = families.setdefault(key, {'family': key[0], 'body': key[1], 'course': key[2],
            'source_ids': [], 'scope_complete': True, 'history_complete': False,
            'traversal_complete': True, 'downloads_complete': True, 'document_count': 0,
            'pending_documents': 0, 'failed_documents': 0, 'skipped_documents': 0,
            'verification_complete': True, 'unreviewed_documents': 0})
        family['source_ids'].append(definition['id'])
        family['scope_complete'] &= scope['scope_complete']
        family['traversal_complete'] &= scope['traversal_complete']
        family['downloads_complete'] &= scope['downloads_complete']
        family['verification_complete'] &= scope['verification_complete']
        # De-duplicate publications appearing in overlapping family roots.
        family_docs = [d for d in documents.values() if document_scopes[d['content_id']] & set(family['source_ids'])]
        family['document_count'] = len(family_docs)
        family['failed_documents'] = sum(d.get('status') == 'unavailable' for d in family_docs)
        family['skipped_documents'] = sum(d.get('status') == 'skipped' for d in family_docs)
        family['pending_documents'] = sum(d.get('work_status') != 'checked' or d.get('downloaded_at') != now for d in family_docs)
        family['unreviewed_documents'] = sum(d.get('reviewed') is not True for d in family_docs)
    work_queues = {name: [] for name in ('recent', 'historical', 'undated')}
    for entry in {**catalogue, **candidates}.values():
        item = announcements[entry['id']]
        name = entry.get('queue', 'undated' if not item.get('published_at') else
                         'historical' if item['published_at'] < since else 'recent')
        if item.get('status') in ('skipped', 'unavailable', 'pending_review') or not item.get('published_at'):
            work_queues[name].append({'id': entry['id'], 'source_ids': item.get('source_ids', []),
                                     'status': item.get('status'), 'attempted_at': item.get('attempted_at')})
    report.update(sources=list(sources.values()), announcements=sorted(announcements.values(), key=lambda a: a['id']),
                  documents=sorted(documents.values(), key=lambda d: d['content_id']), requests_used=requests_used,
                  unresolved_catalogue_dates=unknown_dates, pending_announcements=pending_announcements,
                  status_counts=dict(Counter(d['status'] for d in documents.values())),
                  coverage={'sources': scopes, 'families': list(families.values())}, work_queues=work_queues)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', default='data/source-registry.json')
    parser.add_argument('--source', default='data/position-source.json')
    parser.add_argument('--documents', default='.runtime/source-documents.json',
                        help='Previously activated document metadata; optional before first activation')
    parser.add_argument('--reviewed-documents', default='data/position-documents.json',
                        help='Repository-reviewed documents and separate observation metadata')
    parser.add_argument('--maestros', default='data/position-maestros.json',
                        help='Repository-reviewed Maestros roster and amendments')
    parser.add_argument('--state', default='.runtime/source-inventory.json')
    parser.add_argument('--private-dir', default='.runtime/source-inventory-private')
    parser.add_argument('--max-seconds', type=int)
    parser.add_argument('--max-requests', type=int)
    args = parser.parse_args()
    registry = json.loads(Path(args.registry).read_text(encoding='utf8'))
    for name in ('max_seconds', 'max_requests'):
        if getattr(args, name) is not None:
            registry.setdefault('limits', {})[name] = getattr(args, name)
    source = json.loads(Path(args.source).read_text(encoding='utf8'))
    if source.get('scope') == 'published_list' and not source.get('kind'):
        source['kind'] = 'baseline'
    def optional_metadata(filename):
        path = Path(filename)
        return json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    manifest = _merge_reviewed_metadata(source, optional_metadata(args.reviewed_documents),
                                       optional_metadata(args.maestros), optional_metadata(args.documents))
    path = Path(args.state)
    previous = json.loads(path.read_text(encoding='utf8')) if path.exists() else None
    report = collect_inventory(registry, manifest, previous=previous, private_dir=args.private_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    temporary.replace(path)
    # Never log announcement URLs, titles, names, or the response body.
    print(json.dumps({key: report[key] for key in ('index_complete', 'downloads_complete', 'review_complete',
           'requests_used', 'unresolved_catalogue_dates', 'pending_announcements', 'status_counts')}))
    if not report['review_complete']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
