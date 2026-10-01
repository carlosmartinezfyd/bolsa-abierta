import argparse
import json
from pathlib import Path
import re

from .store import Store, build_site, now


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description='Captador de fuentes oficiales de Bolsa Abierta')
    parser.add_argument('--data-dir', type=Path, default=root / '.runtime')
    parser.add_argument('--seed', type=Path, default=root / 'data/state.json')
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('init')
    refresh = subs.add_parser('refresh')
    refresh.add_argument('--request-id', default='')
    export = subs.add_parser('export')
    export.add_argument('--output', type=Path, required=True)
    server = subs.add_parser('serve')
    server.add_argument('--host', default='127.0.0.1')
    server.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if args.command == 'refresh' and args.request_id and not re.fullmatch('[0-9a-f]{32}', args.request_id):
        parser.error('request-id must be a 32-character lowercase hex string')
    store = Store(args.data_dir, args.seed)
    if args.command == 'refresh':
        from .pipeline import run_refresh
        job, claimed = store.claim_job(cooldown=0 if args.request_id else 60)
        if claimed:
            store.finish_job(job['id'], {'status': 'running'})
            try:
                result = run_refresh(store)
            except Exception:
                store.finish_job(job['id'], {'status': 'failed', 'message': 'Unexpected collector failure'})
                state = store.state()
                state['freshness'].update(status='failed', last_attempt_at=now())
                if args.request_id:
                    state['freshness']['request_id'] = args.request_id
                store.publish(state)
                raise
            job = store.finish_job(job['id'], result)
        if args.request_id and job['status'] in ('completed', 'partial', 'failed'):
            state = store.state()
            state['freshness']['request_id'] = args.request_id
            store.publish(state)
        print(json.dumps(job, ensure_ascii=False))
        # Partial collection is published honestly and must not discard the previous snapshot.
        return 0 if job['status'] in ('completed', 'partial') else 1
    if args.command == 'export':
        state = build_site(store, args.output, root)
        print(json.dumps({'current_id': state['current_id'], 'freshness': state['freshness']}))
    elif args.command == 'serve':
        from .server import serve
        serve(store, root, args.host, args.port)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
