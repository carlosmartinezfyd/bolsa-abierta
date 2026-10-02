"""Discover and privately archive roster updates. Discovery never applies a change."""

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from .sources import OfficialClient, SourceError, _allowed_url, _challenge, _fold, _pdf_link

INDEX_URL = 'https://www.carm.es/web/pagina?IDCONTENIDO=75599&IDTIPO=100'
BASELINE_ID = '208095'
MAX_DOCUMENTS = 30
COLLECTION_SECONDS = 240


def discover_documents(body):
    """Use the specific course section, never a generic site-wide PDF scrape."""
    if _challenge(body):
        raise SourceError('Roster index requires browser verification', 'access_challenge')
    soup = BeautifulSoup(body, 'html.parser')
    heading = next((h for h in soup.select('h2') if
                    re.search(r'cuerpo.*secundaria.*otros.*curso 2026[-/]2027', _fold(h.get_text(' ', strip=True)))), None)
    if heading is None:
        raise SourceError('Unrecognized roster course index', 'invalid_index')
    section = heading.parent
    inventory = {}
    for anchor in section.select('a[href]'):
        url = urljoin(INDEX_URL, anchor['href'])
        if not _pdf_link(url):
            continue
        value = _allowed_url(url)
        query = parse_qs(value.query)
        ids = query.get('IDCONTENIDO', [])
        if value.hostname != 'www.carm.es' or value.path != '/web/descarga' or len(ids) != 1 or not ids[0].isdigit():
            raise SourceError('Unrecognized roster document origin or identity', 'invalid_document_link')
        title = anchor.get_text(' ', strip=True)
        if not title:
            raise SourceError('Roster document has no title', 'invalid_document_link')
        folded = _fold(title)
        if 'provisional' in folded and 'definitiva' in folded:
            kind = 'unclassified'
        elif 'provisional' in folded:
            kind = 'provisional'
        elif ids[0] == BASELINE_ID and 'definitiva' in folded:
            kind = 'baseline'
        elif 'complementaria' in folded and 'definitiva' in folded:
            kind = 'supplement'
        elif 'correccion' in folded and 'definitiva' in folded:
            kind = 'correction'
        else:
            kind = 'unclassified'
        existing = inventory.get(ids[0])
        if existing:
            prior_query = parse_qs(urlsplit(existing['url']).query, keep_blank_values=True)
            current_query = parse_qs(value.query, keep_blank_values=True)
            # Only the official breadcrumb is irrelevant to the downloaded bytes.
            prior_query.pop('RASTRO', None)
            current_query.pop('RASTRO', None)
            if existing['kind'] != kind or prior_query != current_query:
                raise SourceError('Conflicting roster document identities', 'invalid_document_link')
        inventory.setdefault(ids[0], dict(content_id=ids[0], url=url, title=title, kind=kind))
    if inventory.get(BASELINE_ID, {}).get('kind') != 'baseline' or len(inventory) > MAX_DOCUMENTS:
        raise SourceError('Incomplete or unexpectedly large roster index', 'invalid_index')
    return list(inventory.values())


def collect_documents(client, reviewed, private_dir):
    """Map required official IDs to inspected hashes (None means pending review).

    No roster rows are parsed. Treat the full report as private too: document titles
    can contain names. A failed index/download is explicit; active data is retained.
    """
    private_dir = Path(private_dir)
    private_dir.mkdir(parents=True, exist_ok=True)
    report = dict(attempted_at=datetime.now(timezone.utc).isoformat(), index_url=INDEX_URL,
                  index_complete=False, downloads_complete=False, review_complete=False,
                  documents=[], missing_content_ids=[])
    deadline = time.monotonic() + COLLECTION_SECONDS
    try:
        fetched = client.fetch(INDEX_URL)
        documents = discover_documents(fetched.body)
        digest = hashlib.sha256(fetched.body).hexdigest()
        (private_dir / (digest + '.html')).write_bytes(fetched.body)
        report.update(index_complete=True, index_sha256=digest, downloads_complete=True)
    except SourceError as error:
        report['error_code'] = error.code
        return report
    report['missing_content_ids'] = sorted(set(reviewed) - {d['content_id'] for d in documents})
    for doc in documents:
        item = dict(doc)
        if doc['kind'] == 'provisional':
            if doc['content_id'] in reviewed:
                item['status'] = 'classification_conflict'
                report['downloads_complete'] = False
            else:
                item['status'] = 'not_applicable'
        else:
            try:
                if time.monotonic() >= deadline:
                    raise SourceError('Roster collection exceeded time budget', 'time_limit')
                fetched = client.fetch(doc['url'], kind='pdf')
                digest = hashlib.sha256(fetched.body).hexdigest()
                (private_dir / (digest + '.pdf')).write_bytes(fetched.body)
                expected = reviewed.get(doc['content_id'])
                status = 'pending_review' if not expected else ('reviewed' if expected == digest else 'changed')
                item.update(sha256=digest, bytes=len(fetched.body), status=status)
            except SourceError as error:
                item.update(status='unavailable', error_code=error.code)
                report['downloads_complete'] = False
        report['documents'].append(item)
    report['review_complete'] = not report['missing_content_ids'] and all(
        d['status'] in ('reviewed', 'not_applicable') for d in report['documents'])
    if report['review_complete']:
        report['checked_at'] = datetime.now(timezone.utc).isoformat()
    return report


def required_documents(source, inventory):
    required = {str(key): None for key in inventory['required_content_ids']}
    if BASELINE_ID not in required or any(not re.fullmatch(r'\d+', key) for key in required):
        raise ValueError('Invalid required roster inventory')
    required[BASELINE_ID] = source['sha256']
    for amendment in source.get('amendments', []):
        required[amendment['content_id']] = amendment['sha256']
    return required


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='data/position-source.json')
    parser.add_argument('--inventory', default='data/position-updates.json')
    parser.add_argument('--private-dir', default='.runtime/position-updates')
    args = parser.parse_args()
    source = json.loads(Path(args.source).read_text(encoding='utf8'))
    inventory = json.loads(Path(args.inventory).read_text(encoding='utf8'))
    reviewed = required_documents(source, inventory)
    report = collect_documents(OfficialClient(), reviewed, Path(args.private_dir))
    (Path(args.private_dir) / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    counts = {}
    for doc in report['documents']:
        counts[doc['status']] = counts.get(doc['status'], 0) + 1
    print(json.dumps(dict(index_complete=report['index_complete'], downloads_complete=report['downloads_complete'],
                          review_complete=report['review_complete'], statuses=counts,
                          error_code=report.get('error_code')), ensure_ascii=False))
    if not report['review_complete']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
