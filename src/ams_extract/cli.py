"""Typer entrypoint for the ``rbm`` binary (end-user CLI)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ams_extract.export.json_tree import build_tree_document, write_tree_json
from ams_extract.export.parquet_samples import write_spectrum_parquet
from ams_extract.export.spectrum_plot import render_spectrum_png
from ams_extract.logging_setup import LogFormat, LogLevel, configure_logging
from ams_extract.models import Point
from ams_extract.naming import NameSanitizer
from ams_extract.reader import RbmFileError, RbmReader
from ams_extract.records.header import parse_header
from ams_extract.tree import walk_hierarchy, walk_spectra

app = typer.Typer(
    name="rbm",
    help="Read AMS Machinery Manager (.rbm) databases and export to Parquet + JSON.",
    no_args_is_help=True,
    add_completion=False,
)

_console = Console()


def _not_implemented(command: str) -> None:
    """Emit a user-visible 'not implemented yet' notice and exit cleanly."""
    _console.print(f"[yellow]rbm {command}[/yellow]: not implemented yet (Phase 0 stub).")
    raise typer.Exit(code=0)


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
    limit: Annotated[int, typer.Option("--limit", help="Maximum number of samples.")] = 3,
    out: Annotated[
        Path,
        typer.Option("--out", help="Directory where Parquet + PNG outputs are written."),
    ] = Path("samples"),
) -> None:
    """Extract a few FFT spectra from a single point as Parquet + PNG."""
    if not file.exists():
        raise _abort(f"file not found: {file}")
    if limit < 1:
        raise _abort(f"--limit must be >= 1, got {limit}")

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
            written: list[Path] = []
            for idx, spectrum in enumerate(walk_spectra(reader, target)):
                if idx >= limit:
                    break
                base = (
                    out
                    / f"{equipment_short}__{point_slug}__{idx:02d}_"
                    f"{spectrum.timestamp_utc.strftime('%Y%m%d_%H%M%S')}"
                )
                parquet_path = base.with_suffix(".parquet")
                png_path = base.with_suffix(".png")
                write_spectrum_parquet(spectrum, target, parquet_path)
                render_spectrum_png(spectrum, target, png_path)
                written.extend([parquet_path, png_path])
    except RbmFileError as exc:
        raise _abort(str(exc)) from exc

    if not written:
        _console.print(
            f"[yellow]no FFT spectra found for point[/yellow] {target.long_name!r}"
        )
        return
    _console.print(
        f"wrote [bold]{len(written) // 2}[/bold] spectra "
        f"(parquet + png) for [bold]{target.long_name}[/bold] under {out}"
    )


@app.command("export")
def export(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
    out: Annotated[Path, typer.Option("--out", help="Output dataset directory.")],
    types: Annotated[
        str,
        typer.Option("--types", help="Comma-separated sample types to include."),
    ] = "fft",
    areas: Annotated[
        str | None,
        typer.Option("--areas", help="Comma-separated area filter; all areas if omitted."),
    ] = None,
    parallel: Annotated[
        int,
        typer.Option("--parallel", help="Worker processes; 1 means serial."),
    ] = 1,
) -> None:
    """Dump the full database to the standard dataset layout."""
    _ = file, out, types, areas, parallel
    _not_implemented("export")
