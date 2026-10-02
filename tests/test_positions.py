import unittest
from bolsa_abierta import positions


def page(number, rows, specialty='001 FILOSOFIA', block='68 Lista Interinos Bloque 1'):
    return f'''Región de Murcia
Consejería de Educación y Formación Profesional
RELACIÓN DEFINITIVA DEL PERSONAL INTERINO DE SECUNDARIA Y OTROS CUERPOS PARA EL
CURSO 2026/2027
Cuerpo: 0590 CUERPO DE PROFESORES DE ENSEÑANZA SECUNDARIA
Especialidad: {specialty}
Lista: {block}
Nº Lista DNI Apellidos, Nombre Puntos
{rows}
Página {number}'''


def document(*pages):
    return ['Resolución definitiva 2026-2027', *pages,
            'RELACIÓN DEFINITIVA DEL PERSONAL INTERINO EXCLUIDO\n25000010 ***1111** NO INDEXAR, NOMBRE 0.0000']


class PositionParserTests(unittest.TestCase):
    def parse(self, pages):
        self.assertTrue(callable(getattr(positions, 'parse_pages', None)), 'Missing strict roster parser')
        return positions.parse_pages(pages)

    def test_counts_real_rows_not_gaps_or_list_number_and_excludes_annexes(self):
        result = self.parse(document(page(1, '25000010 ***1111** PRUEBA UNO, ANA 10.0000\n25000040 ****2222* PRUEBA DOS, LUIS 9.5000'),
                                     page(2, '4001570 ***3333** PRUEBA TRES, SOL 0.0000', block='23 Lista antigua')))
        self.assertEqual([x['rank'] for x in result], [1, 2, 3])
        self.assertEqual([x['page'] for x in result], [2, 2, 3])
        self.assertEqual(result[2]['list_number'], '4001570')
        self.assertNotIn('1111', str(result))
        self.assertNotIn('points', result[0])

    def test_same_number_in_distinct_blocks_is_distinct_and_specialty_restarts_rank(self):
        result = self.parse(document(page(1, '25000010 ***1111** PRUEBA UNO, ANA 1.0000'),
                                     page(2, '25000010 ***2222** PRUEBA DOS, LUIS 1.0000', block='69 Bloque 2'),
                                     page(3, '25000010 ***3333** PRUEBA TRES, SOL 1.0000', specialty='002 LATIN')))
        self.assertEqual([x['rank'] for x in result], [1, 2, 1])
        self.assertEqual(len(set(x['id'] for x in result)), 3)

    def test_rejects_partial_row_missing_page_duplicate_and_out_of_order(self):
        good = '25000010 ***1111** PRUEBA UNO, ANA 1.0000'
        bads = [document(page(1, good+'\n25000020 ***2222** FILA ROTA')),
                document(page(2, good)), document(page(1, good+'\n'+good)),
                document(page(1, good.replace('25000010','25000020')+'\n'+good)),
                document(page(1, good).replace('2026/2027','2025/2026')),
                ['Resolución', page(1, good)]]
        for pages in bads:
            with self.subTest(pages=len(pages)), self.assertRaises(ValueError):
                self.parse(pages)

    def test_unrecognized_text_is_not_silently_dropped(self):
        with self.assertRaises(ValueError):
            self.parse(document(page(1, 'Texto de fila no reconocido')))


if __name__ == '__main__':
    unittest.main()
