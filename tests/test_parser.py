"""Strict extraction checks against the immutable official corpus and bad inputs."""
import hashlib
import importlib
import io
import json
from pathlib import Path
import unittest

import pdfplumber


FIXTURE = Path(__file__).parent / "fixtures" / "carm-2026-09-30.pdf"
SHA256 = "81cd8ac0cbf38e828198fe37b0f7fb7132aeaa585c1633fe749ef1b3cec41280"
SOURCE = "https://www.carm.es/web/descarga?ALIAS=ARCH&ARCHIVO=ADJVACANTESSEC_SINCUBRIR-499487.pdf&IDCONTENIDO=209318&IDTIPO=60&RASTRO=c77%24m22725%2C22759%2C4254"
RETRIEVED = "2026-10-01T07:00:00+00:00"
HEADER = ["Centro", "Municipio", "Función", "Cupo", "Iti", "Jornada", "Sin Cubrir"]
ROW = ["30011764 IES MIGUEL HERNÁNDEZ", "ALHAMA DE MURCIA", "0590I06 MATEMATICAS / INGLES", "VS", "N", "Completa", "1"]
BOXES = [[35, 107, 285, 127], [285, 107, 373, 127], [373, 107, 638, 127], [638, 107, 668, 127], [668, 107, 688, 127], [688, 107, 770, 127], [770, 107, 824, 127]]


def simple_pdf(text, *, page_count=1, encrypted=False):
    """Minimal real PDF: no optional test dependency or mocked parser."""
    stream = b"BT /F1 12 Tf 35 550 Td (" + text.encode("latin1") + b") Tj ET"
    return pdf_streams([stream] * page_count, encrypted=encrypted)


def pdf_streams(streams, *, encrypted=False):
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    for stream in streams:
        number = len(objects) + 1
        kids.append(f"{number} 0 R")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Resources << /Font << /F1 {number+2} 0 R >> >> /Contents {number+1} 0 R >>".encode())
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(streams)} >>".encode()
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    output.extend(b"".join(f"{off:010} 00000 n \n".encode() for off in offsets[1:]))
    encryption = " /Encrypt << /Filter /Standard /V 1 /R 2 /O () /U () /P -4 >>" if encrypted else ""
    output.extend(f"trailer\n<< /Root 1 0 R /Size {len(objects)+1}{encryption} >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def template_pdf(counts, *, process_ids=None, dates=None, bad_footer=False, bad_header=False, closing=False, clock="14:35"):
    """Independently draw known tables to exercise the actual PDF boundary."""
    streams = []
    columns = [35, 285, 373, 638, 668, 688, 770, 824]
    for page, count in enumerate(counts, 1):
        operations = []
        def text(x, top, value, size=7):
            value = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            operations.append(f"BT /F1 {size} Tf {x} {595-top} Td ({value}) Tj ET")
        text(35, 40, "Listado de Vacantes Sin Cubrir de Secundaria", 12)
        process = process_ids[page-1] if process_ids else "3133"
        date = dates[page-1] if dates else "30/09/2026"
        text(35, 60, f"Convocatoria: Adjudicación semanal {date}. Proceso {process} - Listado a 30 de Septiembre de 2026, a las {clock}", 8)
        text(720, 575, f"Página {2 if bad_footer else page} de {len(counts)}", 7)
        if count is not None:
            top = 87 if page == 1 else 85
            bottom = top + 20 * (count + 1)
            for x in columns:
                operations.append(f"{x} {595-top} m {x} {595-bottom} l S")
            for index in range(count + 2):
                y = 595 - top - 20 * index
                operations.append(f"35 {y} m 824 {y} l S")
            values = HEADER.copy()
            if bad_header:
                values[-1] = "Extra"
            for index, value in enumerate(values):
                text(columns[index]+2, top+12, value)
            for index in range(count):
                for column, value in enumerate(ROW):
                    text(columns[column]+2, top+32+20*index, value)
        elif closing:
            # Deliberately omit signer: this must not be mistaken for a known
            # zero-row closing page.
            text(35, 140, "Murcia, a 30 de septiembre de 2026")
            if closing == "valid":
                text(35, 170, "EL CONSEJERO DE EDUCACIÓN Y FORMACIÓN PROFESIONAL")
                text(35, 200, "P.D.(Orden de 29/09/2023, BORM nº 229)")
                text(35, 230, "LA D.G. DE RECURSOS HUMANOS, PLANIFICACIÓN EDUCATIVA E INNOVACIÓN")
                text(35, 260, "María del Mar Sánchez Rodríguez")
        streams.append("\n".join(operations).encode("latin1"))
    return pdf_streams(streams)


class ParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = FIXTURE.read_bytes()
        cls.parser = importlib.import_module("bolsa_abierta.parser") if importlib.util.find_spec("bolsa_abierta.parser") else None

    def require_parser(self):
        self.assertIsNotNone(self.parser, "Strict official PDF parser has not been implemented")
        return self.parser

    def parse(self, data=None, source=SOURCE, retrieved=RETRIEVED):
        return self.require_parser().parse_pdf(self.data if data is None else data, source, retrieved)

    def test_official_fixture_preserves_totals_dates_and_provenance(self):
        self.assertEqual(hashlib.sha256(self.data).hexdigest(), SHA256)
        doc = self.parse()
        self.assertEqual((doc["id"], doc["sha256"], doc["byte_size"]), (SHA256, SHA256, 170551))
        self.assertEqual((doc["process_id"], doc["act_date"], doc["published_at"]), ("3133", "2026-09-30", "2026-09-30T12:35:00+00:00"))
        self.assertEqual((doc["row_count"], doc["places"], doc["page_counts"]), (77, 85, [21, 22, 22, 12, 0]))
        self.assertEqual((doc["pages"], doc["status"], doc["provenance"], doc["authenticated"]), (5, "approved", "official_download", False))
        self.assertEqual(doc["source_url"], SOURCE)
        self.assertEqual(doc["downloaded_at"], RETRIEVED)
        self.assertRegex(doc["semantic_sha256"], r"^[a-f0-9]{64}$")

    def test_all_raw_cells_and_coordinates_are_retained(self):
        doc = self.parse()
        with pdfplumber.open(io.BytesIO(self.data)) as pdf:
            originals = [(page.page_number, n, row) for page in pdf.pages for table in page.extract_tables() for n, row in enumerate(table[1:], 1)]
        self.assertEqual([(r["page"], r["row_number"], r["raw_cells"]) for r in doc["rows"]], originals)
        row = doc["rows"][0]
        self.assertEqual((row["center_code"], row["center"], row["municipality"], row["function_code"], row["function"]), ("30011764", "IES MIGUEL HERNÁNDEZ", "ALHAMA DE MURCIA", "0590I06", "MATEMATICAS / INGLES"))
        self.assertEqual((row["language"], row["body_code"], row["body"], row["hours"], row["workload"]), ("Inglés", "0590", "Secundaria", None, "full"))
        self.assertEqual(len(row["cell_bboxes"]), 7)
        self.assertEqual(row["bbox"][0::2], [35.0, 824.0])
        self.assertEqual(row["id"], SHA256 + ":1:1")
        self.assertEqual(doc["rows"][-1]["hours"], 10)
        self.assertEqual(doc["rows"][-1]["body"], "Sectores singulares de FP")

    def test_identical_original_rows_keep_distinct_ids(self):
        rows = self.parse()["rows"]
        duplicates = [r for r in rows if r["center_code"] == "30008340" and r["function_code"] == "0590107" and r["jornada"] == "Completa"]
        self.assertEqual(len(duplicates), 2)
        self.assertEqual([r["row_number"] for r in duplicates], [18, 19])
        self.assertNotEqual(duplicates[0]["id"], duplicates[1]["id"])

    def test_download_time_does_not_change_semantic_identity(self):
        first = self.parse()
        second = self.parse(retrieved="2026-10-02T08:00:00+00:00")
        self.assertEqual(first["semantic_sha256"], second["semantic_sha256"])
        self.assertEqual(first["published_at"], second["published_at"])

    def test_invalid_and_unknown_documents_fail_closed(self):
        parser = self.require_parser()
        for data in (b"<html>Challenge</html>", self.data[:-100], simple_pdf("Unknown publication"), simple_pdf("", page_count=2), simple_pdf("", encrypted=True), simple_pdf("", page_count=51), b"%PDF-1.4\n" + b" " * (10 * 1024 * 1024)):
            with self.subTest(size=len(data)), self.assertRaises(parser.ParseError):
                self.parse(data)

    def test_non_official_source_or_naive_timestamp_rejected(self):
        parser = self.require_parser()
        for source, retrieved in (("https://example.com/test.pdf", RETRIEVED), (SOURCE, "2026-10-01T07:00:00"), ("https://www.carm.es@evil.example/test.pdf", RETRIEVED)):
            with self.subTest(source=source, retrieved=retrieved), self.assertRaises(parser.ParseError):
                self.parse(source=source, retrieved=retrieved)

    def test_table_helper_rejects_bad_schema_cells_codes_and_quantities(self):
        parser = self.require_parser()
        errors = [(0, "99999999 IES TEST"), (0, "30011764"), (1, ""), (2, "9999I06 MATEMATICAS / INGLES"), (2, "0590X06 MATEMATICAS / INGLES"), (2, "0590I06"), (3, "UNKNOWN"), (4, "?"), (5, "Tiempo Parcial 0 horas"), (5, "Tiempo Parcial 41 horas"), (5, "Media jornada"), (6, "0"), (6, "-1"), (6, "1.5"), (6, "10000"), (6, None)]
        for index, value in errors:
            invalid = ROW.copy()
            invalid[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(parser.ParseError):
                parser.validate_table(HEADER, [invalid], page=1, document_id=SHA256, cell_bboxes=[BOXES])
        for header, cells in ((HEADER + ["Extra"], [ROW]), (HEADER[:-1], [ROW]), (HEADER, [ROW[:-1]]), (HEADER, [])):
            with self.subTest(header=header, cells=cells), self.assertRaises(parser.ParseError):
                parser.validate_table(header, cells, page=1, document_id=SHA256, cell_bboxes=[BOXES])

    def test_table_helper_normalizes_lines_without_inventing_text(self):
        parser = self.require_parser()
        row = ROW.copy()
        row[1] = "ALHAMA DE\nMURCIA"
        row[5] = "Tiempo Parcial 7\nhoras"
        result = parser.validate_table(HEADER, [row, row], page=2, document_id=SHA256, cell_bboxes=[BOXES, BOXES])
        self.assertEqual((result[0]["municipality"], result[0]["hours"], result[0]["workload"]), ("ALHAMA DE MURCIA", 7, "partial"))
        self.assertEqual(result[0]["raw_cells"][1], "ALHAMA DE\nMURCIA")
        self.assertEqual(len(result), 2)

    def test_page_headers_reject_missing_title_footer_and_invalid_dates(self):
        parser = self.require_parser()
        text = "Listado de Vacantes Sin Cubrir de Secundaria\nConvocatoria: Adjudicación semanal 30/09/2026. Proceso 3133 - Listado a 30 de Septiembre de 2026, a las 14:35\nPágina 1 de 5"
        metadata = parser.validate_page_header(text, page_number=1, page_count=5)
        self.assertEqual(metadata["process_id"], "3133")
        for invalid in (text.replace("Listado de Vacantes Sin Cubrir de Secundaria", "Resultados definitivos"), text.replace("Página 1 de 5", "Página 2 de 5"), text.replace("Página 1 de 5", "Página 1 de 6"), text.replace("Página 1 de 5", ""), text.replace("30 de Septiembre", "31 de Septiembre"), text.replace("14:35", "25:35"), text.replace("Adjudicación semanal", "Proceso desconocido")):
            with self.subTest(text=invalid), self.assertRaises(parser.ParseError):
                parser.validate_page_header(invalid, page_number=1, page_count=5)

    def test_real_pdf_page_drift_and_missing_rows_are_rejected(self):
        parser = self.require_parser()
        valid = self.parse(template_pdf([21, 1]))
        self.assertEqual(valid["page_counts"], [21, 1])
        for data in (template_pdf([1, 1]), template_pdf([21, 1], process_ids=["3133", "3134"]), template_pdf([21, 1], dates=["30/09/2026", "29/09/2026"]), template_pdf([1], bad_footer=True), template_pdf([1], bad_header=True), template_pdf([0]), template_pdf([21, None]), template_pdf([21, None], closing=True)):
            with self.subTest(size=len(data)), self.assertRaises(parser.ParseError):
                self.parse(data)

    def test_table_rejects_missing_or_merged_cell_coordinates(self):
        parser = self.require_parser()
        for boxes in ([None] + BOXES[1:], [[35, 107, 285, float("nan")]] + BOXES[1:], [[35, 107, 285, 107]] + BOXES[1:], [[35, 107, 290, 127]] + BOXES[1:], [BOXES[0], [285, 108, 373, 150]] + BOXES[2:]):
            with self.subTest(boxes=boxes), self.assertRaises(parser.ParseError):
                parser.validate_table(HEADER, [ROW], page=1, document_id=SHA256, cell_bboxes=[boxes])

    def test_new_plausible_speciality_preserves_code_and_label(self):
        parser = self.require_parser()
        row = ROW.copy()
        row[2] = "0594999 NUEVA ESPECIALIDAD PUBLICADA"
        result = parser.validate_table(HEADER, [row], page=1, document_id=SHA256, cell_bboxes=[BOXES])[0]
        self.assertEqual((result["function_code"], result["function"]), ("0594999", "NUEVA ESPECIALIDAD PUBLICADA"))
        row[2] = "0599999 NOMBRE ORIGINAL"
        result = parser.validate_table(HEADER, [row], page=1, document_id=SHA256, cell_bboxes=[BOXES])[0]
        self.assertEqual((result["body_code"], result["body"]), ("0599", "Otros cuerpos"))

    def test_midnight_issue_validates_signature_date_in_madrid(self):
        doc = self.parse(template_pdf([1, None], closing="valid", clock="00:35"))
        self.assertEqual(doc["published_at"], "2026-09-29T22:35:00+00:00")
        self.assertEqual(doc["page_counts"], [1, 0])

    def test_unusable_xref_is_not_recovered_as_approved_pdf(self):
        parser = self.require_parser()
        data = template_pdf([1])
        trailer_start = data.rfind(b"startxref")
        invalid = data[:trailer_start] + b"startxref\n0\n%%EOF\n"
        with self.assertRaises(parser.ParseError):
            self.parse(invalid)


if __name__ == "__main__":
    unittest.main()
