"""Private position collection and authenticated publication."""

import argparse
import hashlib
from io import BytesIO
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.parse import parse_qsl, urlsplit

import requests

from .positions import parse_pdf
from .position_amendments import read_amendment, apply_insertions
from .sources import OfficialClient, SourceError
from .store import atomic_write


VOLATILE_FIELDS = frozenset(('incorporated', 'checked_at', 'validated_at', 'downloaded_at',
    'attempted_at', 'verified_at', 'first_seen_at', 'last_seen_at', 'received_at'))


def semantic_metadata(value):
    """Verification times cannot create a fresh copy of identical personal data."""
    if isinstance(value, dict):
        return {k: semantic_metadata(v) for k, v in value.items() if k not in VOLATILE_FIELDS}
    if isinstance(value, list):
        return [semantic_metadata(v) for v in value]
    return value


def merge_documents(*collections):
    documents = {}
    for collection in collections:
        for item in collection:
            document = {k: v for k, v in item.items() if k != 'incorporated'}
            prior = documents.get(document['content_id'])
            if prior and semantic_metadata(prior) != semantic_metadata(document):
                raise ValueError('Conflicting document revisions require review')
            documents[document['content_id']] = {**(prior or {}), **document}
    return sorted(documents.values(), key=lambda d: d['content_id'])


def reconcile_documents(reviewed, prior):
    """Explicit code-reviewed manifests govern interpretation of the same bytes.

    A changed original also needs an explicit predecessor hash. Discovery alone
    cannot replace a reviewed source or carry its date onto new bytes.
    """
    current = {d['content_id']: {k: v for k, v in d.items() if k != 'incorporated'} for d in reviewed}
    if len(current) != len(reviewed):
        raise ValueError('Duplicate reviewed document identities')
    for item in prior:
        old = {k: v for k, v in item.items() if k != 'incorporated'}
        new = current.get(old['content_id'])
        if new is None:
            current[old['content_id']] = old
        elif new['sha256'] != old['sha256'] and new.get('supersedes_sha256') != old['sha256']:
            raise ValueError('Conflicting original revision requires explicit predecessor review')
    return sorted(current.values(), key=lambda d: d['content_id'])


def fetch_documents(documents, client, private):
    artifacts = []
    private = Path(private)
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    for document in documents:
        downloaded = client.fetch(document['source_url'], kind='pdf')
        digest = verify_source(downloaded.body, document)
        path = private / f'{digest}.pdf'
        atomic_write(path, downloaded.body)
        path.chmod(0o600)
        document['checked_at'] = datetime.now(timezone.utc).isoformat()
        artifacts.append((path, document))
    return artifacts


RECOVERABLE_ORIGIN_ERRORS = frozenset(('access_challenge', 'dns_error', 'network_error',
    'temporary_http', 'http_error', 'timeout', 'time_limit', 'invalid_pdf', 'invalid_response'))
MAX_CACHE_BUNDLES = 100
MAX_CACHE_BYTES = 512 * 1024 * 1024


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.utcoffset() is not None and stamp <= datetime.now(timezone.utc):
            return value
    except ValueError:
        pass
    return None


def _time_key(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _document_identity(document):
    return {**{k: document[k] for k in ('content_id', 'sha256', 'source_url')},
        'kind': document.get('kind') or ('baseline' if document['content_id'] == '208095' else 'correction'),
        **({'published_at': document['published_at']} if 'published_at' in document else
           {'signed_at': document['signed_at']} if 'signed_at' in document else {})}


def _same_original(record, document):
    if not isinstance(record, dict):
        return False
    identity = _document_identity(document)
    if any(record.get(k) != v for k, v in identity.items() if k != 'source_url'):
        return False
    try:
        urls = [urlsplit(value) for value in (record.get('source_url'), identity['source_url'])]
        for url in urls:
            if (url.scheme != 'https' or url.netloc != 'www.carm.es' or url.path != '/web/descarga'
                    or url.fragment or [v for k, v in parse_qsl(url.query) if k == 'IDCONTENIDO'] != [identity['content_id']]):
                return False
        return sorted(parse_qsl(urls[0].query)) == sorted(parse_qsl(urls[1].query))
    except (TypeError, ValueError):
        return False


def _cached_records(metadata):
    """Allowlist operational provenance from an authenticated archive only."""
    records = []
    if metadata.get('schema') == 1 and metadata.get('purpose') == 'position_source_cache':
        documents = metadata.get('documents', [])
        if isinstance(documents, list):
            for item in documents[:100]:
                if isinstance(item, dict) and item.get('received_via') in ('official_download', 'local_file'):
                    records.append({**item, 'origin_checked_at':
                        _timestamp(item.get('origin_checked_at')) if item['received_via'] == 'official_download' else None})
    receipts = metadata.get('receipts', [metadata.get('receipt')])
    if isinstance(receipts, list):
        for item in receipts[:1000]:
            if (isinstance(item, dict) and item.get('status') == 'validated'
                    and item.get('reviewed_eligible') is True and item.get('actual_sha256') == item.get('sha256')
                    and item.get('received_via') in ('local_file', 'official_download')):
                records.append({**item, 'origin_checked_at': _timestamp(item.get('origin_downloaded_at'))
                    if item['received_via'] == 'official_download' and item.get('origin_check_performed') is True else None})
    return records


def _previous_check(document, cached, prior):
    stamps = [document.get('checked_at'), cached.get('origin_checked_at')]
    if re.fullmatch(r'[a-f0-9]{64}', prior.get('active_version') or ''):
        previous = [d for d in [*prior.get('references', []), *prior.get('documents', [])]
            if d.get('incorporated') is True]
        previous += [a for d in prior.get('documents', []) if d.get('incorporated') is True
            for a in d.get('amendments', [])]
        if any(d.get('content_id') == document['content_id'] and d.get('sha256') == document['sha256']
                for d in previous):
            stamps.append(prior.get('checked_at'))
            stamps += [d.get('checked_at') for d in previous
                if d.get('content_id') == document['content_id'] and d.get('sha256') == document['sha256']]
            stamps += [d.get('origin_checked_at') for d in prior.get('source_evidence', [])
                if d.get('content_id') == document['content_id'] and d.get('sha256') == document['sha256']]
    known = [value for value in map(_timestamp, stamps) if value]
    return max(known, key=_time_key) if known else None


def collect_evidence(documents, client, private, *, archive_dir=None, key=None, prior=None, diagnostics=None):
    """Prefer fresh originals; recover only exact reviewed bytes after an outage.

    Cache provenance is authenticated inside AES-GCM bundles. Plain receipt JSON
    and existing loose PDFs never authorize a fallback. A changed official hash
    is a review failure, even if an older original remains recoverable.
    """
    from .private_archive import archive_key, export_bundle, restore_bundle
    private = Path(private)
    if private.is_symlink() or (private.exists() and not private.is_dir()):
        raise ValueError('Invalid private original directory')
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    private.chmod(0o700)
    prior, diagnostics = prior or {}, diagnostics if diagnostics is not None else {}
    fresh, failures, evidence, artifacts = {}, {}, {}, {}
    identities = [(d['content_id'], d['sha256']) for d in documents]
    if len(set(identities)) != len(documents):
        raise ValueError('Duplicate source evidence identity')
    for document in documents:
        identity = (document['content_id'], document['sha256'])
        attempted = datetime.now(timezone.utc).isoformat()
        try:
            path, fetched = fetch_documents([document], client, private)[0]
            fresh[identity] = path
            artifacts[document['sha256']] = path
            evidence[identity] = {**_document_identity(document), 'source_status': 'fresh',
                'attempted_at': attempted, 'origin_checked_at': fetched['checked_at'],
                'received_at': fetched['checked_at'], 'received_via': 'official_download'}
        except (SourceError, ValueError) as error:
            failures[identity] = error
            evidence[identity] = {**_document_identity(document), 'source_status': 'unavailable',
                'attempted_at': attempted, 'origin_checked_at': None,
                'error_code': error.code if isinstance(error, SourceError) else 'source_changed'}
    diagnostics.update(origin_check_complete=not failures, origin_verified_documents=len(fresh),
        origin_failed_documents=len(failures), cached_documents=0, cache_status='unconfigured')
    configured_key = os.environ.get('PRIVATE_ARCHIVE_KEY', '') if key is None else key
    cached = {}
    if archive_dir and configured_key:
        archives = Path(archive_dir)
        try:
            archive_key(configured_key)
            if archives.is_symlink() or (archives.exists() and not archives.is_dir()):
                raise ValueError('Invalid encrypted archive directory')
            paths = sorted(archives.glob('*.baenc')) if archives.exists() else []
            if (len(paths) > MAX_CACHE_BUNDLES or any(p.is_symlink() or not p.is_file() for p in paths)
                    or sum(p.stat().st_size for p in paths) > MAX_CACHE_BYTES):
                raise ValueError('Encrypted cache exceeds recovery budget')
            # Every candidate is authenticated in an isolated private directory;
            # unrelated or unreviewed archived bytes never enter the collection.
            with TemporaryDirectory(prefix='position-recovery-', dir=private.parent) as temporary:
                recovered = []
                for number, path in enumerate(paths):
                    target = Path(temporary) / str(number)
                    restored = restore_bundle(path, target, key=configured_key)
                    for record in _cached_records(restored['metadata']):
                        for document in documents:
                            if record.get('sha256') in restored['hashes'] and _same_original(record, document):
                                recovered.append((document, record, target / (document['sha256'] + '.pdf')))
                for document, record, path in recovered:
                    identity = (document['content_id'], document['sha256'])
                    old = cached.get(identity)
                    if old and _timestamp(old.get('origin_checked_at')) and not _timestamp(record.get('origin_checked_at')):
                        continue
                    cached[identity] = record
                    if identity not in fresh:
                        body = path.read_bytes()
                        verify_source(body, document)
                        destination = private / (document['sha256'] + '.pdf')
                        if destination.is_symlink():
                            raise ValueError('Invalid private recovery destination')
                        atomic_write(destination, body); destination.chmod(0o600)
            diagnostics['cache_status'] = 'ready'
            missing = [d for d in documents if (d['content_id'], d['sha256']) in fresh and
                not _timestamp(cached.get((d['content_id'], d['sha256']), {}).get('origin_checked_at'))]
            if missing:
                with TemporaryDirectory(prefix='position-archive-', dir=private.parent) as temporary:
                    for document in missing:
                        body = fresh[(document['content_id'], document['sha256'])].read_bytes()
                        verify_source(body, document)
                        path = Path(temporary) / (document['sha256'] + '.pdf')
                        atomic_write(path, body); path.chmod(0o600)
                    export_bundle(temporary, archives, key=configured_key,
                        expected_hashes=sorted({d['sha256'] for d in missing}), metadata={
                            'schema': 1, 'purpose': 'position_source_cache',
                            'document_count': len({d['sha256'] for d in missing}),
                            'documents': [{k: v for k, v in evidence[(d['content_id'], d['sha256'])].items()
                                if k not in ('source_status', 'attempted_at')} for d in missing]})
        except Exception:
            # Private metadata and parser/library errors must never reach logs.
            cached = {}
            diagnostics['cache_status'] = 'failed'
    for document in documents:
        identity = (document['content_id'], document['sha256'])
        failure, record = failures.get(identity), cached.get(identity)
        if failure is not None and record is not None and isinstance(failure, SourceError) and failure.code in RECOVERABLE_ORIGIN_ERRORS:
            checked = _previous_check(document, record, prior)
            evidence[identity].update(source_status='cached', origin_checked_at=checked,
                received_at=_timestamp(record.get('received_at')), received_via=record.get('received_via'))
            artifacts[document['sha256']] = private / (document['sha256'] + '.pdf')
            diagnostics['cached_documents'] += 1
    unresolved = [identity for identity in identities if evidence[identity]['source_status'] == 'unavailable']
    if unresolved:
        raise failures[unresolved[0]]
    checks = [evidence[identity]['origin_checked_at'] for identity in identities]
    checked = min(checks, key=_time_key) if checks and all(checks) else None
    return {**diagnostics, 'artifacts': artifacts, 'evidence': [evidence[i] for i in identities], 'checked_at': checked}


def verify_source(body, source):
    digest = hashlib.sha256(body).hexdigest()
    if digest != source['sha256']:
        raise ValueError('The official PDF changed; its date and extraction require review before publication')
    return digest


def publish(version, read_rows, send, *, resume=False):
    existing = send({'action': 'begin', 'version': version})
    if existing.get('ready'):
        if version.get('checked_at') is not None:
            send({'action': 'checked', 'id': version['id'], 'checked_at': version['checked_at']})
        return 'unchanged'
    rows = read_rows()
    if ('row_count' in version and len(rows) != version['row_count']) or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Incomplete or duplicate local extraction; no rows published')
    if resume:
        existing_ids, after = set(), None
        for _ in range(2501):
            progress = send({'action': 'status', 'id': version['id'], **({'after_id': after} if after else {})})
            ids = progress.get('existing_ids')
            if not isinstance(ids, list) or len(ids) > 40 or any(not isinstance(i, str) or not re.fullmatch('[a-f0-9]{32}', i) for i in ids):
                raise ValueError('Invalid private staging progress')
            if ids != sorted(set(ids)) or any(after and i <= after for i in ids) or existing_ids.intersection(ids):
                raise ValueError('Nonconsecutive staging cursor')
            existing_ids.update(ids)
            if not progress.get('more'):
                break
            if not ids or progress.get('next_id') != ids[-1]:
                raise ValueError('Invalid staging continuation')
            after = progress['next_id']
        else:
            raise ValueError('Staging inventory exceeded its record budget')
        if not existing_ids <= {r['id'] for r in rows}:
            raise ValueError('Staging has records outside the reviewed generation')
        rows = [r for r in rows if r['id'] not in existing_ids]
    for start in range(0, len(rows), 40):
        send({'action': 'rows', 'id': version['id'], 'rows': rows[start:start + 40]})
    send({'action': 'activate', 'id': version['id']})
    return 'published'


def build_version(source, checked_at):
    source = semantic_metadata(source)
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
    if source.get('course') or source.get('parser_revision'):
        # Preserve reproducibility of legacy manifests while making every
        # explicitly scoped generation depend on its whole reviewed meaning.
        evidence = {'source': source, 'parser': 'collection-v2-scoped-memberships'}
        version['id'] = hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    return version


class PublicationDeferred(RuntimeError):
    def __init__(self, resume_after):
        super().__init__('Publication deferred by the daily write budget')
        self.resume_after = resume_after


def publication_client(base, token):
    target = urlsplit(base)
    if (target.scheme != 'https' or target.hostname != 'bolsa-abierta-gateway.cmartinezmtez.workers.dev'
            or target.port or target.username or target.password or target.path or target.query
            or target.fragment or len(token) < 40):
        raise ValueError('Position publication service is not configured')
    session = requests.Session()
    session.trust_env = False

    def send(body):
        response = session.post(base + '/internal/positions', json=body,
            headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'BolsaAbierta-PositionCollector/2.0'},
            timeout=(5, 30), allow_redirects=False)
        if response.status_code == 429:
            try:
                limit = response.json()
                if limit.get('pending_budget') is True:
                    raise PublicationDeferred(limit.get('resume_after'))
            except (ValueError, AttributeError):
                pass
        if response.status_code != 200:
            raise RuntimeError(f'Position publication returned HTTP {response.status_code}')
        return response.json()
    return send


def source_collection(args, prior):
    source = json.loads(Path(args.source).read_text(encoding='utf8'))
    manifest = json.loads(Path(args.documents).read_text(encoding='utf8'))
    reviewed = list(manifest['documents'])
    if Path(args.maestros).exists():
        maestro = json.loads(Path(args.maestros).read_text(encoding='utf8'))
        reviewed.append(maestro)
    source['documents'] = reconcile_documents(reviewed, prior.get('documents', []))
    source.setdefault('course', '2026-2027')
    pending = 0
    if args.inventory_state and Path(args.inventory_state).exists():
        from .admin_documents import quiet_parser_output
        from .position_documents import scan_document
        inventory = json.loads(Path(args.inventory_state).read_text(encoding='utf8'))
        known = {d['content_id'] for d in source['documents']}
        for item in inventory.get('documents', []):
            if item['content_id'] in known or item.get('kind') != 'award' or not item.get('sha256'):
                continue
            path = Path(args.inventory_dir) / (item['sha256'] + '.pdf')
            if not path.exists():
                pending += 1
                continue
            try:
                # Assigned-function aliases belong to an explicitly reviewed
                # document. A new original may not borrow another file's alias.
                with quiet_parser_output():
                    scanned = scan_document(path, item['source_url'], checked_at=item['downloaded_at'])
                if scanned['metadata']['sha256'] != item['sha256']:
                    raise ValueError('Inventoried document bytes changed')
                source['documents'] = merge_documents(source['documents'], [scanned['metadata']])
                known.add(item['content_id'])
            except Exception:
                pending += 1
    return source, manifest.get('observation_documents', []), pending


def required_documents(source):
    documents = [{'content_id': '208095', **{k: v for k, v in source.items()
                    if k not in ('amendments', 'documents')}}, *source.get('amendments', [])]
    for document in source.get('documents', []):
        documents.append(document)
        documents.extend(document.get('amendments', []))
    return documents


def read_collection(source, artifacts):
    from .admin_documents import quiet_parser_output
    with quiet_parser_output():
        return _read_collection(source, artifacts)


def _read_collection(source, artifacts):
    baseline = Path(artifacts[source['sha256']]).read_bytes()
    verify_source(baseline, source)
    with BytesIO(baseline) as stream:
        rows = parse_pdf(stream)
    amendments = source.get('amendments', [])
    if amendments:
        if len(rows) != source['baseline_row_count']:
            raise ValueError('Baseline count changed before amendment consolidation')
        changes = [row for document in amendments
                   for row in read_amendment(artifacts[document['sha256']], document)]
        rows = apply_insertions(rows, changes)
    from collections import Counter
    if (len(rows) != source['row_count'] or Counter(r['specialty'] for r in rows)
            != Counter({s['code']: s['count'] for s in source['specialties']})):
        raise ValueError('Extraction differs from the independently reviewed source manifest')
    from .position_documents import read_document
    for document in source.get('documents', []):
        path = artifacts[document['sha256']]
        if document['kind'] == 'award':
            rows.extend(read_document(path, document))
        elif document['kind'] == 'maestros_roster':
            from .position_maestros import read_maestros
            parsed = read_maestros(path, document, amendments=[
                (artifacts[a['sha256']], a) for a in document.get('amendments', [])])
            rows.extend(parsed['rows'])
        else:
            raise ValueError('Unknown document adapter requires review')
    from .position_identity import annotate_memberships
    return annotate_memberships(rows, source.get('course', '2026-2027'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='data/position-source.json')
    parser.add_argument('--documents', default='data/position-documents.json')
    parser.add_argument('--maestros', default='data/position-maestros.json')
    parser.add_argument('--state', default='.runtime/source-documents.json')
    parser.add_argument('--summary', default='.runtime/position-status.json')
    parser.add_argument('--inventory-state')
    parser.add_argument('--inventory-dir', default='.runtime/source-inventory')
    parser.add_argument('--private-dir', default='.runtime/positions')
    parser.add_argument('--archive-dir', help='Authenticated encrypted cache; requires PRIVATE_ARCHIVE_KEY')
    parser.add_argument('--validate-only', action='store_true', help='Validate without contacting the publication service')
    parser.add_argument('--local-evidence', type=Path, help='Hash-addressed originals for local validation only')
    parser.add_argument('--validation-report', type=Path)
    args = parser.parse_args(argv)
    if args.local_evidence and not args.validate_only:
        parser.error('--local-evidence requires --validate-only; it is not a fresh source check')
    state_path = Path(args.state)
    prior = json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else {}
    attempt = datetime.now(timezone.utc).isoformat()
    status = {'status': 'pending', 'attempted_at': attempt, 'checked_at': prior.get('checked_at'),
              'active_version': prior.get('active_version')}
    phase = 'configuration'
    try:
        send = None if args.validate_only else publication_client(
            os.environ.get('PUBLIC_API_BASE', '').rstrip('/'), os.environ.get('POSITION_INGEST_TOKEN', ''))
        source, observations, pending = source_collection(args, prior)
        status['pending_documents'] = pending
        phase = 'source_verification'
        required = required_documents(source)
        if args.local_evidence:
            artifacts = {}
            for document in required:
                path = args.local_evidence / (document['sha256'] + '.pdf')
                verify_source(path.read_bytes(), document)
                artifacts[document['sha256']] = path
            checked = None  # Local re-extraction is not a new origin check.
            evidence = []
            status.update(origin_check_complete=False, cached_documents=0,
                origin_verified_documents=0, origin_failed_documents=0, cache_status='unconfigured')
        else:
            collected = collect_evidence(required, OfficialClient(), Path(args.private_dir),
                archive_dir=args.archive_dir, prior=prior, diagnostics=status)
            artifacts, checked, evidence = collected['artifacts'], collected['checked_at'], collected['evidence']
        status['verified_documents'] = len(required)
        version = build_version(source, checked)
        status.update(staged_version=version['id'], record_count=version['row_count'])
        phase = 'extraction'
        if args.validate_only:
            rows = read_collection(source, artifacts)
            if len(rows) != version['row_count'] or len({r['id'] for r in rows}) != len(rows):
                raise ValueError('Invalid combined record count or identity')
            report = {'version': version, 'validated_at': datetime.now(timezone.utc).isoformat(),
                'origin_check_performed': status['origin_verified_documents'] > 0,
                'origin_check_complete': status['origin_check_complete'],
                'cached_documents': status['cached_documents'], 'record_count': len(rows),
                'ranked_records': sum(r.get('rank') is not None for r in rows),
                'award_records': sum(r.get('record_type') == 'award' for r in rows),
                'required_documents': len(required), 'pending_documents': pending}
            if args.validation_report:
                atomic_write(args.validation_report, json.dumps(report, ensure_ascii=False, indent=2).encode())
            print(json.dumps({k: v for k, v in report.items() if k != 'version'}, ensure_ascii=False))
            return 0
        def read_rows():
            nonlocal phase
            phase = 'extraction'
            rows = read_collection(source, artifacts)
            phase = 'publication'
            return rows
        phase = 'publication'
        result = publish(version, read_rows, send, resume=True)
        active = send({'action': 'metadata', 'id': version['id']})
        if active.get('active') is not True or active.get('ready') is not True:
            raise RuntimeError('The reviewed generation is not active')
        output = {'active_version': version['id'], 'checked_at': checked,
            'source_evidence': evidence,
            'references': [{**d, 'incorporated': True} for d in [
                {'content_id': '208095', 'source_url': source['source_url'], 'sha256': source['sha256'],
                    'kind': 'baseline', 'checked_at': next((e['origin_checked_at'] for e in evidence
                        if e['content_id'] == '208095'), None)},
                *[{**a, 'kind': 'correction'} for a in source.get('amendments', [])]]],
            'documents': [{**d, 'incorporated': True} for d in source['documents']],
            'observation_documents': [{**semantic_metadata(d), 'incorporated': False} for d in observations]}
        atomic_write(state_path, json.dumps(output, ensure_ascii=False, indent=2).encode())
        degraded = status['cached_documents'] > 0
        status.update(status='degraded' if degraded else 'verified', active_version=version['id'], checked_at=checked)
        if degraded:
            status['error_code'] = 'origin_unavailable_cached_evidence'
        status.pop('staged_version', None)
        print(json.dumps({'result': result, 'record_count': version['row_count'],
                          'query_scopes': len(version['specialties']), 'active_version': version['id'],
                          'origin_check_complete': status['origin_check_complete'],
                          'cached_documents': status['cached_documents']}))
        return 3 if degraded else 0
    except PublicationDeferred as error:
        status.update(status='pending_budget', error_code='daily_write_cap', resume_after=error.resume_after)
        print('Position generation remains staged; previous active generation retained (daily write cap).')
        return 2
    except Exception as error:
        code = getattr(error, 'code', None)
        status.update(status='failed', error_code=code if code in (
            'access_challenge', 'invalid_pdf', 'traversal_limit', 'timeout', 'network_error')
            else {'configuration': 'not_configured', 'source_verification': 'source_verification_failed',
                  'extraction': 'extraction_failed', 'publication': 'publication_failed'}[phase])
        print(f'Position check failed: {status["error_code"]}. Previous generation retained.')
        return 1
    finally:
        if not args.validate_only:
            from .coverage import position_summary
            atomic_write(Path(args.summary), json.dumps(position_summary(status), indent=2).encode())


if __name__ == '__main__':
    raise SystemExit(main())
