"""Exact, reviewed 2026 resolutions. No general-purpose interpretation of orders."""

from collections import Counter
import hashlib
from io import BytesIO
import re

import pdfplumber

from .positions import ROW, normalize


def parse_amendment(text, content_id):
    if '2026-2027' not in text:
        raise ValueError('Unexpected amendment course')
    rows = []
    if content_id == '208249':
        section = text.split('PRIMERO.-', 1)[1].split('SEGUNDO.-', 1)[0]
        specialty = block = None
        for line in section.splitlines():
            if match := re.fullmatch(r'Especialidad: (\d{3}) .+', line):
                specialty, block = '0590' + match[1], None
            elif match := re.fullmatch(r'Lista: (\d+) .+', line):
                block = match[1]
            elif match := ROW.fullmatch(line):
                if not specialty or not block:
                    raise ValueError('Amendment row has no context')
                number, name, _ = match.groups()
                rows.append(dict(specialty=specialty, block=block, list_number=number, name=name,
                                 page=1, source_id=content_id))
        if [(r['specialty'], r['block'], r['list_number']) for r in rows] != [
                ('0590108', '69', '25000340'), ('0590006', '69', '25006830')]:
            raise ValueError('Supplement differs from reviewed admissions')
    elif content_id == '208379':
        section = ' '.join(text.split('DISPONGO', 1)[1].split())
        match = re.search(r'\(594428\).*?número de lista (25000080), al aspirante (.+?), con DNI', section)
        if not match:
            raise ValueError('Correction differs from reviewed admission')
        # The order supplies specialty and number. The reviewed baseline brackets
        # that missing number between 25000070 and 25000090 in block 69.
        rows.append(dict(specialty='0594428', block='69', list_number=match[1], name=normalize(match[2]),
                         page=1, source_id=content_id))
    else:
        raise ValueError('Amendment requires a reviewed parser')
    return rows


def read_amendment(path, source):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != source['sha256']:
        raise ValueError('Amendment bytes differ from the reviewed original')
    with BytesIO(data) as stream, pdfplumber.open(stream) as pdf:
        if len(pdf.pages) != source['pages']:
            raise ValueError('Amendment page count changed')
        text = pdf.pages[0].filter(lambda obj: obj.get('upright', True) and obj.get('x0', 100) >= 38).extract_text() or ''
        return parse_amendment(text, source['content_id'])


def apply_insertions(rows, changes):
    result = [{**row, 'source_id': row.get('source_id', '208095')} for row in rows]
    for change in changes:
        group = [(i, r) for i, r in enumerate(result) if (r['specialty'], r['block']) == (change['specialty'], change['block'])]
        if not group or any(r['list_number'] == change['list_number'] for _, r in group):
            raise ValueError('Missing block or admission already present')
        if change['source_id'] == '208379' and not {'25000070', '25000090'} <= {r['list_number'] for _, r in group}:
            raise ValueError('Correction is not bracketed by the reviewed baseline rows')
        index = next((i for i, r in group if int(r['list_number']) > int(change['list_number'])), group[-1][0] + 1)
        template = group[0][1]
        identity = '|'.join([change['specialty'], change['block'], change['list_number'], normalize(change['name'])])
        result.insert(index, {**template, **change, 'id': hashlib.sha256(identity.encode()).hexdigest()[:32],
                              'search_name': normalize(change['name'])})
    ranks = Counter()
    for row in result:
        ranks[row['specialty']] += 1
        row['rank'] = ranks[row['specialty']]
    return result
