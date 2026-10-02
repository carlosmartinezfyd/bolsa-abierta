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
from .sources import OfficialClient


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='data/position-source.json')
    parser.add_argument('--private-dir', default='.runtime/positions')
    args = parser.parse_args()
    base = os.environ.get('PUBLIC_API_BASE', '').rstrip('/')
    token = os.environ.get('POSITION_INGEST_TOKEN', '')
    target = urlsplit(base)
    if target.scheme != 'https' or target.hostname != 'bolsa-abierta-gateway.cmartinezmtez.workers.dev' or target.port or target.username or target.password or target.path or target.query or len(token) < 40:
        raise ValueError('Position publication service is not configured')
    source = json.loads(Path(args.source).read_text(encoding='utf8'))
    downloaded = OfficialClient().fetch(source['source_url'], kind='pdf')
    digest = verify_source(downloaded.body, source)
    private = Path(args.private_dir)
    private.mkdir(parents=True, exist_ok=True)
    artifact = private / f'{digest}.pdf'
    artifact.write_bytes(downloaded.body)
    version = {**source, 'id': digest, 'checked_at': datetime.now(timezone.utc).isoformat()}
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
        counts = {s['code']: s['count'] for s in source['specialties']}
        actual = {}
        for row in rows:
            actual[row['specialty']] = actual.get(row['specialty'], 0) + 1
        if len(rows) != source['row_count'] or actual != counts:
            raise ValueError('Extraction differs from the independently reviewed source manifest')
        return rows

    result = publish(version, read_rows, send)
    print(f'Position reference {result}: {source["row_count"]} rows, {len(source["specialties"])} specialties.')


if __name__ == '__main__':
    main()
