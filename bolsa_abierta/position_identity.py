"""Scoped membership keys, distinct from a global identity for a person."""
import hashlib
import json
import re


def membership_id(row, course):
    scope, block, number = row.get('specialty'), row.get('block'), row.get('list_number')
    if (not isinstance(course, str) or not re.fullmatch(r'\d{4}-\d{4}', course)
            or not isinstance(scope, str) or not re.fullmatch(r'(?:0597|\d{4}[A-Z0-9]\d{2})', scope)
            or not isinstance(block, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,20}', block)
            or not isinstance(number, str) or not re.fullmatch(r'\d{7,8}', number)):
        raise ValueError('A membership needs its reviewed course, list scope, block and number')
    namespace = ('murcia', course, row.get('roster_id', 'secondary-lists'), scope, block, number)
    return hashlib.sha256(json.dumps(namespace, separators=(',', ':')).encode()).hexdigest()[:32]


def annotate_memberships(rows, course):
    result, seen = [], set()
    for original in rows:
        row = dict(original)
        if row.get('record_type', 'list') == 'list':
            identity = membership_id(row, course)
            if identity in seen:
                raise ValueError('Duplicate scoped membership requires review')
            seen.add(identity)
            row['membership_id'] = identity
        # Existing record IDs remain usable by saved explicit selections. This
        # key does not link an award, another course, or a similarly named person.
        result.append(row)
    return result
