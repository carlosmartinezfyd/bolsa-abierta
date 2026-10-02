"""Durable, metadata-only inventory of official teaching-list publications.

Discovery is not incorporation. Only bytes matching the reviewed ingestion
manifest can be marked incorporated; this module never changes a person's rank.
"""
import argparse
from collections import Counter
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
                    'incorporated', 'not_applicable'})


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
    if 'vacantes' in value:
        return 'vacancies'
    if 'complementaria' in value:
        return 'supplement'
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


def _document_links(body, base_url, title=''):
    result = []
    for anchor in _html(body).select('a[href]'):
        url = urljoin(base_url, anchor['href'])
        path = urlsplit(url).path.lower()
        if path != '/web/descarga' and not path.endswith('.pdf'):
            continue
        try:
            identity = _document_url(url)
        except SourceError as error:
            raise SourceError('Unsupported document origin', 'unsupported_document_origin') from error
        label = anchor.get_text(' ', strip=True)
        kind = classify(label)
        if kind == 'unclassified':
            kind = classify(title)
        result.append({'content_id': identity, 'source_url': url, 'kind': kind})
    return result


def _feed(body):
    if _challenge(body):
        raise SourceError('Official feed requires verification', 'access_challenge')
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


def _reviewed(source):
    result = {}
    for item in ([source] if source.get('source_url') else []) + source.get('amendments', []) + source.get('documents', []):
        identity = _document_url(item['source_url'])
        if item.get('content_id', identity) != identity or not re.fullmatch('[a-f0-9]{64}', item.get('sha256', '')):
            raise ValueError('Invalid reviewed document manifest')
        if identity in result and result[identity]['sha256'] != item['sha256']:
            raise ValueError('Conflicting reviewed document hashes')
        result[identity] = item
    return result


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


def _verify_document(doc, known, fetch, now):
    expected = known.get('sha256')
    doc.pop('error_code', None)
    if doc['kind'] == 'provisional' and not expected:
        doc['status'] = 'not_applicable'
        return True
    try:
        body = fetch(doc['source_url'], 'pdf')
        doc['attempted_at'] = now
        if not body.startswith(b'%PDF-'):
            raise SourceError('Not a PDF document', 'invalid_pdf')
        digest, prior = hashlib.sha256(body).hexdigest(), doc.get('sha256')
        doc.update(sha256=digest, bytes=len(body), downloaded_at=now)
        if expected and digest == expected and doc['kind'] == 'provisional':
            doc.update(status='pending_review', error_code='classification_conflict', reviewed=False)
        elif expected and digest == expected:
            doc.update(status='incorporated' if known.get('incorporated') is True else 'pending_review',
                       verified_at=now, reviewed=True)
        elif (expected and digest != expected) or (prior and digest != prior) or doc['status'] == 'changed':
            doc.update(status='changed', reviewed=False)
        else:
            doc['status'] = 'pending_review'
        return True
    except SourceError as error:
        doc.update(status='unavailable', error_code=error.code)
        if error.code != 'traversal_limit':
            doc['attempted_at'] = now
        return False


def collect_inventory(registry, manifest, *, previous=None, client=None, now=None, private_dir=None):
    """Reconcile complete catalogues, bounded checks and retained prior evidence.

    RSS publication dates define the course window. Map-only dates remain unknown;
    they never imply a current-course omission or a verified complete coverage.
    Public state contains opaque announcement identities, not titles or slugs.
    """
    previous = previous or {}
    since = date.fromisoformat(registry['since']).isoformat()
    now = now or datetime.now(timezone.utc).isoformat()
    limits = {'max_feed_pages': 80, 'max_requests': 160, 'max_seconds': 240, 'max_details': 50,
              'max_undated_details': 5}
    limits.update(registry.get('limits', {}))
    if any(not isinstance(v, (int, float)) or v < 0 or (v == 0 and k != 'max_undated_details')
           for k, v in limits.items()):
        raise ValueError('Inventory budgets must be positive')
    reviewed = _reviewed(manifest)
    client = client or OfficialClient(max_pdf_bytes=60_000_000, retries=0, max_seconds=20)
    private_dir = Path(private_dir) if private_dir is not None else None
    if private_dir:
        private_dir.mkdir(parents=True, exist_ok=True)
    deadline, requests_used = time.monotonic()+limits['max_seconds'], 0
    sources = {s['id']: dict(s) for s in previous.get('sources', [])}
    announcements = {a['id']: dict(a) for a in previous.get('announcements', [])}
    documents = {d['content_id']: dict(d) for d in previous.get('documents', [])}
    report = {'schema_version': 1, 'course': registry['course'], 'since': since, 'attempted_at': now,
              'index_complete': True, 'downloads_complete': True, 'review_complete': False}
    if previous.get('checked_at'):
        report['checked_at'] = previous['checked_at']
    candidates, catalogue, observed_documents, map_ids, feed_ids = {}, {}, set(), set(), set()
    source_ids = {s['id'] for s in registry['sources']}
    for identity, source in sources.items():
        if identity not in source_ids:
            source.update(status='unavailable', error_code='source_removed', attempted_at=now)
            report['index_complete'] = False

    def fetch(url, kind='html'):
        nonlocal requests_used
        if requests_used >= limits['max_requests'] or time.monotonic() >= deadline:
            raise SourceError('Inventory traversal budget exhausted', 'traversal_limit')
        requests_used += 1
        fetched = client.fetch(url, kind=kind)
        if fetched.status != 200 or _challenge(fetched.body):
            raise SourceError('Unverified official response', 'invalid_response')
        if private_dir:
            digest = hashlib.sha256(fetched.body).hexdigest()
            (private_dir / (digest + ('.pdf' if kind == 'pdf' else '.html'))).write_bytes(fetched.body)
        return fetched.body

    def record_document(item, source_id):
        identity = item['content_id']
        observed_documents.add(identity)
        doc = documents.setdefault(identity, {'content_id': identity, 'status': 'discovered', 'first_seen_at': now})
        # A classifier disagreement cannot silently downgrade an incorporated final.
        if doc.get('kind') and doc['kind'] != item['kind']:
            doc['kind'] = 'unclassified'
        else:
            doc['kind'] = item['kind']
        doc.update(source_url=item['source_url'], last_seen_at=now)
        doc['source_ids'] = sorted(set(doc.get('source_ids', [])) | {source_id})
        doc.pop('missing_from_index', None)
        if item['kind'] == 'provisional' and identity in reviewed:
            doc.update(status='pending_review', error_code='classification_conflict', reviewed=False)

    for definition in registry['sources']:
        identity, kind, url = definition['id'], definition['kind'], definition['url']
        if not re.fullmatch('[a-z0-9_-]+', identity):
            raise ValueError('Source IDs must be non-personal identifiers')
        _allowed_url(url)
        current = sources.setdefault(identity, {'id': identity, 'kind': kind})
        current.update(attempted_at=now, pages=0)
        current.pop('error_code', None)
        try:
            if kind == 'rss':
                reached_window, page_digests, last_date = False, set(), None
                for page in range(1, int(limits['max_feed_pages'])+1):
                    page_url = url if page == 1 else url+('&' if '?' in url else '?')+urlencode({'paged': page})
                    body = fetch(page_url, 'rss')
                    digest = hashlib.sha256(body).hexdigest()
                    if digest in page_digests:
                        raise SourceError('Official feed repeated a page', 'repeated_page')
                    page_digests.add(digest)
                    entries = _feed(body)
                    current['pages'] += 1
                    if not entries:
                        # Empty feed is only a terminus after at least one populated page.
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
                        candidates[entry['id']] = entry
                        feed_ids.add(entry['id'])
                        item = announcements.setdefault(entry['id'], {'id': entry['id'], 'first_seen_at': now})
                        item.update(published_at=entry['published_at'], kind=classify(entry['title']),
                                    status='discovered', last_seen_at=now)
                        item.pop('missing_from_index', None)
                        for doc in _document_links(entry['body'], entry['url'], entry['title']):
                            record_document(doc, entry['id'])
                    if reached_window:
                        break
                if not reached_window:
                    raise SourceError('Feed pagination limit reached before course boundary', 'traversal_limit')
            elif kind == 'map':
                entries = _map(fetch(url), url)
                current['pages'] = 1
                current['entries'] = len(entries)
                catalogue.update(entries)
                map_ids.update(entries)
                for entry in entries.values():
                    item = announcements.setdefault(entry['id'], {'id': entry['id'], 'first_seen_at': now,
                        'status': 'discovered', 'kind': classify(entry['title'])})
                    item['last_seen_at'] = now
                    item.pop('missing_from_index', None)
            elif kind == 'carm_index':
                body = fetch(url)
                current['pages'] = 1
                docs = _document_links(body, url)
                if not docs:
                    raise SourceError('Official index has no documents', 'invalid_index')
                for doc in docs:
                    record_document(doc, identity)
            else:
                raise ValueError('Unsupported registry source kind')
            current.update(status='checked', checked_at=now)
        except SourceError as error:
            current.update(status='unavailable', error_code=error.code)
            report['index_complete'] = False

    # Active/reviewed bytes get budget before the large article backlog.
    for identity, item in reviewed.items():
        doc = documents.setdefault(identity, {'content_id': identity, 'source_url': item['source_url'],
            'kind': item.get('kind', 'unclassified'), 'status': 'discovered', 'first_seen_at': now, 'source_ids': []})
        if not _verify_document(doc, item, fetch, now):
            report['downloads_complete'] = False

    # Previously dated map-only entries remain part of the refresh queue, even
    # when the article is absent from the current feed window or archive.
    for entry in catalogue.values():
        published = announcements[entry['id']].get('published_at')
        if published and published >= since and entry['id'] not in candidates:
            candidates[entry['id']] = {**entry, 'published_at': published}

    # A small rotating backfill resolves map-only dates without downloading the
    # entire historical archive every half hour. Confirmed older posts stay out
    # of the course, but an undated entry is never silently discarded.
    unknown = sorted((e for e in catalogue.values() if not announcements[e['id']].get('published_at')),
                     key=lambda e: (announcements[e['id']].get('attempted_at', ''), e['id']))
    for entry in unknown[:int(limits['max_undated_details'])]:
        item = announcements[entry['id']]
        try:
            body = fetch(entry['url'])
            item['attempted_at'] = now
            published = _published_date(body)
            if not published:
                raise SourceError('Publication date not established', 'unknown_publication_date')
            item.update(published_at=published, checked_at=now)
            item.pop('error_code', None)
            if published < since:
                item['status'] = 'not_applicable'
            else:
                entry.update(published_at=published, body=body, prefetched=True)
                candidates[entry['id']] = entry
        except SourceError as error:
            item.update(status='unavailable', error_code=error.code)
            if error.code != 'traversal_limit':
                item['attempted_at'] = now
            report['downloads_complete'] = False

    # Revisit article pages: URLs or attachments may change without a new pubDate.
    # Rotate on actual attempts, including failures. A permanently inaccessible
    # article must not monopolize the queue merely because it has no checked_at.
    ordered = sorted(candidates.values(), key=lambda e: (announcements[e['id']].get('attempted_at', ''), e['id']))
    # Preserve request capacity for newly discovered PDFs. Failed requests retain
    # their true attempted_at; skipped work does not jump to the back of the queue.
    detail_budget = min(int(limits['max_details']), max(1, (int(limits['max_requests'])-requests_used)//2))
    for offset, entry in enumerate(ordered):
        item = announcements[entry['id']]
        if offset >= detail_budget:
            item.update(status='discovered', error_code='detail_limit')
            report['downloads_complete'] = False
            continue
        try:
            body = entry['body'] if entry.get('prefetched') else fetch(entry['url'])
            item['attempted_at'] = now
            links = _document_links(body, entry['url'], entry['title'])
            for doc in links:
                record_document(doc, entry['id'])
            item.update(checked_at=now, status='pending_review' if not links else 'discovered',
                        document_ids=sorted({d['content_id'] for d in links}))
            item.pop('error_code', None)
        except SourceError as error:
            item.update(status='unavailable', error_code=error.code)
            if error.code != 'traversal_limit':
                item['attempted_at'] = now
            report['downloads_complete'] = False

    for identity, item in announcements.items():
        if identity not in map_ids | feed_ids:
            item['missing_from_index'] = True
            report['index_complete'] = False
    for identity, item in documents.items():
        if identity not in observed_documents:
            item['missing_from_index'] = True
            report['index_complete'] = False
    # Verify reviewed and least recently attempted documents first, retain every
    # omitted/failing item, and never let a failed attempt refresh verified_at.
    queue = sorted(documents.values(), key=lambda d: (d['content_id'] not in reviewed,
                                                     d.get('attempted_at', ''), d['content_id']))
    for doc in queue:
        if doc['content_id'] in reviewed:
            continue
        if not _verify_document(doc, {}, fetch, now):
            report['downloads_complete'] = False

    unknown_dates = sum(not a.get('published_at') for a in announcements.values())
    pending_announcements = sum(bool(a.get('published_at', '') >= since and (
        a.get('status') in ('pending_review', 'unavailable') or a.get('error_code')))
        for a in announcements.values())
    report['review_complete'] = bool(documents) and report['index_complete'] and report['downloads_complete'] and not pending_announcements and not unknown_dates and all(
        d['status'] in ('incorporated', 'not_applicable') and not d.get('missing_from_index') for d in documents.values())
    if report['review_complete']:
        report['checked_at'] = now
    report.update(sources=list(sources.values()), announcements=sorted(announcements.values(), key=lambda a: a['id']),
                  documents=sorted(documents.values(), key=lambda d: d['content_id']), requests_used=requests_used,
                  unresolved_catalogue_dates=unknown_dates, pending_announcements=pending_announcements,
                  status_counts=dict(Counter(d['status'] for d in documents.values())))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', default='data/source-registry.json')
    parser.add_argument('--source', default='data/position-source.json')
    parser.add_argument('--documents', help='Additional reviewed/activated document metadata; optional before first activation')
    parser.add_argument('--state', default='.runtime/source-inventory.json')
    parser.add_argument('--private-dir', default='.runtime/source-inventory-private')
    parser.add_argument('--max-seconds', type=int)
    parser.add_argument('--max-requests', type=int)
    args = parser.parse_args()
    registry = json.loads(Path(args.registry).read_text(encoding='utf8'))
    for name in ('max_seconds', 'max_requests'):
        if getattr(args, name) is not None:
            registry.setdefault('limits', {})[name] = getattr(args, name)
    manifest = json.loads(Path(args.source).read_text(encoding='utf8'))
    if args.documents and Path(args.documents).exists():
        additional = json.loads(Path(args.documents).read_text(encoding='utf8'))
        manifest['documents'] = (manifest.get('documents', []) + additional.get('documents', [])
                                 + additional.get('references', []))
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
