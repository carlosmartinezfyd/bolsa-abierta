"""Stage fresh official evidence against the fixed preview; never activate it."""
import json
import os
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
import requests
from bolsa_abierta.position_sync import (source_collection, required_documents,
    collect_evidence, OfficialClient, build_version, read_collection, publish)


def main():
    prior = json.loads(Path('saved-state/source-documents.json').read_text())
    args = SimpleNamespace(source='data/position-source.json', documents='data/position-documents.json',
        maestros='data/position-maestros.json', inventory_state='saved-state/source-inventory.json',
        inventory_dir='.runtime/source-inventory', fetch_missing_inventory=True)
    source, _, pending = source_collection(args, prior)
    diagnostics = {}
    collection = collect_evidence(required_documents(source), OfficialClient(), Path('.runtime/positions'),
        prior=prior, diagnostics=diagnostics)
    assert diagnostics['origin_check_complete'] and not diagnostics['cached_documents']
    version = build_version(source, collection['checked_at'])
    rows = read_collection(source, collection['artifacts'])
    session = requests.Session()
    session.trust_env = False
    counts = Counter()
    def send(body):
        action = body['action']
        if action == 'activate':
            body = {**body, 'action': 'validate'}
        if action not in ('begin', 'block', 'activate'):
            raise ValueError('Only staging and validation are allowed')
        response = session.post('https://reliability-bolsa-abierta-gateway.cmartinezmtez.workers.dev/internal/positions',
            json=body, headers={'Authorization': 'Bearer '+os.environ['POSITION_INGEST_TOKEN'],
                'User-Agent': 'BolsaAbierta-PositionCollector/2.0'}, timeout=(5, 30), allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError('Candidate '+action+' failed: HTTP '+str(response.status_code))
        result = response.json()
        if action == 'begin' and (result.get('ready') or result.get('storage') != 'blocks-v1'):
            raise ValueError('Candidate must negotiate a new compact generation')
        counts[action] += 1
        counts['write_units'] += result.get('write_budget', {}).get('batch_writes', 0)
        if action == 'activate':
            assert result.get('validated') is True and result.get('ready') is False
        return result
    publish(version, lambda: rows, send, resume=True)
    print(json.dumps({'version':version['id'], 'records':len(rows), 'documents':len(collection['evidence']),
        'origin_check_complete':True, 'cached_documents':0, 'pending_documents':pending,
        'largest_bucket':max(Counter(r['id'][:2] for r in rows).values()), **counts}))


if __name__ == '__main__':
    main()
