"""Strict parsing of the dated Murcia interino roster; never active availability."""

import hashlib
import re
import unicodedata
from collections import Counter

import pdfplumber

TITLE = 'RELACIÓN DEFINITIVA DEL PERSONAL INTERINO DE SECUNDARIA Y OTROS CUERPOS PARA EL'
ROW = re.compile(r'(\d{7,8}) (?:\*{3}\d{4}\*{2}|\*{4}\d{4}\*) (.+, .+) (\d+\.\d{4})')


def normalize(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', value).upper()
                           if not unicodedata.combining(c)).split())


def parse_pages(pages):
    """Count the admitted rows in document order, without retaining masked DNI.

    The published list number is an identifier, not an ordinal. It may repeat in
    different blocks. We require the end annex and consecutive printed pages so
    truncated downloads and unrecognized rows cannot produce a partial ranking.
    """
    rows, ranks, previous, seen = [], Counter(), {}, set()
    ended = False
    for index, text in enumerate(pages):
        if index == 0:
            continue  # signed resolution cover
        if 'RELACIÓN DEFINITIVA DEL PERSONAL INTERINO' in text and 'EXCLUIDO' in text:
            ended = True
            break
        if TITLE not in text or 'CURSO 2026/2027' not in text:
            raise ValueError(f'Unexpected roster heading on PDF page {index + 1}')
        lines = text.splitlines()
        if not lines or lines[-1] != f'Página {index}':
            raise ValueError(f'Non-consecutive pagination on PDF page {index + 1}')
        body = specialty = block = None
        for line in lines:
            m = re.fullmatch(r'Cuerpo: (\d{4}) (.+)', line)
            if m:
                body = m.groups()
                specialty = block = None
                continue
            m = re.fullmatch(r'Especialidad: (\d{3}) (.+)', line)
            if m:
                specialty = m.groups()
                block = None
                continue
            m = re.fullmatch(r'Lista: (\d{1,3}) (.+)', line)
            if m:
                block = m.groups()
                continue
            m = ROW.fullmatch(line)
            if m:
                if not all((body, specialty, block)):
                    raise ValueError(f'Row without full context on PDF page {index + 1}')
                number, name, _points = m.groups()
                code = body[0] + specialty[0]
                group = (code, block[0])
                identity = (*group, number)
                if identity in seen or int(number) <= previous.get(group, -1):
                    raise ValueError(f'Duplicate or unordered row on PDF page {index + 1}')
                seen.add(identity)
                previous[group] = int(number)
                ranks[code] += 1
                row_id = hashlib.sha256(('|'.join(identity) + '|' + normalize(name)).encode()).hexdigest()[:32]
                rows.append(dict(id=row_id, specialty=code, specialty_name=specialty[1],
                                 body_name=body[1], block=block[0], block_name=block[1],
                                 list_number=number, name=name, search_name=normalize(name),
                                 rank=ranks[code], page=index + 1))
                continue
            if line in ('Región de Murcia', 'Consejería de Educación y Formación Profesional',
                        TITLE, 'CURSO 2026/2027', 'Nº Lista DNI Apellidos, Nombre Puntos', f'Página {index}'):
                continue
            raise ValueError(f'Unrecognized text on PDF page {index + 1}')
    if not ended or not rows:
        raise ValueError('Incomplete admitted roster')
    return rows


def parse_pdf(path):
    with pdfplumber.open(path) as pdf:
        if not 3 <= len(pdf.pages) <= 1200:
            raise ValueError('Unexpected PDF page count')

        def texts():
            for page in pdf.pages:
                # Exclude the vertical signature strip; keep all horizontal table text.
                text = page.filter(lambda obj: obj.get('upright', True) and obj.get('x0', 100) >= 38).extract_text() or ''
                page.close()
                yield text
        return parse_pages(texts())
