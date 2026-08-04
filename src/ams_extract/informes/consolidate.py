"""Consolidados planos del ground truth de informes (spec §5).

``observations.parquet``/``.csv``: una fila por (máquina, ``observed_at``,
modalidad), pensada para el join con las features de VibFrame. Los
``*.diaggt.json`` conservan todo sin deduplicar — el consolidado es una vista.

El ``dataset_machine_id`` no lo resuelve este módulo: lo **proyecta** desde
``crosswalk.csv``, la tabla explícita que la spec §2.4 declara fuente del
mapeo y que produce ``scripts/crosswalk_gt.py`` contra un dataset concreto.
Sin esa tabla la columna sale a ``null`` y el consolidado sigue siendo válido.
"""

# pyright: reportUnknownMemberType=false

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

CROSSWALK_FILE = "crosswalk.csv"
OBSERVATIONS_STEM = "observations"

OBSERVATION_COLUMNS: tuple[str, ...] = (
    "document_id",
    "inspection_date",
    "observed_at",
    "record_kind",
    "external_tag",
    "normalized_tag",
    "dataset_machine_id",
    "external_name",
    "area_code",
    "area_name",
    "modality",
    "status",
    "status_source_label",
    "alarm",
    "fault_modes",
    "fault_groups",
    "diagnosis_text",
    "recommendation_text",
    "analysis_text",
    "rpm1",
    "power_kw",
    "source_page",
)
"""Columnas de ``observations.parquet`` (spec §5), en su orden."""

FINDING_COLUMNS: tuple[str, ...] = (
    "document_id",
    "observation_id",
    "dataset_machine_id",
    "observed_at",
    "modality",
    "record_kind",
    "fault_mode",
    "fault_group",
    "label_quality",
    "mapping_rule",
    "weight",
    "source_text",
)
"""Columnas de ``findings.parquet``, réplica de ``FINDINGS_COLUMNS``.

El contrato las modela (``vibsynth_contracts.diagnosis.external``, 0.1.5) y
aquí se replican como el resto del layout, sin importarlo en runtime
(ADR-0009). La tabla existe aparte de ``observations.parquet`` porque aplanar
los findings dentro de la fila de su observación obliga a colapsarlos en una
cadena, y ese colapso se lleva por delante la multiplicidad, el ``weight``, la
``mapping_rule`` y el ``source_text``.
"""

FINDINGS_STEM = "findings"

_INT_COLUMNS = frozenset({"alarm", "source_page"})
_FLOAT_COLUMNS = frozenset({"rpm1", "power_kw"})

_DEDUPE_KEY = ("normalized_tag", "observed_at", "modality")


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
    modes = sorted({f["fault_mode"] for f in findings if f["fault_mode"]})
    groups = sorted(
        {f["fault_group"] for f in findings if f["fault_group"] not in (None, "UNMAPPED")}
    )
    return {
        "document_id": provenance["document_id"],
        "inspection_date": provenance["inspection_date"],
        "observed_at": observation["observed_at"],
        "record_kind": observation["record_kind"],
        "external_tag": machine["external_tag"],
        "normalized_tag": machine["normalized_tag"],
        "dataset_machine_id": machine["dataset_machine_id"]
        or crosswalk.get(machine["normalized_tag"]),
        "external_name": machine["external_name"],
        "area_code": machine["area_code"],
        "area_name": machine["area_name"],
        "modality": observation["modality"],
        "status": observation["status"],
        "status_source_label": observation["status_source_label"],
        "alarm": observation["alarm"],
        "fault_modes": "+".join(modes) if modes else None,
        "fault_groups": "+".join(groups) if groups else None,
        "diagnosis_text": observation["diagnosis_text"],
        "recommendation_text": observation["recommendation_text"],
        "analysis_text": observation["analysis_text"],
        "rpm1": (observation["operating_context"] or {}).get("rpm1"),
        "power_kw": (observation["operating_context"] or {}).get("power_kw"),
        "source_page": observation["source_page"],
        # claves internas: no son columnas del consolidado, pero sostienen la
        # proyección a findings.parquet sobre el mismo conjunto deduplicado
        "_observation_id": observation["observation_id"],
        "_findings": findings,
    }


def observation_rows(
    documents: list[dict[str, Any]], crosswalk: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Filas del consolidado, deduplicadas y ordenadas (spec §5).

    Los informes mensuales repiten los diagnósticos previos: para cada
    (``normalized_tag``, ``observed_at``, ``modality``) gana el registro
    ``primary``; entre retrospectivos gana el del documento más reciente. El
    desempate va por ``inspection_date`` (ISO) porque el ``document_id``
    («P25/81115-250526») lleva la fecha en DDMMAA y su orden lexicográfico no
    es cronológico.
    """
    lookup = crosswalk or {}
    rows = [
        _observation_row(document, observation, lookup)
        for document in documents
        for observation in document["observations"]
    ]
    rows.sort(
        key=lambda row: (
            row["record_kind"] == "primary",
            row["inspection_date"] or "",
            row["document_id"],
        )
    )
    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        best[tuple(row[name] for name in _DEDUPE_KEY)] = row
    return sorted(best.values(), key=lambda row: tuple(row[name] for name in _DEDUPE_KEY))


def finding_rows(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Una fila por finding de las observaciones **ya deduplicadas**.

    Se deriva del consolidado de observaciones y no de los documentos en bruto
    a propósito: un diagnóstico previo citado por los seis informes mensuales
    contaría seis veces al agregar masa por modo de fallo.
    """
    rows: list[dict[str, Any]] = []
    for observation in observations:
        for finding in observation["_findings"]:
            rows.append(
                {
                    "document_id": observation["document_id"],
                    "observation_id": observation["_observation_id"],
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
                }
            )
    return rows


def _csv_value(value: Any) -> Any:
    return "" if value is None else value


def write_csv(rows: list[dict[str, Any]], path: Path, columns: tuple[str, ...]) -> None:
    """Escribe ``rows`` como CSV con ``columns`` de cabecera."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_csv_value(row[name]) for name in columns])


def write_parquet(rows: list[dict[str, Any]], path: Path, columns: tuple[str, ...]) -> None:
    """Escribe ``rows`` como parquet zstd con el tipo natural de cada columna."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    def column_type(name: str) -> pa.DataType:
        if name == "alarm":
            return pa.int8()
        if name in _INT_COLUMNS:
            return pa.int32()
        if name == "weight":
            return pa.float32()  # el tipo que declara el contrato
        if name in _FLOAT_COLUMNS:
            return pa.float64()
        return pa.string()

    table = pa.table(
        {
            name: pa.array([row[name] for row in rows], type=column_type(name))
            for name in columns
        }
    )
    pq.write_table(table, path, compression="zstd")


def write_observations(rows: list[dict[str, Any]], gt_dir: Path) -> list[Path]:
    """Escribe ``observations.parquet`` y ``observations.csv``."""
    parquet_path = gt_dir / f"{OBSERVATIONS_STEM}.parquet"
    csv_path = gt_dir / f"{OBSERVATIONS_STEM}.csv"
    write_parquet(rows, parquet_path, OBSERVATION_COLUMNS)
    write_csv(rows, csv_path, OBSERVATION_COLUMNS)
    return [parquet_path, csv_path]


def write_findings(rows: list[dict[str, Any]], gt_dir: Path) -> Path:
    """Escribe ``findings.parquet``. Sin CSV: el contrato sólo nombra el parquet."""
    path = gt_dir / f"{FINDINGS_STEM}.parquet"
    write_parquet(rows, path, FINDING_COLUMNS)
    return path
