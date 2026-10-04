"""Synthetic geometry only: no downloaded nominal roster is a test fixture."""

from copy import deepcopy
import hashlib
import importlib
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


LEGEND = {
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


def word(text, x, y):
    return dict(text=text, x0=x, x1=x + len(text) * 3, top=y, bottom=y + 8)


def text_pdf(label):
    """A real one-page PDF for byte-to-extracted-text transport regressions."""
    stream = f'BT /F1 12 Tf 30 800 Td ({label}) Tj ET'.encode('ascii')
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] '
        b'/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(stream)).encode('ascii') + b' >>\nstream\n' + stream + b'\nendstream',
    ]
    result, offsets = bytearray(b'%PDF-1.4\n'), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f'{number} 0 obj\n'.encode('ascii') + body + b'\nendobj\n')
    xref = len(result)
    result.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets:
        result.extend(f'{offset:010d} 00000 n \n'.encode('ascii'))
    result.extend(f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode('ascii'))
    return bytes(result)


class Page:
    """The actual extraction boundary, with independently writable text/geometry."""

    def __init__(self, text, words=(), lines=(), landscape=False):
        self.text, self.words, self.lines = text, list(words), list(lines)
        self.width, self.height = (842, 595) if landscape else (595.32, 842.04)

    def extract_text(self, **_kwargs):
        return self.text

    def extract_words(self, **_kwargs):
        return self.words

    def filter(self, _predicate):
        return self

    def close(self):
        pass


def roster_page(annex, local_page, rows=(), legend=False):
    title = TITLE.format(annex=annex, letter='a' if annex == 'I' else 'b')
    text = title + '\n'
    if legend:
        text += f'ANEXO {annex}\nCÓDIGOS DE ESPECIALIDADES ACREDITADAS\nEspecialidades:\n'
        text += '\n'.join(f'{code} - {name}.' for code, name in LEGEND.items())
        return Page(text + f'\nPágina {local_page} de3', landscape=True)
    text += ('Especialidades Acreditadas\nNLISTA DNI Apellidos y Nombre\n'
             + ('Mayor Calificación Oposición Superada\n' if annex == 'I' else 'Calificación Oposición Actual\n')
             + 'Experiencia Docente Puntuación Total\n')
    shift, left, name_left = (0, 17, 108) if annex == 'I' else (44, 14, 104)
    words = [word('NLISTA', left + 8.06, 115.626), word('DNI', left + 62.224, 115.626),
             word('Apellidos y Nombre', name_left + 61.044, 115.626)]
    for code, x in zip(LEGEND, (309.33, 335.33, 361.33, 387.33, 413.33,
                              439.33, 465.33, 490.33, 516.33)):
        words.append(word(code, x + shift, 134.126))
    lines = []
    for i, (number, name, codes) in enumerate(rows):
        top, bottom, baseline = 144 + 26 * i, 169 + 26 * i, 153.11 + 26 * i
        lines.extend([dict(x0=left, x1=left, top=top, bottom=bottom, height=25),
                      dict(x0=left + 1, x1=left + 44, top=bottom, bottom=bottom, height=0)])
        words.extend([word(number, left, baseline), word('***1234**', left + 51.32, baseline + .5),
                      word(name, name_left + 4, baseline + .5)])
        for code in codes:
            j = list(LEGEND).index(code)
            x = (313.33, 339.33, 365.33, 391.33, 417.33, 443.33, 469.33, 494.33, 520.33)[j]
            words.append(word('X', x + shift, baseline + .5))
        score_x = (546.77, 584.77, 615.77, 643.77, 671.77, 700.77, 742.27, 789.54)
        if annex == 'II':
            score_x = (590.77, 628.77, 659.77, 687.77, 715.77, 744.77, 781.04)
        for x in score_x:
            words.append(word('1,0000', x, baseline + .5))
        text += f'{number} ***1234** {name} ' + ' '.join('X' for _ in codes) + ' 1,0000\n'
    return Page(text + f'Página {local_page} de3', words, lines, landscape=True)


def fixture():
    pages = [
        Page('RESOLUCIÓN DE LA DIRECCIÓN GENERAL DE RECURSOS HUMANOS\n'
             'LISTA DEFINITIVA EN EL CUERPO DE MAESTROS PARA EL CURSO 2026-2027\n'
             'RESUELVO: PRIMERO Anexo I bloque I. SEGUNDO Anexo II bloque II.\n'
             'LA DIRECTORA GENERAL DE RECURSOS HUMANOS\nDocumento firmado electrónicamente\nPágina 1'),
        roster_page('I', 1, legend=True),
        roster_page('I', 2, [('26000010', 'PRUEBA UNO, ANA', ['031', '038']),
                             ('26000020', 'PRUEBA DOS, LUIS', ['034']),
                             ('26000030', 'PRUEBA TRES, SOL', ['035'])]),
        roster_page('I', 3, [('26000040', 'PRUEBA CUATRO, LUZ', ['031']),
                             ('26000050', 'PRUEBA CINCO, MAR', ['038'])]),
        roster_page('II', 1, legend=True),
        roster_page('II', 2, [('26000060', 'PRUEBA SEIS, ELENA', ['034']),
                              ('26000070', 'PRUEBA SIETE, PABLO', ['034', '038'])]),
        roster_page('II', 3),
        Page('ANEXO III\nAPELLIDOS Y NOMBRE\nMOTIVO DE DESESTIMACIÓN'),
        Page('ANEXO IV\nRELACIÓN DE ASPIRANTES A LOS QUE SE LES HA MODIFICADO DE OFICIO ALGUNO\n'
             'DE LOS DATOS PUBLICADOS EN LA FASE DE EXPOSICIÓN PÚBLICA\n1'),
        Page('ANEXO V\nASPIRANTES QUE SE INTEGRAN EN EL BLOQUE I POR TENER CUMPLIDOS\n'
             '55 AÑOS\nDNI APELLIDOS Y NOMBRE CUERPO'),
    ]
    metadata = dict(
        kind='maestros_roster', content_id='208253', course='2026-2027',
        parser_revision='maestros-unique-list-v1', rank_scope='maestros_unique_list',
        source_url='https://www.carm.es/web/descarga?IDCONTENIDO=208253',
        sha256='0' * 64, signed_at='2026-07-28', published_at='2026-07-28',
        checked_at='2026-10-04T00:00:00Z', pages=10, baseline_row_count=7, row_count=7,
        page_row_counts=[0, 0, 3, 2, 0, 2, 0, 0, 0, 0],
        baseline_habilitation_counts={'031': 2, '034': 3, '035': 1, '038': 3},
        habilitation_counts={'031': 2, '034': 3, '035': 1, '038': 3},
        block_row_counts={'I': 5, 'II': 2}, unknown_habilitation_rows=0,
        specialties=[dict(code='0597', name='Lista única de Maestros', body='CUERPO DE MAESTROS', count=7)],
        sections=[dict(kind='resolution', start_page=1, pages=1),
                  dict(kind='roster', annex='I', block='I', start_page=2, pages=3, row_count=5),
                  dict(kind='roster', annex='II', block='II', start_page=5, pages=3, row_count=2),
                  dict(kind='supporting', annex='III', start_page=8, pages=1),
                  dict(kind='supporting', annex='IV', start_page=9, pages=1),
                  dict(kind='supporting', annex='V', start_page=10, pages=1)],
        amendments=[],
    )
    return pages, metadata


def correction_fixture(metadata):
    # Four distinct additions. The identical synthetic masked ID must not merge
    # them with base members: masked values do not establish membership identity.
    pages = [Page(CORRECTION_TITLE + '\n1')]
    first = ('RESUELVO:\nPRIMERO.- Incluir en la Resolución de 28 de julio de 2026 '
             'a los siguientes aspirantes con los datos acreditados:\nAnexo I (bloque I):\n')
    p2 = first + '***1234** ALTA UNO, EVA\nNº LISTA Especialidades acreditadas Experiencia docente Puntuación total\n26000015 035 b.1) 5,6500 8,5292 2,5000 16,6792\n2'
    p3 = ('***1234** ALTA DOS, LEO\nNº LISTA Especialidades acreditadas Experiencia docente Puntuación total\n'
          '26000025 031 b.1) 5,6500 6,2850 1,0000 8,8350\n'
          '***1234** ALTA TRES, IRIS\nNº LISTA Experiencia docente Puntuación total\n'
          '26000035 b.1) 0,5500 7,0663 1 8,6163\n'
          '***1234** ALTA CUATRO, NOA\nNº LISTA Experiencia docente Puntuación total\n'
          '26000045 0,0000 6,7137 1 7,7137\n3')
    p4 = ('SEGUNDO.- Advertido error en las especialidades acreditadas por\n'
          '***1234** PRUEBA SEIS, ELENA, en la solicitud de participación en el proceso selectivo, '
          'procede incluir en la Resolución de 28 de julio de 2026, en el Anexo II (bloque II) '
          'la especialidad 597036 Pedagogía Terapéutica.\n'
          'TERCERO.- Advertido error en las especialidades acreditadas por\n'
          '***1234** PRUEBA SIETE, PABLO en la solicitud para aspirantes a interinidad, '
          'procede incluir en la Resolución de 28 de julio de 2026, en el Anexo II (bloque II) '
          'la especialidad 597037 Audición y Lenguaje\n'
          'LA DIRECTORA GENERAL DE RECURSOS HUMANOS, PLANIFICACIÓN EDUCATIVA E INNOVACIÓN\n'
          '(Firmado electrónicamente al margen)\n4')
    pages.extend([Page(p2), Page(p3), Page(p4)])
    for page, numbers in [(pages[1], ['26000015']), (pages[2], ['26000025', '26000035', '26000045'])]:
        page.words = [word(number, 141.86, 220 + i * 160) for i, number in enumerate(numbers)]
    source = dict(kind='maestros_correction', content_id='208782',
                  source_url='https://www.carm.es/web/descarga?IDCONTENIDO=208782',
                  sha256='1' * 64, signed_at='2026-09-09', published_at='2026-09-09',
                  checked_at='2026-10-04T00:00:00Z', pages=4,
                  page_inclusion_counts=[0, 1, 3, 0],
                  operations=[
                      dict(kind='include', block='I', list_number='26000015', page=2,
                           habilitation_codes=['035'], neighbors=['26000010', '26000020']),
                      dict(kind='include', block='I', list_number='26000025', page=3,
                           habilitation_codes=['031'], neighbors=['26000020', '26000030']),
                      dict(kind='include', block='I', list_number='26000035', page=3,
                           habilitation_codes=None, neighbors=['26000030', '26000040']),
                      dict(kind='include', block='I', list_number='26000045', page=3,
                           habilitation_codes=None, neighbors=['26000040', '26000050']),
                      dict(kind='add_habilitation', block='II', list_number='26000060', page=4,
                           baseline_page=6, code='036', published_code='597036', clause='SEGUNDO'),
                      dict(kind='add_habilitation', block='II', list_number='26000070', page=4,
                           baseline_page=6, code='037', published_code='597037', clause='TERCERO'),
                  ])
    metadata.update(row_count=11, block_row_counts={'I': 9, 'II': 2},
                    habilitation_counts={'031': 3, '034': 3, '035': 2, '036': 1, '037': 1, '038': 3},
                    unknown_habilitation_rows=2, amendments=[deepcopy(source)])
    metadata['specialties'][0]['count'] = 11
    return pages, source


class MaestrosTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('bolsa_abierta.position_maestros'),
                             'Missing reviewed Maestros unique-list adapter')
        return importlib.import_module('bolsa_abierta.position_maestros')

    def test_memberships_have_one_global_rank_and_separate_literal_habilitations(self):
        pages, metadata = fixture()
        result = self.module().parse_maestros_pages(pages, metadata)
        rows = result['rows']
        self.assertEqual([r['rank'] for r in rows], list(range(1, 8)))
        self.assertEqual([r['block'] for r in rows], ['I'] * 5 + ['II'] * 2)
        self.assertTrue(all(r['specialty'] == '0597' and r['roster_id'] == '208253'
                            and r['rank_scope'] == 'maestros_unique_list' for r in rows))
        self.assertEqual(rows[0]['habilitations'], [dict(code='031', name='Educación infantil'),
                                                   dict(code='038', name='Educación primaria')])
        self.assertEqual(result['totals']['row_count'], 7)
        self.assertEqual(result['totals']['habilitation_count'], 9)
        self.assertNotIn('1234', str(result))
        self.assertNotIn('points', rows[0])

    def test_membership_id_survives_a_name_change_and_is_namespaced_by_course_and_body(self):
        pages, metadata = fixture()
        original = self.module().parse_maestros_pages(pages, metadata)['rows'][0]
        pages[2].text = pages[2].text.replace('PRUEBA UNO, ANA', 'PRUEBA UNO, ANABEL')
        for w in pages[2].words:
            if w['text'] == 'PRUEBA UNO, ANA':
                w['text'] = 'PRUEBA UNO, ANABEL'
        renamed = self.module().parse_maestros_pages(pages, metadata)['rows'][0]
        self.assertEqual(original['id'], renamed['id'])
        expected = hashlib.sha256(b'list|2026-2027|0597|I|26000010').hexdigest()[:32]
        self.assertEqual(original['id'], expected)

    def test_wrapped_names_are_read_inside_the_complete_drawn_row(self):
        pages, metadata = fixture()
        pages[2].words = [w for w in pages[2].words if w['text'] != 'PRUEBA UNO, ANA']
        pages[2].words.extend([word('PRUEBA UNO,', 112, 149.61), word('ANA MARIA', 112, 159.61)])
        self.assertEqual(self.module().parse_maestros_pages(pages, metadata)['rows'][0]['name'],
                         'PRUEBA UNO, ANA MARIA')

    def test_missing_repeated_or_reordered_pages_never_create_partial_ranks(self):
        for defect in ('missing', 'repeat', 'footer', 'legend', 'supporting', 'section_gap', 'page_count'):
            pages, metadata = fixture()
            if defect == 'missing': pages.pop(3)
            if defect == 'repeat': pages[3] = pages[2]
            if defect == 'footer': pages[5].text = pages[5].text.replace('Página 2 de3', 'Página 3 de3')
            if defect == 'legend': pages[4].text = pages[4].text.replace('ANEXO II', 'ANEXO I')
            if defect == 'supporting': pages[-1].text = pages[-1].text.replace('ANEXO V', 'ANEXO VI')
            if defect == 'section_gap': metadata['sections'][3]['start_page'] = 9
            if defect == 'page_count': metadata['page_row_counts'][2] = 2
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                self.module().parse_maestros_pages(pages, metadata)

    def test_lost_text_geometry_habilitation_or_row_boundary_is_rejected(self):
        for defect in ('anchor', 'text_row', 'name', 'boundary', 'habilitation_header', 'unknown_mark', 'extra_row'):
            pages, metadata = fixture()
            if defect == 'anchor': pages[2].words = [w for w in pages[2].words if w['text'] != '26000010']
            if defect == 'text_row': pages[2].text = pages[2].text.replace('26000010 ***1234**', 'MISSING')
            if defect == 'name': pages[2].words = [w for w in pages[2].words if w['text'] != 'PRUEBA UNO, ANA']
            if defect == 'boundary': pages[2].lines.pop(0)
            if defect == 'habilitation_header': pages[2].words = [w for w in pages[2].words if w['text'] != '031']
            if defect == 'unknown_mark': pages[2].words.append(word('Y', 339.33, 153.61))
            if defect == 'extra_row': pages[6].text = pages[6].text.replace('Página', '26000080 ***1234** OTRA FILA, EVA\nPágina')
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                self.module().parse_maestros_pages(pages, metadata)

    def test_duplicate_list_numbers_are_rejected_even_with_a_different_name_or_block(self):
        pages, metadata = fixture()
        pages[5].text = pages[5].text.replace('26000060', '26000010')
        for w in pages[5].words:
            if w['text'] == '26000060': w['text'] = '26000010'
        with self.assertRaises(ValueError): self.module().parse_maestros_pages(pages, metadata)

    def test_inclusions_and_habilitation_additions_preserve_source_scope_and_unknowns(self):
        pages, metadata = fixture()
        amendments = [correction_fixture(metadata)]
        result = self.module().parse_maestros_pages(pages, metadata, amendments=amendments)
        rows = result['rows']
        self.assertEqual([r['list_number'] for r in rows],
                         ['26000010', '26000015', '26000020', '26000025', '26000030', '26000035',
                          '26000040', '26000045', '26000050', '26000060', '26000070'])
        self.assertEqual([r['rank'] for r in rows], list(range(1, 12)))
        self.assertEqual(result['totals']['row_count'], 11)
        self.assertEqual(result['totals']['baseline_row_count'], 7)
        self.assertEqual(result['totals']['habilitation_count'], 13)
        self.assertEqual(result['totals']['unknown_habilitation_rows'], 2)
        self.assertEqual(rows[5]['habilitations'], [])
        self.assertEqual(rows[5]['habilitations_status'], 'not_stated')
        self.assertEqual(rows[1]['source_id'], '208782')
        self.assertEqual(rows[1]['page'], 2)
        self.assertNotIn('baseline_page', rows[1])
        self.assertEqual(rows[-2]['source_id'], '208782')
        self.assertEqual(rows[-2]['page'], 4)
        self.assertEqual(rows[-2]['baseline_page'], 6)
        self.assertEqual([h['code'] for h in rows[-2]['habilitations']], ['034', '036'])
        self.assertEqual(rows[-2]['amendment_relation']['previous_id'], rows[-2]['id'])
        self.assertEqual(rows[-2]['amendment_relation']['published_code'], '597036')
        self.assertNotIn('1234', str(result))

    def test_amendment_identity_is_exact_and_cannot_reuse_a_masked_id(self):
        pages, metadata = fixture()
        amendment_pages, source = correction_fixture(metadata)
        amendment_pages[3].text = amendment_pages[3].text.replace('PRUEBA SEIS, ELENA', 'PRUEBA SEIS, HELENA')
        with self.assertRaises(ValueError):
            self.module().parse_maestros_pages(pages, metadata, amendments=[(amendment_pages, source)])

    def test_ambiguous_existing_name_prevents_an_unreviewed_inclusion(self):
        pages, metadata = fixture()
        amendment_pages, source = correction_fixture(metadata)
        amendment_pages[1].text = amendment_pages[1].text.replace('ALTA UNO, EVA', 'PRUEBA UNO, ANA')
        with self.assertRaises(ValueError):
            self.module().parse_maestros_pages(pages, metadata, amendments=[(amendment_pages, source)])

    def test_amendment_pages_counts_target_number_and_habilitation_must_match_review(self):
        for defect in ('missing', 'footer', 'number', 'code', 'baseline_page', 'duplicate_operation', 'missing_amendment'):
            pages, metadata = fixture()
            correction_pages, source = correction_fixture(metadata)
            if defect == 'missing': correction_pages.pop()
            if defect == 'footer': correction_pages[2].text = correction_pages[2].text[:-1] + '2'
            if defect == 'number': correction_pages[2].text = correction_pages[2].text.replace('26000035', '26000025')
            if defect == 'code': correction_pages[3].text = correction_pages[3].text.replace('597036', '597035')
            if defect == 'baseline_page':
                source['operations'][4]['baseline_page'] = 3
                metadata['amendments'] = [deepcopy(source)]
            if defect == 'duplicate_operation':
                source['operations'].append(deepcopy(source['operations'][0]))
                metadata['amendments'] = [deepcopy(source)]
            amendments = [] if defect == 'missing_amendment' else [(correction_pages, source)]
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                self.module().parse_maestros_pages(pages, metadata, amendments=amendments)

    def test_unknown_habilitations_are_preserved_when_all_published_cells_are_blank(self):
        pages, metadata = fixture()
        pages[3] = roster_page('I', 3, [('26000040', 'PRUEBA CUATRO, LUZ', []),
                                      ('26000050', 'PRUEBA CINCO, MAR', ['038'])])
        metadata['baseline_habilitation_counts']['031'] = 1
        metadata['habilitation_counts']['031'] = 1
        metadata['unknown_habilitation_rows'] = 1
        row = self.module().parse_maestros_pages(pages, metadata)['rows'][3]
        self.assertEqual(row['habilitations'], [])
        self.assertEqual(row['habilitations_status'], 'not_stated')

    def test_invalid_manifest_counts_and_invented_specialty_fail_closed(self):
        for field, value in [('page_row_counts', [False] * 10), ('baseline_row_count', 6),
                             ('rank_scope', 'specialty'), ('parser_revision', 'unreviewed')]:
            pages, metadata = fixture()
            metadata[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.module().parse_maestros_pages(pages, metadata)
        pages, metadata = fixture()
        metadata['specialties'][0]['code'] = '0597000'
        with self.assertRaises(ValueError): self.module().parse_maestros_pages(pages, metadata)

    def test_all_hashes_are_checked_before_opening_any_pdf(self):
        module = self.module()
        with TemporaryDirectory() as directory:
            base, correction = Path(directory) / 'base.pdf', Path(directory) / 'correction.pdf'
            base.write_bytes(b'%PDF-1.4 synthetic bytes only')
            correction.write_bytes(b'%PDF-1.4 different synthetic bytes')
            _, metadata = fixture()
            _, source = correction_fixture(metadata)
            metadata['sha256'] = hashlib.sha256(base.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, 'bytes'):
                module.read_maestros(base, metadata, amendments=[(correction, source)])
            for payload, digest in [(b'<html>challenge</html>', hashlib.sha256(b'<html>challenge</html>').hexdigest()),
                                    (b'%PDF-1.4 changed', '0' * 64)]:
                base.write_bytes(payload)
                metadata['sha256'] = digest
                with self.assertRaisesRegex(ValueError, 'bytes'):
                    module.read_maestros(base, metadata)

    def test_verified_bytes_are_parsed_if_both_paths_are_replaced_before_extraction(self):
        module = self.module()
        verified_base, verified_correction = text_pdf('VERIFIED BASE'), text_pdf('VERIFIED CORRECTION')
        replaced_base, replaced_correction = text_pdf('REPLACED BASE'), text_pdf('REPLACED CORRECTION')
        with TemporaryDirectory() as directory:
            base, correction = Path(directory) / 'base.pdf', Path(directory) / 'correction.pdf'
            base.write_bytes(verified_base)
            correction.write_bytes(verified_correction)
            metadata = dict(sha256=hashlib.sha256(verified_base).hexdigest(), bytes=len(verified_base))
            source = dict(sha256=hashlib.sha256(verified_correction).hexdigest(), bytes=len(verified_correction))
            original_open = module.pdfplumber.open

            def open_after_replacement(document, *args, **kwargs):
                # Both files change after their hash checks, immediately before
                # the genuine PDF reader consumes either input.
                base.write_bytes(replaced_base)
                correction.write_bytes(replaced_correction)
                return original_open(document, *args, **kwargs)

            def inspect_decoded_text(pages, _metadata, *, amendments):
                # Keep the real PDF library and byte gate. Only replace roster
                # interpretation so this test observes the actual decoded input.
                return dict(base=pages[0].extract_text(), correction=amendments[0][0][0].extract_text())

            with patch.object(module.pdfplumber, 'open', side_effect=open_after_replacement), \
                    patch.object(module, 'parse_maestros_pages', side_effect=inspect_decoded_text):
                result = module.read_maestros(base, metadata, amendments=[(correction, source)])
            self.assertEqual(result, dict(base='VERIFIED BASE', correction='VERIFIED CORRECTION'))
            self.assertEqual(base.read_bytes(), replaced_base)
            self.assertEqual(correction.read_bytes(), replaced_correction)


if __name__ == '__main__':
    unittest.main()
