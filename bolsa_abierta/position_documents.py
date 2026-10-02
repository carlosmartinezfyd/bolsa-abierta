"""Reviewed document adapters. An award is evidence of an award, never a rank."""
from collections import Counter
from datetime import date, datetime
import hashlib
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

import pdfplumber

from .positions import normalize


TITLE = 'Listado Definitivo De Adjudicatarios Con Plaza En Secundaria'
CODE = re.compile(r'\d{4}[A-Z0-9]\d{2}')
MONTHS = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
          'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')
HEADERS = ((35, 'Pri.'), (60, 'Nº Lista'), (100, 'DNI'), (155, 'Apellido1'),
           (235, 'Apellido2'), (315, 'Nombre'), (395, 'Centro'), (535, 'Municipio'),
           (615, 'Función'), (665, 'Jornada'), (715, 'Perfil'), (765, 'V/S'), (795, 'Obs.'))


def _text(words):
    # Round the baseline because independently drawn cells differ by fractions
    # of a point. Sorting each column preserves wrapped surnames and given names.
    return ' '.join(w['text'] for w in sorted(words, key=lambda w: (round(w['top']), w['x0'])))


def _column(words, left, right):
    return _text([w for w in words if left <= w['x0'] < right])


def _context(words, marker, top):
    markers = [w for w in words if w['text'] == marker and w['top'] < top and w['x0'] == 40]
    if not markers:
        raise ValueError('Award row without its body/function heading')
    last = max(markers, key=lambda w: w['top'])
    return _text([w for w in words if abs(w['top']-last['top']) < 1 and w['x0'] >= 90])


def _headers(words, top):
    heads = [w for w in words if w['text'] == 'Pri.' and w['top'] < top]
    if not heads:
        raise ValueError('Missing award column headers')
    y = max(w['top'] for w in heads)
    line = [w for w in words if abs(w['top']-y) < 1]
    for index, (left, expected) in enumerate(HEADERS):
        right = HEADERS[index+1][0] if index+1 < len(HEADERS) else 825
        if _column(line, left, right) != expected:
            raise ValueError('Unrecognized award column layout')


def parse_award_pages(pages, metadata):
    """Parse the reviewed landscape definitive-awards layout, fail closed.

    Structural and manifest checks are independent: every list-number anchor
    must belong to exactly one drawn row; page and specialty counts must agree
    with the reviewed source. No masked IDs, priority, or substitution details
    enter the search dataset.
    """
    if metadata.get('kind') != 'award' or len(pages) != metadata.get('pages'):
        raise ValueError('Unknown or incomplete award document')
    counts = metadata.get('page_row_counts')
    if not isinstance(counts, list) or len(counts) != len(pages) or counts[-1] != 0:
        raise ValueError('Missing reviewed award page counts')
    expected = metadata.get('specialties')
    if not isinstance(expected, list) or not expected:
        raise ValueError('Missing reviewed award specialty counts')
    specialties = {s['code']: s for s in expected}
    if len(specialties) != len(expected) or any(not CODE.fullmatch(s['code']) for s in expected):
        raise ValueError('Invalid award specialties')
    published = date.fromisoformat(metadata['published_at'])
    prefix = (f'Convocatoria: Adjudicación semanal {published:%d/%m/%Y}. '
              f'Proceso {metadata["process_id"]}. Fecha de incorporación: ')
    rows, seen, actual_counts = [], set(), Counter()
    for page_number, page in enumerate(pages, 1):
        text = page.extract_text() or ''
        lines = text.splitlines()
        if (page.width != 842 or page.height != 595 or not lines or lines[0] != TITLE
                or len(lines) < 3 or not lines[1].startswith(prefix)
                or lines[-1] != f'Página {page_number} de {len(pages)}'):
            raise ValueError(f'Unexpected award heading or pagination on page {page_number}')
        if lines[1] != (pages[0].extract_text() or '').splitlines()[1]:
            raise ValueError('Award pages belong to different publication revisions')
        listed_date = re.search(r' - Listado a (\d{1,2}) de (\w+) de (\d{4}), a las \d{2}:\d{2}$', lines[1])
        if (not listed_date or int(listed_date[1]) != published.day
                or listed_date[2].lower() != MONTHS[published.month-1]
                or int(listed_date[3]) != published.year):
            raise ValueError('Award publication date does not match its header')
        if page_number == len(pages):
            if 'EL CONSEJERO DE EDUCACIÓN Y FORMACIÓN PROFESIONAL' not in text or 'Murcia, a ' not in text:
                raise ValueError('Missing signed end of award document')
        words = page.extract_words(use_text_flow=True)
        anchors = sorted([w for w in words if 59 <= w['x0'] < 61 and w['top'] > 80
                          and re.fullmatch(r'\d{7,8}', w['text'])], key=lambda w: w['top'])
        # Text row signatures are a second extraction path, independent of the
        # list-column geometry, so moving/loss of anchors cannot hide records.
        signatures = re.findall(r'^\d{1,3}\s+(\d{7,8})\s+\*+\d+\*+', text, re.MULTILINE)
        if (len(anchors) != counts[page_number-1]
                or Counter(w['text'] for w in anchors) != Counter(signatures)):
            raise ValueError(f'Incomplete award rows on page {page_number}')
        row_rectangles = [r for r in page.rects if r['x0'] == 35 and r['x1'] == 824
                          and r['bottom']-r['top'] >= 20]
        if len(row_rectangles) != len(anchors):
            raise ValueError('Unrecognized or empty drawn award row')
        for anchor in anchors:
            _headers(words, anchor['top'])
            rectangles = [r for r in page.rects if r['x0'] == 35 and r['x1'] == 824
                          and r['bottom']-r['top'] >= 20 and r['top'] <= anchor['top']
                          and r['bottom'] >= anchor['bottom']]
            if len(rectangles) != 1:
                raise ValueError('Missing or ambiguous award row boundary')
            rectangle = rectangles[0]
            cells = [w for w in words if rectangle['top'] <= w['top'] < rectangle['bottom']
                     and w['x0'] >= 35]
            # Observations are drawn below the identity/destination cells; they
            # can contain other people's masked IDs and are deliberately omitted.
            observations = [w['top'] for w in cells
                            if w['text'].startswith('OBSERVACIONES:') or w['text'] == 'Sustituye']
            if observations:
                cells = [w for w in cells if w['top'] < min(observations)]
            body = _context(words, 'CUERPO:', anchor['top'])
            function = _context(words, 'FUNCIÓN:', anchor['top'])
            body_code, body_name = body.split(' ', 1)
            code, specialty_name = function.split(' ', 1)
            assigned_function = _column(cells, 615, 665)
            assigned_group = metadata.get('assigned_function_groups', {}).get(assigned_function, assigned_function)
            if (code not in specialties or code[:4] != body_code
                    or assigned_group != code
                    or specialties[code]['name'] != specialty_name
                    or specialties[code]['body'] != body_name):
                raise ValueError('Conflicting award body/function')
            number = _column(cells, 60, 100)
            surname1, surname2, given = (_column(cells, 155, 235), _column(cells, 235, 315), _column(cells, 315, 395))
            center, municipality = _column(cells, 395, 535), _column(cells, 535, 615)
            workload = _column(cells, 665, 715)
            if (number != anchor['text'] or not all((surname1, given, municipality))
                    or not re.fullmatch(r'\d{8} .+', center)
                    or not re.fullmatch(r'(Completa|Tiempo Parcial \d{1,2} horas)', workload)
                    or _column(cells, 765, 795) not in ('VP', 'VS')):
                raise ValueError('Unrecognized award row cells')
            name = f'{surname1} {surname2}, {given}'.replace(' ,', ',')
            if any(c.isdigit() or c == '*' for c in name):
                raise ValueError('Unrecognized award name')
            identity = '|'.join(('award', str(metadata['content_id']), code, number, normalize(name)))
            row_id = hashlib.sha256(identity.encode()).hexdigest()[:32]
            if row_id in seen:
                raise ValueError('Duplicate award identity requires review')
            seen.add(row_id)
            actual_counts[code] += 1
            rows.append(dict(id=row_id, record_type='award', source_id=str(metadata['content_id']),
                             specialty=code, specialty_name=specialty_name, body_name=body_name,
                             name=name, search_name=normalize(name), list_number=number,
                             rank=None, block='', block_name='', page=page_number,
                             destination=f'{center[9:]} · {municipality}', workload=workload,
                             assigned_function=assigned_function))
    if (len(rows) != metadata.get('row_count')
            or actual_counts != Counter({s['code']: s['count'] for s in expected})):
        raise ValueError('Award totals differ from reviewed source')
    return rows


def read_document(path, metadata):
    """Verify the reviewed bytes before extraction; never parse a challenge page."""
    data = Path(path).read_bytes()
    if not data.startswith(b'%PDF-') or hashlib.sha256(data).hexdigest() != metadata.get('sha256'):
        raise ValueError('Document bytes differ from reviewed source')
    with pdfplumber.open(path) as document:
        return parse_award_pages(document.pages, metadata)


def scan_document(path, source_url, checked_at, *, assigned_function_groups=None):
    """Validate a complete new awards PDF before admitting its facts to a version.

    The caller supplies the actual successful download time. A new format, a
    provisional document, or an unreviewed assigned-function mapping raises
    ValueError and must stay pending in the inventory.
    """
    parsed = urlsplit(source_url)
    ids = parse_qs(parsed.query).get('IDCONTENIDO', [])
    if (parsed.scheme != 'https' or parsed.netloc != 'www.carm.es' or parsed.path != '/web/descarga'
            or len(ids) != 1 or not ids[0].isdigit() or parsed.fragment):
        raise ValueError('Awards require an identified official document URL')
    try:
        checked = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
    except (ValueError, AttributeError) as exc:
        raise ValueError('Missing actual source verification time') from exc
    if checked.utcoffset() is None:
        raise ValueError('Source verification time requires a timezone')
    data = Path(path).read_bytes()
    if not data.startswith(b'%PDF-'):
        raise ValueError('Source is not a PDF document')
    with pdfplumber.open(path) as document:
        pages = document.pages
        if not 2 <= len(pages) <= 1000:
            raise ValueError('Unexpected award document size')
        lines = (pages[0].extract_text() or '').splitlines()
        header = re.match(r'^Convocatoria: Adjudicación semanal (\d{2}/\d{2}/\d{4})\. Proceso (\d+)\.',
                          lines[1] if len(lines) > 1 else '')
        if not header:
            raise ValueError('Unknown award document heading')
        published = datetime.strptime(header[1], '%d/%m/%Y').date().isoformat()
        metadata = dict(kind='award', content_id=ids[0], source_url=source_url,
                        sha256=hashlib.sha256(data).hexdigest(), published_at=published,
                        checked_at=checked_at, process_id=header[2], pages=len(pages),
                        page_row_counts=[], assigned_function_groups=assigned_function_groups or {})
        specialties, counts = {}, Counter()
        for page in pages:
            text = page.extract_text() or ''
            metadata['page_row_counts'].append(len(re.findall(r'^\d{1,3}\s+\d{7,8}\s+\*+\d+\*+', text, re.MULTILINE)))
            words = page.extract_words(use_text_flow=True)
            for anchor in (w for w in words if 59 <= w['x0'] < 61 and w['top'] > 80
                           and re.fullmatch(r'\d{7,8}', w['text'])):
                body = _context(words, 'CUERPO:', anchor['top']).split(' ', 1)
                function = _context(words, 'FUNCIÓN:', anchor['top']).split(' ', 1)
                if len(body) != 2 or len(function) != 2:
                    raise ValueError('Incomplete award section')
                specialty = dict(code=function[0], name=function[1], body=body[1])
                if function[0] in specialties and specialties[function[0]] != specialty:
                    raise ValueError('Conflicting repeated award section')
                specialties[function[0]] = specialty
                counts[function[0]] += 1
        metadata['row_count'] = sum(metadata['page_row_counts'])
        metadata['specialties'] = [dict(**s, count=counts[code]) for code, s in sorted(specialties.items())]
        rows = parse_award_pages(pages, metadata)
    return dict(metadata=metadata, rows=rows)
