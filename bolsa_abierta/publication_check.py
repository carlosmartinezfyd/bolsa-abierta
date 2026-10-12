"""Verify public API/Pages convergence without searching or logging personal data."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import time
import requests


def matching_publication(expected, api, published):
    def stamp(value):
        if value is None:
            return None
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.utcoffset() is None:
            raise ValueError('Timezone missing')
        return result
    try:
        return bool(re.fullmatch('[a-f0-9]{64}', expected.get('active_version', ''))
            and type(expected.get('record_count')) is int and expected['record_count'] > 0
            and expected['active_version'] == api.get('id') == published.get('active_version')
            and expected['record_count'] == api.get('row_count') == published.get('record_count')
            and stamp(expected.get('checked_at')) == stamp(api.get('checked_at')) == stamp(published.get('checked_at')))
    except (TypeError, ValueError, AttributeError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', required=True)
    args = parser.parse_args()
    expected = json.loads(Path(args.snapshot).read_text(encoding='utf-8'))['position_status']
    session = requests.Session(); session.trust_env = False
    for attempt in range(12):
        try:
            api = session.get('https://bolsa-abierta-gateway.cmartinezmtez.workers.dev/api/positions',
                headers={'Cache-Control': 'no-cache'}, timeout=(5, 10), allow_redirects=False)
            pages = session.get('https://carlosmartinezfyd.github.io/bolsa-abierta/data/gateway-status.json',
                params={'verify': time.time_ns()}, headers={'Cache-Control': 'no-cache'},
                timeout=(5, 10), allow_redirects=False)
            if api.status_code == pages.status_code == 200 and matching_publication(expected,
                    api.json().get('version', {}), pages.json().get('health', {})):
                print('API and Pages agree on generation, record count and actual source verification time.')
                return 0
        except (requests.RequestException, ValueError):
            pass
        if attempt < 11:
            time.sleep(5)
    print('Public publication consistency could not be confirmed; source evidence remains preserved.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
