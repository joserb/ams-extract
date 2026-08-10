"""Materializador de las proyecciones normativas DiagGT 0.2 (spec §§4-5).

Los ``*.diaggt.json`` son la fuente documental; este módulo proyecta de ellos
las tres tablas normativas del sidecar ``ground-truth/`` de VibFrame 0.2 y su
manifiesto de procedencia, todo en la misma operación:

- ``observations.parquet`` — proyección **completa**, una fila por observación
  de cada documento, sin deduplicar y de todas las familias (``origin`` separa
  el informe de analista de la alarma de sistema; ya no existe un
  ``observations_system.parquet`` aparte).
- ``observations_consolidated.parquet`` — la selección deduplicada bajo la
  política ``dedup-primary-latest/1.0`` (clave
  ``(origin, normalized_tag, observed_at, modality)``: gana ``primary``; entre
  retrospectivos, el del documento más reciente) más la vigencia explícita
  ``valid_to`` (fecha ISO exclusiva; null = abierta). Cada fila consolidada ES
  una fila de la proyección completa: selección, nunca agregación (el colapso
  ``"+".join`` de 0.1 desaparece).
- ``findings.parquet`` — proyección completa alineada 1:1 con
  ``observations.parquet`` vía ``observation_id``, con ``finding_index``
  contiguo 0..n-1 y ``matched_text``. Quien puntúe masa se queda con los
  findings cuyas observaciones ganaron: join con el consolidado.
- ``materialization.json`` — herramienta, política, inputs (sha256 y nº de
  observaciones por documento) y outputs (sha256 y filas), conforme a
  ``GTMaterialization``.

Cero CSV: ``observations.csv``, ``findings.csv`` y ``observations_system.csv``
no son parte del formato 0.2 (``ground-truth.legacy-csv``).

Los esquemas parquet son **explícitos**, construidos desde las ``ColumnSpec``
vendorizadas (ADR-0009: sin importar ``vibsynth_contracts`` en runtime),
incluso para columnas toda-null — nunca inferencia pandas → tipo ``null``.
Las fechas documentales viajan como strings ISO ``YYYY-MM-DD``, sin
promoverse a instantes.

El ``dataset_machine_id`` no lo resuelve este módulo: lo **proyecta** desde
``crosswalk.csv``, la tabla explícita que la spec §2.4 declara fuente del
mapeo y que produce ``scripts/crosswalk_gt.py`` contra un dataset concreto.
Sin esa tabla la columna sale a ``null`` y las proyecciones siguen siendo
válidas.
"""

# pyright: reportUnknownMemberType=false

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

from ams_extract.export.vibframe_contract import (
    CONSOLIDATION_POLICY,
    DIAGGT_FILE_SUFFIX,
    FINDINGS_COLUMNS,
    FINDINGS_FILE,
    GT_MATERIALIZATION_FILE,
    GT_MATERIALIZATION_KIND,
    GT_MATERIALIZATION_SCHEMA_VERSION,
    OBSERVATIONS_COLUMNS,
    OBSERVATIONS_CONSOLIDATED_COLUMNS,
    OBSERVATIONS_CONSOLIDATED_FILE,
    OBSERVATIONS_FILE,
    ColumnSpec,
    schema,
)

CROSSWALK_FILE = "crosswalk.csv"

OBSERVATION_COLUMNS: tuple[str, ...] = tuple(c.name for c in OBSERVATIONS_COLUMNS)
"""Nombres de columna de ``observations.parquet`` (0.2), en su orden."""

FINDING_COLUMNS: tuple[str, ...] = tuple(c.name for c in FINDINGS_COLUMNS)
"""Nombres de columna de ``findings.parquet`` (0.2), en su orden."""

_DEDUPE_KEY = ("origin", "normalized_tag", "observed_at", "modality")
_VALIDITY_KEY = ("origin", "normalized_tag", "modality")


def _tool_name() -> str:
    try:
        return f"ams-extract {version('ams-extract')}"
    except PackageNotFoundError:
        return "ams-extract 0.0.0"


def read_crosswalk(gt_dir: Path) -> dict[str, str]:
    """``normalized_tag`` → ``dataset_machine_id`` de ``crosswalk.csv``.

    Diccionario vacío si la tabla no existe o no resuelve nada: el crosswalk
    es un post-proceso opcional y su ausencia no es un error.
    """
    path = gt_dir / CROSSWALK_FILE
    if not path.exists():
        return {}
    mapping: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            machine_id = (row.get("dataset_machine_id") or "").strip()
            tag = (row.get("normalized_tag") or "").strip()
            if tag and machine_id:
                mapping[tag] = machine_id
    return mapping


def _observation_row(
    document: dict[str, Any], observation: dict[str, Any], crosswalk: dict[str, str]
) -> dict[str, Any]:
    provenance = document["provenance"]
    machine = observation["machine"]
    findings = observation["findings"]
    context = cast(dict[str, Any], observation.get("operating_context") or {})
    return {
        "document_id": provenance["document_id"],
        "observation_id": observation["observation_id"],
        "origin": provenance["origin"],
        "record_kind": observation["record_kind"],
        "normalized_tag": machine["normalized_tag"],
        "dataset_machine_id": machine["dataset_machine_id"]
        or crosswalk.get(machine["normalized_tag"]),
        "external_tag": machine["external_tag"],
        "external_name": machine["external_name"],
        "area_code": machine["area_code"],
        "area_name": machine["area_name"],
        "modality": observation["modality"],
        "observed_at": observation["observed_at"],
        "inspection_date": provenance["inspection_date"],
        "status": observation["status"],
        "status_source_label": observation["status_source_label"],
        "alarm": observation["alarm"],
        "global_status_label": observation.get("global_status_label"),
        "diagnosis_text": observation["diagnosis_text"],
        "analysis_text": observation["analysis_text"],
        "recommendation_text": observation["recommendation_text"],
        "rpm1": context.get("rpm1"),
        "rpm2": context.get("rpm2"),
        "power_kw": context.get("power_kw"),
        "source_page": observation.get("source_page"),
        "n_findings": len(findings),
        # clave interna: no es columna, sostiene la proyección de findings
        # alineada 1:1 con la completa.
        "_findings": findings,
    }


def observation_rows(
    documents: list[dict[str, Any]], crosswalk: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Proyección COMPLETA: una fila por observación de cada documento.

    Sin deduplicar — los retrospectivos repetidos por seis informes mensuales
    son seis filas, como en los JSON. El orden es el documental: documentos en
    el orden recibido, observaciones en su orden de origen.
    """
    lookup = crosswalk or {}
    return [
        _observation_row(document, observation, lookup)
        for document in documents
        for observation in document["observations"]
    ]


def consolidated_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Selección deduplicada (política ``dedup-primary-latest/1.0``) + vigencia.

    Para cada clave ``(origin, normalized_tag, observed_at, modality)`` gana el
    registro ``primary``; entre retrospectivos gana el del documento más
    reciente (desempate por ``inspection_date`` ISO, porque el ``document_id``
    lleva la fecha en DDMMAA y su orden lexicográfico no es cronológico). Cada
    fila seleccionada ES una fila de la proyección completa; se añade solo
    ``valid_to``: el ``observed_at`` de la siguiente observación consolidada
    del mismo ``(origin, normalized_tag, modality)``, fecha ISO exclusiva,
    null = vigencia abierta.
    """
    ordered = sorted(
        range(len(rows)),
        key=lambda i: (
            rows[i]["record_kind"] == "primary",
            rows[i]["inspection_date"] or "",
            rows[i]["document_id"],
        ),
    )
    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    for i in ordered:
        row = rows[i]
        best[tuple(row[name] for name in _DEDUPE_KEY)] = row
    selected = [
        dict(best[key]) for key in sorted(best, key=lambda k: tuple(str(v) for v in k))
    ]
    by_series: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in selected:
        by_series.setdefault(tuple(row[name] for name in _VALIDITY_KEY), []).append(row)
    for series in by_series.values():
        series.sort(key=lambda row: row["observed_at"])
        for current, following in pairwise(series):
            current["valid_to"] = following["observed_at"]
        series[-1]["valid_to"] = None
    return selected


def finding_rows(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Proyección completa de findings, alineada 1:1 con ``observations``.

    Se proyecta del conjunto **completo** (no del deduplicado, a diferencia de
    0.1): la deduplicación es una selección de observaciones y vive en un solo
    sitio; un consumidor que puntúe masa filtra por join con
    ``observations_consolidated.parquet``. ``finding_index`` materializa el
    orden del texto del analista, contiguo 0..n-1 dentro de su observación.
    """
    rows: list[dict[str, Any]] = []
    for observation in observations:
        for index, finding in enumerate(observation["_findings"]):
            rows.append(
                {
                    "document_id": observation["document_id"],
                    "observation_id": observation["observation_id"],
                    "finding_index": index,
                    "dataset_machine_id": observation["dataset_machine_id"],
                    "observed_at": observation["observed_at"],
                    "modality": observation["modality"],
                    "record_kind": observation["record_kind"],
                    "fault_mode": finding["fault_mode"],
                    "fault_group": finding["fault_group"],
                    "label_quality": finding["label_quality"],
                    "mapping_rule": finding["mapping_rule"],
                    "weight": finding.get("weight"),
                    "source_text": finding["source_text"],
                    "matched_text": finding.get("matched_text"),
                }
            )
    return rows


def write_parquet(
    rows: list[dict[str, Any]], path: Path, columns: tuple[ColumnSpec, ...]
) -> Path:
    """Escribe ``rows`` como parquet zstd con el esquema explícito del contrato.

    El esquema sale de las ``ColumnSpec`` (tipos fijados, obligatorias
    non-nullable), nunca de inferencia: una columna toda-null se escribe con
    su tipo declarado, jamás como tipo ``null``.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    pa_schema = schema(columns)
    arrays = {
        field.name: pa.array((row.get(field.name) for row in rows), type=field.type)
        for field in pa_schema
    }
    pq.write_table(pa.table(arrays, schema=pa_schema), path, compression="zstd")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class MaterializationSummary:
    """Qué proyectó una pasada de :func:`materialize_ground_truth`."""

    documents: int
    observations: int
    consolidated: int
    findings: int
    written: tuple[Path, ...]


def materialize_ground_truth(
    gt_dir: Path,
    *,
    crosswalk: dict[str, str] | None = None,
    now: datetime | None = None,
) -> MaterializationSummary:
    """Proyecta TODOS los ``*.diaggt.json`` de ``gt_dir`` y ancla su procedencia.

    Escribe las tres proyecciones normativas y ``materialization.json`` en la
    misma operación (regla §4.5.4 del workplan 09): los inputs se hashean tal
    como están en disco y los outputs tal como acaban de escribirse, de modo
    que ``vibframe-validate`` pueda detectar proyecciones desfasadas.

    Todas las familias documentales presentes entran en la proyección completa
    (``origin`` las separa); la clave de dedup del consolidado lleva ``origin``
    para que una alarma de sistema y un informe de analista nunca compitan
    como duplicados.
    """
    documents = sorted(gt_dir.glob(f"*{DIAGGT_FILE_SUFFIX}"))
    if not documents:
        raise ValueError(f"no *{DIAGGT_FILE_SUFFIX} documents in {gt_dir}")
    lookup = crosswalk if crosswalk is not None else read_crosswalk(gt_dir)

    inputs: list[dict[str, Any]] = []
    parsed: list[dict[str, Any]] = []
    for path in documents:
        document = json.loads(path.read_text(encoding="utf-8"))
        parsed.append(document)
        inputs.append(
            {
                "file": path.name,
                "sha256": _sha256(path),
                "observations": len(document["observations"]),
            }
        )

    complete = observation_rows(parsed, lookup)
    consolidated = consolidated_rows(complete)
    findings = finding_rows(complete)

    observations_path = write_parquet(
        complete, gt_dir / OBSERVATIONS_FILE, OBSERVATIONS_COLUMNS
    )
    consolidated_path = write_parquet(
        consolidated, gt_dir / OBSERVATIONS_CONSOLIDATED_FILE, OBSERVATIONS_CONSOLIDATED_COLUMNS
    )
    findings_path = write_parquet(findings, gt_dir / FINDINGS_FILE, FINDINGS_COLUMNS)

    created_at = (now or datetime.now(tz=UTC)).astimezone(UTC)
    manifest = {
        "$schema_version": GT_MATERIALIZATION_SCHEMA_VERSION,
        "kind": GT_MATERIALIZATION_KIND,
        "tool": _tool_name(),
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "consolidation_policy": CONSOLIDATION_POLICY,
        "inputs": inputs,
        "outputs": [
            {
                "file": observations_path.name,
                "sha256": _sha256(observations_path),
                "rows": len(complete),
            },
            {
                "file": consolidated_path.name,
                "sha256": _sha256(consolidated_path),
                "rows": len(consolidated),
            },
            {
                "file": findings_path.name,
                "sha256": _sha256(findings_path),
                "rows": len(findings),
            },
        ],
    }
    manifest_path = gt_dir / GT_MATERIALIZATION_FILE
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    _remove_legacy_projections(gt_dir)
    return MaterializationSummary(
        documents=len(documents),
        observations=len(complete),
        consolidated=len(consolidated),
        findings=len(findings),
        written=(observations_path, consolidated_path, findings_path, manifest_path),
    )


_LEGACY_PROJECTIONS = (
    "observations.csv",
    "findings.csv",
    "observations_system.csv",
    "observations_system.parquet",
)


def _remove_legacy_projections(gt_dir: Path) -> None:
    """Retira las vistas 0.1 al re-materializar (spec §4.5.5 del workplan 09).

    Los CSV nunca tuvieron lector y ``observations_system.parquet`` queda
    integrado en la proyección completa vía ``origin``; dejarlos junto a las
    proyecciones 0.2 sería exactamente la mezcla que
    ``ground-truth.legacy-csv``/``ground-truth.legacy-projection`` señalan.
    """
    for name in _LEGACY_PROJECTIONS:
        path = gt_dir / name
        if path.exists():
            path.unlink()
