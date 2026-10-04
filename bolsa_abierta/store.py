"""Durable publication state and content-addressed evidence; no network access."""
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def compare(current, previous):
    """Observable quantity changes only; absence is not an adjudication result."""
    fields = ('center_code', 'function_code', 'cupo', 'itinerant', 'jornada')
    groups = []
    for doc in (previous, current):
        table = defaultdict(list)
        for row in (doc or {}).get('rows', []):
            table[tuple(row[f] for f in fields)].append(row)
        groups.append(table)
    before, after = groups
    result = []
    for key in sorted(before.keys() | after.keys()):
        old = sum(r['quantity'] for r in before[key])
        new = sum(r['quantity'] for r in after[key])
        if old == new:
            continue
        result.append({'id': hashlib.sha256(repr(key).encode()).hexdigest()[:24],
                       'kind': 'appeared' if not old else 'disappeared' if not new else 'quantity_changed',
                       'before': old, 'after': new, 'delta': new - old,
                       'row': (after[key] or before[key])[0],
                       'before_rows': len(before[key]), 'after_rows': len(after[key])})
    return result


def select_documents(state):
    docs = state['documents']
    docs.sort(key=lambda d: (datetime.fromisoformat(d['published_at']).timestamp(),
                            d.get('retrieved_at', d.get('imported_at', ''))), reverse=True)
    approved = [d for d in docs if d.get('status') == 'approved']
    current = approved[0] if approved else None
    previous = next((d for d in approved[1:] if d['process_id'] != current['process_id']), None) if current else None
    state['current_id'] = current['id'] if current else None
    state['previous_id'] = previous['id'] if previous else None
    state['changes'] = compare(current, previous) if previous else []


class Store:
    def __init__(self, root, seed_path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'artifacts').mkdir(exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL, payload TEXT NOT NULL)')
            if not db.execute('SELECT 1 FROM state').fetchone():
                seed = json.loads(Path(seed_path).read_text(encoding='utf-8'))
                seed['version'] = '0.2.0'
                seed.setdefault('freshness', {'last_attempt_at': None, 'last_success_at': None, 'status': 'never_checked'})
                for doc in seed['documents']:
                    doc.pop('artifact_url', None)
                    bundled = Path(seed_path).resolve().parent.parent / 'documents' / (doc['id'] + '.pdf')
                    if bundled.exists():
                        data = bundled.read_bytes()
                        if hashlib.sha256(data).hexdigest() != doc['id']:
                            raise ValueError('Bundled evidence hash mismatch')
                        self.archive(data)
                        doc['evidence_status'] = 'archived'
                        continue
                    doc['evidence_status'] = 'original_unavailable'
                    doc['provenance_label'] = 'Datos históricos del prototipo; PDF original no incluido. No contrastados por este captador.'
                    note = 'El archivo original de esta copia histórica no está disponible para verificar sus filas.'
                    if note not in doc['warnings']:
                        doc['warnings'].append(note)
                seed['catalog'].setdefault('notices', [])
                seed['catalog']['coverage'] = 'Avisos públicos de RRHH: vacantes sin cubrir de Secundaria y otros cuerpos. Sin cobertura completa de adjudicaciones o listas personales.'
                db.execute('INSERT OR IGNORE INTO state VALUES (1, ?)', (json.dumps(seed, ensure_ascii=False),))
        self.segregate_unpublished()

    def private_artifact(self, digest):
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid private artifact hash')
        return self.root / 'private-artifacts' / (digest + '.pdf')

    def quarantine(self, data):
        digest = hashlib.sha256(data).hexdigest()
        path = self.private_artifact(digest)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(path, data)
        path.chmod(0o600)
        return digest

    def segregate_unpublished(self):
        """Unreviewed bytes must not enter the public durable vacancy archive."""
        with self.connect() as db:
            state = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        approved = {d['id'] for d in state['documents']
                    if d.get('status') == 'approved' and d.get('evidence_status') == 'archived'}
        for path in (self.root / 'artifacts').glob('*.pdf'):
            if path.stem not in approved:
                body = path.read_bytes()
                if hashlib.sha256(body).hexdigest() != path.stem:
                    raise ValueError('Unreviewed legacy evidence hash mismatch')
                self.quarantine(body)
                path.unlink()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / 'state.sqlite3', timeout=30)
        db.execute('PRAGMA busy_timeout=30000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def state(self, mode='server'):
        with self.connect() as db:
            state = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        state['mode'] = mode
        state['capabilities'].update(source_check='available' if mode == 'server' else 'snapshot_only', manual_import=False)
        for doc in state['documents']:
            doc.pop('artifact_url', None)
            if doc.get('evidence_status') == 'archived':
                if not self.artifact(doc['id']).exists():
                    raise ValueError('Published evidence is missing from the archive')
                doc['artifact_url'] = f"/api/documents/{doc['id']}.pdf" if mode == 'server' else f"documents/{doc['id']}.pdf"
        return state

    def publish(self, state):
        # All accepted new documents must have been archived before this transaction.
        for doc in state['documents']:
            if doc.get('evidence_status') == 'archived':
                self.verified_artifact(doc['id'])
        select_documents(state)
        state['generated_at'] = now()
        with self.connect() as db:
            db.execute('UPDATE state SET payload=? WHERE id=1', (json.dumps(state, ensure_ascii=False),))

    def artifact(self, digest):
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid artifact hash')
        return self.root / 'artifacts' / (digest + '.pdf')

    def verified_artifact(self, digest):
        path = self.artifact(digest)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Archived evidence hash mismatch')
        return path

    def archive(self, data):
        digest = hashlib.sha256(data).hexdigest()
        path = self.artifact(digest)
        if path.exists():
            self.verified_artifact(digest)
        else:
            atomic_write(path, data)
        return digest

    def claim_job(self, cooldown=60, lease=900):
        timestamp = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id, created, updated, payload FROM jobs ORDER BY created DESC LIMIT 1').fetchone()
            if row:
                job = json.loads(row[3])
                if job['status'] in ('queued', 'running'):
                    if timestamp - row[2] < lease:
                        return job, False
                    job.update(status='failed', message='Comprobación interrumpida; se permite reintentar.')
                    db.execute('UPDATE jobs SET payload=?, updated=? WHERE id=?', (json.dumps(job), timestamp, row[0]))
                elif timestamp - row[2] < cooldown:
                    return job, False
            job = {'id': uuid.uuid4().hex, 'status': 'queued', 'created_at': now()}
            db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?)', (job['id'], timestamp, timestamp, json.dumps(job)))
            db.execute('DELETE FROM jobs WHERE created < ?', (timestamp - 7 * 86400,))
            return job, True

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM jobs WHERE id=?', (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def finish_job(self, job_id, fields):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise ValueError('Unknown job')
            job = json.loads(row[0])
            job.update(fields)
            job['updated_at'] = now()
            db.execute('UPDATE jobs SET payload=?, updated=? WHERE id=?', (json.dumps(job, ensure_ascii=False), time.time(), job_id))
        return job


def public_state(state, byte_budget=8 * 1024 * 1024):
    """Bound browser payload; retain full durable history and PDF links separately."""
    state = json.loads(json.dumps(state, ensure_ascii=False))
    protected = {state['current_id'], state['previous_id']}
    loaded = {d['id'] for d in state['documents']}
    state['history_documents'] = [d for d in state.get('history_documents', []) if d['id'] not in loaded]
    history_note = 'Las copias más antiguas no se cargan en esta vista. Se conserva su historial y los PDF disponibles; algunos favoritos antiguos pueden no mostrarse.'
    state['history_window'] = {'omitted_documents': len(state['history_documents']),
                               'note': history_note if state['history_documents'] else ''}
    notices = state['catalog'].get('notices', [])
    state['catalog']['notices'] = sorted(notices, key=lambda n: n.get('date') or '', reverse=True)[:300]
    state['catalog']['omitted_notices'] = max(0, len(notices) - 300)
    while len(json.dumps(state, ensure_ascii=False, separators=(',', ':')).encode()) > byte_budget:
        old = next((d for d in reversed(state['documents']) if d['id'] not in protected), None)
        if old is None:
            raise ValueError('Current comparison exceeds the public snapshot budget; partitioning required')
        state['documents'].remove(old)
        state['history_documents'].append({k: old[k] for k in ('id', 'title', 'published_at', 'row_count', 'places', 'status', 'artifact_url', 'source_url') if k in old})
        state['history_window'].update(omitted_documents=len(state['history_documents']),
                                       note=history_note)
    return state


def export_static(store, output_dir, *, inventory=None, positions=None, operations=None):
    output = Path(output_dir)
    state = store.state(mode='static')
    from .coverage import inventory_summary, position_summary
    if inventory is not None:
        state['source_inventory'] = inventory_summary(inventory)
    if positions is not None:
        state['position_status'] = position_summary(positions)
    if operations is not None:
        from .operations import public_summary
        state['operations'] = public_summary(operations)
    # Publish immutable evidence first; the single state pointer is replaced last.
    for doc in state['documents']:
        if 'artifact_url' in doc:
            source = store.verified_artifact(doc['id'])
            atomic_write(output / doc['artifact_url'], source.read_bytes())
    state = public_state(state)
    atomic_write(output / 'data/state.json', json.dumps(state, ensure_ascii=False, separators=(',', ':')).encode())
    return state


def build_site(store, output_dir, source_dir, **summaries):
    output, source = Path(output_dir), Path(source_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name in ('index.html', 'LICENSE', 'NOTICE', '.nojekyll'):
        shutil.copyfile(source / name, output / name)
    shutil.copytree(source / 'web', output / 'web', dirs_exist_ok=True)
    return export_static(store, output, **summaries)
