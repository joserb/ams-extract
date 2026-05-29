"""Full-database export to the standard dataset layout (Fase 6).

``export_dataset`` walks the hierarchy once, writes ``hierarchy.json``,
then for every equipment emits a per-type Parquet file under
``samples/area=<area>/equipment=<equipment>__<type>.parquet`` and a global
``manifest.parquet`` index. See PLAN.md §3.5.

Equipment are independent work units: serial by default, or one
``ProcessPoolExecutor`` task per equipment with ``parallel > 1`` (each
worker re-opens the mmap, keeping the memory footprint bounded). The walk
functions already log-and-skip per-record failures; this module wraps each
equipment so one bad machine never aborts the run.
"""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

from ams_extract.export.json_tree import build_tree_document, write_tree_json
from ams_extract.export.manifest import write_manifest
from ams_extract.export.parquet_samples import (
    sample_id,
    write_spectra_parquet,
    write_waveforms_parquet,
)
from ams_extract.models import Area, Equipment, Point
from ams_extract.reader import RbmReader
from ams_extract.tree import walk_hierarchy, walk_spectra, walk_waveforms

_log = structlog.get_logger(__name__)

FFT = "fft"
WAVEFORM = "waveform"
VALID_TYPES = frozenset({FFT, WAVEFORM})


@dataclass(frozen=True)
class EquipmentResult:
    """Outcome of exporting a single equipment."""

    area_short: str
    equipment_short: str
    manifest_rows: list[dict[str, Any]]
    n_fft: int
    n_waveform: int
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
    parquet_files: int
    manifest_rows: int


def _fft_relpath(area_short: str, equipment_short: str) -> str:
    return f"samples/area={area_short}/equipment={equipment_short}__fft.parquet"


def _waveform_relpath(area_short: str, equipment_short: str) -> str:
    return f"samples/area={area_short}/equipment={equipment_short}__waveform.parquet"


def _filter_areas(areas: Iterable[Area], area_filter: set[str] | None) -> list[Area]:
    """Return areas selected by ``area_filter`` (case-insensitive).

    A token matches an area when it equals its ``long_name`` or its
    ``short_code`` (both lowercased). ``None`` selects every area. Tokens
    that match nothing are logged as a warning.
    """
    area_list = list(areas)
    if area_filter is None:
        return area_list
    wanted = {t.strip().lower() for t in area_filter if t.strip()}
    selected = [
        a
        for a in area_list
        if a.long_name.lower() in wanted or a.short_code.lower() in wanted
    ]
    matched = {a.long_name.lower() for a in selected} | {
        a.short_code.lower() for a in selected
    }
    for token in wanted - matched:
        _log.warning("area_filter_no_match", token=token)
    return selected


def _fft_manifest_row(
    spectrum: Any, point: Point, *, area_short: str, area_long: str,
    equipment_short: str, equipment_long: str, relpath: str,
) -> dict[str, Any]:
    return {
        "sample_id": sample_id(point.record_num, spectrum.record_num, "FFT"),
        "area": area_short,
        "area_long_name": area_long,
        "equipment": equipment_short,
        "equipment_long_name": equipment_long,
        "point_record_num": point.record_num,
        "point_long_name": point.long_name,
        "point_short_code": point.short_code,
        "timestamp_utc": spectrum.timestamp_utc,
        "sample_type": "FFT",
        "units": spectrum.units,
        "fmax_hz": spectrum.fmax_hz,
        "n_lines": spectrum.n_lines,
        "sample_rate_hz": None,
        "rpm": None,
        "n_samples": None,
        "parquet_path": relpath,
    }


def _waveform_manifest_row(
    waveform: Any, point: Point, *, area_short: str, area_long: str,
    equipment_short: str, equipment_long: str, relpath: str,
) -> dict[str, Any]:
    return {
        "sample_id": sample_id(point.record_num, waveform.record_num, "WAVEFORM"),
        "area": area_short,
        "area_long_name": area_long,
        "equipment": equipment_short,
        "equipment_long_name": equipment_long,
        "point_record_num": point.record_num,
        "point_long_name": point.long_name,
        "point_short_code": point.short_code,
        "timestamp_utc": waveform.timestamp_utc,
        "sample_type": "WAVEFORM",
        "units": waveform.units,
        "fmax_hz": None,
        "n_lines": None,
        "sample_rate_hz": waveform.sample_rate_hz,
        "rpm": waveform.rpm,
        "n_samples": waveform.n_samples,
        "parquet_path": relpath,
    }


def _process_equipment(
    reader: RbmReader,
    area_short: str,
    area_long: str,
    equipment: Equipment,
    types: set[str],
    out_dir: Path,
) -> EquipmentResult:
    """Export every sample of ``equipment``; never raises for one machine."""
    try:
        spectra_items: list[tuple[Any, Point]] = []
        waveform_items: list[tuple[Any, Point]] = []
        for point in equipment.points:
            if FFT in types:
                spectra_items.extend(
                    (sp, point) for sp in walk_spectra(reader, point)
                )
            if WAVEFORM in types:
                waveform_items.extend(
                    (wf, point) for wf in walk_waveforms(reader, point)
                )

        rows: list[dict[str, Any]] = []
        n_files = 0

        if FFT in types and spectra_items:
            rel = _fft_relpath(area_short, equipment.short_code)
            write_spectra_parquet(spectra_items, out_dir / rel)
            n_files += 1
            rows.extend(
                _fft_manifest_row(
                    sp, point, area_short=area_short, area_long=area_long,
                    equipment_short=equipment.short_code,
                    equipment_long=equipment.long_name, relpath=rel,
                )
                for sp, point in spectra_items
            )

        if WAVEFORM in types and waveform_items:
            rel = _waveform_relpath(area_short, equipment.short_code)
            write_waveforms_parquet(waveform_items, out_dir / rel)
            n_files += 1
            rows.extend(
                _waveform_manifest_row(
                    wf, point, area_short=area_short, area_long=area_long,
                    equipment_short=equipment.short_code,
                    equipment_long=equipment.long_name, relpath=rel,
                )
                for wf, point in waveform_items
            )

        return EquipmentResult(
            area_short=area_short,
            equipment_short=equipment.short_code,
            manifest_rows=rows,
            n_fft=len(spectra_items),
            n_waveform=len(waveform_items),
            n_files=n_files,
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
            manifest_rows=[],
            n_fft=0,
            n_waveform=0,
            n_files=0,
            error=str(exc),
        )


def _export_equipment_worker(
    job: tuple[str, str, str, Equipment, list[str], str],
) -> EquipmentResult:
    """ProcessPool entry point: re-open the mmap and export one equipment."""
    file_str, area_short, area_long, equipment, type_list, out_str = job
    with RbmReader(file_str) as reader:
        return _process_equipment(
            reader, area_short, area_long, equipment, set(type_list), Path(out_str)
        )


def _make_progress() -> Progress:
    return Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    )


def export_dataset(
    file: Path,
    out: Path,
    *,
    types: set[str],
    area_filter: set[str] | None = None,
    parallel: int = 1,
    show_progress: bool = True,
) -> ExportSummary:
    """Export the database under ``file`` to the dataset rooted at ``out``.

    Args:
        file: Path to the ``.rbm`` database.
        types: Subset of ``{"fft", "waveform"}`` to emit.
        area_filter: Area long-names / short-codes to include; ``None`` = all.
        parallel: Worker processes (one equipment per task); ``<= 1`` = serial.
        show_progress: Render a Rich progress bar.

    Returns:
        An :class:`ExportSummary` with aggregate counts.
    """
    out = Path(out)
    with RbmReader(file) as reader:
        areas = walk_hierarchy(reader)
        document = build_tree_document(reader, areas, source_path=file)
    write_tree_json(document, out / "hierarchy.json")

    selected = _filter_areas(areas, area_filter)
    work: list[tuple[Area, Equipment]] = [
        (area, eq) for area in selected for eq in area.equipment
    ]
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
                            reader, area.short_code, area.long_name, eq, types, out
                        )
                    )
                    if progress is not None and task_id is not None:
                        progress.advance(task_id)
        else:
            type_list = sorted(types)
            jobs = [
                (str(file), area.short_code, area.long_name, eq, type_list, str(out))
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

    # Deterministic manifest order regardless of completion order.
    results.sort(key=lambda r: (r.area_short, r.equipment_short))
    manifest_rows = [row for r in results for row in r.manifest_rows]
    write_manifest(manifest_rows, out / "manifest.parquet")

    summary = ExportSummary(
        areas=len(selected),
        equipment_total=len(work),
        equipment_with_samples=sum(1 for r in results if r.n_files > 0),
        equipment_failed=sum(1 for r in results if r.error is not None),
        fft_samples=sum(r.n_fft for r in results),
        waveform_samples=sum(r.n_waveform for r in results),
        parquet_files=sum(r.n_files for r in results),
        manifest_rows=len(manifest_rows),
    )
    _log.info(
        "export_done",
        equipment_with_samples=summary.equipment_with_samples,
        equipment_failed=summary.equipment_failed,
        fft_samples=summary.fft_samples,
        waveform_samples=summary.waveform_samples,
        parquet_files=summary.parquet_files,
    )
    return summary
