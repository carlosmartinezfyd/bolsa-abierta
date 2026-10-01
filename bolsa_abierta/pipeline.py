"""Collect observations, validate evidence, and publish only accepted documents."""
import hashlib
import json
import subprocess
import sys
import time

from .store import now


def isolated_parse(data, source_url, retrieved_at):
    try:
        completed = subprocess.run([sys.executable, '-m', 'bolsa_abierta.parser_worker', source_url, retrieved_at],
                                   input=data, capture_output=True, timeout=45, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('PDF analysis exceeded 45 seconds') from exc
    if completed.returncode != 0:
        # Child output is diagnostic data, never executable or publication content.
        raise ValueError(completed.stderr.decode('utf-8', errors='replace')[-600:] or 'PDF analysis failed')
    return json.loads(completed.stdout)


def run_refresh(store, client=None, discover=None, parser=None):
    if client is None or discover is None:
        from .sources import OfficialClient, discover_notices
        client = client or OfficialClient()
        discover = discover or discover_notices
    parser = parser or isolated_parse
    state = store.state()
    attempt = now()
    state['freshness'].update(last_attempt_at=attempt, status='running')
    store.publish(state)
    errors, added, checks = [], [], []
    deadline = time.monotonic() + 600
    try:
        discovered = discover(client, known_notices=state['catalog'].get('notices', []))
    except Exception as exc:
        state['freshness']['status'] = 'failed'
        state['freshness']['error'] = str(exc)[:600]
        store.publish(state)
        return {'status': 'failed', 'message': 'No se pudo consultar el catálogo oficial.', 'errors': [str(exc)[:600]]}
    checks.extend(discovered['checks'])
    notices = discovered['notices']
    documents = {doc['id']: doc for doc in state['documents']}
    seen = {}
    rejected = {d['id']: d for d in state['catalog'].get('rejected_documents', [])}
    for notice in notices:
        if notice.get('kind') != 'vacancies' or notice.get('should_check') is False:
            continue
        notice.pop('error', None)
        accepted = []
        notice_errors = []
        failed_hashes = []
        urls = notice.get('pdf_urls', [])
        if not urls:
            notice_errors.append('El aviso no ofrece un PDF compatible accesible.')
        for url in urls:
            if url in seen:
                digest, error, failed_hash = seen[url]
                if digest:
                    accepted.append(digest)
                if error:
                    notice_errors.append(error)
                if failed_hash:
                    failed_hashes.append(failed_hash)
                continue
            archived = None
            try:
                if time.monotonic() > deadline:
                    raise ValueError('Se agotó el tiempo disponible para esta comprobación.')
                fetched = client.fetch(url, kind='pdf')
                if fetched.status != 200 or not fetched.body.startswith(b'%PDF-') or len(fetched.body) > 10 * 1024 * 1024:
                    raise ValueError('La respuesta no es un PDF completo (posible bloqueo de acceso).')
                digest = hashlib.sha256(fetched.body).hexdigest()
                retrieved = now()
                # Preserve unaccepted evidence for maintainer review, but never publish its rows/PDF endpoint.
                archived = store.archive(fetched.body)
                if digest not in documents or documents[digest].get('extraction_status') != 'validated':
                    doc = parser(fetched.body, fetched.final_url, retrieved)
                    if doc['id'] != digest or doc.get('status') != 'approved' or not doc.get('rows'):
                        raise ValueError('El extractor no devolvió un documento validado.')
                    doc.update(evidence_status='archived', downloaded_at=retrieved,
                               extraction_status='validated', extracted_at=now(), approved_at=now(),
                               response_url=fetched.final_url, response_headers={k: v for k, v in fetched.headers.items()
                               if k.lower() in ('etag', 'last-modified', 'content-type', 'content-length')})
                    doc.setdefault('retrieved_at', retrieved)
                    documents[digest] = doc
                    added.append(digest)
                else:
                    documents[digest]['evidence_status'] = 'archived'
                accepted.append(digest)
                rejected.pop(digest, None)
                seen[url] = digest, None, None
                checks.append({'id': digest, 'url': url, 'checked_at': retrieved, 'status': 'read', 'success': True})
            except Exception as exc:
                error = str(exc)[:600]
                seen[url] = None, error, archived
                notice_errors.append(error)
                if archived:
                    failed_hashes.append(archived)
                    rejected[archived] = {'id': archived, 'source_url': url, 'downloaded_at': retrieved,
                                          'status': 'extraction_failed', 'error': error, 'byte_size': len(fetched.body)}
                checks.append({'id': hashlib.sha256(url.encode()).hexdigest(), 'url': url,
                               'checked_at': now(), 'status': 'failed', 'success': False, 'error': error})
        notice['checked_at'] = now()
        if accepted:
            notice['document_ids'] = accepted
            notice['document_id'] = max(accepted, key=lambda key: documents[key]['published_at'])
        notice['status'] = ('extraction_failed' if failed_hashes else 'fetch_failed') if notice_errors else 'incorporated'
        if failed_hashes:
            notice['failed_document_id'] = failed_hashes[-1]
        elif not notice_errors:
            notice.pop('failed_document_id', None)
        if notice_errors:
            notice['error'] = '; '.join(notice_errors)
            errors.extend(notice_errors)
    state['documents'] = list(documents.values())
    state['catalog']['notices'] = notices
    state['catalog']['rejected_documents'] = list(rejected.values())
    state['catalog']['checks'] = checks
    state['catalog']['audit_at'] = attempt
    state['catalog']['audit_method'] = 'Captador oficial con validación estructural y archivo SHA-256; sin autenticación de firma electrónica.'
    vacancy_notices = [n for n in notices if n.get('kind') == 'vacancies']
    if vacancy_notices:
        latest = max(vacancy_notices, key=lambda n: n.get('date') or '')
        state['catalog']['latest_notice'] = dict(latest, pdf_url=next(iter(latest.get('pdf_urls', [])), None))
    complete = discovered['complete'] and not errors and all(c.get('success') for c in checks)
    status = 'completed' if complete else 'partial'
    state['freshness'].update(status=status, checked_scope='recent_rrhh_vacancy_notices')
    state['freshness'].pop('error', None)
    if complete:
        state['freshness']['last_success_at'] = now()
    if added:
        state['events'].insert(0, {'id': attempt, 'created_at': now(), 'kind': 'official_documents_added',
                                  'title': f'{len(added)} copias oficiales validadas e incorporadas',
                                  'details': {'document_ids': added}})
    state['events'] = state['events'][:200]
    store.publish(state)
    return {'status': status, 'added': added, 'errors': errors,
            'message': 'Comprobación completada para los avisos cubiertos.' if complete else 'Comprobación parcial. Se conservan los datos válidos.'}
