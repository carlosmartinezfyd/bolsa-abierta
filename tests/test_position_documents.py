import importlib
import importlib.util
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch


TITLE = 'Listado Definitivo De Adjudicatarios Con Plaza En Secundaria'
HEADER = ('Convocatoria: Adjudicación semanal 24/09/2026. Proceso 3125. '
          'Fecha de incorporación: 25-SEP-26 - Listado a 24 de Septiembre de 2026, a las 14:16')


def word(text, x, y):
    return dict(text=text, x0=x, x1=x+len(text)*3, top=y, bottom=y+8)


class Page:
    width, height = 842, 595

    def __init__(self, number, rows=()):
        self.text = TITLE+'\n'+HEADER+'\n'
        self.words, self.rects = [], []
        if rows:
            self.text += 'CUERPO: 0590 PROFESORES DE ENSEÑANZA SECUNDARIA\nFUNCIÓN: 0590I09 DIBUJO / INGLES\n'
            self.words += [word('CUERPO:',40,92),word('0590',92,92),word('PROFESORES DE ENSEÑANZA SECUNDARIA',117,92),
                           word('FUNCIÓN:',40,106),word('0590I09',92,106),word('DIBUJO / INGLES',131,106)]
            for x, text in [(35,'Pri.'),(60,'Nº Lista'),(100,'DNI'),(155,'Apellido1'),(235,'Apellido2'),
                            (315,'Nombre'),(395,'Centro'),(535,'Municipio'),(615,'Función'),(665,'Jornada'),
                            (715,'Perfil'),(765,'V/S'),(795,'Obs.')]:
                self.words.append(word(text,x,125))
            for i, (number_, first, second, name) in enumerate(rows):
                y=139+i*60
                self.rects.append(dict(x0=35,x1=824,top=y,bottom=y+54))
                self.words += [word('97',38,y+8),word(number_,60,y+8),word('***1234**',103,y+8),
                               word(first,155,y+3),word(second,235,y+8),word(name,315,y+8),
                               word('30000001 IES EJEMPLO',396,y+3),word('(MURCIA)',396,y+12),
                               word('MURCIA',535,y+8),word('0590I09',615,y+8),word('Tiempo',665,y+3),
                               word('Parcial 10',665,y+12),word('horas',665,y+21),word('VP',765,y+8)]
                self.text += f'97 {number_} ***1234** {first} {second} {name} 0590I09\n'
        else:
            self.text += 'Murcia, a 24 de septiembre de 2026\nEL CONSEJERO DE EDUCACIÓN Y FORMACIÓN PROFESIONAL\n'
        self.text += f'Página {number} de 3'

    def extract_text(self):
        return self.text

    def extract_words(self, **_kwargs):
        return self.words


def fixture():
    pages=[Page(1,[('26300010','PRUEBA','UNO','ANA')]),
           Page(2,[('26300020','PRUEBA','DOS','LUIS'),('26300030','PRUEBA','TRES','SOL')]),Page(3)]
    metadata=dict(kind='award',content_id='209126',published_at='2026-09-24',process_id='3125',
                  pages=3,row_count=3,page_row_counts=[1,2,0],
                  specialties=[dict(code='0590I09',name='DIBUJO / INGLES',body='PROFESORES DE ENSEÑANZA SECUNDARIA',count=3)])
    return pages,metadata


class PositionDocumentTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('bolsa_abierta.position_documents'), 'Missing strict award document adapter')
        return importlib.import_module('bolsa_abierta.position_documents')

    def test_complete_bilingual_awards_have_provenance_without_a_rank_or_identity_document(self):
        pages,metadata=fixture()
        records=self.module().parse_award_pages(pages,metadata)
        self.assertEqual(len(records),3)
        self.assertEqual([r['page'] for r in records],[1,2,2])
        self.assertEqual(len({r['id'] for r in records}),3)
        self.assertEqual(records[0]['name'],'PRUEBA UNO, ANA')
        self.assertEqual(records[0]['destination'],'IES EJEMPLO (MURCIA) · MURCIA')
        self.assertEqual(records[0]['workload'],'Tiempo Parcial 10 horas')
        self.assertTrue(all(r['rank'] is None and r['block']=='' and r['record_type']=='award' for r in records))
        self.assertTrue(all(r['source_id']=='209126' and r['specialty']=='0590I09' for r in records))
        self.assertNotIn('1234',str(records))
        self.assertNotIn('priority',records[0])

    def test_wrapped_surnames_keep_column_order(self):
        pages,metadata=fixture()
        pages[0].words += [word('DEL RIO',155,160),word('MARIA',315,160)]
        record=self.module().parse_award_pages(pages,metadata)[0]
        self.assertEqual(record['name'],'PRUEBA DEL RIO UNO, ANA MARIA')

    def test_substitution_notes_do_not_pollute_cells_or_expose_another_identity(self):
        pages,metadata=fixture()
        pages[0].words += [word('Sustituye',749,178),word('a',784,178),word('***9876**',790,178)]
        record=self.module().parse_award_pages(pages,metadata)[0]
        self.assertNotIn('9876',str(record))
        self.assertEqual(record['workload'],'Tiempo Parcial 10 horas')

    def test_reviewed_assigned_variant_keeps_its_published_group_and_raw_function(self):
        pages,metadata=fixture()
        for w in pages[0].words:
            if w['x0']==615 and w['top']>130: w['text']='059009S'
        metadata['assigned_function_groups']={'059009S':'0590I09'}
        record=self.module().parse_award_pages(pages,metadata)[0]
        self.assertEqual(record['specialty'],'0590I09')
        self.assertEqual(record['assigned_function'],'059009S')

    def test_rejects_missing_reordered_provisional_or_wrong_process_pages(self):
        for kind in ('missing','reordered','provisional','process','date','closing'):
            with self.subTest(kind=kind):
                pages,metadata=fixture()
                if kind=='missing': pages.pop(1)
                if kind=='reordered': pages[0],pages[1]=pages[1],pages[0]
                if kind=='provisional': pages[0].text=pages[0].text.replace('Definitivo','Provisional')
                if kind=='process': pages[1].text=pages[1].text.replace('3125','9999')
                if kind=='date': pages[1].text=pages[1].text.replace('24/09/2026','25/09/2026')
                if kind=='closing': pages[2].text=pages[2].text.replace('EL CONSEJERO','FALTA FIRMA')
                with self.assertRaises(ValueError): self.module().parse_award_pages(pages,metadata)

    def test_rejects_dropped_rows_changed_columns_or_conflicting_function(self):
        for kind in ('number','name','rect','code','column','body','count','per_page'):
            with self.subTest(kind=kind):
                pages,metadata=fixture()
                if kind=='number': pages[0].words=[w for w in pages[0].words if w['text']!='26300010']
                if kind=='name': pages[0].words=[w for w in pages[0].words if w['text']!='ANA']
                if kind=='rect': pages[0].rects=[]
                if kind=='code': pages[0].words[-5]['text']='0590I19'
                if kind=='column': pages[0].words=[w for w in pages[0].words if w['text']!='Apellido1']
                if kind=='body': metadata['specialties'][0]['body']='OTRO CUERPO'
                if kind=='count': metadata['row_count']=2
                if kind=='per_page': metadata['page_row_counts']=[2,1,0]
                with self.assertRaises(ValueError): self.module().parse_award_pages(pages,metadata)

    def test_duplicate_awards_are_rejected_instead_of_silently_merged(self):
        pages,metadata=fixture()
        pages[1]=Page(2,[('26300010','PRUEBA','UNO','ANA'),('26300030','PRUEBA','TRES','SOL')])
        with self.assertRaises(ValueError): self.module().parse_award_pages(pages,metadata)

    def test_unknown_kind_and_unreviewed_metadata_fail_closed(self):
        for field,value in [('kind','provisional'),('page_row_counts',None),('specialties',[])]:
            pages,metadata=fixture();metadata[field]=value
            with self.subTest(field=field), self.assertRaises(ValueError): self.module().parse_award_pages(pages,metadata)

    def test_hash_gate_rejects_challenge_or_changed_bytes_before_pdf_extraction(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'source.pdf'
            for payload,digest in [(b'<html>captcha</html>',hashlib.sha256(b'<html>captcha</html>').hexdigest()),
                                   (b'%PDF-1.4 changed', '0'*64)]:
                path.write_bytes(payload)
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    self.module().read_document(path,{'sha256':digest})

    def test_scan_future_complete_document_derives_metadata_but_never_a_rank(self):
        pages,expected=fixture()
        module=self.module()
        self.assertTrue(callable(getattr(module,'scan_document',None)), 'Missing complete future-document scan')
        with TemporaryDirectory() as directory:
            path=Path(directory)/'source.pdf'; path.write_bytes(b'%PDF-1.4 test fixture')
            with patch.object(module.pdfplumber,'open') as opened:
                opened.return_value.__enter__.return_value=SimpleNamespace(pages=pages)
                result=module.scan_document(path,'https://www.carm.es/web/descarga?IDCONTENIDO=209126',
                                            '2026-10-02T20:06:59Z')
        self.assertEqual(result['metadata']['row_count'],3)
        self.assertEqual(result['metadata']['page_row_counts'],[1,2,0])
        self.assertEqual(result['metadata']['specialties'],expected['specialties'])
        self.assertEqual(result['metadata']['published_at'],'2026-09-24')
        self.assertEqual(result['metadata']['process_id'],'3125')
        self.assertEqual(result['metadata']['content_id'],'209126')
        self.assertTrue(all(r['rank'] is None for r in result['rows']))

    def test_future_scan_rejects_repeated_or_disagreeing_page_headers(self):
        module=self.module()
        self.assertTrue(callable(getattr(module,'scan_document',None)), 'Missing complete future-document scan')
        for mutation in ('repeat','listed_date','publication_time','partial'):
            pages,_=fixture()
            if mutation=='repeat': pages[1]=pages[0]
            if mutation=='listed_date': pages[1].text=pages[1].text.replace('24 de Septiembre','23 de Septiembre')
            if mutation=='publication_time': pages[1].text=pages[1].text.replace('14:16','15:16')
            if mutation=='partial': pages[1].words.pop()
            with TemporaryDirectory() as directory:
                path=Path(directory)/'source.pdf';path.write_bytes(b'%PDF-1.4 test fixture')
                with patch.object(module.pdfplumber,'open') as opened:
                    opened.return_value.__enter__.return_value=SimpleNamespace(pages=pages)
                    with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                        module.scan_document(path,'https://www.carm.es/web/descarga?IDCONTENIDO=209126',
                                             '2026-10-02T20:06:59Z')


if __name__=='__main__': unittest.main()
