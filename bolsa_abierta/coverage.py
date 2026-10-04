"""Small public operational summaries; never export the nominal inventory."""
from collections import Counter
from datetime import datetime
import re


STATES = frozenset(('discovered', 'unavailable', 'changed', 'pending_review',
    'incorporated', 'not_applicable', 'skipped', 'partial', 'completed',
    'failed', 'verified', 'pending_budget', 'never_checked', 'pending', 'degraded', 'checked'))
KINDS = frozenset(('award', 'baseline', 'correction', 'supplement', 'provisional',
    'vacancies', 'opening', 'admission', 'procedure', 'closed_procedure',
    'reactivation', 'cessation', 'habilitation', 'maestros_roster',
    'optan_observation', 'unclassified'))


def _stamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value if parsed.utcoffset() is not None else None
    except ValueError:
        return None


def _code(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value) else None


def _count(value):
    return value if type(value) is int and 0 <= value <= 10_000_000 else 0


def _scope(item):
    scope_course = item.get('course')
    if not isinstance(scope_course, str) or not re.fullmatch(r'(?:\d{4}[-/]\d{4}|unknown)', scope_course):
        scope_course = None
    result = {'course': scope_course, 'scope_complete': item.get('scope_complete') is True,
              'history_complete': item.get('history_complete') is True}
    for key in ('traversal_complete', 'downloads_complete', 'verification_complete'):
        if key in item:
            result[key] = item[key] is True
    for key in ('source_id', 'family', 'body'):
        if value := _code(item.get(key)):
            result[key] = value
    if isinstance(item.get('source_ids'), list):
        result['source_ids'] = [s for s in map(_code, item['source_ids']) if s][:100]
    if item.get('status') in STATES:
        result['status'] = item['status']
    for key in ('pages', 'pending_pages', 'pending_details', 'document_count',
                'pending_documents', 'failed_documents', 'skipped_documents', 'unreviewed_documents'):
        if key in item:
            result[key] = _count(item[key])
    for key in ('attempted_at', 'checked_at', 'downloaded_at'):
        result[key] = _stamp(item.get(key))
    return result


def inventory_summary(inventory):
    course = inventory.get('course')
    if not isinstance(course, str) or not re.fullmatch(r'\d{4}-\d{4}', course):
        course = None
    documents = inventory.get('documents', [])
    states = Counter(d.get('status') if d.get('status') in STATES else 'pending' for d in documents)
    kinds = Counter(d.get('kind') if d.get('kind') in KINDS else 'unclassified' for d in documents)
    coverage = inventory.get('coverage', {})
    if not isinstance(coverage, dict):
        coverage = {}
    sources = coverage.get('sources', [{**s, 'source_id': s.get('id')} for s in inventory.get('sources', [])])
    return {'schema_version': 1, 'course': course,
        'attempted_at': _stamp(inventory.get('attempted_at')),
        'checked_at': _stamp(inventory.get('checked_at')),
        'index_complete': inventory.get('index_complete') is True,
        'downloads_complete': inventory.get('downloads_complete') is True,
        'review_complete': inventory.get('review_complete') is True,
        'document_count': len(documents), 'announcement_count': len(inventory.get('announcements', [])),
        'status_counts': dict(sorted(states.items())), 'kinds': dict(sorted(kinds.items())),
        'coverage': {'sources': [_scope(s) for s in sources[:100]],
                     'families': [_scope(s) for s in coverage.get('families', [])[:100]]},
        'queue_counts': {k: len(v) for k, v in inventory.get('work_queues', {}).items()
                         if k in ('recent', 'historical', 'undated') and isinstance(v, list)}}


def position_summary(status):
    result = {'status': status.get('status') if status.get('status') in STATES else 'never_checked'}
    for key in ('attempted_at', 'checked_at', 'resume_after'):
        result[key] = _stamp(status.get(key))
    for key in ('active_version', 'staged_version'):
        value = status.get(key)
        if isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value):
            result[key] = value
    for key in ('record_count', 'pending_documents', 'verified_documents',
                'origin_verified_documents', 'origin_failed_documents', 'cached_documents'):
        if key in status:
            result[key] = _count(status[key])
    if 'origin_check_complete' in status:
        result['origin_check_complete'] = status['origin_check_complete'] is True
    if status.get('cache_status') in ('unconfigured', 'ready', 'failed'):
        result['cache_status'] = status['cache_status']
    if code := _code(status.get('error_code')):
        result['error_code'] = code
    return result
