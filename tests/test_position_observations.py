import hashlib
import importlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.test_position_documents import word


TITLE='Listados De Adjudicatarios Que Optan En Secundaria'
HEADER=('Convocatoria: Adjudicación semanal 24/09/2026. Proceso 3125 - '
        'Listado a 24 de Septiembre de 2026, a las 14:15')
COLUMNS=((29,79,'Nº Lista'),(79,134,'DNI'),(134,224,'Primer Apellido'),
         (224,314,'Segundo Apellido'),(314,404,'Nombre'),(404,454,'Cuerpo'),(454,820,'Función'))


class ObservationPage:
    width,height=842,595
    def __init__(self):
        self.text=(TITLE+'\n'+HEADER+'\nNº Lista DNI Primer Apellido Segundo Apellido Nombre Cuerpo Función\n'
                   '26300010 ***1234** PRUEBA UNO ANA 0590 0590206 INSTALACIONES ELECTROTECNICAS\n'
                   'Murcia, a 24 de septiembre de 2026\n'
                   'LA D.G. DE RECURSOS HUMANOS, PLANIFICACIÓN EDUCATIVA E INNOVACIÓN\nPágina 1 de 1')
        self.words=[word(label,left,90) for left,right,label in COLUMNS]
        self.words += [word(value,left,110) for left,value in
                       [(29,'26300010'),(79,'***1234**'),(134,'PRUEBA'),(224,'UNO'),
                        (314,'ANA'),(404,'0590'),(454,'0590206'),(487,'INSTALACIONES ELECTROTECNICAS')]]
        self.rects=[dict(x0=left,x1=right,top=top,bottom=bottom)
                    for top,bottom in [(84,104),(104,122)] for left,right,label in COLUMNS]
    def extract_text(self): return self.text
    def extract_words(self,**kwargs): return self.words


def fixture():
    return [ObservationPage()],dict(kind='optan_observation',content_id='209124',
        published_at='2026-09-24',process_id='3125',pages=1,row_count=1,page_row_counts=[1],
        semantic_status='unconfirmed',specialties=[dict(code='0590206',name='INSTALACIONES ELECTROTECNICAS',
                                                      body_code='0590',count=1)])


class PositionObservationTests(unittest.TestCase):
    def module(self): return importlib.import_module('bolsa_abierta.position_observations')

    def test_observation_validates_source_without_producing_person_or_award_rows(self):
        pages,metadata=fixture()
        evidence=self.module().parse_observation_pages(pages,metadata)
        self.assertEqual(evidence['kind'],'optan_observation')
        self.assertEqual(evidence['source_id'],'209124')
        self.assertEqual(evidence['row_count'],1)
        self.assertEqual(evidence['page_row_counts'],[1])
        self.assertEqual(evidence['semantic_status'],'unconfirmed')
        for value in ['PRUEBA','ANA','26300010','1234','rank','award','available','destination','rows']:
            self.assertNotIn(value,str(evidence))

    def test_unknown_semantics_layout_and_counts_fail_closed(self):
        for mutation in ['kind','meaning','count','page_count','signature','process','date','footer',
                         'header','cell','rectangle','extra_cell','body','specialty','missing_anchor']:
            pages,metadata=fixture();page=pages[0]
            if mutation=='kind': metadata['kind']='award'
            if mutation=='meaning': metadata['semantic_status']='available'
            if mutation=='count': metadata['row_count']=2
            if mutation=='page_count': metadata['page_row_counts']=[0]
            if mutation=='signature': page.text=page.text.replace('***1234**','MASKED')
            if mutation=='process': page.text=page.text.replace('3125','9999')
            if mutation=='date': page.text=page.text.replace('24 de Septiembre','25 de Septiembre')
            if mutation=='footer': page.text=page.text.replace('LA D.G.','FALTA FIRMA')
            if mutation=='header': page.words[0]['text']='Número'
            if mutation=='cell': page.words=[w for w in page.words if w['text']!='ANA']
            if mutation=='rectangle': page.rects.pop()
            if mutation=='extra_cell': page.rects.append(dict(x0=29,x1=79,top=125,bottom=143))
            if mutation=='body': metadata['specialties'][0]['body_code']='0597'
            if mutation=='specialty': metadata['specialties'][0]['name']='OTRA'
            if mutation=='missing_anchor': page.words=[w for w in page.words if w['text']!='26300010']
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                self.module().parse_observation_pages(pages,metadata)

    def test_observation_hash_gate_precedes_pdf_extraction(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'source.pdf'
            for payload,digest in [(b'<html>challenge</html>',hashlib.sha256(b'<html>challenge</html>').hexdigest()),
                                   (b'%PDF-1.4 changed','0'*64)]:
                path.write_bytes(payload)
                with self.subTest(payload=payload),self.assertRaises(ValueError):
                    self.module().read_observation_document(path,{'sha256':digest})


if __name__=='__main__': unittest.main()
