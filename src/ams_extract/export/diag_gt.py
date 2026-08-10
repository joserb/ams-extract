"""Emit the alarms AMS itself raised as a DiagGT ground-truth document.

Every point of an AMS database carries the verdict of its last exception
analysis — *"SUBSINCRONO - 1.986 mm/Seg - C Alarm"* — in a ``gdnl`` note
dated by its ``gdsc`` header (FORMAT §5.9). That is a **judgement about
the state of a machine at an instant**, which is exactly what DiagGT
represents (``docs/GROUND_TRUTH.md``), so this module publishes it as a
``<name>.diaggt.json`` with ``provenance.origin = "system-alarm"``: the
system's own threshold verdict, complementary to (and independent of) the
analyst reports extracted from the inspection PDFs.

Design notes:

- **One observation per alarming point**, not per machine: a machine can
  have several points in alarm, each with its own band, value and date.
  The point is named in ``analysis_text`` because DiagGT v0.1 has no
  component reference (spec §6); the machine is the join key.
- **Only validated alarms are emitted** (repo rule "no emitir lo no
  validado"): the note's value must fall inside the interval its level
  claims, against the point's ``pdla`` thresholds, in the same unit. The
  18 BUNGE alarms whose ``pdla`` slot disagrees in unit with the note are
  counted and skipped, never silently emitted.
- **No dependency on vibsynth-contracts at runtime** (ADR-0009): the
  document is built as plain dicts and the normative Pydantic models are
  applied in the tests.
- Calm points produce no observation. Absence of an observation therefore
  means "not in alarm *or* not analysed", never a positive OK.

Status mapping (spec §3.1): AMS's ``C Alarm`` is the "Alerta" tier →
``ALERT`` / ``alarm = 2``; ``D Alarm`` is "Peligro" → ``DANGER`` /
``alarm = 3``. This is the same 0/2/3 scale the derived trend column uses
(ADR-0012); ``WATCH``/1 stays unused because AMS has no tier between
normal and alert.
"""

# pyright: reportUnknownMemberType=false

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import structlog

from ams_extract.models import AlarmNote, Area, Equipment, Point
from ams_extract.reader import RbmReader
from ams_extract.records.pdpa import ParamSetIndex
from ams_extract.tree import walk_alarm_note, walk_hierarchy

_log = structlog.get_logger(__name__)

DIAGGT_SCHEMA_VERSION = "0.1.2"
DIAGGT_KIND = "diagnosis_ground_truth"
DIAGGT_FILE_SUFFIX = ".diaggt.json"
GROUND_TRUTH_DIR = "ground-truth"
"""Optional root directory of a VibFrame dataset that hosts DiagGT documents."""

DOCUMENT_ID_PREFIX = "ams-gdnl"
PROVIDER = "AMS Machinery Manager (Emerson)"
MODALITY = "vibration"
ORIGIN = "system-alarm"
EXTRACTION_METHOD = "structured_read"
"""Decode of a binary record, no free-text interpretation (spec §2.2, 0.1.2)."""

STATUS_BY_LEVEL = {"C": ("ALERT", 2), "D": ("DANGER", 3)}
"""AMS alarm level → (DiagGT ``status``, VibFrame ``alarm``)."""

BAND_FINDING_RULES: dict[str, tuple[str, str | None, str, str]] = {
    "DESEQUILIBRIO": ("GT050", "IMBALANCE", "IMBALANCE", "weak"),
    "DESALINEACION": ("GT051", None, "MISALIGNMENT", "group"),
    "HOLGURAS": ("GT052", "LOOSENESS", "LOOSENESS", "weak"),
    "FALLO ELECTRIC": ("GT053", "ELECTRICAL_ROTOR", "ELECTRICAL", "weak"),
}
"""Band name → ``(rule, fault_mode, fault_group, label_quality)``.

The GT050 family (spec §3.4) exists because a band alarm is *evidence*,
not a diagnosis: the band is named by the plant's own ``pdpa`` template,
so "the DESEQUILIBRIO band crossed its limit" supports IMBALANCE but does
not assert it the way an analyst's sentence does — hence ``weak`` where
the analyst-prose rules GT001/GT004/GT013 say ``direct``/``approximate``.
Bands with no fault semantics (SUBSINCRONO, OVERALL VALUE, Mp Wave,
``11-40 X RPM``, ``1 - 20 KHz``…) map to nothing and produce the
mandatory ``unmapped`` finding instead.
"""

UNMAPPED_FINDING = ("UNMAPPED", "unmapped")

_TAG_RE = re.compile(r"\b([A-Za-z]{2,4}[-./][A-Za-z0-9][A-Za-z0-9/.\- ]*)$")
"""Plant TAG at the tail of an AMS equipment name (``… AG-100`` → ``AG-100``)."""

_NON_ALNUM = re.compile(r"[^A-Z0-9]")

HASH_CHUNK = 1 << 20


@dataclass(frozen=True, slots=True)
class AlarmGroundTruthSummary:
    """What one :func:`build_alarm_ground_truth` run found and published."""

    points: int
    notes: int
    alarms: int
    emitted: int
    skipped_unit_mismatch: int
    skipped_incoherent: int
    machines: int
    alert: int
    danger: int
    first_observed: str | None
    last_observed: str | None

    @property
    def coherent_pct(self) -> float:
        """Percentage of parsed alarms whose value matches its ``pdla`` interval."""
        if not self.alarms:
            return 0.0
        return 100.0 * (self.alarms - self.skipped_incoherent) / self.alarms


def machine_tag(equipment_name: str) -> str | None:
    """Return the plant TAG at the tail of an AMS equipment name, if any.

    ``"MECLADOR AGITADOR AG-100"`` → ``"AG-100"``,
    ``"Bomba Centrifuga PM-0CI/1"`` → ``"PM-0CI/1"``. Names that carry no
    TAG (``"MEZCLADOR"``, ``"AGITADOR"``) return ``None``.
    """
    match = _TAG_RE.search(equipment_name.strip())
    return match.group(1).strip() if match else None


def normalize_tag(tag: str) -> str:
    """Uppercase, separator-free form of a TAG, for joins across sources.

    Same normalization the analyst-report crosswalk uses (spec §2.4), so
    ``"AG-100"`` here and ``"AG.100"`` there both become ``"AG100"``.
    """
    return _NON_ALNUM.sub("", tag.upper())


def file_sha256(path: Path) -> str:
    """SHA-256 of ``path``, the verification anchor of the provenance block."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _extractor_name() -> str:
    try:
        return f"ams-extract {version('ams-extract')}"
    except PackageNotFoundError:
        return "ams-extract 0.0.0"


def _findings(note: AlarmNote) -> list[dict[str, Any]]:
    """Canonical findings of an alarm note — never empty, never silent."""
    band = (note.band or "").upper()
    rule = BAND_FINDING_RULES.get(band)
    if rule is None:
        group, quality = UNMAPPED_FINDING
        return [
            {
                "source_text": note.text,
                "matched_text": note.band,
                "fault_mode": None,
                "fault_group": group,
                "label_quality": quality,
                "mapping_rule": None,
            }
        ]
    rule_id, fault_mode, fault_group, quality = rule
    return [
        {
            "source_text": note.text,
            "matched_text": note.band,
            "fault_mode": fault_mode,
            "fault_group": fault_group,
            "label_quality": quality,
            "mapping_rule": rule_id,
        }
    ]


def _analysis_text(point: Point, note: AlarmNote) -> str:
    """Derived evidence line: where the alarm fired and against what limits."""
    units = note.units or ""
    parts = [
        f"Punto {point.long_name} ({point.short_code})",
        f"banda {note.band} = {note.value} {units}".strip(),
    ]
    if note.alert is not None or note.danger is not None:
        alert = "-" if note.alert is None else f"{note.alert:.4g}"
        danger = "-" if note.danger is None else f"{note.danger:.4g}"
        limits = f"umbrales C {alert} / D {danger} {units}".strip()
        if note.limit_set:
            limits += f' (set pdla "{note.limit_set}")'
        parts.append(limits)
    parts.append(f"severidad AMS {note.severity}/100")
    return "; ".join(parts) + "."


def _observation(
    area: Area,
    equipment: Equipment,
    point: Point,
    note: AlarmNote,
    document_id: str,
) -> dict[str, Any] | None:
    """Build one DiagGT observation from a validated alarm note."""
    if note.level is None or note.measured_at_utc is None:
        return None
    status, alarm = STATUS_BY_LEVEL[note.level]
    tag = machine_tag(equipment.long_name)
    observed_at = note.measured_at_utc.date().isoformat()
    return {
        "observation_id": (
            f"{document_id}:{equipment.short_code}:{point.short_code}:"
            f"{MODALITY}:{observed_at}"
        ),
        "record_kind": "primary",
        "machine": {
            "external_tag": tag,
            "external_name": equipment.long_name,
            "normalized_tag": normalize_tag(tag or equipment.long_name),
            "area_code": "",
            "area_name": area.long_name,
            "dataset_machine_id": equipment.short_code,
        },
        "modality": MODALITY,
        "observed_at": observed_at,
        "status": status,
        "status_source_label": f"{note.level} Alarm",
        "alarm": alarm,
        "global_status_label": None,
        "diagnosis_text": note.text,
        "analysis_text": _analysis_text(point, note),
        "recommendation_text": None,
        "findings": _findings(note),
        "operating_context": None,
        "source_page": None,
    }


def _iter_points(areas: Iterable[Area]) -> Iterator[tuple[Area, Equipment, Point]]:
    for area in areas:
        for equipment in area.equipment:
            for point in equipment.points:
                yield area, equipment, point


def build_alarm_ground_truth(
    reader: RbmReader,
    *,
    source_path: Path,
    source_sha256: str | None = None,
    client: str = "",
    plant: str = "",
    extracted_at: datetime | None = None,
) -> tuple[dict[str, Any], AlarmGroundTruthSummary]:
    """Return the DiagGT document of the alarms stored in ``reader``'s database.

    Walks the whole hierarchy, reads each point's alarm note (FORMAT §5.9)
    and emits one observation per **validated** alarm — the ones whose
    value falls where its C/D level claims, checked against the point's
    ``pdla`` thresholds in a matching unit. Everything else is counted in
    the returned summary and left out of the document.
    """
    areas = walk_hierarchy(reader)
    param_sets = ParamSetIndex.load(reader)
    document_id = f"{DOCUMENT_ID_PREFIX}:{source_path.stem}"

    observations: list[dict[str, Any]] = []
    machines: set[str] = set()
    points = notes = alarms = unit_mismatch = incoherent = 0
    alert = danger = 0
    dates: list[str] = []

    for area, equipment, point in _iter_points(areas):
        points += 1
        note = walk_alarm_note(reader, point, param_sets)
        if note is None:
            continue
        notes += 1
        if not note.in_alarm:
            continue
        alarms += 1
        if note.coherent is not True:
            incoherent += 1
            _log.warning(
                "alarm_note_incoherent_with_limits",
                equipment=equipment.long_name,
                point=point.long_name,
                band=note.band,
                value=note.value,
                level=note.level,
                alert=note.alert,
                danger=note.danger,
            )
            continue
        if not note.unit_consistent:
            unit_mismatch += 1
            _log.info(
                "alarm_note_unit_mismatch_skipped",
                equipment=equipment.long_name,
                point=point.long_name,
                band=note.band,
                units=note.units,
                limit_set=note.limit_set,
            )
            continue
        observation = _observation(area, equipment, point, note, document_id)
        if observation is None:
            continue
        observations.append(observation)
        machines.add(equipment.short_code)
        dates.append(observation["observed_at"])
        if note.level == "C":
            alert += 1
        else:
            danger += 1

    observations.sort(key=lambda obs: obs["observation_id"])
    summary = AlarmGroundTruthSummary(
        points=points,
        notes=notes,
        alarms=alarms,
        emitted=len(observations),
        skipped_unit_mismatch=unit_mismatch,
        skipped_incoherent=incoherent,
        machines=len(machines),
        alert=alert,
        danger=danger,
        first_observed=min(dates) if dates else None,
        last_observed=max(dates) if dates else None,
    )
    now = extracted_at or datetime.now(tz=UTC)
    document: dict[str, Any] = {
        "$schema_version": DIAGGT_SCHEMA_VERSION,
        "kind": DIAGGT_KIND,
        "provenance": {
            "origin": ORIGIN,
            "provider": PROVIDER,
            "document_id": document_id,
            "document_title": f"Alarmas almacenadas por AMS - {source_path.stem}",
            "source_ref": source_path.name,
            "source_sha256": source_sha256,
            "client": client,
            "plant": plant,
            "inspection_date": None,
            "measurement_period": {
                "from": summary.first_observed,
                "to": summary.last_observed,
            },
            "routes": [],
            "analysts": [],
            "reviewers": [],
            "extractor": _extractor_name(),
            "extracted_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "extraction_method": EXTRACTION_METHOD,
        },
        "machines_stopped": [],
        "machines_not_measured": [],
        "observations": observations,
    }
    return document, summary


def write_alarm_ground_truth(
    document: dict[str, Any],
    out_dir: Path,
    *,
    stem: str,
) -> list[Path]:
    """Write ``document`` to ``out_dir`` and return the paths written.

    Only the ``*.diaggt.json`` is written here: since VibFrame 0.2 the
    system-alarm observations consolidate into the same normative
    projections as every other family (``observations.parquet`` and friends,
    with the ``origin`` column keeping the judgements apart), materialized by
    :func:`ams_extract.informes.consolidate.materialize_ground_truth` over the
    whole ``ground-truth/`` directory. The 0.1 side files
    ``observations_system.parquet``/``.csv`` are legacy
    (``ground-truth.legacy-projection``/``legacy-csv``) and are no longer
    emitted.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{stem}{DIAGGT_FILE_SUFFIX}"
    json_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return [json_path]
