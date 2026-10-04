"""Responsible administrator intake; pinned adapters validate, never activate."""
import argparse
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from datetime import date, datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
import threading
from urllib.parse import parse_qs, urlsplit

from .store import atomic_write
from .private_archive import HASH, MAX_FILE_BYTES, export_bundle

KINDS = ('award', 'optan_observation', 'maestros_roster', 'maestros_correction')
PARSER_OUTPUT_LOCK = threading.RLock()
RECEIPT_FIELDS = frozenset(('content_id', 'source_url', 'sha256', 'actual_sha256',
    'published_at', 'kind', 'received_at', 'received_via', 'last_received_at',
    'origin_downloaded_at', 'origin_check_performed', 'byte_count', 'status',
    'reviewed_eligible', 'activated', 'human_seconds', 'reason', 'cache_status',
    'row_count', 'collection_row_count', 'source_inclusion_count', 'source_operation_count',
    'pages', 'semantic_status', 'result', 'attempts'))


@contextmanager
def quiet_parser_output():
    """Discard Python, native-fd and configured logging output while parsing.

    PDF libraries can put operand contents in warnings before raising. The
    boundary is serialized because file descriptors and logging are process
    state; callers keep only aggregate results and closed diagnostic codes.
    """
    with PARSER_OUTPUT_LOCK, open(os.devnull, 'w') as discarded:
        sys.stdout.flush(); sys.stderr.flush()
        saved_fds = [os.dup(1), os.dup(2)]
        disabled = logging.root.manager.disable
        loggers = [logging.getLogger()] + [item for item in logging.root.manager.loggerDict.values()
            if isinstance(item, logging.Logger)]
        handlers = [(logger, logger.handlers[:]) for logger in loggers]
        last_resort = logging.lastResort
        try:
            logging.disable(sys.maxsize)
            for logger, _ in handlers:
                logger.handlers = []
            logging.lastResort = logging.NullHandler()
            os.dup2(discarded.fileno(), 1); os.dup2(discarded.fileno(), 2)
            with redirect_stdout(discarded), redirect_stderr(discarded):
                yield
        finally:
            discarded.flush()
            for destination, saved in zip((1, 2), saved_fds):
                os.dup2(saved, destination); os.close(saved)
            for logger, saved in handlers:
                logger.handlers = saved
            logging.lastResort = last_resort
            logging.disable(disabled)


def safe_receipt(receipt):
    return {key: value for key, value in receipt.items() if key in RECEIPT_FIELDS}


def validate_request(request):
    if not isinstance(request, dict):
        raise ValueError('Invalid administrative request')
    content_id = request.get('content_id')
    if not isinstance(content_id, str) or not re.fullmatch(r'[0-9]{1,12}', content_id):
        raise ValueError('Invalid official content identifier')
    url = request.get('source_url', '')
    parsed = urlsplit(url)
    if (not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 32 for c in url) or '\\' in url
            or parsed.scheme != 'https' or parsed.netloc != 'www.carm.es' or parsed.path != '/web/descarga'
            or parsed.fragment or parse_qs(parsed.query, keep_blank_values=True).get('IDCONTENIDO') != [content_id]):
        raise ValueError('An identified official CARM download URL is required')
    if not isinstance(request.get('sha256'), str) or not HASH.fullmatch(request['sha256']):
        raise ValueError('Invalid expected original hash')
    if request.get('kind') not in KINDS:
        raise ValueError('Unreviewed document kind')
    published = request.get('published_at', '')
    if not isinstance(published, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', published):
        raise ValueError('Invalid administrative publication date')
    date.fromisoformat(published)
    received = datetime.fromisoformat(request.get('received_at', '').replace('Z', '+00:00'))
    if received.utcoffset() is None:
        raise ValueError('Actual receipt timestamp requires a timezone')
    if request.get('received_via') not in ('local_file', 'official_download'):
        raise ValueError('Invalid receipt provenance')
    seconds = request.get('human_seconds', 0)
    if type(seconds) is not int or not 0 <= seconds <= 86400:
        raise ValueError('Invalid human processing time')


def load_reviewed(documents='data/position-documents.json', maestros='data/position-maestros.json'):
    manifest = json.loads(Path(documents).read_text(encoding='utf8'))
    reviewed = list(manifest.get('documents', [])) + list(manifest.get('observation_documents', []))
    if Path(maestros).exists():
        parent = json.loads(Path(maestros).read_text(encoding='utf8'))
        reviewed.append(parent)
        reviewed.extend({**amendment, '_parent': parent} for amendment in parent.get('amendments', []))
    if len({item['content_id'] for item in reviewed}) != len(reviewed):
        raise ValueError('Duplicate pinned official identities')
    return reviewed


def _validate_original(path, pinned, private):
    if pinned['kind'] == 'award':
        from .position_documents import read_document
        rows = read_document(path, pinned)
        return {'row_count': len(rows), 'pages': pinned['pages']}
    if pinned['kind'] == 'optan_observation':
        from .position_observations import read_observation_document
        evidence = read_observation_document(path, pinned)
        return {'row_count': evidence['row_count'], 'pages': evidence['pages'], 'semantic_status': 'unconfirmed'}
    if pinned['kind'] in ('maestros_roster', 'maestros_correction'):
        from .position_maestros import read_maestros
        parent = pinned if pinned['kind'] == 'maestros_roster' else pinned['_parent']
        baseline_path = path if pinned['kind'] == 'maestros_roster' else private / (parent['sha256'] + '.pdf')
        if baseline_path.is_symlink() or not baseline_path.is_file():
            raise ValueError('Required reviewed baseline is missing')
        amendments = []
        for amendment in parent.get('amendments', []):
            amendment_path = private / (amendment['sha256'] + '.pdf')
            if not amendment_path.is_file() or amendment_path.is_symlink():
                raise ValueError('Required reviewed correction is missing')
            amendments.append((amendment_path, amendment))
        parsed = read_maestros(baseline_path, parent, amendments=amendments)
        counts = {'collection_row_count': len(parsed['rows']), 'pages': pinned['pages']}
        if pinned['kind'] == 'maestros_correction':
            counts['source_inclusion_count'] = sum(pinned['page_inclusion_counts'])
            counts['source_operation_count'] = len(pinned['operations'])
        else:
            counts['row_count'] = parent['baseline_row_count']
        return counts
    raise ValueError('Unknown strict adapter')


def intake_document(path, request, reviewed_documents, *, private_dir, state=None):
    """Store a private original and return only allowlisted receipt metadata.

    A reviewed receipt authorizes later validation by sync, never bypassing its
    generation checks. Local delivery and origin download have distinct provenance.
    """
    validate_request(request)
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError('Invalid original size or path')
    body = path.read_bytes()
    if len(body) > MAX_FILE_BYTES:
        raise ValueError('Original exceeds byte budget')
    actual_hash = hashlib.sha256(body).hexdigest()
    private = Path(private_dir)
    if private.is_symlink() or (private.exists() and not private.is_dir()):
        raise ValueError('Invalid private original directory')
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    stored = private / (actual_hash + ('.pdf' if body.startswith(b'%PDF-') else '.bin'))
    if stored.is_symlink() or (stored.exists() and stored.read_bytes() != body):
        raise ValueError('Conflicting private original')
    if not stored.exists():
        atomic_write(stored, body); stored.chmod(0o600)
    safe_keys = ('content_id', 'source_url', 'sha256', 'published_at', 'kind', 'received_at', 'received_via')
    receipt = {k: request[k] for k in safe_keys}
    # Caller query values are not public metadata. Only reviewed URLs, or an
    # ID-only official URL for unknown originals, may leave the private boundary.
    receipt['source_url'] = 'https://www.carm.es/web/descarga?IDCONTENIDO=' + request['content_id']
    receipt.update(actual_sha256=actual_hash, byte_count=len(body), status='quarantined',
                   reviewed_eligible=False, activated=False, origin_check_performed=False,
                   human_seconds=request.get('human_seconds', 0), reason='unreviewed_document',
                   cache_status='unconfigured')
    if request['received_via'] == 'official_download':
        receipt['origin_check_performed'] = True
        receipt['origin_downloaded_at'] = request['received_at']
    matches = [d for d in reviewed_documents if d.get('content_id') == request['content_id']]
    if actual_hash != request['sha256']:
        receipt['reason'] = 'hash_mismatch'
    elif not body.startswith(b'%PDF-'):
        receipt['reason'] = 'invalid_pdf'
    elif len(matches) > 1:
        receipt['reason'] = 'manifest_conflict'
    elif matches:
        pinned = matches[0]
        # Query ordering may differ, but source identity and exact ID are validated.
        fields = ('content_id', 'sha256', 'published_at', 'kind')
        pinned_valid = all(pinned.get(k) == request[k] for k in fields)
        try:
            validate_request({**request, 'source_url': pinned['source_url']})
        except (ValueError, TypeError, KeyError):
            pinned_valid = False
        if not pinned_valid:
            receipt['reason'] = 'manifest_mismatch'
        else:
            receipt['source_url'] = pinned['source_url']
            try:
                with quiet_parser_output():
                    counts = _validate_original(stored, pinned, private)
                receipt.update(counts, status='validated', reviewed_eligible=True, reason=None)
            except Exception:
                # Parser errors may contain nominal PDF contents. Redact completely.
                receipt['reason'] = 'adapter_rejected'
    previous = state or {}
    documents = list(previous.get('documents', []))
    identity = (request['content_id'], actual_hash, request['kind'])
    prior = next((d for d in documents if (d.get('content_id'), d.get('actual_sha256'), d.get('kind')) == identity), None)
    receipt['result'] = 'already_received' if prior else 'received'
    entry = dict(receipt, last_received_at=request['received_at'], attempts=1)
    if prior:
        entry['received_at'] = prior['received_at']
        entry['attempts'] = prior.get('attempts', 1) + 1
        documents.remove(prior)
    documents.append(entry)
    new_state = {'schema': 1, 'documents': sorted(documents, key=lambda d: (d['content_id'], d['actual_sha256'], d['kind'])),
        'pending_documents': sum(d['status'] != 'validated' for d in documents),
        'human_seconds_total': previous.get('human_seconds_total', 0) + request.get('human_seconds', 0),
        'last_received_at': request['received_at']}
    return {'receipt': receipt, 'state': new_state}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, help='Privately delivered original; never a fresh official source check')
    parser.add_argument('--url', required=True)
    parser.add_argument('--content-id', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--published-at', required=True)
    parser.add_argument('--kind', choices=KINDS, required=True)
    parser.add_argument('--human-seconds', type=int, default=0)
    parser.add_argument('--documents', default='data/position-documents.json')
    parser.add_argument('--maestros', default='data/position-maestros.json')
    parser.add_argument('--state', default='.runtime/admin-intake.json')
    parser.add_argument('--private-dir', default='.runtime/admin-originals')
    parser.add_argument('--archive-dir', help='Opt-in encrypted original destination; requires PRIVATE_ARCHIVE_KEY')
    args = parser.parse_args(argv)
    try:
        request = {'content_id': args.content_id, 'source_url': args.url, 'sha256': args.sha256,
            'published_at': args.published_at, 'kind': args.kind, 'human_seconds': args.human_seconds,
            'received_at': datetime.now(timezone.utc).isoformat(),
            'received_via': 'local_file' if args.file else 'official_download'}
        validate_request(request)
        private = Path(args.private_dir)
        if args.file:
            path = args.file
        else:
            from .sources import OfficialClient
            fetched = OfficialClient(max_pdf_bytes=MAX_FILE_BYTES).fetch(args.url, kind='pdf')
            request['received_at'] = datetime.now(timezone.utc).isoformat()
            private.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = private / 'download.part'
            atomic_write(path, fetched.body); path.chmod(0o600)
        state_path = Path(args.state)
        state = json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else None
        result = intake_document(path, request, load_reviewed(args.documents, args.maestros), private_dir=private, state=state)
        if not args.file:
            path.unlink()
        receipt = result['receipt']
        if args.archive_dir and os.environ.get('PRIVATE_ARCHIVE_KEY'):
            # Archive only the received hash and reviewed corrections when present.
            # All raw files remain private; known receipts need no nominal payload.
            try:
                archive = export_bundle(private, args.archive_dir, metadata={
                    'document_count': len(list(private.glob('*.pdf'))),
                    'receipt_record_count': receipt.get('row_count'),
                    'receipt': safe_receipt(receipt),
                    'receipts': [safe_receipt(entry) for entry in result['state']['documents']
                        if (private / (entry['actual_sha256'] + '.pdf')).is_file()]})
                receipt.update(cache_status='encrypted', bundle_id=archive['bundle_id'])
            except Exception:
                receipt['cache_status'] = 'archive_failed'
        for entry in result['state']['documents']:
            if entry['content_id'] == receipt['content_id'] and entry['actual_sha256'] == receipt['actual_sha256'] and entry['kind'] == receipt['kind']:
                entry['cache_status'] = receipt['cache_status']
                if receipt.get('bundle_id'): entry['bundle_id'] = receipt['bundle_id']
        atomic_write(state_path, json.dumps(result['state'], ensure_ascii=True, indent=2).encode())
        print(json.dumps({'receipt': receipt, 'pending_documents': result['state']['pending_documents'],
            'human_seconds_total': result['state']['human_seconds_total']}, sort_keys=True))
        return 0
    except Exception:
        print('Administrative intake failed; no generation activated and no nominal data logged.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
