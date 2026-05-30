"""Typer entrypoint for the ``rbm`` binary (end-user CLI)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ams_extract.export.dataset import VALID_TYPES, export_dataset
from ams_extract.export.json_tree import build_tree_document, write_tree_json
from ams_extract.export.parquet_samples import (
    write_spectrum_parquet,
    write_trend_parquet,
    write_waveform_parquet,
)
from ams_extract.export.spectrum_plot import render_spectrum_png
from ams_extract.export.trend_plot import render_trend_png
from ams_extract.export.waveform_plot import render_waveform_png
from ams_extract.logging_setup import LogFormat, LogLevel, configure_logging
from ams_extract.models import Point
from ams_extract.naming import NameSanitizer
from ams_extract.reader import RbmFileError, RbmReader
from ams_extract.records.header import parse_header
from ams_extract.tree import walk_hierarchy, walk_spectra, walk_trends, walk_waveforms

app = typer.Typer(
    name="rbm",
    help="Read AMS Machinery Manager (.rbm) databases and export to Parquet + JSON.",
    no_args_is_help=True,
    add_completion=False,
)

_console = Console()


class SampleKind(StrEnum):
    """Which sample representations ``rbm extract`` should emit."""

    FFT = "fft"
    WAVEFORM = "waveform"
    TREND = "trend"
    BOTH = "both"


def _abort(message: str) -> typer.Exit:
    """Print an error message in red and return a non-zero ``typer.Exit``."""
    _console.print(f"[red]error:[/red] {message}")
    return typer.Exit(code=1)


@app.callback()
def root(
    log_format: Annotated[
        LogFormat,
        typer.Option("--log-format", help="Log output format."),
    ] = "json",
    log_level: Annotated[
        LogLevel,
        typer.Option("--log-level", help="Minimum log severity."),
    ] = "info",
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Abort on the first non-fatal error instead of skipping."),
    ] = False,
) -> None:
    """Configure structured logging before any subcommand runs."""
    configure_logging(log_format=log_format, log_level=log_level)
    _ = strict  # placeholder: consumed by future subcommands via context


@app.command("info")
def info(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
) -> None:
    """Print signature, version, size and quick counts for FILE."""
    if not file.exists():
        raise _abort(f"file not found: {file}")
    try:
        with RbmReader(file) as reader:
            header = parse_header(reader)
            record_count = reader.record_count
            size = reader.size
    except RbmFileError as exc:
        raise _abort(str(exc)) from exc

    table = Table(title=f"rbm info — {file.name}", show_header=False, box=None)
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row("path", str(file))
    table.add_row("size", f"{size:,} bytes")
    table.add_row("records", f"{record_count:,}")
    table.add_row("signature", header.signature)
    table.add_row("db_tag", header.db_tag)
    table.add_row("version_marker", header.version_marker.hex(" "))
    table.add_row("guid", header.guid.hex())
    table.add_row("description", header.description or "(empty)")
    ts = header.timestamp
    table.add_row(
        "timestamp",
        f"{ts.isoformat()} (raw=0x{header.timestamp_raw:08x})"
        if ts is not None
        else f"(unparseable; raw=0x{header.timestamp_raw:08x})",
    )
    table.add_row(
        "area_chain_first_record",
        str(header.area_chain_first_record),
    )
    _console.print(table)


@app.command("tree")
def tree(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write the hierarchy JSON to this path."),
    ] = None,
) -> None:
    """Export the Areas / Equipment / Points hierarchy as JSON."""
    if not file.exists():
        raise _abort(f"file not found: {file}")
    try:
        with RbmReader(file) as reader:
            areas = walk_hierarchy(reader)
            document = build_tree_document(reader, areas, source_path=file)
    except RbmFileError as exc:
        raise _abort(str(exc)) from exc

    meta = document["meta"]
    if out is None:
        _console.print(
            f"[bold]{meta['area_count']} areas[/bold]  "
            f"{meta['equipment_count']} equipment  "
            f"{meta['point_count']} points"
        )
        for area_dict in document["areas"]:
            _console.print(
                f"  rec={area_dict['record_num']:>3} "
                f"slot={area_dict['slot_index']:>2}  "
                f"{area_dict['short_code']:<24} {area_dict['long_name']} "
                f"[dim]({len(area_dict['equipment'])} equipment)[/dim]"
            )
    else:
        write_tree_json(document, out)
        _console.print(
            f"wrote [bold]{out}[/bold]  "
            f"({meta['area_count']} areas, "
            f"{meta['equipment_count']} equipment, "
            f"{meta['point_count']} points)"
        )


def _find_points_by_name(
    reader: RbmReader, target: str, equipment_filter: str | None
) -> list[tuple[Point, str]]:
    """Return every point matching ``target`` (exact long_name).

    If ``equipment_filter`` is set, restrict to points whose equipment's
    ``long_name`` contains the filter substring (case-insensitive).
    Returns a list of ``(point, equipment_short_code)`` so the caller
    can disambiguate when more than one match remains.
    """
    target_norm = target.strip()
    eq_needle = equipment_filter.strip().lower() if equipment_filter else None
    matches: list[tuple[Point, str]] = []
    for area in walk_hierarchy(reader):
        for eq in area.equipment:
            if eq_needle is not None and eq_needle not in eq.long_name.lower():
                continue
            for pt in eq.points:
                if pt.long_name == target_norm:
                    matches.append((pt, eq.short_code))
    return matches


def _extract_spectra(
    reader: RbmReader,
    target: Point,
    equipment_short: str,
    point_slug: str,
    limit: int,
    out: Path,
) -> int:
    """Write up to ``limit`` FFT spectra; return the number emitted."""
    written = 0
    for idx, spectrum in enumerate(walk_spectra(reader, target)):
        if idx >= limit:
            break
        base = (
            out
            / f"{equipment_short}__{point_slug}__fft_{idx:02d}_"
            f"{spectrum.timestamp_utc.strftime('%Y%m%d_%H%M%S')}"
        )
        write_spectrum_parquet(spectrum, target, base.with_suffix(".parquet"))
        render_spectrum_png(spectrum, target, base.with_suffix(".png"))
        written += 1
    return written


def _extract_waveforms(
    reader: RbmReader,
    target: Point,
    equipment_short: str,
    point_slug: str,
    limit: int,
    out: Path,
) -> int:
    """Write up to ``limit`` waveforms; return the number emitted."""
    written = 0
    for idx, waveform in enumerate(walk_waveforms(reader, target)):
        if idx >= limit:
            break
        base = (
            out
            / f"{equipment_short}__{point_slug}__waveform_{idx:02d}_"
            f"{waveform.timestamp_utc.strftime('%Y%m%d_%H%M%S')}"
        )
        write_waveform_parquet(waveform, target, base.with_suffix(".parquet"))
        render_waveform_png(waveform, target, base.with_suffix(".png"))
        written += 1
    return written


def _extract_trend(
    reader: RbmReader,
    target: Point,
    equipment_short: str,
    point_slug: str,
    out: Path,
) -> int:
    """Write the point's trend series (one file, one row per reading).

    Returns the number of readings emitted. A trend is a single series per
    point, so ``--limit`` does not apply; the whole series is written.
    """
    trend = next(walk_trends(reader, target), None)
    if trend is None or trend.overall.size == 0:
        return 0
    base = out / f"{equipment_short}__{point_slug}__trend"
    write_trend_parquet(trend, target, base.with_suffix(".parquet"))
    render_trend_png(trend, target, base.with_suffix(".png"))
    return int(trend.overall.size)


@app.command("extract")
def extract(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
    point: Annotated[str, typer.Option("--point", help="Long name of the target point.")],
    equipment: Annotated[
        str | None,
        typer.Option(
            "--equipment",
            help="Substring filter on equipment long_name to disambiguate.",
        ),
    ] = None,
    type_: Annotated[
        SampleKind,
        typer.Option("--type", help="Which sample representation(s) to extract."),
    ] = SampleKind.BOTH,
    limit: Annotated[int, typer.Option("--limit", help="Maximum samples per type.")] = 3,
    out: Annotated[
        Path,
        typer.Option("--out", help="Directory where Parquet + PNG outputs are written."),
    ] = Path("samples"),
) -> None:
    """Extract FFT spectra, waveforms and/or the trend from a point as Parquet + PNG."""
    if not file.exists():
        raise _abort(f"file not found: {file}")
    if limit < 1:
        raise _abort(f"--limit must be >= 1, got {limit}")

    want_fft = type_ in (SampleKind.FFT, SampleKind.BOTH)
    want_waveform = type_ in (SampleKind.WAVEFORM, SampleKind.BOTH)
    want_trend = type_ is SampleKind.TREND

    try:
        with RbmReader(file) as reader:
            located = _find_points_by_name(reader, point, equipment)
            if not located:
                hint = f" under equipment matching {equipment!r}" if equipment else ""
                raise _abort(f"point not found in hierarchy{hint}: {point!r}")
            if len(located) > 1:
                _console.print(
                    f"[yellow]ambiguous:[/yellow] {len(located)} points named "
                    f"{point!r} found. Disambiguate with --equipment. Candidates:"
                )
                for pt, eq_short in located:
                    _console.print(f"  - equipment={eq_short}  point_rec={pt.record_num}")
                raise typer.Exit(code=2)
            target, equipment_short = located[0]

            sanitizer = NameSanitizer()
            point_slug = sanitizer.sanitize(target.long_name)
            n_fft = (
                _extract_spectra(reader, target, equipment_short, point_slug, limit, out)
                if want_fft
                else 0
            )
            n_waveform = (
                _extract_waveforms(reader, target, equipment_short, point_slug, limit, out)
                if want_waveform
                else 0
            )
            n_trend = (
                _extract_trend(reader, target, equipment_short, point_slug, out)
                if want_trend
                else 0
            )
    except RbmFileError as exc:
        raise _abort(str(exc)) from exc

    if n_fft == 0 and n_waveform == 0 and n_trend == 0:
        _console.print(
            f"[yellow]no samples found for point[/yellow] {target.long_name!r} "
            f"(type={type_.value})"
        )
        return
    parts: list[str] = []
    if want_fft:
        parts.append(f"{n_fft} spectra")
    if want_waveform:
        parts.append(f"{n_waveform} waveforms")
    if want_trend:
        parts.append(f"{n_trend} trend readings")
    _console.print(
        f"wrote [bold]{' + '.join(parts)}[/bold] (parquet + png) for "
        f"[bold]{target.long_name}[/bold] under {out}"
    )


@app.command("export")
def export(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
    out: Annotated[Path, typer.Option("--out", help="Output dataset directory.")],
    types: Annotated[
        str,
        typer.Option("--types", help="Comma-separated sample types: fft, waveform, trend."),
    ] = "fft,waveform",
    areas: Annotated[
        str | None,
        typer.Option("--areas", help="Comma-separated area filter; all areas if omitted."),
    ] = None,
    parallel: Annotated[
        int,
        typer.Option("--parallel", help="Worker processes; 1 means serial."),
    ] = 1,
) -> None:
    """Dump the full database to the standard dataset layout.

    Writes ``hierarchy.json``, ``manifest.parquet`` and one Parquet file
    per equipment and sample type under
    ``samples/area=<area>/equipment=<equipment>__<type>.parquet``.
    """
    if not file.exists():
        raise _abort(f"file not found: {file}")
    if parallel < 1:
        raise _abort(f"--parallel must be >= 1, got {parallel}")

    type_set = {t.strip().lower() for t in types.split(",") if t.strip()}
    if not type_set:
        raise _abort(
            "no sample types selected; --types must list fft, waveform and/or trend"
        )
    unknown = type_set - VALID_TYPES
    if unknown:
        raise _abort(
            f"unknown sample type(s): {', '.join(sorted(unknown))}; "
            f"valid types are {', '.join(sorted(VALID_TYPES))}"
        )

    area_filter = (
        {a.strip() for a in areas.split(",") if a.strip()} if areas else None
    )

    try:
        summary = export_dataset(
            file,
            out,
            types=type_set,
            area_filter=area_filter,
            parallel=parallel,
        )
    except RbmFileError as exc:
        raise _abort(str(exc)) from exc

    _console.print(
        f"wrote dataset to [bold]{out}[/bold]\n"
        f"  areas: {summary.areas}  "
        f"equipment: {summary.equipment_with_samples}/{summary.equipment_total} "
        f"with samples"
        + (
            f"  ([red]{summary.equipment_failed} failed[/red])"
            if summary.equipment_failed
            else ""
        )
        + f"\n  samples: {summary.fft_samples} FFT + "
        f"{summary.waveform_samples} waveform + "
        f"{summary.trend_samples} trend  "
        f"({summary.parquet_files} parquet files, "
        f"{summary.manifest_rows} manifest rows)"
    )
