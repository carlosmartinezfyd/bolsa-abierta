"""Reviewed optan evidence, without inferred administrative or personal facts.

The authority has not confirmed what this document does to list membership or
availability. This adapter validates the complete observation source and emits
only non-nominal document counts. It must not feed the person/award row store.
"""
from collections import Counter
from datetime import date
import hashlib
from io import BytesIO
from pathlib import Path
import re

import pdfplumber

from .position_documents import CODE, MONTHS, _column


OBSERVATION_PARSER_REVISION = 'optan-v1-document-evidence-only'
TITLE = 'Listados De Adjudicatarios Que Optan En Secundaria'
COLUMNS = ((29,79,'Nº Lista'), (79,134,'DNI'), (134,224,'Primer Apellido'),
           (224,314,'Segundo Apellido'), (314,404,'Nombre'), (404,454,'Cuerpo'), (454,820,'Función'))


def parse_observation_pages(pages, metadata):
    """Fail closed on unknown layout; never return identity or availability."""
    if (metadata.get('kind') != 'optan_observation' or metadata.get('semantic_status') != 'unconfirmed'
            or not pages or len(pages) != metadata.get('pages')):
        raise ValueError('Unknown or incomplete optan observation document')
    counts = metadata.get('page_row_counts')
    if (not isinstance(counts,list) or len(counts) != len(pages)
            or any(type(count) is not int or count < 0 for count in counts)):
        raise ValueError('Missing reviewed observation page counts')
    expected = metadata.get('specialties')
    if not isinstance(expected,list) or not expected:
        raise ValueError('Missing reviewed observation specialty counts')
    specialties = {s['code']:s for s in expected}
    if (len(specialties) != len(expected) or any(not CODE.fullmatch(s['code']) for s in expected)
            or any(s['code'][:4] != s['body_code'] for s in expected)):
        raise ValueError('Invalid observation specialties')
    published = date.fromisoformat(metadata['published_at'])
    prefix = f'Convocatoria: Adjudicación semanal {published:%d/%m/%Y}. Proceso {metadata["process_id"]} - '
    actual = Counter()
    first_header = None
    for page_number,page in enumerate(pages,1):
        text = page.extract_text() or ''
        lines = text.splitlines()
        if (page.width != 842 or page.height != 595 or len(lines) < 3 or lines[0] != TITLE
                or not lines[1].startswith(prefix) or lines[-1] != f'Página {page_number} de {len(pages)}'):
            raise ValueError('Unexpected observation heading or pagination')
        if first_header is None: first_header = lines[1]
        if lines[1] != first_header:
            raise ValueError('Observation pages belong to different revisions')
        listed = re.search(r' - Listado a (\d{1,2}) de (\w+) de (\d{4}), a las \d{2}:\d{2}$', lines[1])
        if (not listed or int(listed[1]) != published.day or listed[2].lower() != MONTHS[published.month-1]
                or int(listed[3]) != published.year):
            raise ValueError('Observation publication date differs from header')
        if page_number == len(pages) and ('Murcia, a ' not in text or
                'LA D.G. DE RECURSOS HUMANOS, PLANIFICACIÓN EDUCATIVA E INNOVACIÓN' not in text):
            raise ValueError('Missing signed end of observation document')
        words = page.extract_words(use_text_flow=True)
        anchors = [w for w in words if w['x0'] == 29 and w['top'] > 100
                   and re.fullmatch(r'\d{7,8}',w['text'])]
        signatures = re.findall(r'^\s*(\d{7,8})\s+\*+\d+\*+',text,re.MULTILINE)
        if len(anchors) != counts[page_number-1] or Counter(w['text'] for w in anchors) != Counter(signatures):
            raise ValueError('Incomplete observation rows')
        # This table draws individual cell rectangles, unlike the award layout.
        row_cells = [r for r in page.rects if r['top'] >= 104 and r['x0'] >= 29 and r['x1'] <= 820]
        if len(row_cells) != len(anchors)*len(COLUMNS):
            raise ValueError('Unexpected observation drawn cell count')
        for anchor in anchors:
            bounds = [r for r in row_cells if r['x0'] == 29 and r['x1'] == 79
                      and r['top'] <= anchor['top'] and r['bottom'] >= anchor['bottom']]
            if len(bounds) != 1:
                raise ValueError('Missing or ambiguous observation row boundary')
            bound = bounds[0]
            heads = [w for w in words if w['text'] in ('Nº','Nº Lista') and w['top'] < bound['top'] and w['x0'] == 29]
            if not heads: raise ValueError('Missing observation table header')
            y = max(w['top'] for w in heads)
            heading = [w for w in words if abs(w['top']-y) < 1]
            for left,right,label in COLUMNS:
                if _column(heading,left,right) != label:
                    raise ValueError('Unrecognized observation column layout')
                matching = [r for r in row_cells if r['x0'] == left and r['x1'] == right
                            and r['top'] == bound['top'] and r['bottom'] == bound['bottom']]
                if len(matching) != 1:
                    raise ValueError('Missing or ambiguous observation drawn cell')
            cells = [w for w in words if bound['top'] <= w['top'] < bound['bottom']]
            number = _column(cells,29,79)
            first,second,given = (_column(cells,134,224),_column(cells,224,314),_column(cells,314,404))
            body = _column(cells,404,454)
            function = _column(cells,454,820).split(' ',1)
            if (number != anchor['text'] or not first or not given or
                    any(c.isdigit() or c == '*' for c in first+second+given) or len(function) != 2):
                raise ValueError('Unrecognized observation identity/function cells')
            code,name = function
            if code not in specialties or specialties[code]['body_code'] != body or specialties[code]['name'] != name:
                raise ValueError('Conflicting observation body/function')
            actual[code] += 1
    if sum(counts) != metadata.get('row_count') or actual != Counter({s['code']:s['count'] for s in expected}):
        raise ValueError('Observation totals differ from reviewed source')
    return dict(kind='optan_observation',source_id=str(metadata['content_id']),pages=len(pages),
                page_row_counts=counts.copy(),row_count=sum(counts),semantic_status='unconfirmed',
                specialty_counts=dict(actual))


def read_observation_document(path, metadata):
    """Validate exact reviewed bytes and return non-nominal document evidence."""
    data = Path(path).read_bytes()
    if not data.startswith(b'%PDF-') or hashlib.sha256(data).hexdigest() != metadata.get('sha256'):
        raise ValueError('Observation document bytes differ from reviewed source')
    with BytesIO(data) as stream, pdfplumber.open(stream) as document:
        return parse_observation_pages(document.pages,metadata)
