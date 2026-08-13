"""Lectura de la ficha de máquina del informe PDF y documento DiagGT.

Geometría de la ficha (auditoría de lectura completa 2026-07-28)
---------------------------------------------------------------
El maquetador reparte los bloques de la ficha entre dos columnas según quepan,
así que **ninguna sección tiene columna fija**. En particular
``DIAGNÓSTICOS PREVIOS:`` cae en la izquierda en ~4 de cada 5 fichas, y leer
sólo la derecha perdía el 87 % de los diagnósticos retrospectivos. De ahí:

  (a) los previos se leen de las **cuatro fuentes** (izquierda/derecha x
      sección/``_pre``) y se deduplican por (fecha, modalidad);
  (b) las **páginas de continuación** sin cabecera de máquina se arrastran a la
      última ficha vista;
  (c) :func:`column_text` recorta cabecera y pie de página en **las dos**
      columnas;
  (d) ``global_status_label`` se valida contra un vocabulario cerrado;
  (e) los **pies de figura** se separan del texto a ``figures``.

Invariante de anclas: para cada ficha, el número de anclas
``-DD/MM/AAAA: (Modalidad)`` que aparecen en el cuerpo de la página tiene que
ser exactamente el que suman las cuatro fuentes. Si no cuadra, es que la
geometría se ha vuelto a comer texto — :func:`build_document` lo cuenta y el
CLI aborta.

``pdfplumber`` es un extra (``ams-extract[informes]``): este módulo sólo se
importa desde el comando que lo necesita.
"""

# pdfplumber es un extra y no lleva stubs: sus dicts de palabra entran como
# Any y el tipado estricto no puede seguirlos más allá de la frontera.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportUnknownLambdaType=false

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pdfplumber  # pyright: ignore[reportMissingImports]
import structlog

from ams_extract.informes import EXTRACTOR_VERSION
from ams_extract.informes.rules import (
    GLOBAL_STATUS_RE,
    MODALITY_MAP,
    SCHEMA_VERSION,
    map_findings,
    map_status,
    norm_tag,
    status_from_text,
)

_log = structlog.get_logger(__name__)

COLUMN_SPLIT_X = 297.0
"""A4 mide 595 pt: las páginas de máquina son a dos columnas."""

HEADER_Y = 45.0
"""Por encima de esta ``top`` está la cabecera del documento (REF, fecha)."""

FOOTER_MARGIN = 40.0
"""Por debajo de ``height - 40`` está el número de página."""

ORIGIN = "inspection-report"
PROVIDER = "Preditec"
EXTRACTION_METHOD = "pdf_text_parse"

SECTION_HEADS = ("DIAGNÓSTICO:", "RECOMENDACIÓN:", "ANÁLISIS:", "DIAGNÓSTICOS PREVIOS:")
PREVIOUS_HEAD = "DIAGNÓSTICOS PREVIOS:"

FIGURE_RE = re.compile(
    r"^(Tendencias?|Espectros?|Evoluci[oó]n|Firmas?|Formas? de onda|"
    r"Comparaci[oó]n|Waterfall|Cascada|[OÓ]rbitas?|Diagrama)\b"
)
"""Arranques de pie de figura (catálogo cerrado, auditoría §3.9.3)."""

FIGURE_CONT_RE = re.compile(r"^[^A-ZÁÉÍÓÚÑ]")
"""Un pie se prolonga mientras las líneas arranquen en minúscula o signo.

Los pies parten a mitad de sintagma; la prosa de análisis siempre reabre con
mayúscula.
"""

CAPTION_SECTIONS = ("ANÁLISIS:", PREVIOUS_HEAD, "_pre")
"""Secciones donde se filtran los pies.

No en DIAGNÓSTICO/RECOMENDACIÓN, cuyas líneas nunca son leyendas y sí pueden
empezar por «Espectros …».
"""

MODALITY_SPLIT_RE = re.compile(
    r"(Vibraciones|Inspecci[oó]n visual|Termograf[ií]a|Ultrasonidos):", re.U
)
OVERFLOW_MODALITY_ANCHORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "vibration",
        re.compile(r"\bvibratori|\bpeakvue\b|\bfirmas? espectral", re.I),
    ),
    (
        "ultrasound",
        re.compile(
            r"\bultrasonid|\bmedidas? (?:realizadas? )?mediante ultrasonidos", re.I
        ),
    ),
    ("thermography", re.compile(r"\btermograf|\btermograma", re.I)),
    ("visual_inspection", re.compile(r"\binspecci[oó]n visual", re.I)),
)
"""Anclas léxicas que permiten atribuir un ``_pre`` sin etiqueta.

El maquetador puede desbordar ``ANÁLISIS`` a la columna derecha sin repetir ni
la cabecera de sección ni la modalidad. No basta con asumir que pertenece a la
única modalidad ya vista: la ficha de abril de ``TC.1523A2`` tiene Vibraciones
a la izquierda y Ultrasonidos a la derecha. Sólo se recupera el párrafo cuando
su propio vocabulario deja una modalidad inequívoca.
"""
PREV_DIAG_RE = re.compile(r"-\s*(\d{2}/\d{2}/\d{4}):\s*\(([^)]+)\)\s*")
TITLE_RE = re.compile(r"^(?:\d+(?:\.\d+)*\s+)?(.+)$")
RPM_RE = re.compile(
    r"RPM1:\s*([\d.,]+)\s*r\.?p\.?m\.?\s*Potencia:\s*([\d.,]+)\s*kW\s*RPM2:\s*([\d.,]+)",
    re.S,
)
TAG_TOKEN_RE = re.compile(r"^[A-ZÑ]{2,6}[.\-][A-Z0-9Ñ/.\-]+$")


@dataclass(slots=True)
class ExtractionReport:
    """Contadores de la invariante de anclas y de las continuaciones."""

    fichas: int = 0
    anchors_page: int = 0
    anchors_sources: int = 0
    anchor_mismatch: list[tuple[str, int, str | None, int, int]] = field(default_factory=list)
    continuations: list[tuple[str, int, str | None, int]] = field(default_factory=list)

    @property
    def anchors_ok(self) -> bool:
        return self.anchors_page == self.anchors_sources and not self.anchor_mismatch


# ---------------------------------------------------------------------------
# Reconstrucción de texto por columnas
# ---------------------------------------------------------------------------


def words_to_lines(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agrupa palabras en líneas por coordenada vertical (tolerancia 3 pt)."""
    lines: list[dict[str, Any]] = []
    for word in sorted(words, key=lambda w: (round(w["top"] / 3), w["x0"])):
        if lines and abs(word["top"] - lines[-1]["top"]) <= 3:
            lines[-1]["words"].append(word)
        else:
            lines.append({"top": word["top"], "words": [word]})
    for line in lines:
        line["words"].sort(key=lambda w: w["x0"])
        line["text"] = " ".join(w["text"] for w in line["words"])
        line["x0"] = min(w["x0"] for w in line["words"])
        line["size"] = max(w.get("size", 0) for w in line["words"])
        line["bold"] = any("Bold" in w.get("fontname", "") for w in line["words"])
    return lines


def column_text(
    words: list[dict[str, Any]],
    *,
    left: bool,
    y_min: float = 0.0,
    y_max: float = float("inf"),
) -> list[dict[str, Any]]:
    """Líneas de una columna dentro de la banda vertical ``[y_min, y_max)``.

    ``y_max`` es imprescindible: sin él, el número de página del pie cae dentro
    de la última sección de la columna derecha y se pega al último diagnóstico
    previo (auditoría §3.9.1, 106 textos contaminados).
    """
    selected = [
        w for w in words if (w["x0"] < COLUMN_SPLIT_X) == left and y_min <= w["top"] < y_max
    ]
    return words_to_lines(selected)


def strip_captions(lines: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Separa los pies de figura: devuelve (líneas sin pies, pies)."""
    kept: list[dict[str, Any]] = []
    captions: list[str] = []
    i = 0
    while i < len(lines):
        text = lines[i]["text"].strip()
        if FIGURE_RE.match(text):
            j = i + 1
            while j < len(lines) and FIGURE_CONT_RE.match(lines[j]["text"].strip()):
                j += 1
            captions.append(" ".join(ln["text"].strip() for ln in lines[i:j]))
            i = j
        else:
            kept.append(lines[i])
            i += 1
    return kept, captions


def split_sections(lines: list[dict[str, Any]]) -> tuple[dict[str, str], list[str]]:
    """Divide una columna en secciones por sus cabeceras en negrita.

    Devuelve (secciones, pies de figura). Los pies se filtran de
    :data:`CAPTION_SECTIONS`, donde son leyendas de gráficos que el maquetador
    intercala con el texto (auditoría §3.9.3).
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    current = "_pre"
    for line in lines:
        text = line["text"].strip()
        head = next((h for h in SECTION_HEADS if text.startswith(h)), None)
        if head:
            current = head
            rest = text[len(head) :].strip()
            buckets.setdefault(current, [])
            if current not in order:
                order.append(current)
            if rest:
                buckets[current].append({**line, "text": rest})
        else:
            buckets.setdefault(current, []).append(line)
            if current not in order:
                order.append(current)
    sections: dict[str, str] = {}
    captions: list[str] = []
    for key in order:
        block = buckets[key]
        if key in CAPTION_SECTIONS:
            block, caps = strip_captions(block)
            captions.extend(caps)
        sections[key] = "\n".join(ln["text"].strip() for ln in block).strip()
    return sections, captions


def split_by_modality(section_text: str) -> dict[str, str]:
    """``"Vibraciones: xxx Inspección visual: yyy"`` → ``{vibration: xxx, …}``."""
    out: dict[str, str] = {}
    if not section_text:
        return out
    parts = MODALITY_SPLIT_RE.split(section_text)
    # parts = [prefijo, etiqueta1, texto1, etiqueta2, texto2, …]
    for i in range(1, len(parts) - 1, 2):
        label = parts[i]
        modality = MODALITY_MAP.get(label, MODALITY_MAP.get(label.capitalize()))
        if modality is None:
            modality = label.strip().lower().replace(" ", "_")
        text = parts[i + 1].strip().strip("\n")
        out[modality] = re.sub(r"[ \t]*\n[ \t]*", " ", text).strip()
    return out


def merge_analysis_overflow(analysis: dict[str, str], overflow: str) -> dict[str, str]:
    """Incorpora un desborde derecho de ``ANÁLISIS`` con atribución demostrable.

    Una etiqueta explícita (``Ultrasonidos:``) es el ancla más fuerte. Cuando
    el maquetador no la repite, se exige que el párrafo contenga anclas léxicas
    de exactamente una modalidad. Un bloque ambiguo se deja intacto: recuperar
    menos texto es preferible a asignar evidencia a la modalidad equivocada.
    """
    text = re.sub(r"[ \t]*\n[ \t]*", " ", overflow or "").strip()
    if not text or count_anchors(text):
        return dict(analysis)

    attributed = split_by_modality(text)
    if not attributed:
        modalities = [
            modality
            for modality, pattern in OVERFLOW_MODALITY_ANCHORS
            if pattern.search(text)
        ]
        if len(modalities) != 1:
            return dict(analysis)
        attributed = {modalities[0]: text}

    merged = dict(analysis)
    for modality, extra in attributed.items():
        current = merged.get(modality)
        merged[modality] = f"{current} {extra}".strip() if current else extra
    return merged


def parse_previous(text: str) -> list[dict[str, str]]:
    """Parsea el bloque DIAGNÓSTICOS PREVIOS en entradas fechadas."""
    if not text:
        return []
    flat = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    entries: list[dict[str, str]] = []
    matches = list(PREV_DIAG_RE.finditer(flat))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(flat)
        body = flat[match.end() : end].strip()
        date = datetime.strptime(match.group(1), "%d/%m/%Y").date().isoformat()
        label = match.group(2).strip()
        modality = MODALITY_MAP.get(label, label.lower())
        entries.append({"date": date, "modality": modality, "text": body})
    return entries


def count_anchors(text: str) -> int:
    """Anclas ``-DD/MM/AAAA: (Modalidad)`` de un texto (invariante §3.1)."""
    return len(PREV_DIAG_RE.findall(re.sub(r"[ \t]*\n[ \t]*", " ", text or "")))


def merge_previous(sources: list[str]) -> list[dict[str, str]]:
    """Une los previos de las cuatro fuentes deduplicando por (fecha, modalidad).

    El maquetador reparte el bloque entre columnas y a veces lo repite al
    refluir; la clave (fecha, modalidad) es la del consolidado (spec §5). Ante
    dos textos para la misma clave gana el más largo — el corto es siempre un
    recorte del reflujo.
    """
    best: dict[tuple[str, str], dict[str, str]] = {}
    order: list[tuple[str, str]] = []
    for text in sources:
        for entry in parse_previous(text):
            key = (entry["date"], entry["modality"])
            previous = best.get(key)
            if previous is None:
                best[key] = entry
                order.append(key)
            elif len(entry["text"]) > len(previous["text"]):
                best[key] = entry
    return [best[key] for key in order]


# ---------------------------------------------------------------------------
# Parseo del documento
# ---------------------------------------------------------------------------


def parse_machine_title(title: str) -> tuple[str | None, str]:
    """Separa el TAG de planta del nombre legible.

    ``"PM.1250A - Bomba Centrifuga"`` → ``("PM.1250A", "Bomba Centrifuga")``;
    ``"TC.1523A1 (lado Iberdrola) - Transporte Cadena"`` →
    ``("TC.1523A1", "Transporte Cadena (lado Iberdrola)")``;
    ``"BOMBA CENTRIFUGA PM.OSMOSIS2"`` → ``("PM.OSMOSIS2", "BOMBA CENTRIFUGA")``.
    """
    title = re.sub(r"\s+", " ", title).strip()
    if " - " in title:
        left, right = title.split(" - ", 1)
        tokens = left.strip().split()
        if tokens and TAG_TOKEN_RE.match(tokens[0]):
            qualifier = " ".join(tokens[1:])
            name = f"{right.strip()} {qualifier}".strip()
            return tokens[0], name
    for token in title.split():
        if TAG_TOKEN_RE.match(token):
            name = " ".join(t for t in title.split() if t != token).strip(" -")
            return token, name or title
    return None, title


def is_machine_page(lines: list[dict[str, Any]]) -> str | None:
    """Título de máquina si la página es una ficha, ``None`` si no lo es."""
    area_top = next(
        (ln["top"] for ln in lines if ln["text"].startswith("Área:") and ln["top"] < 170),
        None,
    )
    if area_top is None:
        return None
    candidates: list[str] = []
    for line in lines:
        if line["size"] >= 11.5 and line["bold"] and 40 < line["top"] < area_top:
            text = line["text"].strip()
            if (
                not text
                or re.match(r"^\d+(\.\d+)*\s", text)
                or text.lower().startswith("análisis")
            ):
                continue  # cabeceras de sección ("2 Análisis", "2.1 DEP - …")
            candidates.append(text)
    # los títulos largos parten en dos líneas consecutivas de 12 pt: unirlas
    return " ".join(candidates) if candidates else None


def parse_header_status(
    lines: list[dict[str, Any]], area_top: float
) -> tuple[str | None, dict[str, str]]:
    """Etiqueta global y estados por modalidad de la banda de cabecera.

    La banda se ancla al ``Área:`` de la ficha en vez de a un ``top``
    absoluto: la primera ficha de cada área baja ~45 pt por el epígrafe «2
    Análisis» y con la ventana fija se perdía su estado (auditoría §3.9.2). Se
    corta en la línea de RPM o en la primera cabecera de sección, y la etiqueta
    global se valida contra :data:`~ams_extract.informes.rules.GLOBAL_STATUS_RE`.
    """
    global_label: str | None = None
    status_words: list[dict[str, Any]] = []
    for line in sorted(
        (ln for ln in lines if ln["x0"] < COLUMN_SPLIT_X), key=lambda ln: ln["top"]
    ):
        if line["top"] <= area_top:
            continue
        text = line["text"].strip()
        if text.startswith("RPM1:") or text.startswith(SECTION_HEADS):
            break
        if line["top"] > area_top + 120:
            break
        for word in line["words"]:
            if 150 < word["x0"] < COLUMN_SPLIT_X:
                status_words.append(word)
        if global_label is None and line["x0"] < 150 and line["bold"]:
            match = GLOBAL_STATUS_RE.match(text)
            if match:
                global_label = match.group(1)
    status_text = " ".join(
        w["text"] for w in sorted(status_words, key=lambda w: (w["top"], w["x0"]))
    )
    return global_label, split_by_modality(status_text)


def parse_machine_page(page: Any) -> dict[str, Any] | None:
    """Ficha de máquina de una página, o ``None`` si la página no lo es."""
    words = page.extract_words(extra_attrs=["size", "fontname"])
    y_max = page.height - FOOTER_MARGIN
    all_lines = words_to_lines(words)
    # descartar cabecera del documento (top < 45) y pie de página
    body = [ln for ln in all_lines if HEADER_Y < ln["top"] < y_max]
    title = is_machine_page(body)
    if title is None:
        return None
    tag, name = parse_machine_title(title)

    header = [ln for ln in body if ln["top"] < 340]
    area_code: str | None = None
    area_name: str | None = None
    area_top = 0.0
    for line in header:
        match = re.match(r"Área:\s*(\S+)\s*-\s*(.+)$", line["text"])
        if match:
            area_code, area_name = match.group(1), match.group(2).strip()
            area_top = line["top"]
            break

    global_status_label, statuses = parse_header_status(header, area_top)

    page_text = page.extract_text() or ""
    rpm1 = power_kw = rpm2 = None
    match = RPM_RE.search(page_text)
    if match:
        rpm1 = float(match.group(1).replace(",", "."))
        power_kw = float(match.group(2).replace(",", "."))
        rpm2 = float(match.group(3).replace(",", "."))

    # La izquierda arranca bajo la banda de cabecera (título/área/estados); la
    # derecha en cuanto acaba la cabecera del documento — el bloque de previos
    # empieza a veces por encima de y=100 (§3.2).
    left, cap_left = split_sections(column_text(words, left=True, y_min=160, y_max=y_max))
    right, cap_right = split_sections(
        column_text(words, left=False, y_min=HEADER_Y, y_max=y_max)
    )

    diagnosis = split_by_modality(left.get("DIAGNÓSTICO:", ""))
    recommendation = split_by_modality(left.get("RECOMENDACIÓN:", ""))
    analysis = split_by_modality(left.get("ANÁLISIS:", ""))
    analysis = merge_analysis_overflow(analysis, right.get("_pre", ""))
    # Los previos viven en cualquiera de las cuatro fuentes (§3.1, §3.2).
    sources = [
        left.get(PREVIOUS_HEAD, ""),
        right.get(PREVIOUS_HEAD, ""),
        left.get("_pre", ""),
        right.get("_pre", ""),
    ]
    previous = merge_previous(sources)

    body_text = "\n".join(ln["text"] for ln in body)
    return {
        "title": title,
        "tag": tag,
        "name": name,
        "area_code": area_code,
        "area_name": area_name,
        "global_status_label": global_status_label,
        "statuses": statuses,
        "rpm1": rpm1,
        "power_kw": power_kw,
        "rpm2": rpm2,
        "diagnosis": diagnosis,
        "recommendation": recommendation,
        "analysis": analysis,
        "previous": previous,
        "figures": cap_left + cap_right,
        "page_number": page.page_number,
        "_anchors_page": count_anchors(body_text),
        "_anchors_sources": sum(count_anchors(s) for s in sources),
    }


def parse_continuation_page(page: Any) -> list[dict[str, str]] | None:
    """Previos de una página de continuación (sin cabecera de máquina).

    Cuando el bloque de previos no cabe, desborda a una página entera sin
    título ni ``Área:``; :func:`is_machine_page` devuelve ``None`` y la página
    se descartaba (auditoría §3.3, 6 páginas / 39 entradas en el corpus). La
    atribución es inequívoca: la continuación sigue inmediatamente a su ficha.
    """
    words = page.extract_words(extra_attrs=["size", "fontname"])
    y_max = page.height - FOOTER_MARGIN
    lines = [ln for ln in words_to_lines(words) if HEADER_Y < ln["top"] < y_max]
    text = "\n".join(ln["text"] for ln in lines)
    if not count_anchors(text):
        return None
    left, _ = split_sections(column_text(words, left=True, y_min=HEADER_Y, y_max=y_max))
    right, _ = split_sections(column_text(words, left=False, y_min=HEADER_Y, y_max=y_max))
    sources = [
        left.get(PREVIOUS_HEAD, ""),
        right.get(PREVIOUS_HEAD, ""),
        left.get("_pre", ""),
        right.get("_pre", ""),
    ]
    return merge_previous(sources) or None


def parse_front_matter(pdf: Any) -> dict[str, Any]:
    """Portada, alcance, rutas, analistas y listados de paradas/no medidas."""
    meta: dict[str, Any] = {
        "routes": [],
        "machines_stopped": [],
        "machines_not_measured": [],
        "analysts": [],
        "reviewers": [],
    }
    first = pdf.pages[0].extract_text() or ""
    for pattern, key in (
        (r"REF:\s*(\S+)", "document_id"),
        (r"CLIENTE:\s*(.+)", "client"),
        (r"PLANTA:\s*(.+)", "plant"),
        (r"FECHA INSPECCIÓN:\s*([\d/]+)", "inspection_date"),
        (r"FECHA IMPRESIÓN:\s*([\d/]+)", "printed_date"),
    ):
        match = re.search(pattern, first)
        if match:
            meta[key] = match.group(1).strip()
    match = re.search(r"^(Inspecci[oó]n .+)$", first, re.M)
    if match:
        meta["document_title"] = match.group(1).strip()

    listing_mode: str | None = None
    in_body = False
    for page in pdf.pages[1:30]:
        text = page.extract_text() or ""
        if "Este informe presenta los resultados" in text:
            in_body = True  # fin del índice, empieza la introducción
        if not in_body:
            continue
        if "Este informe presenta los resultados" in text:
            match = re.search(r"entre el ([\d/]+) y (?:el )?([\d/]+)", text)
            if match:
                meta["period_from"], meta["period_to"] = match.group(1), match.group(2)
            for route in re.finditer(r"\*\s*(.+)$", text, re.M):
                meta["routes"].append(route.group(1).strip())
        if "Análisis realizados por:" in text:
            for analyst in re.finditer(r"Análisis realizados por:\s*(.+)$", text, re.M):
                meta["analysts"].append(analyst.group(1).strip())
            for reviewer in re.finditer(r"Revisión realizada por:\s*(.+)$", text, re.M):
                meta["reviewers"].append(reviewer.group(1).strip())
        if "Global Inspecciones" in text:  # matriz de estados: fin del front matter
            break
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("Máquinas Paradas"):
                listing_mode = "machines_stopped"
            elif line.startswith("Máquinas No Medidas"):
                listing_mode = "machines_not_measured"
            elif line.startswith(("Resumen", "Estado de Planta")):
                listing_mode = None
            elif listing_mode and line.startswith("- "):
                item = line[2:].strip()
                if item and item not in meta[listing_mode]:
                    meta[listing_mode].append(item)
    return meta


def iso_date(value: str | None) -> str | None:
    """``"26/01/2026"`` → ``"2026-01-26"``."""
    if not value:
        return None
    return datetime.strptime(value, "%d/%m/%Y").date().isoformat()


def file_sha256(path: Path) -> str:
    """SHA-256 del PDF fuente — ancla de verificación de la procedencia."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _machine_ref(machine: dict[str, Any]) -> dict[str, Any]:
    return {
        "external_tag": machine["tag"],
        "external_name": machine["name"],
        "normalized_tag": norm_tag(machine["tag"] or machine["title"]),
        "area_code": machine["area_code"],
        "area_name": machine["area_name"],
        "dataset_machine_id": None,  # crosswalk posterior contra VibFrame
    }


def _observations(machines: list[dict[str, Any]], doc_id: str, insp_date: str | None):
    observations: list[dict[str, Any]] = []
    for machine in machines:
        machine_ref = _machine_ref(machine)
        operating = {
            "rpm1": machine["rpm1"],
            "rpm2": machine["rpm2"],
            "power_kw": machine["power_kw"],
        }
        modalities = set(machine["statuses"]) | set(machine["diagnosis"])
        for modality in sorted(modalities):
            status_label = machine["statuses"].get(modality)
            diagnosis_text = machine["diagnosis"].get(modality)
            status, alarm = map_status(status_label or "")
            if status == "UNKNOWN" and diagnosis_text and len(diagnosis_text) < 60:
                status, alarm = map_status(diagnosis_text)
            if status == "UNKNOWN" and diagnosis_text:
                from_text = status_from_text(diagnosis_text)
                if from_text is not None:
                    status, alarm = from_text
            observations.append(
                {
                    "observation_id": (
                        f"{norm_tag(doc_id)}:{machine_ref['normalized_tag']}:{modality}"
                    ),
                    "record_kind": "primary",
                    "machine": machine_ref,
                    "modality": modality,
                    "observed_at": insp_date,
                    "status": status,
                    "status_source_label": status_label,
                    "alarm": alarm,
                    "global_status_label": machine["global_status_label"],
                    "diagnosis_text": diagnosis_text,
                    "analysis_text": machine["analysis"].get(modality),
                    "recommendation_text": machine["recommendation"].get(modality),
                    "findings": map_findings(diagnosis_text or ""),
                    "operating_context": operating,
                    "figures": machine["figures"],
                    "source_page": machine["page_number"],
                }
            )
        for previous in machine["previous"]:
            from_text = status_from_text(previous["text"])
            status, alarm = from_text if from_text is not None else ("UNKNOWN", None)
            observations.append(
                {
                    "observation_id": (
                        f"{norm_tag(doc_id)}:{machine_ref['normalized_tag']}"
                        f":{previous['modality']}:{previous['date']}"
                    ),
                    "record_kind": "retrospective",
                    "machine": machine_ref,
                    "modality": previous["modality"],
                    "observed_at": previous["date"],
                    "status": status,
                    "status_source_label": None,
                    "alarm": alarm,
                    "global_status_label": None,
                    "diagnosis_text": previous["text"],
                    "analysis_text": None,
                    "recommendation_text": None,
                    "findings": map_findings(previous["text"]),
                    "operating_context": None,
                    "source_page": machine["page_number"],
                }
            )
    return observations


def build_document(
    pdf_path: Path,
    report: ExtractionReport | None = None,
    *,
    extracted_at: datetime | None = None,
) -> dict[str, Any]:
    """Documento DiagGT de un informe PDF.

    ``report`` acumula los contadores de la invariante de anclas y las páginas
    de continuación arrastradas a través de varios informes.
    """
    stats = report if report is not None else ExtractionReport()
    sha = file_sha256(pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        meta = parse_front_matter(pdf)
        machines: list[dict[str, Any]] = []
        for page in pdf.pages:
            try:
                record = parse_machine_page(page)
            except Exception as exc:  # página anómala: registrar y seguir
                _log.warning(
                    "informes_page_failed",
                    document=pdf_path.name,
                    page=page.page_number,
                    error=str(exc),
                )
                continue
            if record is None:
                continuation = parse_continuation_page(page) if machines else None
                if continuation:
                    last = machines[-1]
                    keys = {(e["date"], e["modality"]) for e in last["previous"]}
                    added = [e for e in continuation if (e["date"], e["modality"]) not in keys]
                    last["previous"].extend(added)
                    stats.continuations.append(
                        (pdf_path.name, page.page_number, last["tag"], len(added))
                    )
                continue
            # invariante de anclas (§3.1): la unión de las cuatro fuentes tiene
            # que reproducir el recuento de anclas del cuerpo de la página.
            n_page = record.pop("_anchors_page")
            n_sources = record.pop("_anchors_sources")
            stats.fichas += 1
            stats.anchors_page += n_page
            stats.anchors_sources += n_sources
            if n_page != n_sources:
                stats.anchor_mismatch.append(
                    (pdf_path.name, page.page_number, record["tag"], n_page, n_sources)
                )
            machines.append(record)

    doc_id = meta.get("document_id", pdf_path.stem)
    insp_date = iso_date(meta.get("inspection_date"))
    now = extracted_at or datetime.now(tz=UTC)
    return {
        "$schema_version": SCHEMA_VERSION,
        "kind": "diagnosis_ground_truth",
        "provenance": {
            "origin": ORIGIN,
            "provider": PROVIDER,
            "document_id": doc_id,
            "document_title": meta.get("document_title"),
            "source_ref": pdf_path.name,
            "source_sha256": sha,
            "client": meta.get("client"),
            "plant": meta.get("plant"),
            "inspection_date": insp_date,
            "measurement_period": {
                "from": iso_date(meta.get("period_from")),
                "to": iso_date(meta.get("period_to")),
            },
            "routes": meta["routes"],
            "analysts": sorted(set(meta["analysts"])),
            "reviewers": sorted(set(meta["reviewers"])),
            "extractor": EXTRACTOR_VERSION,
            "extracted_at": now.astimezone(UTC).isoformat(timespec="seconds"),
            "extraction_method": EXTRACTION_METHOD,
        },
        "machines_stopped": meta["machines_stopped"],
        "machines_not_measured": meta["machines_not_measured"],
        "observations": _observations(machines, doc_id, insp_date),
    }
