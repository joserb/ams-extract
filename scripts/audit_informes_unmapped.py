#!/usr/bin/env python3
"""Audita de forma reproducible los ``unmapped`` de una generación DiagGT.

Uso::

    uv run python scripts/audit_informes_unmapped.py \
        <informes>/ground-truth/deterministic-0.4.0
    uv run python scripts/audit_informes_unmapped.py GTDIR --format json

La entrada no se modifica. El informe agrupa por ``diagnosis_text`` y muestra
las observaciones afectadas, la masa publicada, el corte en cláusulas y la
lectura de las reglas instaladas (incluidos sus vetos). La clasificación es
del texto fuente, no una proyección DiagGT: sirve para decidir qué regla merece
existir sin convertir peticiones administrativas en fallos.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from ams_extract.informes import EXTRACTOR_VERSION
from ams_extract.informes.rules import (
    FINDING_RULES,
    RULE_VETOES,
    clause_findings,
    clauses,
    is_marker_clause,
    is_status_clause,
    map_findings,
)

CLASSIFICATIONS = (
    "true_fault",
    "healthy_or_stable",
    "administrative_request",
    "insufficient_context",
)

ADMINISTRATIVE_RE = re.compile(
    r"\b(?:informar|comentar) a preditec\b|^revisar\b|\bse solicita (?:dicha )?informaci[oó]n",
    re.I,
)
TRUE_FAULT_RE = re.compile(
    r"(?:suciedad|desgaste|deterioro).{0,35}v[aá]lvula|"
    r"deterioro\s+(?:en|del?)\s+(?:el\s+)?acoplamiento|"
    r"barras?.{0,20}(?:rotas?|sueltas?)|"
    r"\bhuelgo\b|ruido\s+(?:en|del?)\s+(?:el\s+)?acople",
    re.I,
)
HEALTHY_OR_STABLE_RE = re.compile(
    r"\b(?:estable|estabilidad|sin evoluci[oó]n|menor amplitud|descenso de amplitudes?)\b|"
    r"\bbuen estado\b|\bno se aprecian? (?:\S+\s+){0,2}?trazas? de fallo\b|"
    r"\bniveles? aptos? (?:de|para) operaci[oó]n\b|\bl[ií]nea .{0,40} parada\b",
    re.I,
)


def classify_clause(clause: str) -> str | None:
    """Clasificación auditora de una cláusula que participó en ``unmapped``."""
    if ADMINISTRATIVE_RE.search(clause):
        return "administrative_request"
    if TRUE_FAULT_RE.search(clause):
        return "true_fault"
    if HEALTHY_OR_STABLE_RE.search(clause) or is_status_clause(clause):
        return "healthy_or_stable"
    if clause_findings(clause) or is_marker_clause(clause):
        return None
    return "insufficient_context"


def _rule_trace(clause: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    low = clause.lower()
    applied: list[dict[str, str]] = []
    vetoed: list[dict[str, str]] = []
    applied_indices = {index for index, _matched in clause_findings(clause)}
    for index, (rule_id, pattern, _mode, group, _quality) in enumerate(FINDING_RULES):
        match = re.search(pattern, low)
        if match is None:
            continue
        item = {"rule": rule_id, "matched_text": match.group(0), "fault_group": group}
        veto = RULE_VETOES.get(rule_id)
        if veto is not None and veto.search(low):
            vetoed.append(item)
        elif index in applied_indices:
            applied.append(item)
    return applied, vetoed


def audit(gt_dir: Path) -> dict[str, Any]:
    paths = sorted(gt_dir.glob("*.diaggt.json"))
    if not paths:
        raise ValueError(f"no *.diaggt.json files in {gt_dir}")

    grouped: dict[str, dict[str, Any]] = {}
    source_extractors: set[str] = set()
    total_observations = 0
    documents: list[dict[str, Any]] = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        provenance = document.get("provenance", {})
        source_extractors.add(str(provenance.get("extractor")))
        observations = document.get("observations", [])
        total_observations += len(observations)
        documents.append(
            {
                "diaggt": path.name,
                "source_ref": provenance.get("source_ref"),
                "source_sha256": provenance.get("source_sha256"),
                "observations": len(observations),
            }
        )
        for observation in observations:
            unmapped = [
                finding
                for finding in observation.get("findings", [])
                if finding.get("label_quality") == "unmapped"
            ]
            if not unmapped:
                continue
            text = observation.get("diagnosis_text") or ""
            entry = grouped.setdefault(
                text,
                {"diagnosis_text": text, "observations": [], "published_unmapped_mass": 0.0},
            )
            entry["observations"].append(
                {
                    "document": path.name,
                    "observation_id": observation.get("observation_id"),
                    "record_kind": observation.get("record_kind"),
                    "external_tag": observation.get("machine", {}).get("external_tag"),
                    "modality": observation.get("modality"),
                }
            )
            entry["published_unmapped_mass"] += sum(float(f["weight"]) for f in unmapped)

    classification_counts: Counter[str] = Counter()
    classification_mass: Counter[str] = Counter()
    current_unmapped_findings = 0
    current_unmapped_mass = 0.0
    texts: list[dict[str, Any]] = []
    for text, entry in sorted(grouped.items()):
        clause_rows: list[dict[str, Any]] = []
        text_classes: set[str] = set()
        for clause in clauses(text):
            applied, vetoed = _rule_trace(clause)
            classification = classify_clause(clause)
            if classification is not None:
                text_classes.add(classification)
            clause_rows.append(
                {
                    "text": clause,
                    "classification": classification,
                    "status_clause": is_status_clause(clause),
                    "marker_clause": is_marker_clause(clause),
                    "rules": applied,
                    "vetoes": vetoed,
                }
            )
        classification = next(
            (
                candidate
                for candidate in (
                    "true_fault",
                    "administrative_request",
                    "healthy_or_stable",
                    "insufficient_context",
                )
                if candidate in text_classes
            ),
            "insufficient_context",
        )
        classification_counts[classification] += len(entry["observations"])
        classification_mass[classification] += entry["published_unmapped_mass"]
        entry["published_unmapped_mass"] = round(entry["published_unmapped_mass"], 6)
        entry["classification"] = classification
        entry["clauses"] = clause_rows
        entry["current_findings"] = map_findings(text)
        current_unmapped = [
            finding
            for finding in entry["current_findings"]
            if finding["label_quality"] == "unmapped"
        ]
        if current_unmapped:
            current_unmapped_findings += len(entry["observations"])
            current_unmapped_mass += len(entry["observations"]) * sum(
                float(finding["weight"]) for finding in current_unmapped
            )
        texts.append(entry)

    try:
        pdfplumber_version = version("pdfplumber")
    except PackageNotFoundError:
        pdfplumber_version = None
    return {
        "input": str(gt_dir),
        "documents": len(paths),
        "document_sources": documents,
        "observations": total_observations,
        "source_extractors": sorted(source_extractors),
        "rules_extractor": EXTRACTOR_VERSION,
        "pdfplumber": pdfplumber_version,
        "unmapped_findings": sum(len(entry["observations"]) for entry in texts),
        "distinct_texts": len(texts),
        "published_unmapped_mass": round(
            sum(entry["published_unmapped_mass"] for entry in texts), 6
        ),
        "current_unmapped_findings": current_unmapped_findings,
        "current_unmapped_mass": round(current_unmapped_mass, 6),
        "classification_observations": {
            key: classification_counts[key] for key in CLASSIFICATIONS
        },
        "classification_published_mass": {
            key: round(classification_mass[key], 6) for key in CLASSIFICATIONS
        },
        "texts": texts,
    }


def as_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Auditoría de `unmapped` de informes",
        "",
        f"- entrada: `{report['input']}`",
        f"- documentos / observaciones: {report['documents']} / {report['observations']}",
        f"- extractor fuente: {', '.join(report['source_extractors'])}",
        f"- reglas evaluadas: {report['rules_extractor']}",
        f"- pdfplumber: {report['pdfplumber'] or 'no instalado'}",
        f"- `unmapped`: {report['unmapped_findings']} findings, "
        f"{report['distinct_texts']} textos, masa {report['published_unmapped_mass']:.6f}",
        f"- con las reglas actuales: {report['current_unmapped_findings']} findings, "
        f"masa {report['current_unmapped_mass']:.6f}",
        "",
    ]
    for index, entry in enumerate(report["texts"], 1):
        lines.extend(
            [
                f"## {index}. {entry['diagnosis_text']}",
                "",
                f"Observaciones: {len(entry['observations'])}; masa publicada: "
                f"{entry['published_unmapped_mass']:.6f}; clasificación: "
                f"{entry['classification']}.",
                "",
            ]
        )
        for clause in entry["clauses"]:
            rules = ", ".join(item["rule"] for item in clause["rules"]) or "—"
            vetoes = ", ".join(item["rule"] for item in clause["vetoes"]) or "—"
            lines.append(
                f"- `{clause['text']}` — {clause['classification'] or 'covered'}; "
                f"reglas: {rules}; vetos: {vetoes}"
            )
        current = ", ".join(
            f"{finding.get('mapping_rule') or 'unmapped'}={finding['weight']:.6f}"
            for finding in entry["current_findings"]
        )
        lines.extend(["", f"Lectura actual: {current or 'sin findings'}.", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gt_dir", type=Path)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()
    report = audit(args.gt_dir)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(as_markdown(report))


if __name__ == "__main__":
    main()
