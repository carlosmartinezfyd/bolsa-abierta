"""Bounded authenticated restore drill. Never print original bytes or metadata."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from .private_archive import restore_bundle
from .operations import validated_archive_paths
from .store import atomic_write


def retention_candidates(records, protected_hashes, now):
    dated = []
    for record in records:
        try:
            stamp = datetime.fromisoformat(record['checked_at'].replace('Z', '+00:00'))
            if stamp.utcoffset() is not None and stamp <= now:
                dated.append((stamp, record))
        except (KeyError, TypeError, ValueError, AttributeError):
            pass  # Unknown authenticated age never authorizes removal.
    dated.sort(key=lambda item: item[0], reverse=True)
    return [record for stamp, record in dated[2:]
            if stamp < now - timedelta(days=90) and not protected_hashes.intersection(record['hashes'])]


def recovery_drill(archive_dir, expected_hashes, *, key=None, prune=False):
    expected = set(expected_hashes)
    if not expected or len(expected) > 100 or any(not re.fullmatch('[a-f0-9]{64}', h) for h in expected):
        raise ValueError('Invalid restore manifest')
    # Same strict count, authentication and byte budgets as durable publication.
    paths = validated_archive_paths(Path(archive_dir), key=key)
    restored, records = set(), []
    with TemporaryDirectory(prefix='ba-private-restore-') as directory:
        for number, path in enumerate(paths):
            target = Path(directory) / str(number)
            report = restore_bundle(path, target, key=key)
            documents = report['metadata'].get('documents', [])
            stamps = [d.get('origin_checked_at') for d in documents]
            records.append({'path': path, 'hashes': report['hashes'],
                            'checked_at': max(stamps) if stamps and all(isinstance(s, str) for s in stamps) else None})
            for digest in report['hashes']:
                if hashlib.sha256((target / (digest + '.pdf')).read_bytes()).hexdigest() != digest:
                    raise ValueError('Restore verification failed')
                restored.add(digest)
        if not expected <= restored:
            raise ValueError('Current original missing from recovery')
    expired = retention_candidates(records, expected, datetime.now(timezone.utc)) if prune else []
    root = Path(archive_dir).resolve()
    for item in expired:
        path = item['path']
        if path.is_symlink() or path.resolve().parent != root:
            raise ValueError('Invalid archive retention path')
    # Only after a successful current-generation restore; retain >=90 days,
    # two newest dated bundles, every active original and every unknown-age file.
    for item in expired:
        item['path'].unlink()
    return {'status': 'verified', 'checked_at': datetime.now(timezone.utc).isoformat(),
            'restored_documents': len(expected), 'retained_documents': len(restored),
            'encrypted_bundles': len(paths) - len(expired), 'expired_bundles': len(expired),
            'origin_check_performed': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archives', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    try:
        state = json.loads(Path(args.state).read_text())
        hashes = [item['sha256'] for item in state.get('source_evidence', [])]
        report = recovery_drill(args.archives, hashes, key=os.environ.get('PRIVATE_ARCHIVE_KEY'), prune=True)
        code = 0
    except Exception:
        report = {'status': 'failed', 'checked_at': datetime.now(timezone.utc).isoformat(),
                  'origin_check_performed': False}
        code = 1
    atomic_write(Path(args.report), (json.dumps(report) + '\n').encode())
    print(json.dumps(report))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
