"""Fail-closed parser for the reviewed CARM weekly unfilled-vacancies template.

Acceptance is structural, not electronic-signature authentication. The reviewed
corpus is tests/fixtures/carm-2026-09-30.pdf; only its seven-column landscape
template is accepted. Function codes are validated structurally; their labels
are retained from the original instead of guessed from a speciality dictionary.
No OCR, network or filesystem access is performed. A caller must enforce process
CPU/memory/time limits in addition to the byte/page budgets enforced here.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pdfplumber


PARSER_VERSION = "carm-sin-cubrir/1.0.0"
MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 50
TITLE = "Listado de Vacantes Sin Cubrir de Secundaria"
HEADERS = ["Centro", "Municipio", "Función", "Cupo", "Iti", "Jornada", "Sin Cubrir"]
COLUMNS = [35, 285, 373, 638, 668, 688, 770, 824]
BODIES = {
    "0590": "Secundaria",
    "0592": "Escuelas oficiales de idiomas",
    "0593": "Catedráticos de música y artes escénicas",
    "0594": "Música y artes escénicas",
    "0596": "Maestros de taller de artes plásticas",
    "0598": "Sectores singulares de FP",
}
LANGUAGES = {"A": "Alemán", "F": "Francés", "I": "Inglés"}
MONTHS = {name: n for n, name in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"), 1)}
NOTICE = re.compile(r"Convocatoria: (Adjudicación semanal) (\d{2}/\d{2}/\d{4})\. Proceso ([1-9]\d{0,9}) - Listado a (\d{1,2}) de ([A-Za-záéíóú]+) de (\d{4}), a las (\d{2}:\d{2})")


class ParseError(ValueError):
    """Extraction is incomplete, invalid or outside the reviewed template."""


def _normal(value):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ParseError("Missing or invalid table cell")
    return " ".join(value.split())


def _utc(value):
    return value.astimezone(timezone.utc).isoformat()


def validate_page_header(text, *, page_number, page_count):
    """Validate title, issue metadata, and the physical page's printed identity."""
    lines = text.splitlines()
    if not lines or lines[0] != TITLE or len(lines) < 3:
        raise ParseError("Unknown or missing vacancy document header")
    match = NOTICE.fullmatch(lines[1])
    if not match:
        raise ParseError("Unknown procedure or issue header")
    footer = f"Página {page_number} de {page_count}"
    if lines[-1] != footer or len(re.findall(r"Página \d+ de \d+", text)) != 1:
        raise ParseError("Missing or inconsistent page sequence")
    act_title, act_date, process_id, day, month, year, clock = match.groups()
    try:
        act = datetime.strptime(act_date, "%d/%m/%Y").date()
        hour, minute = map(int, clock.split(":"))
        issued = datetime(int(year), MONTHS[month.lower()], int(day), hour, minute, tzinfo=ZoneInfo("Europe/Madrid"))
        # A local clock repeated or skipped on a daylight-saving transition is
        # not enough evidence to choose an instant automatically.
        if issued.utcoffset() != issued.replace(fold=1).utcoffset():
            raise ValueError("ambiguous clock")
        if issued.astimezone(timezone.utc).astimezone(issued.tzinfo).replace(tzinfo=None) != issued.replace(tzinfo=None):
            raise ValueError("nonexistent clock")
        if act > issued.date():
            raise ValueError("issue precedes act")
    except (ValueError, KeyError) as exc:
        raise ParseError("Invalid act or issue date/time") from exc
    return {"title": TITLE, "act_title": act_title, "act_date": act.isoformat(), "process_id": process_id, "published_at": _utc(issued), "document_issued_at": _utc(issued)}


def validate_table(header, cells, *, page, document_id, cell_bboxes):
    """Validate extracted cells independently of PDF decoding; preserve each row.

    Every row has seven nonempty cells and seven contiguous, finite, increasing
    cell rectangles. Murcia centre IDs have eight digits starting 30, function
    codes have body 05xx and a three-digit or A/F/I plus two-digit speciality,
    label is nonempty original text, Cupo is VS/VP, Iti is N/S,
    jornada is Completa or Tiempo Parcial 1..40 horas, quantity is 1..999.
    """
    if not isinstance(header, (list, tuple)) or [_normal(c) for c in header] != HEADERS:
        raise ParseError("Unknown table columns")
    if not cells or len(cells) > 22 or len(cell_bboxes) != len(cells):
        raise ParseError("Empty, oversized or incomplete table")
    result = []
    for number, (raw, boxes) in enumerate(zip(cells, cell_bboxes), 1):
        if len(raw) != 7 or len(boxes) != 7:
            raise ParseError("Incomplete row or coordinates")
        values = [_normal(v) for v in raw]
        center = re.fullmatch(r"(30\d{6}) (\S.*)", values[0])
        function = re.fullmatch(r"(05\d{2}(?:\d{3}|[AFI]\d{2})) (\S.*)", values[2])
        if not center or not function:
            raise ParseError("Invalid centre or function code")
        code, label = function.groups()
        if values[3] not in {"VP", "VS"} or values[4] not in {"N", "S"}:
            raise ParseError("Unknown Cupo or Iti code")
        hours = None
        if values[5] == "Completa":
            workload = "full"
        else:
            partial = re.fullmatch(r"Tiempo Parcial ([1-9]\d?) horas", values[5])
            if not partial or not 1 <= int(partial[1]) <= 40:
                raise ParseError("Unknown or invalid jornada")
            hours, workload = int(partial[1]), "partial"
        if not re.fullmatch(r"[1-9]\d{0,2}", values[6]):
            raise ParseError("Invalid vacancy quantity")
        for index, box in enumerate(boxes):
            if box is None or len(box) != 4 or not all(isinstance(n, (int, float)) and math.isfinite(n) for n in box):
                raise ParseError("Missing or invalid cell coordinates")
            x0, top, x1, bottom = box
            if x1 <= x0 or bottom <= top or top < 0 or bottom > 595:
                raise ParseError("Invalid cell rectangle")
            if abs(x0 - COLUMNS[index]) > 2 or abs(x1 - COLUMNS[index+1]) > 2:
                raise ParseError("Unknown table column geometry")
            if abs(top - boxes[0][1]) > 1 or abs(bottom - boxes[0][3]) > 1:
                raise ParseError("Split or merged table row")
        result.append({
            "id": f"{document_id}:{page}:{number}", "document_id": document_id,
            "page": page, "row_number": number,
            "center_code": center[1], "center": center[2], "municipality": values[1],
            "function_code": code, "function": label, "body_code": code[:4], "body": BODIES.get(code[:4], "Otros cuerpos"),
            "cupo": values[3], "itinerant": values[4], "jornada": values[5], "workload": workload,
            "hours": hours, "quantity": int(values[6]), "language": LANGUAGES.get(code[4], "Sin mención bilingüe"),
            "duration": None, "eligibility": "not_evaluated", "raw_cells": list(raw),
            "bbox": [float(boxes[0][0]), float(boxes[0][1]), float(boxes[-1][2]), float(boxes[0][3])],
            "cell_bboxes": [[float(n) for n in box] for box in boxes],
        })
    return result


def _signature_page(text, metadata):
    lines = text.splitlines()[2:-1]
    if len(lines) != 5:
        raise ParseError("Empty page or unknown closing page")
    match = re.fullmatch(r"Murcia, a (\d{1,2}) de ([a-záéíóú]+) de (\d{4})", lines[0])
    try:
        date = datetime(int(match[3]), MONTHS[match[2]], int(match[1])).date() if match else None
    except (ValueError, KeyError) as exc:
        raise ParseError("Invalid signature page date") from exc
    local_issue_date = datetime.fromisoformat(metadata["document_issued_at"]).astimezone(ZoneInfo("Europe/Madrid")).date()
    if date is None or date != local_issue_date:
        raise ParseError("Inconsistent signature page date")
    if lines[1:5] != ["EL CONSEJERO DE EDUCACIÓN Y FORMACIÓN PROFESIONAL", "P.D.(Orden de 29/09/2023, BORM nº 229)", "LA D.G. DE RECURSOS HUMANOS, PLANIFICACIÓN EDUCATIVA E INNOVACIÓN", "María del Mar Sánchez Rodríguez"]:
        raise ParseError("Unreviewed signature block")


def _parse_pages(pdf, document_id):
    pages = pdf.pages
    if not 1 <= len(pages) <= MAX_PAGES:
        raise ParseError("PDF page budget exceeded or no pages")
    metadata, rows, counts = None, [], []
    for number, page in enumerate(pages, 1):
        if abs(page.width - 842) > 2 or abs(page.height - 595) > 2 or page.rotation not in {0, 90}:
            raise ParseError("Unknown page size or rotation")
        text = page.extract_text() or ""
        current = validate_page_header(text, page_number=number, page_count=len(pages))
        if metadata is None:
            metadata = current
        elif current != metadata:
            raise ParseError("Inconsistent dates, process or header between pages")
        top_text = page.crop((0, 0, page.width, 85)).extract_text() or ""
        if top_text != "\n".join(text.splitlines()[:2]):
            raise ParseError("Unknown header geometry or stray content")
        tables = page.find_tables()
        if not tables:
            if number != len(pages) or not rows:
                raise ParseError("Missing vacancy table on data page; OCR unavailable")
            _signature_page(text, metadata)
            counts.append(0)
            continue
        if len(tables) != 1:
            raise ParseError("Unexpected multiple tables")
        table = tables[0]
        extracted = table.extract()
        if abs(table.bbox[1] - (87 if number == 1 else 85)) > 2 or table.bbox[3] > 547:
            raise ParseError("Unknown table position")
        if number > 1 and counts[-1] != (21 if number == 2 else 22):
            raise ParseError("Incomplete preceding data page")
        page_rows = validate_table(extracted[0], extracted[1:], page=number, document_id=document_id, cell_bboxes=[r.cells for r in table.rows[1:]])
        if len(page_rows) > (21 if number == 1 else 22):
            raise ParseError("Unexpected page row count")
        for row in page_rows:
            if not 18 <= row["bbox"][3] - row["bbox"][1] <= 22:
                raise ParseError("Unknown row height or merged rows")
        # Independently account for every centre ID in the page text. Extra or
        # missing IDs indicate that table detection dropped visible content.
        if Counter(re.findall(r"\b30\d{6}\b", text)) != Counter(r["center_code"] for r in page_rows):
            raise ParseError("Vacancy text and extracted table disagree")
        after = page.crop((0, table.bbox[3] + 0.5, page.width, page.height)).extract_text() or ""
        if after != f"Página {number} de {len(pages)}":
            raise ParseError("Unparsed content below table")
        rows.extend(page_rows)
        counts.append(len(page_rows))
    if not rows:
        raise ParseError("Unexpectedly empty vacancy extraction")
    return metadata, rows, counts


def parse_pdf(data: bytes, source_url: str, retrieved_at: str) -> dict:
    """Extract a fully validated known official PDF or raise ParseError."""
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        raise ParseError("Invalid PDF bytes or download budget exceeded")
    trailer = re.search(rb"startxref\s+(\d+)\s+%%EOF\s*\Z", data)
    if not re.match(rb"%PDF-1\.[0-9]\b", data) or not trailer:
        raise ParseError("Missing PDF signature or complete trailer")
    xref_offset = int(trailer[1])
    if not 0 < xref_offset < trailer.start() or data[xref_offset:xref_offset+4] != b"xref":
        raise ParseError("Invalid or unreviewed PDF cross-reference structure")
    try:
        url = urlsplit(source_url)
        if url.scheme != "https" or url.hostname not in {"www.carm.es", "rrhheducacion.carm.es"} or url.username or url.password or url.port not in {None, 443} or url.fragment:
            raise ValueError("nonofficial URL")
        retrieved = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        if retrieved.tzinfo is None or retrieved.utcoffset() is None:
            raise ValueError("naive timestamp")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ParseError("Official source URL and timezone-aware retrieval timestamp required") from exc
    digest = hashlib.sha256(data).hexdigest()
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if pdf.doc.encryption is not None:
                raise ParseError("Encrypted PDF is unsupported")
            metadata, rows, counts = _parse_pages(pdf, digest)
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError("PDF decoding failed or unsupported document") from exc
    normalized = [{k: v for k, v in row.items() if k not in {"id", "document_id", "page", "row_number", "raw_cells", "bbox", "cell_bboxes"}} for row in rows]
    # Sorting keeps content identity stable across harmless page reflow while
    # retaining duplicates. Issue metadata belongs to the publication identity.
    semantic = {**metadata, "rows": sorted(normalized, key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False))}
    semantic_digest = hashlib.sha256(json.dumps(semantic, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    duplicates = sum(count > 1 for count in Counter(tuple(r["raw_cells"]) for r in rows).values())
    warnings = [f"{duplicates} grupos contienen filas idénticas en el original. Se conservan por separado; no se eliminan como duplicados."] if duplicates else []
    return {
        **metadata, "id": digest, "sha256": digest, "semantic_sha256": semantic_digest,
        "pages": len(counts), "page_counts": counts, "row_count": len(rows), "places": sum(r["quantity"] for r in rows),
        "parser_version": PARSER_VERSION, "warnings": warnings, "byte_size": len(data), "source_url": source_url,
        "provenance": "official_download", "provenance_label": "Descarga del origen oficial; plantilla y celdas validadas. Firma electrónica no autenticada.",
        "authenticated": False, "status": "approved", "downloaded_at": _utc(retrieved), "retrieved_at": _utc(retrieved),
        "imported_at": _utc(retrieved), "replaces_id": None, "rows": rows,
    }
