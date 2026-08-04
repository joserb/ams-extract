"""Full-database export to the VibFrame layout.

``rbm export`` writes a local copy of the VibFrame exchange format imported
from ``vibsynth-contracts``. The previous ``manifest.parquet`` + ``samples/``
layout is obsolete; ``rbm serve dataset/`` reads this layout directly.
"""

# pyright: reportUnknownMemberType=false

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import structlog
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

from ams_extract.export.html_report import write_inventory_html
from ams_extract.export.json_tree import build_tree_document
from ams_extract.export.vibframe_contract import (
    DATASET_FILE,
    MACHINE_DOC_FILE,
    MACHINE_PARTITION_PREFIX,
    METRICS_COLUMNS,
    METRICS_FILE,
    SCHEMA_VERSION,
    SPECTRA_COLUMNS,
    SPECTRA_FILE,
    TRENDS_COLUMNS,
    TRENDS_FILE,
    WAVES_COLUMNS,
    WAVES_FILE,
    ColumnSpec,
    schema,
)
from ams_extract.models import (
    Area,
    Equipment,
    Point,
    Spectrum,
    Trend,
    TrendBand,
    Waveform,
)
from ams_extract.point_naming import parse_point_name
from ams_extract.reader import RbmReader
from ams_extract.records.pdpa import ParamSetIndex
from ams_extract.report import collect_inventory
from ams_extract.tree import walk_hierarchy, walk_spectra, walk_trends, walk_waveforms

_log = structlog.get_logger(__name__)

FFT = "fft"
WAVEFORM = "waveform"
TREND = "trend"
VALID_TYPES = frozenset({FFT, WAVEFORM, TREND})
CONFIG_ID = ""
TREND_METRIC_NAME_VELOCITY = "overall_velocity_rms"
TREND_METRIC_NAME_ACCELERATION = "overall_acceleration_rms"
# Reserved machine-level operating-context metric ids (VibFrame spec,
# "Reserved context metrics"). AMS has no machine state -> no "state".
CONTEXT_METRIC_SPEED = "speed"
CONTEXT_METRIC_LOAD = "load"
CONTEXT_METRIC_UNITS = {CONTEXT_METRIC_SPEED: "Hz", CONTEXT_METRIC_LOAD: "%"}


@dataclass(frozen=True)
class EquipmentResult:
    """Outcome of exporting a single asset/machine."""

    area_short: str
    equipment_short: str
    n_fft: int
    n_waveform: int
    n_trend: int
    n_files: int
    error: str | None = None


@dataclass(frozen=True)
class ExportSummary:
    """Aggregate counts for a completed export."""

    areas: int
    equipment_total: int
    equipment_with_samples: int
    equipment_failed: int
    fft_samples: int
    waveform_samples: int
    trend_samples: int
    parquet_files: int
    manifest_rows: int = 0


def _extractor_name() -> str:
    try:
        return f"ams-extract {version('ams-extract')}"
    except PackageNotFoundError:
        return "ams-extract 0.0.0"


def _timestamp_us(ts: datetime) -> int:
    """Return epoch microseconds UTC for ``ts``."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return int(ts.astimezone(UTC).timestamp() * 1_000_000)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raise TypeError(f"object of type {type(value).__name__} is not JSON serializable")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _pa_table(rows: Sequence[dict[str, Any]], columns: tuple[ColumnSpec, ...]) -> pa.Table:
    pa_schema = schema(columns)
    arrays = {
        field.name: pa.array(
            [row.get(field.name) for row in rows],
            type=field.type,
        )
        for field in pa_schema
    }
    return pa.table(arrays, schema=pa_schema)


def _write_parquet(
    rows: Sequence[dict[str, Any]],
    columns: tuple[ColumnSpec, ...],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(_pa_table(rows, columns), path)


def _filter_areas(areas: Iterable[Area], area_filter: set[str] | None) -> list[Area]:
    """Return areas selected by ``area_filter`` (case-insensitive)."""
    area_list = list(areas)
    if area_filter is None:
        return area_list
    wanted = {t.strip().lower() for t in area_filter if t.strip()}
    selected = [
        a for a in area_list if a.long_name.lower() in wanted or a.short_code.lower() in wanted
    ]
    matched = {a.long_name.lower() for a in selected} | {a.short_code.lower() for a in selected}
    for token in wanted - matched:
        _log.warning("area_filter_no_match", token=token)
    return selected


def _signal_family(unit: str) -> str:
    if unit == "mm/s":
        return "velocity"
    if unit in {"G's", "g"}:
        return "acceleration"
    return "non_vibration"


def _proc_prefix(unit: str) -> str:
    family = _signal_family(unit)
    if family == "velocity":
        return "VEL"
    if family == "acceleration":
        return "ACC"
    return "UNK"


def _canonical_unit(unit: str) -> str:
    """Map AMS display-unit spellings to VibFrame canonical units."""
    return "g" if unit == "G's" else unit


def _fmt_num(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}".replace(".", "p")


def _spectrum_mode_id(spectrum: Spectrum) -> str:
    return f"{_proc_prefix(spectrum.units)}_{_fmt_num(spectrum.fmax_hz)}"


def _waveform_mode_id(waveform: Waveform) -> str:
    return f"WAVE_{_proc_prefix(waveform.units)}_{_fmt_num(waveform.sample_rate_hz)}"


def _trend_metric_name(trend: Trend) -> str:
    if _signal_family(trend.units) == "acceleration":
        return TREND_METRIC_NAME_ACCELERATION
    return TREND_METRIC_NAME_VELOCITY


def _trend_metric_id(trend: Trend, point: Point) -> str:
    return f"{_trend_metric_name(trend)}__{point.short_code}"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _band_metric_id(point: Point, band: TrendBand) -> str:
    return f"band_{_slug(band.name)}__{point.short_code}"


def _machine_dir(out_dir: Path, equipment: Equipment) -> Path:
    return out_dir / f"{MACHINE_PARTITION_PREFIX}{equipment.short_code}"


def _build_point_doc(point: Point) -> dict[str, Any]:
    """Return the VibFrame ``PointDoc`` of an AMS point.

    AMS stores no structured placement, so ``location``/``direction`` are read
    off the point name — the only place the analyst wrote them (see
    :mod:`ams_extract.point_naming`); names that declare neither stay ``None``.
    ``sensor`` and ``speed_source`` have no counterpart in the ``.rbm`` at all.

    ``bearing_designations`` and ``nominal_speed_rpm`` are what the point's
    ``vdpm`` record declares about its shaft (FORMAT §3.2), emitted
    **verbatim**: the designations keep the analyst's free text (``6204``,
    ``SKF 6308``, ``22218 EKC3``) because normalizing them against a catalogue
    is the enricher's job, and the speed goes out in RPM as stored. A point
    that declares no bearing gets an empty list; one without a usable speed
    gets ``null``, never ``0``.
    """
    placement = parse_point_name(point.long_name)
    return {
        "id": point.short_code,
        "name": point.long_name,
        "location": placement.location,
        "direction": placement.direction,
        "sensor": None,
        "speed_source": None,
        "bearing_designations": list(point.bearing_designations),
        "nominal_speed_rpm": point.nominal_speed_rpm,
    }


def _build_machine_doc(
    *,
    source_path: str,
    extracted_at: datetime,
    area_long: str,
    equipment: Equipment,
    proc_modes: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "origin": "ams-rbm",
            "extractor": _extractor_name(),
            "extracted_at": extracted_at,
            "source_ref": source_path,
            "device": None,
        },
        "machine": {
            "id": equipment.short_code,
            "name": equipment.long_name,
            # Location levels only (area); the machine is its own level in
            # the location -> machine hierarchy the viewers build from path.
            "path": [area_long],
            "fault_frequencies_order": {},
            "definition": None,
        },
        "points": [_build_point_doc(point) for point in equipment.points],
        "proc_modes": list(proc_modes),
        "config_generations": [],
        "states": [],
        "ground_truth": None,
    }


PROC_MODE_NOTES = "Decoded from AMS RBM; detailed acquisition metadata not decoded yet."


def _proc_mode_notes(n_samples: int | None, nominal_n_samples: int | None) -> str:
    """Base note plus, for waveforms, the nominal block the analyzer asked for.

    ``n_samples`` is always the emitted array length; the AMS acquisition
    block (``vdfw.0x2C``) differs from it by design (FORMAT §5.5), so it is
    recorded here as prose instead of overwriting the length field.
    """
    if nominal_n_samples is None or nominal_n_samples == n_samples:
        return PROC_MODE_NOTES
    return (
        f"{PROC_MODE_NOTES} AMS acquisition block is {nominal_n_samples} samples; "
        f"{n_samples} are stored and emitted (FORMAT §5.5)."
    )


def _add_proc_mode(
    modes: dict[tuple[str, str], dict[str, Any]],
    *,
    point_id: str,
    mode_id: str,
    signal_family: str,
    sample_rate_hz: float | None = None,
    n_samples: int | None = None,
    nominal_n_samples: int | None = None,
    fmax_hz: float | None = None,
    lines: int | None = None,
) -> None:
    key = (point_id, mode_id)
    if key in modes:
        return
    modes[key] = {
        "id": mode_id,
        "point_id": point_id,
        "signal_family": signal_family,
        "sample_rate_hz": sample_rate_hz,
        "n_samples": n_samples,
        "fmin_hz": 0.0 if fmax_hz is not None else None,
        "fmax_hz": fmax_hz,
        "lines": lines,
        "window": None,
        "averages": None,
        "overlap": None,
        "spectrum_detector": "peak" if fmax_hz is not None else None,
        "power": False if fmax_hz is not None else None,
        "grid_kind": "hz_uniform",
        "integrate_spectrum": None,
        "integrate_waveform": None,
        "hp_filter_freq_hz": None,
        "hp_filter_order": None,
        "notes": _proc_mode_notes(n_samples, nominal_n_samples),
    }


def _spectrum_row(spectrum: Spectrum, point: Point) -> dict[str, Any]:
    signal_family = _signal_family(spectrum.units)
    return {
        "t": _timestamp_us(spectrum.timestamp_utc),
        "snap_t": None,
        "point_id": point.short_code,
        "proc_mode_id": _spectrum_mode_id(spectrum),
        "fmin_hz": 0.0,
        "fmax_hz": spectrum.fmax_hz,
        "lines": spectrum.n_lines,
        "window": None,
        "averages": None,
        "spectrum_detector": "peak",
        "power": False,
        "unit": _canonical_unit(spectrum.units),
        "signal_family": signal_family,
        "speed_hz": spectrum.rpm / 60.0 if spectrum.rpm > 0 else None,
        "config_id": CONFIG_ID,
        "data": spectrum.amplitude.tolist(),
    }


def _waveform_row(waveform: Waveform, point: Point) -> dict[str, Any]:
    # VibFrame requires n_samples == len(data): the time axis is derived
    # from t + i / sample_rate_hz, so any other value breaks the wave
    # (vibframe-validate `waves.data-length`). Waveform.n_samples already
    # is the emitted length; the AMS nominal block lives in the proc mode
    # notes (FORMAT §5.5, ADR-0017).
    rpm = float(waveform.rpm)
    return {
        "t": _timestamp_us(waveform.timestamp_utc),
        "snap_t": None,
        "point_id": point.short_code,
        "proc_mode_id": _waveform_mode_id(waveform),
        "sample_rate_hz": waveform.sample_rate_hz,
        "n_samples": waveform.n_samples,
        "unit": _canonical_unit(waveform.units),
        "signal_family": _signal_family(waveform.units),
        "speed_hz": rpm / 60.0 if rpm > 0 else None,
        "sync": None,
        "tacho_rising": None,
        "tacho_falling": None,
        "config_id": CONFIG_ID,
        "data": waveform.samples.tolist(),
    }


def _alarm_at(alarms: Sequence[int | None], i: int) -> int | None:
    """Derived alarm level for reading ``i``, or ``None`` if not computed."""
    return alarms[i] if i < len(alarms) else None


def _trend_rows(trend: Trend, point: Point) -> list[dict[str, Any]]:
    metric_id = _trend_metric_id(trend, point)
    return [
        {
            "t": _timestamp_us(trend.timestamps_utc[i]),
            "metric_id": metric_id,
            "value": float(trend.overall[i]),
            # DERIVED from the pdla thresholds (0 normal / 2 alert / 3
            # danger), not read from the undecoded per-slot flags (ADR-0012).
            "alarm": _alarm_at(trend.alarms, i),
            "config_id": CONFIG_ID,
        }
        for i in range(len(trend.overall))
    ]


def _band_trend_rows(band: TrendBand, point: Point) -> list[dict[str, Any]]:
    metric_id = _band_metric_id(point, band)
    return [
        {
            "t": _timestamp_us(band.timestamps_utc[i]),
            "metric_id": metric_id,
            "value": float(band.values[i]),
            # DERIVED from the pdla thresholds; see _trend_rows.
            "alarm": _alarm_at(band.alarms, i),
            "config_id": CONFIG_ID,
        }
        for i in range(len(band.values))
    ]


def _band_metric_row(band: TrendBand, point: Point) -> dict[str, Any]:
    """Descriptor for one named vddt band (FORMAT §5.7/§5.8).

    "Mp Wave" (F.Onda Pico Máx) is a waveform acceleration peak, not a
    spectral band; every bounded band is a spectral RMS whose frequency
    bounds come from the point's pdpa analysis parameter set — in shaft
    orders for order-scaled bands, in Hz for fixed-frequency bands
    (velocity in mm/s, or acceleration in g for the HF "1 - 20 KHz" band).
    """
    family = _signal_family(band.units)
    has_bounds = band.low_order is not None or band.low_hz is not None
    is_peak = family == "acceleration" and not has_bounds
    return {
        "metric_id": _band_metric_id(point, band),
        "config_id": CONFIG_ID,
        "point_id": point.short_code,
        "proc_mode_id": None,
        "name": band.name,
        "path": f"{point.short_code}:{band.name}",
        "statistic": "true_peak" if is_peak else "spectrum_rms",
        "signal_family": family,
        "detector": "peak" if is_peak else "rms",
        "unit": _canonical_unit(band.units),
        "integrate": False,
        "band_type": "single" if has_bounds else "none",
        "band_low_hz": band.low_hz,
        "band_high_hz": band.high_hz,
        "band_low_order": band.low_order,
        "band_high_order": band.high_order,
        "frequency_role": None,
        "harmonic_orders": None,
        "n_sidebands": None,
        "modulator": None,
        "flags": [],
        "canonical_metric": None,
        "proxy_quality": None,
        "mapping_rule": None,
    }


def _metric_row(trend: Trend, point: Point) -> dict[str, Any]:
    name = _trend_metric_name(trend)
    return {
        "metric_id": _trend_metric_id(trend, point),
        "config_id": CONFIG_ID,
        "point_id": point.short_code,
        "proc_mode_id": None,
        "name": name,
        "path": f"{point.short_code}:{name}",
        "statistic": "spectrum_rms",
        "signal_family": _signal_family(trend.units),
        "detector": "rms",
        "unit": _canonical_unit(trend.units),
        "integrate": False,
        "band_type": "none",
        "band_low_hz": None,
        "band_high_hz": None,
        "band_low_order": None,
        "band_high_order": None,
        "frequency_role": None,
        "harmonic_orders": None,
        "n_sidebands": None,
        "modulator": None,
        "flags": [],
        "canonical_metric": None,
        "proxy_quality": None,
        "mapping_rule": None,
    }


def _context_trend_rows(
    captures: Iterable[tuple[int, float, float]],
) -> list[dict[str, Any]]:
    """Machine-level ``speed``/``load`` readings from capture context.

    ``captures`` yields ``(t_us, rpm, carga_pct)`` from every spectrum and
    waveform of the machine. ``speed`` is the AMS analysis RPM / 60 (Hz;
    it may differ from the physical shaft speed, ADR-0013/ADR-0015);
    readings with rpm <= 0 are skipped. ``load`` is the CARGA % field
    emitted as-is (0.0 and 100.0 are valid readings). Exact duplicates
    (same t + metric + value) collapse: spectrum and waveform of the same
    point/timestamp share the rpm.
    """
    seen: set[tuple[int, str, float]] = set()
    rows: list[dict[str, Any]] = []
    for t_us, rpm, carga_pct in captures:
        readings: list[tuple[str, float]] = [(CONTEXT_METRIC_LOAD, float(carga_pct))]
        if rpm > 0:
            readings.append((CONTEXT_METRIC_SPEED, rpm / 60.0))
        for metric_id, value in readings:
            key = (t_us, metric_id, value)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "t": t_us,
                    "metric_id": metric_id,
                    "value": value,
                    "alarm": None,
                    "config_id": CONFIG_ID,
                }
            )
    rows.sort(key=lambda r: (r["metric_id"], r["t"]))
    return rows


def _context_metric_row(metric_id: str, machine_id: str) -> dict[str, Any]:
    """Descriptor for a reserved machine-level context metric.

    Reserved ids are literal (no point suffix) with ``point_id`` null; the
    canonical labelling stays null like every other metric — it is a
    post-process with t8-mapper (ADR-0011), whose engine resolves these
    ids through its RESERVED rule.
    """
    return {
        "metric_id": metric_id,
        "config_id": CONFIG_ID,
        "point_id": None,
        "proc_mode_id": None,
        "name": metric_id,
        "path": f"{machine_id}:{metric_id}",
        "statistic": "value",
        "signal_family": "non_vibration",
        "detector": None,
        "unit": CONTEXT_METRIC_UNITS[metric_id],
        "integrate": None,
        "band_type": "none",
        "band_low_hz": None,
        "band_high_hz": None,
        "band_low_order": None,
        "band_high_order": None,
        "frequency_role": None,
        "harmonic_orders": None,
        "n_sidebands": None,
        "modulator": None,
        "flags": [],
        "canonical_metric": None,
        "proxy_quality": None,
        "mapping_rule": None,
    }


def _process_equipment(
    reader: RbmReader,
    source_path: str,
    extracted_at: datetime,
    area_short: str,
    area_long: str,
    equipment: Equipment,
    types: set[str],
    out_dir: Path,
) -> EquipmentResult:
    """Export every sample of ``equipment`` as one VibFrame asset."""
    try:
        spectra_rows: list[dict[str, Any]] = []
        wave_rows: list[dict[str, Any]] = []
        trend_rows: list[dict[str, Any]] = []
        metric_rows: dict[str, dict[str, Any]] = {}
        proc_modes: dict[tuple[str, str], dict[str, Any]] = {}
        # (t_us, rpm, carga_pct) of every capture: machine-level context.
        context_captures: list[tuple[int, float, float]] = []
        param_sets = ParamSetIndex.load(reader) if TREND in types else None

        for point in equipment.points:
            if FFT in types:
                for spectrum in walk_spectra(reader, point):
                    row = _spectrum_row(spectrum, point)
                    spectra_rows.append(row)
                    context_captures.append((row["t"], spectrum.rpm, spectrum.carga_pct))
                    _add_proc_mode(
                        proc_modes,
                        point_id=point.short_code,
                        mode_id=_spectrum_mode_id(spectrum),
                        signal_family=_signal_family(spectrum.units),
                        fmax_hz=spectrum.fmax_hz,
                        lines=spectrum.n_lines,
                    )
            if WAVEFORM in types:
                for waveform in walk_waveforms(reader, point):
                    row = _waveform_row(waveform, point)
                    wave_rows.append(row)
                    context_captures.append((row["t"], float(waveform.rpm), waveform.carga_pct))
                    _add_proc_mode(
                        proc_modes,
                        point_id=point.short_code,
                        mode_id=_waveform_mode_id(waveform),
                        signal_family=_signal_family(waveform.units),
                        sample_rate_hz=waveform.sample_rate_hz,
                        n_samples=waveform.n_samples,
                        nominal_n_samples=waveform.nominal_n_samples,
                    )
            if TREND in types:
                for trend in walk_trends(reader, point, param_sets):
                    rows = _trend_rows(trend, point)
                    if rows:
                        trend_rows.extend(rows)
                        metric_rows[_trend_metric_id(trend, point)] = _metric_row(
                            trend, point
                        )
                    for band in trend.bands:
                        band_rows = _band_trend_rows(band, point)
                        if band_rows:
                            trend_rows.extend(band_rows)
                            metric_rows[_band_metric_id(point, band)] = _band_metric_row(
                                band, point
                            )

        context_rows = _context_trend_rows(context_captures)
        if context_rows:
            trend_rows.extend(context_rows)
            for metric_id in sorted({r["metric_id"] for r in context_rows}):
                metric_rows[metric_id] = _context_metric_row(metric_id, equipment.short_code)

        machine_dir = _machine_dir(out_dir, equipment)
        _write_json(
            machine_dir / MACHINE_DOC_FILE,
            _build_machine_doc(
                source_path=source_path,
                extracted_at=extracted_at,
                area_long=area_long,
                equipment=equipment,
                proc_modes=sorted(proc_modes.values(), key=lambda m: (m["point_id"], m["id"])),
            ),
        )
        _write_parquet(
            sorted(metric_rows.values(), key=lambda r: r["metric_id"]),
            METRICS_COLUMNS,
            machine_dir / METRICS_FILE,
        )
        _write_parquet(spectra_rows, SPECTRA_COLUMNS, machine_dir / SPECTRA_FILE)
        _write_parquet(wave_rows, WAVES_COLUMNS, machine_dir / WAVES_FILE)
        _write_parquet(trend_rows, TRENDS_COLUMNS, machine_dir / TRENDS_FILE)

        return EquipmentResult(
            area_short=area_short,
            equipment_short=equipment.short_code,
            n_fft=len(spectra_rows),
            n_waveform=len(wave_rows),
            n_trend=len(trend_rows),
            n_files=5,
        )
    except Exception as exc:  # defensive: keep the run alive past a bad machine
        _log.warning(
            "equipment_export_failed",
            area=area_short,
            equipment=equipment.short_code,
            error=str(exc),
        )
        return EquipmentResult(
            area_short=area_short,
            equipment_short=equipment.short_code,
            n_fft=0,
            n_waveform=0,
            n_trend=0,
            n_files=0,
            error=str(exc),
        )


def _export_equipment_worker(
    job: tuple[str, str, str, str, str, Equipment, list[str], str],
) -> EquipmentResult:
    """ProcessPool entry point: re-open the mmap and export one equipment."""
    (
        file_str,
        source_path,
        extracted_at_iso,
        area_short,
        area_long,
        equipment,
        type_list,
        out_str,
    ) = job
    extracted_at = datetime.fromisoformat(extracted_at_iso)
    with RbmReader(file_str) as reader:
        return _process_equipment(
            reader,
            source_path,
            extracted_at,
            area_short,
            area_long,
            equipment,
            set(type_list),
            Path(out_str),
        )


def _make_progress() -> Progress:
    return Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    )


def _assert_safe_output_dir(out: Path) -> None:
    """Reject output paths where automatic cleanup would be dangerous."""
    resolved = out.resolve()
    cwd = Path.cwd().resolve()
    home = Path.home().resolve()
    forbidden = {Path("/").resolve(), cwd, home}
    if resolved in forbidden:
        raise ValueError(f"refusing to clear unsafe output directory: {out}")
    if (resolved / ".git").exists() or resolved.name == ".git":
        raise ValueError(f"refusing to clear git directory: {out}")
    if resolved.parent == resolved:
        raise ValueError(f"refusing to clear filesystem root: {out}")


def _prepare_output_dir(out: Path) -> None:
    _assert_safe_output_dir(out)
    if out.exists():
        if not out.is_dir():
            raise ValueError(f"output path exists and is not a directory: {out}")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)


def export_dataset(
    file: Path,
    out: Path,
    *,
    types: set[str],
    area_filter: set[str] | None = None,
    parallel: int = 1,
    show_progress: bool = True,
) -> ExportSummary:
    """Export the database under ``file`` to VibFrame rooted at ``out``."""
    out = Path(out)
    _prepare_output_dir(out)
    extracted_at = datetime.now(UTC)

    with RbmReader(file) as reader:
        areas = walk_hierarchy(reader)
        document = build_tree_document(reader, areas, source_path=file)
        inventory = collect_inventory(reader, source_path=file)

    dataset_doc = {
        "schema_version": SCHEMA_VERSION,
        "name": Path(file).stem,
        "generator": _extractor_name(),
        "created_at": extracted_at,
        "description": document["meta"].get("description") or "",
    }
    _write_json(out / DATASET_FILE, dataset_doc)
    write_inventory_html(
        inventory,
        out / "report.html",
        viewer_url="http://localhost:8000/",
    )

    selected = _filter_areas(areas, area_filter)
    work: list[tuple[Area, Equipment]] = [(area, eq) for area in selected for eq in area.equipment]
    _log.info(
        "export_start",
        areas=len(selected),
        equipment=len(work),
        types=sorted(types),
        parallel=parallel,
    )

    results: list[EquipmentResult] = []
    progress = _make_progress() if show_progress and work else None
    if progress is not None:
        progress.start()
    task_id = progress.add_task("exporting", total=len(work)) if progress else None
    try:
        if parallel <= 1:
            with RbmReader(file) as reader:
                for area, eq in work:
                    results.append(
                        _process_equipment(
                            reader,
                            str(file),
                            extracted_at,
                            area.short_code,
                            area.long_name,
                            eq,
                            types,
                            out,
                        )
                    )
                    if progress is not None and task_id is not None:
                        progress.advance(task_id)
        else:
            type_list = sorted(types)
            extracted_at_iso = extracted_at.isoformat()
            jobs = [
                (
                    str(file),
                    str(file),
                    extracted_at_iso,
                    area.short_code,
                    area.long_name,
                    eq,
                    type_list,
                    str(out),
                )
                for area, eq in work
            ]
            with ProcessPoolExecutor(max_workers=parallel) as pool:
                futures = [pool.submit(_export_equipment_worker, job) for job in jobs]
                for fut in as_completed(futures):
                    results.append(fut.result())
                    if progress is not None and task_id is not None:
                        progress.advance(task_id)
    finally:
        if progress is not None:
            progress.stop()

    results.sort(key=lambda r: (r.area_short, r.equipment_short))
    summary = ExportSummary(
        areas=len(selected),
        equipment_total=len(work),
        equipment_with_samples=sum(1 for r in results if r.n_fft + r.n_waveform + r.n_trend > 0),
        equipment_failed=sum(1 for r in results if r.error is not None),
        fft_samples=sum(r.n_fft for r in results),
        waveform_samples=sum(r.n_waveform for r in results),
        trend_samples=sum(r.n_trend for r in results),
        parquet_files=sum(r.n_files for r in results),
        manifest_rows=0,
    )
    _log.info(
        "export_done",
        equipment_with_samples=summary.equipment_with_samples,
        equipment_failed=summary.equipment_failed,
        fft_samples=summary.fft_samples,
        waveform_samples=summary.waveform_samples,
        trend_samples=summary.trend_samples,
        parquet_files=summary.parquet_files,
    )
    return summary
