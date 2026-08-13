#!/usr/bin/env python3
"""Censa evidencia rica de informes sin proyectarla a DiagGT.

Produce dos inventarios auditables:

- fragmentos geométricos del bloque ad hoc ``ACTUALIZACIÓN`` y sus páginas de
  continuación, conservados por página/columna y sin deduplicación heurística;
- candidatos de intervención, medida numérica y petición/contexto encontrados
  en los campos textuales de una generación DiagGT ya emitida.

La salida es deliberadamente no normativa. Sirve para diseñar un contrato
futuro sin convertir una medida citada en muestra VibFrame ni una intervención
inferida en un evento estructurado.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pdfplumber  # pyright: ignore[reportMissingImports]

from ams_extract.informes.parse import (
    FOOTER_MARGIN,
    HEADER_Y,
    PREVIOUS_HEAD,
    column_text,
    parse_machine_page,
)

UPDATE_MARKER = "ACTUALIZACIÓN"
FIELDS = ("diagnosis_text", "analysis_text", "recommendation_text")

EVIDENCE_PATTERNS: dict[str, re.Pattern[str]] = {
    "intervention_candidate": re.compile(
        r"\b(?:intervenci[oó]n|intervenido|intervenida|intervinieron|"
        r"se (?:ha |han |hab[ií]a )?(?:sustituido|cambiado|reparado|limpiado|"
        r"lubricado)|tras (?:la |su )?(?:intervenci[oó]n|sustituci[oó]n|cambio))\b",
        re.I,
    ),
    "numeric_measure": re.compile(
        r"(?<![\w.,])\d+(?:[.,]\d+)?\s*(?:mm/s|Hz|G'?s?|RPM|kW|°C)\b",
        re.I,
    ),
    "client_request_or_context": re.compile(
        r"\b(?:(?:informar|comentar) a Preditec|se solicita (?:dicha )?informaci[oó]n|"
        r"seg[uú]n (?:me |nos )?informas?|qu[eé] labores|si se ha intervenido)\b",
        re.I,
    ),
}


@dataclass(frozen=True, slots=True)
class UpdateFragment:
    source_ref: str
    source_page: int
    external_tag: str | None
    external_name: str | None
    column: str
    marker_on_page: bool
    text: str


def _flat(lines: list[dict[str, Any]]) -> str:
    return re.sub(r"\s+", " ", "\n".join(line["text"] for line in lines)).strip()


def _bounded(text: str, *, start: str | None = None, end: str | None = None) -> str:
    if start and start in text:
        text = text[text.index(start) :]
    if end and end in text:
        text = text[: text.index(end)]
    return text.strip()


def extract_update_fragments(path: Path) -> list[UpdateFragment]:
    """Conserva el reflujo por columna; no intenta fabricar un texto canónico."""
    fragments: list[UpdateFragment] = []
    active = False
    machine_tag: str | None = None
    machine_name: str | None = None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            marker = UPDATE_MARKER in page_text
            if not active and not marker:
                continue
            parsed = parse_machine_page(page) if marker else None
            if marker and parsed is not None:
                machine_tag, machine_name = parsed["tag"], parsed["name"]
            words = page.extract_words(extra_attrs=["size", "fontname"])
            y_max = page.height - FOOTER_MARGIN
            left = _flat(column_text(words, left=True, y_min=HEADER_Y, y_max=y_max))
            right = _flat(column_text(words, left=False, y_min=HEADER_Y, y_max=y_max))
            if marker:
                active = True
            if not active:
                continue

            for name, raw in (("left", left), ("right", right)):
                text = raw
                if marker and UPDATE_MARKER in text:
                    text = _bounded(text, start=UPDATE_MARKER)
                elif marker and parsed is not None:
                    # En la ficha que abre el bloque, la otra columna todavía
                    # contiene el análisis ordinario: no pertenece al reflujo.
                    continue
                if PREVIOUS_HEAD in text:
                    text = _bounded(text, end=PREVIOUS_HEAD)
                if text:
                    fragments.append(
                        UpdateFragment(
                            source_ref=path.name,
                            source_page=page.page_number,
                            external_tag=machine_tag,
                            external_name=machine_name,
                            column=name,
                            marker_on_page=marker,
                            text=text,
                        )
                    )
            if PREVIOUS_HEAD in left or PREVIOUS_HEAD in right:
                active = False
    return fragments


def census_text_evidence(gt_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(gt_dir.glob("*.diaggt.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("provenance", {}).get("origin") != "inspection-report":
            continue
        for observation in document["observations"]:
            for field in FIELDS:
                text = observation.get(field) or ""
                for category, pattern in EVIDENCE_PATTERNS.items():
                    matches = [match.group(0) for match in pattern.finditer(text)]
                    if matches:
                        rows.append(
                            {
                                "source_ref": document["provenance"]["source_ref"],
                                "observation_id": observation["observation_id"],
                                "external_tag": observation["machine"]["external_tag"],
                                "modality": observation["modality"],
                                "observed_at": observation["observed_at"],
                                "field": field,
                                "category": category,
                                "matches": matches,
                                "text": text,
                            }
                        )
    return rows


def build_report(pdf_dir: Path, gt_dir: Path) -> dict[str, Any]:
    fragments = [
        fragment
        for path in sorted(pdf_dir.glob("*.pdf"))
        for fragment in extract_update_fragments(path)
    ]
    candidates = census_text_evidence(gt_dir)
    categories = Counter(row["category"] for row in candidates)
    occurrences = Counter(
        {
            category: sum(
                len(row["matches"]) for row in candidates if row["category"] == category
            )
            for category in EVIDENCE_PATTERNS
        }
    )
    return {
        "kind": "informes_rich_evidence_audit",
        "normative": False,
        "input": str(pdf_dir),
        "ground_truth": str(gt_dir),
        "policy": {
            "update": "raw page/column fragments; repeated reflow is preserved",
            "candidates": "regex census for review; no event or sample is emitted",
        },
        "update_fragments": len(fragments),
        "update_pages": sorted({fragment.source_page for fragment in fragments}),
        "update_machines": sorted(
            {fragment.external_tag for fragment in fragments if fragment.external_tag}
        ),
        "candidate_rows": len(candidates),
        "candidate_rows_by_category": dict(sorted(categories.items())),
        "candidate_occurrences_by_category": dict(sorted(occurrences.items())),
        "fragments": [asdict(fragment) for fragment in fragments],
        "candidates": candidates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_dir", type=Path)
    parser.add_argument("--ground-truth", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    gt_dir = args.ground_truth or args.pdf_dir / "ground-truth"
    report = build_report(args.pdf_dir, gt_dir)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(payload + "\n", encoding="utf-8")
    detailed = {"fragments", "candidates"}
    print(
        json.dumps(
            {key: value for key, value in report.items() if key not in detailed},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
