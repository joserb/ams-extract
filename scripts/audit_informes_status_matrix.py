#!/usr/bin/env python3
"""Extrae la matriz de estados de los informes como artefacto de auditoría.

La salida NO es DiagGT: conserva una fila por icono y su coordenada para
medir cobertura, repetición entre informes y crosswalk antes de decidir una
forma normativa. Las celdas son imágenes raster 15x15, no rectángulos PDF.

Uso::

    uv run python scripts/audit_informes_status_matrix.py PDFDIR --out matrix.json
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber  # pyright: ignore[reportMissingImports]

from ams_extract.informes.rules import norm_tag

MATRIX_MARKER = "Global Inspecciones"
ICON_SIZE = (15, 15)
DATE_RE = re.compile(r"\d{2}-\d{2}-\d{4}")
TAG_RE = re.compile(r"^[A-ZÑ]{1,6}[.\-][A-Z0-9Ñ/.\-]+$")
TAG_SEARCH_RE = re.compile(r"(?<![A-Z0-9Ñ])([A-ZÑ]{1,6}[.\-][A-Z0-9Ñ/.\-]+)")

# SHA-256 de los bytes RGB de los siete iconos incrustados por Preconcerto.
# El hash evita convertir un color aproximado en semántica; un icono nuevo
# queda UNKNOWN y obliga a revisar el catálogo en un diff.
ICON_STATUS = {
    "abf932e7492d": "OK",  # check verde
    "5dbd1bd2c1cc": "WATCH",  # exclamación amarilla
    "383607498384": "ALERT",  # exclamación naranja
    "1af556557759": "DANGER",  # exclamación roja
    "158ce126b67d": "STOPPED",  # pausa gris
    "a351c16df309": "NOT_MEASURED",  # asterisco azul
    "cf3bab56c5c4": "OUT_OF_SERVICE",  # llave gris
}


@dataclass(frozen=True, slots=True)
class MatrixCell:
    source_ref: str
    source_page: int
    area: str | None
    external_tag: str
    external_name: str
    normalized_tag: str
    column: str
    observed_at: str | None
    status: str
    icon_sha256_12: str
    bbox: tuple[float, float, float, float]


def _machine_ref(text: str) -> tuple[str, str]:
    flattened = " ".join(text.split())
    head, separator, tail = flattened.partition(" - ")
    if separator and TAG_RE.fullmatch(head):
        return head, tail
    match = TAG_SEARCH_RE.search(flattened)
    if match is not None:
        external_tag = match.group(1).rstrip(".-")
        external_name = (
            flattened[: match.start()] + " " + flattened[match.end() :]
        ).strip(" -")
        return external_tag, external_name or external_tag
    return flattened, flattened


def _icon_in_cell(page: Any, bbox: tuple[float, float, float, float]) -> dict[str, Any] | None:
    x0, top, x1, bottom = bbox
    matches = [
        image
        for image in page.images
        if image.get("srcsize") == ICON_SIZE
        and x0 <= (float(image["x0"]) + float(image["x1"])) / 2 <= x1
        and top <= (float(image["top"]) + float(image["bottom"])) / 2 <= bottom
    ]
    return matches[0] if len(matches) == 1 else None


def _iso_date(label: str) -> str:
    return datetime.strptime(label, "%d-%m-%Y").date().isoformat()


def extract_pdf(path: Path) -> tuple[list[MatrixCell], int]:
    cells: list[MatrixCell] = []
    matrix_pages = 0
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            if MATRIX_MARKER not in (page.extract_text() or ""):
                continue
            matrix_pages += 1
            for table in page.find_tables():
                values = table.extract()
                header_index = next(
                    (
                        index
                        for index, row in enumerate(values)
                        if len(row) >= 3 and row[:3] == ["Área", "Máquina", "Estado"]
                    ),
                    None,
                )
                if header_index is None:
                    continue
                headers = values[header_index]
                current_area: str | None = None
                for row_index in range(header_index + 1, len(values)):
                    row_values = values[row_index]
                    row = table.rows[row_index]
                    if row_values[0]:
                        current_area = " ".join(row_values[0].split())
                    machine_text = row_values[1] if len(row_values) > 1 else None
                    if not machine_text:
                        continue
                    external_tag, external_name = _machine_ref(machine_text)
                    for column_index in range(2, min(len(headers), len(row.cells))):
                        bbox = row.cells[column_index]
                        if bbox is None:
                            continue
                        header = headers[column_index]
                        if column_index != 2 and (not header or not DATE_RE.fullmatch(header)):
                            continue
                        image = _icon_in_cell(page, bbox)
                        if image is None:
                            continue
                        payload = image["stream"].get_data()
                        signature = hashlib.sha256(payload).hexdigest()[:12]
                        cells.append(
                            MatrixCell(
                                source_ref=path.name,
                                source_page=page_number,
                                area=current_area,
                                external_tag=external_tag,
                                external_name=external_name,
                                normalized_tag=norm_tag(external_tag),
                                column="current" if column_index == 2 else "inspection",
                                observed_at=None if column_index == 2 else _iso_date(header),
                                status=ICON_STATUS.get(signature, "UNKNOWN"),
                                icon_sha256_12=signature,
                                bbox=tuple(round(float(value), 3) for value in bbox),
                            )
                        )
    return cells, matrix_pages


def _known_tags(gt_dir: Path) -> set[str]:
    tags: set[str] = set()
    for path in gt_dir.glob("*.diaggt.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("provenance", {}).get("origin") != "inspection-report":
            continue
        tags.update(
            observation["machine"]["normalized_tag"]
            for observation in document.get("observations", [])
        )
    return tags


def _crosswalk_tags(gt_dir: Path) -> set[str]:
    path = gt_dir / "crosswalk.csv"
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            row["normalized_tag"]
            for row in csv.DictReader(handle)
            if (row.get("dataset_machine_id") or "").strip()
        }


def build_report(pdf_dir: Path, gt_dir: Path) -> dict[str, Any]:
    all_cells: list[MatrixCell] = []
    pages_by_document: dict[str, int] = {}
    for path in sorted(pdf_dir.glob("*.pdf")):
        cells, pages = extract_pdf(path)
        all_cells.extend(cells)
        pages_by_document[path.name] = pages

    machine_tags = {cell.normalized_tag for cell in all_cells}
    known_tags = _known_tags(gt_dir)
    crosswalk_tags = _crosswalk_tags(gt_dir)
    historical = [cell for cell in all_cells if cell.column == "inspection"]
    unique_history: dict[tuple[str, str], set[str]] = {}
    for cell in historical:
        key = (cell.normalized_tag, cell.observed_at or "")
        unique_history.setdefault(key, set()).add(cell.status)
    disagreements = {key: statuses for key, statuses in unique_history.items() if len(statuses) > 1}
    signatures = Counter(cell.icon_sha256_12 for cell in all_cells)
    statuses = Counter(cell.status for cell in all_cells)

    return {
        "kind": "informes_status_matrix_audit",
        "normative": False,
        "input": str(pdf_dir),
        "ground_truth": str(gt_dir),
        "documents": len(pages_by_document),
        "matrix_pages": sum(pages_by_document.values()),
        "matrix_pages_by_document": pages_by_document,
        "cells": len(all_cells),
        "historical_cells": len(historical),
        "unique_historical_cells": len(unique_history),
        "unique_machines": len(machine_tags),
        "machines_already_in_diaggt": len(machine_tags & known_tags),
        "matrix_only_machines": len(machine_tags - known_tags),
        "machines_resolved_by_existing_crosswalk": len(machine_tags & crosswalk_tags),
        "cross_report_disagreements": len(disagreements),
        "status_counts": dict(sorted(statuses.items())),
        "icon_signatures": dict(sorted(signatures.items())),
        "unknown_icon_signatures": sorted(
            signature for signature in signatures if signature not in ICON_STATUS
        ),
        "matrix_only_normalized_tags": sorted(machine_tags - known_tags),
        "disagreements": [
            {"normalized_tag": key[0], "observed_at": key[1], "statuses": sorted(value)}
            for key, value in sorted(disagreements.items())
        ],
        "rows": [asdict(cell) for cell in all_cells],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_dir", type=Path)
    parser.add_argument(
        "--ground-truth",
        type=Path,
        help="DiagGT/crosswalk used for coverage; defaults to PDFDIR/ground-truth.",
    )
    parser.add_argument("--out", type=Path, help="Write the complete non-normative JSON.")
    args = parser.parse_args()
    gt_dir = args.ground_truth or args.pdf_dir / "ground-truth"
    report = build_report(args.pdf_dir, gt_dir)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(payload + "\n", encoding="utf-8")
    detailed = {"rows", "disagreements", "matrix_only_normalized_tags"}
    summary = {key: value for key, value in report.items() if key not in detailed}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
