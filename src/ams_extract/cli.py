"""Typer entrypoint for the ``rbm`` binary (end-user CLI)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ams_extract.export.json_tree import build_tree_document, write_tree_json
from ams_extract.logging_setup import LogFormat, LogLevel, configure_logging
from ams_extract.reader import RbmFileError, RbmReader
from ams_extract.records.header import parse_header
from ams_extract.tree import walk_hierarchy

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


@app.command("extract")
def extract(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
    point: Annotated[str, typer.Option("--point", help="Long name of the target point.")],
    limit: Annotated[int, typer.Option("--limit", help="Maximum number of samples.")] = 3,
    out: Annotated[
        Path,
        typer.Option("--out", help="Directory where Parquet + PNG outputs are written."),
    ] = Path("samples"),
) -> None:
    """Extract a few samples from a single point as Parquet + PNG."""
    _ = file, point, limit, out
    _not_implemented("extract")


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
