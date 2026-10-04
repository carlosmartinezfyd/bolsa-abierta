"""Reviewed 2026 Maestros unique list and its complete September correction.

Memberships, habilitations and evidence have separate scopes. Numbers and
names from explanatory annexes never become additional list memberships.
"""

from collections import Counter
from contextlib import ExitStack
from datetime import date, datetime
import hashlib
from io import BytesIO
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

import pdfplumber

from .positions import normalize


MAESTROS_PARSER_REVISION = 'maestros-unique-list-v1'
BODY = '0597'
BODY_NAME = 'CUERPO DE MAESTROS'
GROUP_NAME = 'Lista única de Maestros'
RANK_SCOPE = 'maestros_unique_list'
HABILITATIONS = {
    '031': 'Educación infantil', '032': 'Lengua extranjera: inglés',
    '033': 'Lengua extranjera: francés', '034': 'Educación física',
    '035': 'Música', '036': 'Pedagogía terapéutica',
    '037': 'Audición y lenguaje', '038': 'Educación primaria',
    '039': 'Lengua extranjera: alemán',
}
TITLE = ('Listado definitivo de Interinos del Cuerpo de Maestros a los que alude '
         'el artículo 96 de la Orden de 21 de enero de 2026, para el curso '
         '2026-2027. Anexo {annex} Lista de aspirantes a la que alude el artículo 96.2 {letter})')
CORRECTION_TITLE = ('CORRECCIÓN DE ERRORES A LA RESOLUCIÓN DE 28 DE JULIO DE 2026 '
                    'DE LA DIRECCIÓN GENERAL DE RECURSOS HUMANOS, PLANIFICACIÓN '
                    'EDUCATIVA E INNOVACIÓN POR LA QUE SE PUBLICA LA LISTA DEFINITIVA '
                    'DE ASPIRANTES A DESEMPEÑAR PUESTOS DOCENTES EN RÉGIMEN DE '
                    'INTERINIDAD EN EL CUERPO DE MAESTROS, PARA EL CURSO 2026-2027')
NUMBER = re.compile(r'26\d{6}')
MASKED = r'(?:\*{3}\d{4}\*{2}|\*{4}\d{4}\*)'
ROW_SIGNATURE = re.compile(r'^\s*(\d{8})\s+' + MASKED + r'\s+', re.MULTILINE)


def _squash(text):
    return ' '.join(text.split())


def _text(words):
    return ' '.join(w['text'] for w in sorted(words, key=lambda w: (round(w['top']), w['x0'])))


def _column(words, left, right):
    return _text([w for w in words if left <= w['x0'] < right])


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _count_map(value, allowed):
    if (not isinstance(value, dict) or not set(value) <= set(allowed)
            or any(not _integer(count) for count in value.values())):
        raise ValueError('Missing or invalid reviewed Maestros counts')
    return Counter(value)


def _validate_source(source):
    parsed = urlsplit(source.get('source_url', ''))
    if (parsed.scheme != 'https' or parsed.netloc != 'www.carm.es'
            or parsed.path != '/web/descarga' or parsed.fragment
            or parse_qs(parsed.query).get('IDCONTENIDO') != [str(source.get('content_id'))]
            or not re.fullmatch(r'\d+', str(source.get('content_id', '')))
            or not re.fullmatch(r'[a-f0-9]{64}', source.get('sha256', ''))):
        raise ValueError('Maestros source requires reviewed official provenance')
    try:
        date.fromisoformat(source['published_at'])
        date.fromisoformat(source['signed_at'])
        checked = datetime.fromisoformat(source['checked_at'].replace('Z', '+00:00'))
        if checked.utcoffset() is None:
            raise ValueError('No verification timezone')
    except (ValueError, KeyError, AttributeError, TypeError) as exc:
        raise ValueError('Maestros source requires dated verification') from exc


def _validate_manifest(metadata, page_count, amendments):
    _validate_source(metadata)
    if (metadata.get('kind') != 'maestros_roster' or metadata.get('course') != '2026-2027'
            or metadata.get('rank_scope') != RANK_SCOPE
            or metadata.get('parser_revision') != MAESTROS_PARSER_REVISION
            or not _integer(metadata.get('pages'), 1) or metadata['pages'] != page_count
            or page_count > 1200 or not _integer(metadata.get('row_count'), 1)
            or not _integer(metadata.get('baseline_row_count'), 1)):
        raise ValueError('Unknown or incomplete reviewed Maestros roster')
    expected_group = dict(code=BODY, name=GROUP_NAME, body=BODY_NAME, count=metadata['row_count'])
    if metadata.get('specialties') != [expected_group]:
        raise ValueError('Maestros is one body-wide list, with no specialty ordinals')
    counts = metadata.get('page_row_counts')
    if (not isinstance(counts, list) or len(counts) != page_count
            or any(not _integer(count) for count in counts)
            or sum(counts) != metadata['baseline_row_count']):
        raise ValueError('Missing or inconsistent reviewed Maestros page counts')
    _count_map(metadata.get('baseline_habilitation_counts'), HABILITATIONS)
    _count_map(metadata.get('habilitation_counts'), HABILITATIONS)
    _count_map(metadata.get('block_row_counts'), ('I', 'II'))
    if not _integer(metadata.get('unknown_habilitation_rows')):
        raise ValueError('Missing reviewed Maestros unknown habilitation count')
    if metadata.get('amendments') != [source for _pages, source in amendments]:
        raise ValueError('Missing or different reviewed Maestros amendments')
    sections = metadata.get('sections')
    expected = [('resolution', None), ('roster', 'I'), ('roster', 'II'),
                ('supporting', 'III'), ('supporting', 'IV'), ('supporting', 'V')]
    if (not isinstance(sections, list) or len(sections) != len(expected)
            or [(s.get('kind'), s.get('annex')) for s in sections] != expected):
        raise ValueError('Missing reviewed Maestros annex boundaries')
    next_page = 1
    assignment = []
    for section in sections:
        if (section.get('start_page') != next_page or not _integer(section.get('pages'), 1)
                or next_page + section['pages'] - 1 > page_count):
            raise ValueError('Overlapping, missing or truncated Maestros annex')
        if section['kind'] == 'roster' and (
                section.get('block') != section['annex']
                or not _integer(section.get('row_count'), 1) or section['pages'] < 2):
            raise ValueError('Invalid Maestros block manifest')
        assignment.extend([(section, local) for local in range(1, section['pages'] + 1)])
        next_page += section['pages']
    if next_page != page_count + 1:
        raise ValueError('Unreviewed pages after Maestros annexes')
    return assignment


def _clean_page(page, *, roster=False):
    # Landscape tables begin at x=14; the portrait signature strip is outside
    # the x=38 body. Never apply that portrait crop to roster tables.
    return page if roster else page.filter(
        lambda obj: obj.get('upright', True) and obj.get('x0', 100) >= 38)


def _check_other_page(page, text, section, local_page, page_number):
    if not text.strip() or not 594 <= page.width <= 596 or not 840 <= page.height <= 843:
        raise ValueError(f'Unexpected Maestros supporting page {page_number}')
    if ROW_SIGNATURE.search(text):
        raise ValueError(f'Unexpected list rows outside ranked annexes on page {page_number}')
    lines = text.splitlines()
    flat = _squash(text)
    if section['kind'] == 'resolution':
        if lines[-1] != f'Página {local_page}':
            raise ValueError(f'Non-consecutive Maestros resolution page {page_number}')
        if local_page == 1 and not all(marker in re.sub(r'\s*-\s*', '-', flat)
                                       for marker in ('LISTA DEFINITIVA', 'CUERPO DE MAESTROS', '2026-2027')):
            raise ValueError('Unknown Maestros definitive resolution')
        if local_page == section['pages'] and not all(
                marker in flat for marker in ('LA DIRECTORA GENERAL DE RECURSOS HUMANOS',
                                               'Documento firmado electrónicamente')):
            raise ValueError('Missing signed end of Maestros resolution')
        return
    annex = section['annex']
    if local_page == 1 and not re.search(r'\bANEXO ' + annex + r'\b', flat):
        raise ValueError(f'Missing Maestros annex {annex} boundary')
    if annex == 'III' and 'APELLIDOS Y NOMBRE' not in flat:
        raise ValueError(f'Unrecognized Maestros rejected-claims page {page_number}')
    if annex == 'IV' and ('DE LOS DATOS PUBLICADOS EN LA FASE DE EXPOSICIÓN PÚBLICA' not in flat
                           or lines[-1] != str(local_page)):
        raise ValueError(f'Unrecognized Maestros explanatory correction page {page_number}')
    if annex == 'V' and not all(marker in flat for marker in ('55 AÑOS', 'BLOQUE I', 'CUERPO')):
        raise ValueError('Missing final Maestros explanatory annex')


def _identity(course, block, number):
    namespace = '|'.join(('list', course, BODY, block, number))
    return hashlib.sha256(namespace.encode()).hexdigest()[:32]


def _safe_name(value):
    name = _squash(value)
    if not re.fullmatch(r'[^,\d*]+,\s*[^,\d*]+', name):
        raise ValueError('Unrecognized Maestros name cells')
    return name


def _membership(metadata, number, name, block, codes, source_id, page):
    name = _safe_name(name)
    return dict(id=_identity(metadata['course'], block, number), record_type='list',
                roster_id=str(metadata['content_id']), source_id=source_id,
                specialty=BODY, specialty_name=GROUP_NAME, body_name=BODY_NAME,
                rank_scope=RANK_SCOPE, block=block, block_name=f'Bloque {block}',
                list_number=number, name=name, search_name=normalize(name), rank=None, page=page,
                habilitations=[dict(code=code, name=HABILITATIONS[code]) for code in codes],
                habilitations_status='published' if codes else 'not_stated')


def _roster_page(page, text, section, local_page, page_number, metadata):
    annex = section['annex']
    title = TITLE.format(annex=annex, letter='a' if annex == 'I' else 'b')
    footer = re.fullmatch(r'Página (\d+) de\s*(\d+)', text.splitlines()[-1] if text else '')
    if (page.width != 842 or page.height != 595 or title not in _squash(text)
            or not footer or (int(footer[1]), int(footer[2])) != (local_page, section['pages'])):
        raise ValueError(f'Unexpected Maestros heading or pagination on page {page_number}')
    expected = metadata['page_row_counts'][page_number - 1]
    signatures = ROW_SIGNATURE.findall(text)
    if local_page == 1:
        if (expected or signatures or f'ANEXO {annex}' not in text
                or 'CÓDIGOS DE ESPECIALIDADES ACREDITADAS' not in text
                or any(f'{code} - {name}.' not in text for code, name in HABILITATIONS.items())):
            raise ValueError(f'Missing reviewed Maestros code legend on page {page_number}')
        return []
    words = page.extract_words()
    shift, left, name_left = (0, 17, 108) if annex == 'I' else (44, 14, 104)
    edges = [x + shift for x in (303, 329, 355, 381, 407, 433, 459, 484, 510, 535)]
    for code, x in zip(HABILITATIONS, (309.33, 335.33, 361.33, 387.33, 413.33,
                                     439.33, 465.33, 490.33, 516.33)):
        matches = [w for w in words if abs(w['x0'] - x - shift) < .1
                   and abs(w['top'] - 134.126) < .1 and w['text'] == code]
        if len(matches) != 1:
            raise ValueError(f'Unrecognized Maestros habilitation columns on page {page_number}')
    header_words = [w for w in words if abs(w['top'] - 115.626) < 1]
    if (_column(header_words, left, left + 45) != 'NLISTA'
            or _column(header_words, left + 45, name_left) != 'DNI'
            or _column(header_words, name_left, edges[0]) != 'Apellidos y Nombre'):
        raise ValueError(f'Unrecognized Maestros identity columns on page {page_number}')
    required = 'Mayor Calificación Oposición Superada' if annex == 'I' else 'Calificación Oposición Actual'
    if not all(token in text for token in required.split()):
        raise ValueError(f'Unrecognized Maestros block scoring layout on page {page_number}')
    anchors = sorted([w for w in words if w['x0'] < 60 and w['top'] > 145
                      and re.fullmatch(r'\d{8}', w['text'])], key=lambda w: w['top'])
    if (len(anchors) != expected or [w['text'] for w in anchors] != signatures
            or len(anchors) > 15):
        raise ValueError(f'Incomplete Maestros rows on page {page_number}')
    rows = []
    covered = set()
    for index, anchor in enumerate(anchors):
        top, bottom = 144 + 26 * index, 169 + 26 * index
        if (not NUMBER.fullmatch(anchor['text']) or abs(anchor['x0'] - left) > .1
                or abs(anchor['top'] - (153.11 + 26 * index)) > .1):
            raise ValueError(f'Unrecognized Maestros row position on page {page_number}')
        vertical = [line for line in page.lines if abs(line['x0'] - left) < .1
                    and abs(line['x1'] - left) < .1 and abs(line['top'] - top) < .1
                    and abs(line['bottom'] - bottom) < .1]
        horizontal = [line for line in page.lines if abs(line['x0'] - left - 1) < .1
                      and abs(line['x1'] - left - 44) < .1
                      and abs(line['top'] - bottom) < .1 and abs(line['bottom'] - bottom) < .1]
        if len(vertical) != 1 or len(horizontal) != 1:
            raise ValueError(f'Missing drawn Maestros row boundary on page {page_number}')
        cells = [w for w in words if top <= w['top'] < bottom]
        covered.update(id(w) for w in cells)
        if (_column(cells, left, left + 45) != anchor['text']
                or not re.fullmatch(MASKED, _column(cells, left + 45, name_left))):
            raise ValueError(f'Unrecognized Maestros number or identity cell on page {page_number}')
        name = _column(cells, name_left, edges[0])
        codes = []
        for code, a, b in zip(HABILITATIONS, edges, edges[1:]):
            value = _column(cells, a, b)
            if value not in ('', 'X'):
                raise ValueError(f'Unknown Maestros habilitation mark on page {page_number}')
            if value:
                codes.append(code)
        score_words = [w for w in cells if edges[-1] <= w['x0'] < 826]
        if (len(score_words) != (8 if annex == 'I' else 7)
                or any(not re.fullmatch(r'\d+,\d{4}', w['text']) for w in score_words)
                or any(w['x0'] < left or w['x0'] >= 826 for w in cells)):
            raise ValueError(f'Incomplete Maestros row cells on page {page_number}')
        rows.append(_membership(metadata, anchor['text'], name, annex, codes,
                                str(metadata['content_id']), page_number))
    if any(144 <= w['top'] < 533 and id(w) not in covered for w in words):
        raise ValueError(f'Unassigned Maestros table text on page {page_number}')
    return rows


def _parse_correction(pages, source):
    _validate_source(source)
    if (source.get('kind') != 'maestros_correction' or str(source.get('content_id')) != '208782'
            or source.get('pages') != 4 or len(pages) != 4
            or source.get('page_inclusion_counts') != [0, 1, 3, 0]):
        raise ValueError('Unknown or incomplete reviewed Maestros correction')
    operations = source.get('operations')
    if (not isinstance(operations, list) or len(operations) != 6
            or [op.get('kind') for op in operations] != ['include'] * 4 + ['add_habilitation'] * 2):
        raise ValueError('Unreviewed Maestros correction operations')
    texts, inclusion_rows = [], []
    for page_number, page in enumerate(pages, 1):
        try:
            body = _clean_page(page)
            text = body.extract_text() or ''
            texts.append(text)
            if (not 594 <= page.width <= 596 or not 840 <= page.height <= 843
                    or not text or text.splitlines()[-1] != str(page_number)):
                raise ValueError(f'Unexpected Maestros correction page {page_number}')
            if page_number == 1 and CORRECTION_TITLE not in _squash(text):
                raise ValueError('Unknown Maestros correction title')
            numbers = re.findall(r'^(26\d{6})\s+', text, re.MULTILINE)
            anchors = [w['text'] for w in body.extract_words()
                       if 141 <= w['x0'] <= 143 and NUMBER.fullmatch(w['text'])]
            if (len(numbers) != source['page_inclusion_counts'][page_number - 1]
                    or Counter(anchors) != Counter(numbers)):
                raise ValueError(f'Incomplete Maestros correction table on page {page_number}')
            if page_number not in (2, 3):
                continue
            identities = list(re.finditer(r'^' + MASKED + r'\s+([^\n]+)$', text, re.MULTILINE))
            if len(identities) != len(numbers):
                raise ValueError('Incomplete Maestros inclusion identity rows')
            for i, identity in enumerate(identities):
                end = identities[i + 1].start() if i + 1 < len(identities) else len(text)
                table = text[identity.end():end]
                row = re.findall(r'^(26\d{6})\s+([^\n]+)$', table, re.MULTILINE)
                if len(row) != 1 or not all(marker in table for marker in ('Nº LISTA', 'Experiencia', 'Puntuación')):
                    raise ValueError('Unrecognized Maestros inclusion table')
                codes = None
                if 'Especialidades' in table:
                    code = re.match(r'(0\d{2})\s+', row[0][1])
                    if not code or code[1] not in HABILITATIONS:
                        raise ValueError('Unrecognized Maestros inclusion habilitation')
                    codes = [code[1]]
                inclusion_rows.append(dict(kind='include', block='I', list_number=row[0][0],
                                           page=page_number, name=_safe_name(identity[1]),
                                           habilitation_codes=codes))
        finally:
            page.close()
    if ('RESUELVO:' not in texts[1] or 'PRIMERO.- Incluir' not in _squash(texts[1])
            or 'Anexo I (bloque I):' not in texts[1]
            or 'LA DIRECTORA GENERAL DE RECURSOS HUMANOS' not in texts[3]
            or 'Firmado electrónicamente' not in texts[3]):
        raise ValueError('Missing complete Maestros correction clauses')
    changes = []
    for row, operation in zip(inclusion_rows, operations[:4]):
        if any(row[key] != operation.get(key) for key in ('kind', 'block', 'list_number', 'page', 'habilitation_codes')):
            raise ValueError('Maestros inclusion differs from reviewed correction')
        changes.append({**operation, 'name': row['name']})
    if len(inclusion_rows) != 4:
        raise ValueError('Missing Maestros correction inclusions')
    flat = _squash(texts[3])
    clauses = re.findall(r'(SEGUNDO|TERCERO)\.-\s*(.*?)(?=TERCERO\.-|LA DIRECTORA|$)', flat)
    if [clause for clause, _text_ in clauses] != ['SEGUNDO', 'TERCERO']:
        raise ValueError('Missing Maestros habilitation correction clauses')
    for (clause, text), operation in zip(clauses, operations[4:]):
        person = re.search(MASKED + r'\s+(.+?)\s*,?\s+en la solicitud', text)
        qualification = re.search(r'la especialidad (597\d{3})\s+(.+?)(?:\.|$)', text)
        if (not person or not qualification or 'Anexo II (bloque II)' not in text
                or operation.get('clause') != clause or operation.get('block') != 'II'
                or operation.get('page') != 4 or operation.get('published_code') != qualification[1]
                or operation.get('code') != qualification[1][-3:]
                or operation.get('code') not in HABILITATIONS
                or normalize(qualification[2]) != normalize(HABILITATIONS[operation['code']])):
            raise ValueError('Maestros habilitation differs from reviewed correction')
        changes.append({**operation, 'name': _safe_name(person[1].rstrip(','))})
    return changes


def _apply_correction(rows, changes, source, metadata):
    result = [dict(row, habilitations=list(row['habilitations'])) for row in rows]
    baseline = {(row['block'], row['list_number']): row for row in rows}
    group = [row['list_number'] for row in rows if row['block'] == 'I']
    if len({(change['kind'], change.get('list_number')) for change in changes}) != len(changes):
        raise ValueError('Duplicate Maestros correction operations')
    for change in changes:
        number = change.get('list_number', '')
        if not NUMBER.fullmatch(number):
            raise ValueError('Invalid reviewed Maestros correction membership')
        name_matches = [row for row in result if normalize(row['name']) == normalize(change['name'])]
        if change['kind'] == 'include':
            neighbors = change.get('neighbors')
            if (any(row['list_number'] == number for row in result) or name_matches
                    or not isinstance(neighbors, list) or len(neighbors) != 2
                    or neighbors[0] not in group or neighbors[1] not in group
                    or group.index(neighbors[1]) != group.index(neighbors[0]) + 1
                    or not int(neighbors[0]) < int(number) < int(neighbors[1])):
                raise ValueError('Ambiguous or unbracketed Maestros inclusion requires review')
            row = _membership(metadata, number, change['name'], 'I', change['habilitation_codes'] or [],
                              str(source['content_id']), change['page'])
            row['amendment_relation'] = dict(kind='inclusion', previous_id=None, previous_list_number=None)
            result.append(row)
        elif change['kind'] == 'add_habilitation':
            old = baseline.get((change['block'], number))
            if (not old or old['page'] != change.get('baseline_page') or len(name_matches) != 1
                    or name_matches[0]['id'] != old['id']
                    or normalize(old['name']) != normalize(change['name'])):
                raise ValueError('Ambiguous Maestros habilitation membership relation')
            row = next(row for row in result if row['id'] == old['id'])
            if change['code'] in {h['code'] for h in row['habilitations']}:
                raise ValueError('Maestros habilitation correction is already present')
            row['habilitations'] = sorted(row['habilitations'] + [dict(code=change['code'],
                                                                      name=HABILITATIONS[change['code']])],
                                          key=lambda h: h['code'])
            row.update(source_id=str(source['content_id']), page=change['page'], baseline_page=old['page'],
                       habilitations_status='published',
                       amendment_relation=dict(kind='habilitation_added', previous_id=old['id'],
                                               previous_list_number=old['list_number'],
                                               baseline_source_id=str(metadata['content_id']),
                                               baseline_page=old['page'], code=change['code'],
                                               published_code=change['published_code']))
        else:
            raise ValueError('Unsupported Maestros correction operation')
    return result


def parse_maestros_pages(pages, metadata, *, amendments=()):
    """Validate every page and return safe memberships plus explicit totals.

    ``amendments`` holds ``(pages, source_metadata)`` pairs in the exact reviewed
    manifest order. Page objects are closed as they are read to bound memory.
    All failure messages contain structural facts only, never nominal values.
    """
    amendments = list(amendments)
    assignment = _validate_manifest(metadata, len(pages), amendments)
    rows, block_counts, resolution = [], Counter(), []
    seen_numbers, seen_ids = set(), set()
    for page_number, (page, (section, local_page)) in enumerate(zip(pages, assignment), 1):
        try:
            body = _clean_page(page, roster=section['kind'] == 'roster')
            text = body.extract_text() or ''
            if section['kind'] != 'roster':
                _check_other_page(page, text, section, local_page, page_number)
                if metadata['page_row_counts'][page_number - 1]:
                    raise ValueError('Supporting Maestros annex counted as membership')
                if section['kind'] == 'resolution':
                    resolution.append(text)
                continue
            parsed = _roster_page(page, text, section, local_page, page_number, metadata)
            for row in parsed:
                if (row['list_number'] in seen_numbers or row['id'] in seen_ids
                        or rows and int(row['list_number']) <= int(rows[-1]['list_number'])):
                    raise ValueError(f'Duplicate or unordered Maestros membership on page {page_number}')
                seen_numbers.add(row['list_number'])
                seen_ids.add(row['id'])
                block_counts[row['block']] += 1
                rows.append(row)
        finally:
            page.close()
    resolution_text = _squash(' '.join(resolution))
    if not all(re.search(marker, resolution_text, re.IGNORECASE)
               for marker in (r'RESUELVO:', r'Anexo I\b', r'bloque I\b', r'Anexo II\b', r'bloque II\b')):
        raise ValueError('Missing Maestros resolution of both ranked annexes')
    expected_blocks = Counter({section['block']: section['row_count'] for section in metadata['sections']
                               if section['kind'] == 'roster'})
    baseline_habs = Counter(h['code'] for row in rows for h in row['habilitations'])
    if (len(rows) != metadata['baseline_row_count'] or block_counts != expected_blocks
            or baseline_habs != Counter(metadata['baseline_habilitation_counts'])):
        raise ValueError('Maestros baseline totals differ from independent review')
    amendment_counts = Counter()
    for amendment_pages, source in amendments:
        changes = _parse_correction(amendment_pages, source)
        rows = _apply_correction(rows, changes, source, metadata)
        amendment_counts.update(change['kind'] for change in changes)
    rows.sort(key=lambda row: (0 if row['block'] == 'I' else 1, int(row['list_number'])))
    for rank, row in enumerate(rows, 1):
        row['rank'] = rank
    counts = Counter(row['block'] for row in rows)
    habs = Counter(h['code'] for row in rows for h in row['habilitations'])
    unknown = sum(row['habilitations_status'] == 'not_stated' for row in rows)
    if (len(rows) != metadata['row_count'] or len({r['id'] for r in rows}) != len(rows)
            or len({r['list_number'] for r in rows}) != len(rows)
            or counts != Counter(metadata['block_row_counts'])
            or habs != Counter(metadata['habilitation_counts'])
            or unknown != metadata['unknown_habilitation_rows']):
        raise ValueError('Consolidated Maestros totals differ from reviewed source')
    totals = dict(row_count=len(rows), baseline_row_count=metadata['baseline_row_count'],
                  block_row_counts=dict(counts), habilitation_count=sum(habs.values()),
                  habilitation_counts=dict(sorted(habs.items())), unknown_habilitation_rows=unknown,
                  amendment_counts=dict(amendment_counts), pages=metadata['pages'],
                  amendment_pages=sum(source['pages'] for _pages, source in amendments))
    return dict(rows=rows, totals=totals)


def read_maestros(path, metadata, *, amendments=()):
    """Check every original's bytes before opening any PDF, then fail atomically.

    The result is ``{'rows': [...], 'totals': {...}}``. Originals and temporary
    extraction data stay local; the adapter does not write or log names. Each
    reader consumes the retained verified bytes, even if a path is replaced.
    """
    amendments = list(amendments)
    verified = []
    for source_path, source in [(path, metadata), *amendments]:
        data = Path(source_path).read_bytes()
        if (not data.startswith(b'%PDF-')
                or hashlib.sha256(data).hexdigest() != source.get('sha256')
                or 'bytes' in source and len(data) != source['bytes']):
            raise ValueError('Maestros document bytes differ from reviewed source')
        verified.append((data, source))
    with ExitStack() as stack:
        documents = []
        for data, source in verified:
            stream = stack.enter_context(BytesIO(data))
            document = stack.enter_context(pdfplumber.open(stream))
            documents.append((document, source))
        amendment_documents = [(document.pages, source) for document, source in documents[1:]]
        return parse_maestros_pages(documents[0][0].pages, metadata, amendments=amendment_documents)
