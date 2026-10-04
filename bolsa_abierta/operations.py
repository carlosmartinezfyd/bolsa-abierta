"""Bounded, metadata-only run evidence. Never persist command output or exceptions."""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import statistics
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_RUNS = 1024
RETENTION_DAYS = 30
PHASES = ('inventory', 'positions', 'vacancies', 'build')
STATUSES = ('running', 'success', 'failed', 'partial', 'pending_budget', 'skipped')
TRIGGERS = ('schedule', 'workflow_dispatch', 'worker_cron', 'push', 'local', 'unknown')


def timestamp(value=None):
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except (ValueError, OverflowError):
        return None


def _moment(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _seconds(start, end):
    if not start or not end:
        return None
    return max(0, (_moment(end) - _moment(start)).total_seconds())


def _number(value):
    return value if type(value) in (int, float) and 0 <= value < 1e12 else None


def _text(value, pattern):
    return value if isinstance(value, str) and re.fullmatch(pattern, value) else None


def _run(raw):
    phases = {}
    for name in PHASES:
        phase = raw.get('phases', {}).get(name, {}) if isinstance(raw.get('phases'), dict) else {}
        if not isinstance(phase, dict) or not phase:
            continue
        phases[name] = {
            'started_at': timestamp(phase.get('started_at')) if phase.get('started_at') else None,
            'ended_at': timestamp(phase.get('ended_at')) if phase.get('ended_at') else None,
            'elapsed_seconds': _number(phase.get('elapsed_seconds')),
            'status': phase.get('status') if phase.get('status') in STATUSES else 'failed',
            'exit_code': phase.get('exit_code') if type(phase.get('exit_code')) is int and -255 <= phase['exit_code'] <= 255 else None,
        }
    return {
        'run_id': _text(raw.get('run_id'), r'[a-zA-Z0-9:_-]{1,100}'),
        'code_sha': _text(raw.get('code_sha'), r'[a-fA-F0-9]{7,64}'),
        'trigger': raw.get('trigger') if raw.get('trigger') in TRIGGERS else 'unknown',
        'request_id': _text(raw.get('request_id'), r'[a-f0-9]{32}'),
        **{key: timestamp(raw.get(key)) if raw.get(key) else None for key in
           ('started_at', 'ended_at', 'scheduled_at', 'clock_received_at', 'dispatch_at')},
        'elapsed_seconds': _number(raw.get('elapsed_seconds')),
        'status': raw.get('status') if raw.get('status') in STATUSES else 'failed',
        'phases': phases,
    }


def _clean(state):
    state = state if isinstance(state, dict) else {}
    raw_trial = state.get('trial', {})
    raw_trial = raw_trial if isinstance(raw_trial, dict) else {}
    raw_retention = state.get('retention', {})
    raw_retention = raw_retention if isinstance(raw_retention, dict) else {}
    return {
        'version': 1,
        'trial': {'started_at': timestamp(raw_trial.get('started_at')) if raw_trial.get('started_at') else None,
                  'duration_days': 14, 'nominal_windows': 672},
        'retention': {'max_runs': MAX_RUNS, 'days': RETENTION_DAYS,
                      'discarded_runs': int(_number(raw_retention.get('discarded_runs')) or 0)},
        'runs': [_run(r) for r in state.get('runs', []) if isinstance(r, dict)]
                if isinstance(state.get('runs'), list) else [],
    }


def start_run(state, *, run_id, code_sha=None, trigger='local', now=None,
              scheduled_at=None, clock_received_at=None, dispatch_at=None, request_id=None):
    state = _clean(state)
    now = timestamp(now)
    if now is None:
        raise ValueError('invalid_time')
    run_id = _text(run_id, r'[a-zA-Z0-9:_-]{1,100}')
    if not run_id:
        raise ValueError('invalid_run_id')
    if not any(run['run_id'] == run_id for run in state['runs']):
        state['runs'].append(_run({'run_id': run_id, 'code_sha': code_sha, 'trigger': trigger,
            'started_at': now, 'status': 'running', 'scheduled_at': scheduled_at,
            'clock_received_at': clock_received_at, 'dispatch_at': dispatch_at, 'request_id': request_id}))
    if not state['trial']['started_at']:
        state['trial']['started_at'] = now
    cutoff = (datetime.fromisoformat(now.replace('Z', '+00:00')) - timedelta(days=RETENTION_DAYS)).isoformat().replace('+00:00', 'Z')
    kept = [run for run in state['runs'] if run['started_at'] and _moment(run['started_at']) >= _moment(cutoff)][-MAX_RUNS:]
    state['retention']['discarded_runs'] += len(state['runs']) - len(kept)
    state['runs'] = kept
    return state


def finish_run(state, run_id, *, status, now=None):
    if status not in ('success', 'failed', 'partial', 'skipped'):
        raise ValueError('invalid_status')
    state = _clean(state)
    for run in state['runs']:
        if run['run_id'] == run_id:
            run['ended_at'] = timestamp(now)
            run['elapsed_seconds'] = _seconds(run['started_at'], run['ended_at'])
            run['status'] = status
            break
    return state


def public_summary(state):
    """Recompute a strict whitelist; supplied summaries/notes/rows never pass through."""
    clean = _clean(state)
    runs = clean['runs'][-MAX_RUNS:]
    starts = sorted((r['started_at'] for r in runs if r['started_at']), key=_moment)
    intervals = [_seconds(a, b) for a, b in zip(starts, starts[1:])]
    scheduled = [r for r in runs if r['scheduled_at'] and r['started_at'] and r['trigger'] == 'worker_cron'
                 and _moment(r['scheduled_at']) <= _moment(r['started_at'])]
    lags = [_seconds(r['scheduled_at'], r['started_at']) for r in scheduled]
    trial_start = clean['trial']['started_at']
    latest = max((r['ended_at'] or r['started_at'] for r in runs if r['started_at']), key=_moment, default=None)
    elapsed = _seconds(trial_start, latest) or 0
    last = max(runs, key=lambda r: _moment(r['started_at']) if r['started_at'] else datetime.min.replace(tzinfo=timezone.utc), default=None)
    return {
        'version': 1,
        'run_counts': {status: sum(r['status'] == status for r in runs) for status in STATUSES},
        'phase_counts': {name: {status: sum(r['phases'].get(name, {}).get('status') == status for r in runs)
                                for status in STATUSES} for name in PHASES},
        'last_run': {key: last[key] for key in ('code_sha', 'trigger', 'started_at', 'ended_at', 'elapsed_seconds', 'status')} if last else None,
        'cadence': {'median_run_interval_seconds': statistics.median(intervals) if intervals else None,
                    'known_scheduled_runs': len(scheduled),
                    'median_scheduled_lag_seconds': statistics.median(lags) if lags else None,
                    'native_schedule_causal_time': 'unknown'},
        'trial': {**clean['trial'], 'status': 'not_started' if not trial_start else
                  ('evaluation_pending' if elapsed >= 14 * 86400 else 'collecting'),
                  'elapsed_nominal_windows': min(672, int(elapsed // 1800)),
                  'acceptance_met': None, 'source_age_pass_fraction': None,
                  'checker_cpu_p95_ms': None, 'budget_margin_fraction': None,
                  'resource_evidence': 'pending', 'source_cohort_evidence': 'pending'},
        'retention': clean['retention'],
    }


def gateway_status(state, operations):
    """Correlate one published request to its run and actual source-check interval."""
    freshness = state.get('freshness', {}) if isinstance(state, dict) else {}
    freshness = freshness if isinstance(freshness, dict) else {}
    runs = _clean(operations)['runs']
    last = max(runs, key=lambda r: _moment(r['started_at']) if r['started_at'] else datetime.min.replace(tzinfo=timezone.utc), default=None)
    request_id = _text(freshness.get('request_id'), r'[a-f0-9]{32}')
    attempt = timestamp(freshness.get('last_attempt_at')) if freshness.get('last_attempt_at') else None
    vacancy = last['phases'].get('vacancies', {}) if last else {}
    def inside(start, end):
        # Store.now rounds to seconds; wrapper timestamps retain milliseconds.
        return bool(start and end and attempt and _moment(start) <= _moment(end)
                    and _moment(start) - timedelta(seconds=1) <= _moment(attempt)
                    <= _moment(end) + timedelta(seconds=1))
    correlated = bool(last and request_id and request_id == last['request_id']
                      and inside(last['started_at'], last['ended_at'])
                      and inside(vacancy.get('started_at'), vacancy.get('ended_at')))
    complete = correlated and last['status'] == 'success' and all(last['phases'].get(name, {}).get('status') == 'success' for name in PHASES)
    status = freshness.get('status')
    status = status if status in ('completed', 'partial', 'failed') else 'failed'
    if status == 'completed' and not complete:
        status = 'partial'
    return {'freshness': {'request_id': request_id if correlated else None,
                          'status': status,
                          'last_attempt_at': attempt if correlated else None}}


def split_migration_indexes(source):
    """Keep eight populated B-tree creations out of additive empty/core DDL."""
    pattern = re.compile(r'CREATE INDEX IF NOT EXISTS (position_(rows|entries)_(version|number|scope|name)) ON (position_(?:rows|entries))\([^;]+\);')
    indexes = [{'name': match[1], 'table': match[4], 'sql': match[0]} for match in pattern.finditer(source)]
    if len(indexes) != 8 or len({index['name'] for index in indexes}) != 8:
        raise ValueError('unexpected_migration_index_plan')
    return pattern.sub('', source), indexes


def prepare_gateway_migration(execute, source, reservation_id, *, limit=70000, max_seconds=240):
    """Resume per-index DDL using sqlite_schema as durable progress, never delete rows."""
    core, indexes = split_migration_indexes(source)
    deadline = time.monotonic() + max_seconds
    def rows(sql):
        return [row for item in execute(sql) for row in item.get('results', [])]
    existing = {row['name'] for row in rows('SELECT name FROM sqlite_schema')}
    created = 0
    def outcome(status, reason):
        return {'status': status, 'reason': reason, 'created_indexes': created,
                'remaining_indexes': sum(index['name'] not in existing for index in indexes)}
    def reserve(name, units):
        if units > limit:
            return False
        rid = reservation_id + ':' + name
        accepted = rows(migration_reservation_sql(rid, units, limit))
        return any(row.get('id') == rid for row in accepted)
    required = set(re.findall(r'CREATE (?:VIRTUAL )?(?:TABLE|INDEX|TRIGGER|VIEW) IF NOT EXISTS ([a-z_]+)', core))
    if not required <= existing:
        count = rows('SELECT COUNT(*) AS count FROM position_versions')[0]['count'] if 'position_versions' in existing else 0
        other_indexes = re.findall(r'CREATE INDEX IF NOT EXISTS ([a-z_]+) ON ([a-z_]+)', core)
        extra = sum(int(rows('SELECT COUNT(*) AS count FROM ' + table)[0]['count'])
                    for name, table in other_indexes if name not in existing and table in existing)
        if not reserve('core', int(count) * 2 + extra + 100):
            return outcome('pending_budget', 'core_allowance')
        execute(core)
        execute(migration_settlement_sql(reservation_id + ':core'))
        existing = {row['name'] for row in rows('SELECT name FROM sqlite_schema')}
    for index in indexes:
        if index['name'] in existing:
            continue
        if time.monotonic() >= deadline:
            return outcome('pending', 'bounded_run')
        count = int(rows('SELECT COUNT(*) AS count FROM ' + index['table'])[0]['count'])
        if not reserve(index['name'], count + 100):
            return outcome('pending_budget', 'index_allowance')
        execute(index['sql'])
        execute(migration_settlement_sql(reservation_id + ':' + index['name']))
        existing.add(index['name'])
        created += 1
    return outcome('ready', 'complete')


def migration_reservation_sql(reservation_id, units, limit=70000):
    """One D1 batch reserves before DDL, retaining legacy and unresolved usage."""
    if not _text(reservation_id, r'ddl:[0-9]+:[0-9]+(?::[a-z0-9_]+)?') or type(units) is not int or type(limit) is not int or not 0 < units <= limit <= 70000:
        raise ValueError('invalid_migration_reservation')
    return f"""
INSERT INTO position_write_allocations(reservation_id,day,charged)
 SELECT 'legacy:'||day,day,writes FROM position_write_budget WHERE singleton=1 AND day<>'' AND writes>0
 ON CONFLICT(reservation_id,day) DO UPDATE SET charged=MAX(charged,excluded.charged);
INSERT OR IGNORE INTO position_write_reservations(id,day,reserved)
 SELECT '{reservation_id}',date('now'),{units}
 WHERE date('now')>=COALESCE((SELECT MAX(day) FROM position_write_allocations),'')
 AND (SELECT writes FROM position_write_usage)+{units}<={limit};
INSERT OR IGNORE INTO position_write_allocations(reservation_id,day,charged)
 SELECT id,day,reserved FROM position_write_reservations WHERE id='{reservation_id}';
SELECT r.id AS id,r.reserved AS reserved FROM position_write_reservations r
 JOIN position_write_reservation_leases l ON l.id=r.id
 WHERE r.id='{reservation_id}' AND r.reserved>={units} AND r.settled=0
 AND l.expires_at>unixepoch('now') AND r.day<=date('now');
"""


def migration_settlement_sql(reservation_id):
    """Keep the conservative estimate on both DB UTC days if DDL crosses midnight."""
    if not _text(reservation_id, r'ddl:[0-9]+:[0-9]+(?::[a-z0-9_]+)?'):
        raise ValueError('invalid_migration_reservation')
    return f"""
INSERT INTO position_write_allocations(reservation_id,day,charged)
 SELECT id,day,reserved FROM position_write_reservations WHERE id='{reservation_id}'
 UNION ALL SELECT r.id,
 CASE WHEN l.expires_at<=unixepoch('now') THEN date(l.expires_at,'unixepoch') ELSE date('now') END,r.reserved
 FROM position_write_reservations r JOIN position_write_reservation_leases l ON l.id=r.id
 WHERE r.id='{reservation_id}' AND r.day<CASE WHEN l.expires_at<=unixepoch('now') THEN date(l.expires_at,'unixepoch') ELSE date('now') END
 UNION ALL SELECT r.id,date('now'),12 FROM position_write_reservations r JOIN position_write_reservation_leases l ON l.id=r.id
 WHERE r.id='{reservation_id}' AND date('now')>date(l.expires_at,'unixepoch')
 ON CONFLICT(reservation_id,day) DO UPDATE SET charged=MAX(charged,excluded.charged);
UPDATE position_write_reservations SET settled=1 WHERE id='{reservation_id}';
"""


def validated_archive_paths(directory, *, key=None):
    """Allow only complete authenticated bundles; plaintext is never returned."""
    from .private_archive import (archive_key, _decode_bundle, _validated_files,
                                  MAX_FILES, MAX_TOTAL_BYTES)
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError('invalid_archive_directory')
    if not directory.exists():
        return []
    paths = sorted(directory.glob('*.baenc'))
    if len(paths) > 100 or sum(path.stat().st_size for path in paths) > 512 * 1024 * 1024:
        raise ValueError('archive_bundle_budget')
    secret = archive_key(key)
    originals = {}
    for path in paths:
        value, _ = _decode_bundle(path, secret)
        files, _ = _validated_files(value)
        for digest, body in files:
            originals[digest] = len(body)
        if len(originals) > MAX_FILES or sum(originals.values()) > MAX_TOTAL_BYTES:
            raise ValueError('archive_original_budget')
    return paths


def _freshness_status(path):
    """Read only the aggregate check result; no nominal JSON enters metrics."""
    try:
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5) as db:
            row = db.execute("SELECT json_extract(payload, '$.freshness.status') FROM state WHERE id=1").fetchone()
        status = row[0] if row else None
        return {'completed': 'success', 'partial': 'partial', 'failed': 'failed'}.get(status, 'failed')
    except (sqlite3.Error, TypeError, ValueError):
        return 'failed'


def _read(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('invalid_operations_state') from None


def _write(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix='.operations-', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(state, stream, ensure_ascii=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--run-id', default=None)
    subs = parser.add_subparsers(dest='action', required=True)
    subs.add_parser('start')
    run_parser = subs.add_parser('run')
    run_parser.add_argument('--phase', choices=PHASES, required=True)
    run_parser.add_argument('--freshness-db', type=Path, help='Read-only vacancy check status after the process exits')
    run_parser.add_argument('command', nargs=argparse.REMAINDER)
    finish_parser = subs.add_parser('finish')
    finish_parser.add_argument('--status', choices=('success', 'failed', 'partial', 'skipped'), required=True)
    subs.add_parser('summary')
    args = parser.parse_args(argv)
    run_id = args.run_id or (os.environ.get('GITHUB_RUN_ID', '') + ':' + os.environ.get('GITHUB_RUN_ATTEMPT', '1'))
    if run_id.startswith(':'):
        run_id = 'local-' + uuid.uuid4().hex
    try:
        state = _read(args.state)
        if args.action == 'summary':
            print(json.dumps(public_summary(state), sort_keys=True))
            return 0
        state = start_run(state, run_id=run_id, code_sha=os.environ.get('GITHUB_SHA'),
            trigger=os.environ.get('OPERATIONS_TRIGGER') or os.environ.get('GITHUB_EVENT_NAME', 'local'),
            request_id=os.environ.get('REQUEST_ID'), scheduled_at=os.environ.get('SCHEDULED_TIME'),
            clock_received_at=os.environ.get('CLOCK_RECEIVED_AT'), dispatch_at=os.environ.get('DISPATCH_AT'))
        if args.action == 'finish':
            state = finish_run(state, run_id, status=args.status)
        _write(args.state, state)
        if args.action != 'run':
            return 0
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        if not command:
            return 2
        run = next(r for r in state['runs'] if r['run_id'] == run_id)
        phase = {'started_at': timestamp(), 'ended_at': None, 'elapsed_seconds': None,
                 'status': 'running', 'exit_code': None}
        run['phases'][args.phase] = phase
        _write(args.state, state)
        started = time.monotonic()
        try:
            result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            code = result.returncode
        except OSError:
            code = 127
        status = 'success' if code == 0 else ('pending_budget' if args.phase == 'positions' and code == 2 else ('partial' if args.phase == 'positions' and code == 3 else 'failed'))
        if code == 0 and args.phase == 'vacancies' and args.freshness_db:
            status = _freshness_status(args.freshness_db)
        phase.update(ended_at=timestamp(), elapsed_seconds=round(time.monotonic() - started, 3),
                     status=status, exit_code=code)
        _write(args.state, state)
        return code if code >= 0 else 128 - code
    except (ValueError, OSError):
        print('operations_state_error', file=__import__('sys').stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
