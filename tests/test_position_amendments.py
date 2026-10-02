import unittest
from copy import deepcopy
from bolsa_abierta import position_amendments as amendments


class AmendmentTests(unittest.TestCase):
    def test_supplement_extracts_only_two_admissions_not_rejections(self):
        text = '''ORDEN COMPLEMENTARIA CURSO 2026-2027
PRIMERO.- Incluir
Especialidad: 108 Intervención Sociocomunitaria
Lista: 69 Lista Interinos Bloque 2 Oposición 2025
Nº Lista DNI Apellidos, Nombre Puntos
25000340 ***1111** PRUEBA, ANA 3.0000
Especialidad: 006 Matemáticas
Lista: 69 Lista Interinos Bloque 2 Oposición 2025
Nº Lista DNI Apellidos, Nombre Puntos
25006830 ***2222** EJEMPLO, SOL 0.0000
SEGUNDO.- Desestimar las reclamaciones'''
        rows = amendments.parse_amendment(text, '208249')
        self.assertEqual([(r['specialty'],r['block'],r['list_number']) for r in rows],
                         [('0590108','69','25000340'),('0590006','69','25006830')])
        self.assertNotIn('1111', str(rows))
        self.assertNotIn('points', str(rows))
        with self.assertRaises(ValueError):
            amendments.parse_amendment(text.replace('25006830','25006831'), '208249')

    def test_prose_correction_has_one_admission_and_source_page(self):
        text = 'CURSO 2026-2027 DISPONGO ÚNICO.- Incluir especialidad (594428), en su orden correspondiente con el número de lista 25000080, al aspirante NOMBRE APELLIDO PRUEBA, con DNI ***1111** y la puntuación 5.2265.'
        row, = amendments.parse_amendment(text, '208379')
        self.assertEqual((row['specialty'],row['list_number'],row['page'],row['source_id']),('0594428','25000080',1,'208379'))
        self.assertNotIn('1111',str(row))

    def test_insert_preserves_existing_ids_order_and_document_provenance(self):
        original = [dict(id=str(i),specialty='0594428',block='69',block_name='Bloque 2',
                         specialty_name='TROMPETA',body_name='MÚSICA',list_number=n,name='PRUEBA',rank=i,page=504)
                    for i,n in enumerate(['25000070','25000090'],1)]
        before=deepcopy(original)
        change=dict(specialty='0594428',block='69',list_number='25000080',name='OTRA PERSONA',page=1,source_id='208379')
        result=amendments.apply_insertions(original,[change])
        self.assertEqual(original,before)
        self.assertEqual([r['list_number'] for r in result],['25000070','25000080','25000090'])
        self.assertEqual([r['rank'] for r in result],[1,2,3])
        self.assertEqual([result[0]['id'],result[-1]['id']],['1','2'])
        self.assertEqual([r['source_id'] for r in result],['208095','208379','208095'])
        self.assertEqual(result[1]['page'],1)
        with self.assertRaises(ValueError): amendments.apply_insertions(result,[change])
        with self.assertRaises(ValueError): amendments.apply_insertions(original,[{**change,'block':'70'}])

    def test_same_number_in_another_block_is_not_moved(self):
        rows=[dict(id='old',specialty='0590006',block='69',block_name='B2',specialty_name='MATH',body_name='SEC',
                   list_number='25006820',name='PRUEBA',rank=1,page=79),
              dict(id='next',specialty='0590006',block='70',block_name='B3',specialty_name='MATH',body_name='SEC',
                   list_number='25000010',name='OTRA',rank=2,page=80)]
        result=amendments.apply_insertions(rows,[dict(specialty='0590006',block='69',list_number='25006830',name='NUEVA',page=1,source_id='208249')])
        self.assertEqual([r['block'] for r in result],['69','69','70'])
