"""Private position collection and authenticated publication."""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .positions import parse_pdf
from .position_amendments import read_amendment, apply_insertions
from .sources import OfficialClient


def merge_documents(*collections):
    documents = {}
    for collection in collections:
        for item in collection:
            document = {k: v for k, v in item.items() if k not in ('incorporated', 'checked_at')}
            prior = documents.get(document['content_id'])
            if prior and prior != document:
                raise ValueError('Conflicting document revisions require review')
            documents[document['content_id']] = document
    return sorted(documents.values(), key=lambda d: d['content_id'])


def fetch_documents(documents, client, private):
    artifacts = []
    for document in documents:
        downloaded = client.fetch(document['source_url'], kind='pdf')
        digest = verify_source(downloaded.body, document)
        path = private / f'{digest}.pdf'
        path.write_bytes(downloaded.body)
        artifacts.append((path, document))
    return artifacts


def verify_source(body, source):
    digest = hashlib.sha256(body).hexdigest()
    if digest != source['sha256']:
        raise ValueError('The official PDF changed; its date and extraction require review before publication')
    return digest


def publish(version, read_rows, send):
    existing = send({'action': 'begin', 'version': version})
    if existing.get('ready'):
        send({'action': 'checked', 'id': version['id'], 'checked_at': version['checked_at']})
        return 'unchanged'
    rows = read_rows()
    for start in range(0, len(rows), 40):
        send({'action': 'rows', 'id': version['id'], 'rows': rows[start:start + 40]})
    send({'action': 'activate', 'id': version['id']})
    return 'published'


def build_version(source, checked_at):
    identity = source['sha256']
    if source.get('amendments'):
        evidence = {'baseline': source['sha256'], 'amendments': source['amendments'],
                    'parser': 'reviewed-insertions-v1'}
        identity = hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    version = {**source, 'id': identity, 'checked_at': checked_at}
    if source.get('documents'):
        evidence = {'reference': identity, 'documents': source['documents'], 'parser': 'document-evidence-v1'}
        version['id'] = hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        version['coverage'] = 'multi_source'
        version['ranked_specialties'] = source['specialties']
        counts = {s['code']: dict(s) for s in source['specialties']}
        for document in source['documents']:
            for specialty in document['specialties']:
                if specialty['code'] not in counts:
                    counts[specialty['code']] = {**specialty, 'count': 0}
                counts[specialty['code']]['count'] += specialty['count']
        version['specialties'] = sorted(counts.values(), key=lambda s: s['code'])
        version['row_count'] += sum(d['row_count'] for d in source['documents'])
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='data/position-source.json')
    parser.add_argument('--documents', default='data/position-documents.json')
    parser.add_argument('--state', default='.runtime/source-documents.json')
    parser.add_argument('--inventory-state')
    parser.add_argument('--inventory-dir', default='.runtime/source-inventory')
    parser.add_argument('--private-dir', default='.runtime/positions')
    args = parser.parse_args()
    base = os.environ.get('PUBLIC_API_BASE', '').rstrip('/')
    token = os.environ.get('POSITION_INGEST_TOKEN', '')
    target = urlsplit(base)
    if target.scheme != 'https' or target.hostname != 'bolsa-abierta-gateway.cmartinezmtez.workers.dev' or target.port or target.username or target.password or target.path or target.query or len(token) < 40:
        raise ValueError('Position publication service is not configured')
    source = json.loads(Path(args.source).read_text(encoding='utf8'))
    state_path = Path(args.state)
    prior = json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else {}
    source['documents'] = merge_documents(json.loads(Path(args.documents).read_text(encoding='utf8'))['documents'], prior.get('documents', []))
    if args.inventory_state and Path(args.inventory_state).exists():
        from .position_documents import scan_document
        inventory = json.loads(Path(args.inventory_state).read_text(encoding='utf8'))
        known = {d['content_id'] for d in source['documents']}
        aliases = {}
        for d in source['documents']:
            for code, group in d.get('assigned_function_groups', {}).items():
                if code in aliases and aliases[code] != group:
                    raise ValueError('Conflicting reviewed function groups')
                aliases[code] = group
        pending = 0
        for item in inventory.get('documents', []):
            if item['content_id'] in known or item.get('kind') != 'award' or not item.get('sha256'):
                continue
            path = Path(args.inventory_dir) / (item['sha256'] + '.pdf')
            if not path.exists():
                continue
            try:
                scanned = scan_document(path, item['source_url'], checked_at=item['downloaded_at'], assigned_function_groups=aliases)
                if scanned['metadata']['sha256'] != item['sha256']:
                    raise ValueError('Inventoried document bytes changed')
                source['documents'] = merge_documents(source['documents'], [scanned['metadata']])
                known.add(item['content_id'])
            except Exception:
                pending += 1  # A different layout/revision stays pending, never silently accepted.
        print(f'Additional award formats pending review: {pending}.')
    downloaded = OfficialClient().fetch(source['source_url'], kind='pdf')
    digest = verify_source(downloaded.body, source)
    private = Path(args.private_dir)
    private.mkdir(parents=True, exist_ok=True)
    artifact = private / f'{digest}.pdf'
    artifact.write_bytes(downloaded.body)
    amendments = fetch_documents(source.get('amendments', []), OfficialClient(), private)
    documents = fetch_documents(source.get('documents', []), OfficialClient(), private)
    version = build_version(source, datetime.now(timezone.utc).isoformat())
    session = requests.Session()
    session.trust_env = False

    def send(body):
        response = session.post(base + '/internal/positions', json=body,
                                headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'BolsaAbierta-PositionCollector/1.0'},
                                timeout=(5, 30), allow_redirects=False)
        if response.status_code != 200:
            # Never print request bodies, candidate names, tokens or remote exceptions.
            raise RuntimeError(f'Position publication returned HTTP {response.status_code}')
        return response.json()

    def read_rows():
        rows = parse_pdf(artifact)
        if amendments:
            if len(rows) != source['baseline_row_count']:
                raise ValueError('Baseline count changed before amendment consolidation')
            changes = [row for path, amendment in amendments for row in read_amendment(path, amendment)]
            rows = apply_insertions(rows, changes)
        counts = {s['code']: s['count'] for s in source['specialties']}
        actual = {}
        for row in rows:
            actual[row['specialty']] = actual.get(row['specialty'], 0) + 1
        if len(rows) != source['row_count'] or actual != counts:
            raise ValueError('Extraction differs from the independently reviewed source manifest')
        from .position_documents import read_document
        for path, document in documents:
            rows.extend(read_document(path, document))
        return rows

    result = publish(version, read_rows, send)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({'active_version': version['id'], 'checked_at': version['checked_at'],
        'references': [{**d, 'incorporated': True} for d in [
            {'content_id': '208095', 'source_url': source['source_url'], 'sha256': source['sha256'], 'kind': 'baseline'},
            *[{**a, 'kind': 'correction'} for a in source.get('amendments', [])]]],
        'documents': [{**d, 'incorporated': True} for d in source['documents']]}, ensure_ascii=False, indent=2), encoding='utf8')
    print(f'Position reference {result}: {version["row_count"]} rows, {len(version["specialties"])} specialties.')


if __name__ == '__main__':
    main()
