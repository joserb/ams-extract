"""Typer entrypoint for the ``rbm`` binary (end-user CLI)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ams_extract.export.dataset import VALID_TYPES, export_dataset
from ams_extract.export.diag_gt import (
    build_alarm_ground_truth,
    file_sha256,
    write_alarm_ground_truth,
)
from ams_extract.export.html_report import write_inventory_html
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
from ams_extract.report import collect_inventory
from ams_extract.stats import collect_machine_stats, summarize
from ams_extract.tree import (
    count_point_samples,
    walk_hierarchy,
    walk_spectra,
    walk_trends,
    walk_waveforms,
)

app = typer.Typer(
    name="rbm",
    help="Read AMS Machinery Manager (.rbm) databases and export to VibFrame.",
    no_args_is_help=True,
    add_completion=False,
)

stats_app = typer.Typer(
    name="stats",
    help="Sample-count statistics (machines and FFT/waveform/trend data counts).",
    no_args_is_help=True,
)
app.add_typer(stats_app)

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


@app.command("report")
def report(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write the interactive HTML report to this path."),
    ] = None,
    area: Annotated[
        str | None,
        typer.Option("--area", help="Restrict to areas matching this substring."),
    ] = None,
) -> None:
    """Build an interactive HTML inventory: locations → machines, counts and dates.

    Reads the ``.rbm`` directly (no extraction needed). Each machine shows how
    many FFT spectra, waveforms and trend readings it holds and the date span
    (first → last) of each type.
    """
    if not file.exists():
        raise _abort(f"file not found: {file}")
    try:
        with RbmReader(file) as reader:
            inventory = collect_inventory(reader, area_filter=area, source_path=file)
    except RbmFileError as exc:
        raise _abort(str(exc)) from exc

    if out is None:
        _console.print(
            f"[bold]{inventory.n_areas} areas[/bold]  "
            f"{inventory.n_machines} machines  "
            f"{inventory.n_points} points  "
            f"[dim]({inventory.spectra.count:,} sp / "
            f"{inventory.waveforms.count:,} wv / "
            f"{inventory.trend.count:,} tn)[/dim]\n"
            f"[dim]pass --out report.html to write the interactive report[/dim]"
        )
        return
    write_inventory_html(inventory, out)
    _console.print(
        f"wrote [bold]{out}[/bold]  "
        f"({inventory.n_areas} areas, {inventory.n_machines} machines, "
        f"{inventory.spectra.count:,} sp / {inventory.waveforms.count:,} wv / "
        f"{inventory.trend.count:,} tn)"
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
            out / f"{equipment_short}__{point_slug}__fft_{idx:02d}_"
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
            out / f"{equipment_short}__{point_slug}__waveform_{idx:02d}_"
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
            f"[yellow]no samples found for point[/yellow] {target.long_name!r} (type={type_.value})"
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
    """Dump the full database to the VibFrame layout.

    Writes ``dataset.json``, ``report.html`` and one ``machine=<asset_id>``
    directory per AMS equipment, with ``machine.json`` plus spectra, waves,
    trends and metrics Parquet tables.
    """
    if not file.exists():
        raise _abort(f"file not found: {file}")
    if parallel < 1:
        raise _abort(f"--parallel must be >= 1, got {parallel}")

    type_set = {t.strip().lower() for t in types.split(",") if t.strip()}
    if not type_set:
        raise _abort("no sample types selected; --types must list fft, waveform and/or trend")
    unknown = type_set - VALID_TYPES
    if unknown:
        raise _abort(
            f"unknown sample type(s): {', '.join(sorted(unknown))}; "
            f"valid types are {', '.join(sorted(VALID_TYPES))}"
        )

    area_filter = {a.strip() for a in areas.split(",") if a.strip()} if areas else None

    try:
        summary = export_dataset(
            file,
            out,
            types=type_set,
            area_filter=area_filter,
            parallel=parallel,
        )
    except (RbmFileError, ValueError) as exc:
        raise _abort(str(exc)) from exc

    _console.print(
        f"wrote dataset to [bold]{out}[/bold]\n"
        f"  areas: {summary.areas}  "
        f"equipment: {summary.equipment_with_samples}/{summary.equipment_total} "
        f"with samples"
        + (f"  ([red]{summary.equipment_failed} failed[/red])" if summary.equipment_failed else "")
        + f"\n  samples: {summary.fft_samples} FFT + "
        f"{summary.waveform_samples} waveform + "
        f"{summary.trend_samples} trend  "
        f"({summary.parquet_files} parquet files)"
    )


@app.command("alarms")
def alarms(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
    out: Annotated[
        Path,
        typer.Option(
            "--out",
            help="Directory for the DiagGT document, normally <dataset>/ground-truth.",
        ),
    ] = Path("ground-truth"),
    name: Annotated[
        str | None,
        typer.Option("--name", help="Stem of the .diaggt.json; defaults to <file stem>."),
    ] = None,
    client: Annotated[
        str, typer.Option("--client", help="Client name for the provenance block.")
    ] = "",
    plant: Annotated[
        str, typer.Option("--plant", help="Plant name for the provenance block.")
    ] = "",
    consolidate: Annotated[
        bool,
        typer.Option(
            "--consolidate",
            help="Also write observations_system.parquet/.csv (flat view).",
        ),
    ] = False,
    skip_hash: Annotated[
        bool,
        typer.Option("--skip-hash", help="Do not hash the .rbm (faster, weaker provenance)."),
    ] = False,
) -> None:
    """Export the alarms AMS stored in the database as DiagGT ground truth.

    Reads every point's alarm note (``gdsc`` + ``gdnl``, FORMAT §5.9) and
    writes one observation per alarm whose value is confirmed against the
    point's ``pdla`` thresholds, with ``origin="system-alarm"``. Alarms
    that fail the cross-check are counted and left out.
    """
    if not file.exists():
        raise _abort(f"file not found: {file}")

    try:
        with RbmReader(file) as reader:
            digest = None if skip_hash else file_sha256(file)
            document, summary = build_alarm_ground_truth(
                reader,
                source_path=file,
                source_sha256=digest,
                client=client,
                plant=plant,
            )
    except RbmFileError as exc:
        raise _abort(str(exc)) from exc

    written = write_alarm_ground_truth(
        document, out, stem=name or file.stem, consolidate=consolidate
    )
    skipped = summary.skipped_unit_mismatch + summary.skipped_incoherent
    _console.print(
        f"wrote [bold]{summary.emitted}[/bold] system-alarm observations "
        f"({summary.alert} ALERT + {summary.danger} DANGER) on "
        f"[bold]{summary.machines}[/bold] machines to {written[0]}\n"
        f"  notes: {summary.notes}/{summary.points} points  "
        f"alarms: {summary.alarms}  "
        f"coherent with pdla: {summary.coherent_pct:.1f}%"
        + (f"  ([yellow]{skipped} skipped[/yellow])" if skipped else "")
        + f"\n  observed: {summary.first_observed} .. {summary.last_observed}"
    )
    for path in written[1:]:
        _console.print(f"  also wrote {path}")


def _serve_vibframe_dataset(source: Path, *, host: str, port: int, no_browser: bool) -> int:
    """Delegate an exported dataset to the ecosystem viewer (``vibframe-viewer``).

    The viewer is a repo of its own (portable: stdlib + pyarrow), so every
    VibFrame producer serves its datasets with the same browser. This wrapper
    only translates the ``rbm serve`` options into its CLI; the serve loop,
    the browser and Ctrl-C handling are the viewer's.
    """
    from vibframe_viewer.cli import main as viewer_main

    argv = ["serve", str(source), "--host", host, "--port", str(port)]
    if no_browser:
        argv.append("--no-browser")
    return viewer_main(argv)


@app.command("serve")
def serve(
    source: Annotated[
        Path,
        typer.Argument(help="A .rbm database file, or an exported dataset directory."),
    ],
    host: Annotated[
        str, typer.Option("--host", help="Interface to bind (default loopback only).")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="TCP port to listen on.")] = 8000,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Do not open a web browser.")
    ] = False,
) -> None:
    """Serve an interactive on-demand viewer over a .rbm file or a dataset.

    Two backends, picked automatically from ``SOURCE``:

    * an **exported dataset directory** → delegates to the ecosystem viewer
      (``vibframe-viewer serve``), common to every VibFrame producer: tree,
      timeline, spectra, waves, trends and parameter matrix, plotted in the
      browser. ``vibframe-viewer report`` writes the static report;
    * a **.rbm file** → renders straight from the database, walking the
      hierarchy on startup and rendering each plot on demand (no export
      needed; machines/points/samples load lazily as you drill in). This
      backend is ams-extract's own debugging tool: it needs no export.

    Either way the plots are built on the fly. Press Ctrl-C to stop.
    """
    import webbrowser

    if source.is_dir():
        raise typer.Exit(
            code=_serve_vibframe_dataset(source, host=host, port=port, no_browser=no_browser)
        )
    if source.is_file():
        from ams_extract.export.live_viewer import LiveViewerError
        from ams_extract.export.live_viewer import serve as build_live_server

        try:
            server = build_live_server(source, host=host, port=port)
        except LiveViewerError as exc:
            raise _abort(str(exc)) from exc
    else:
        raise _abort(f"not a .rbm file or dataset directory: {source}")

    url = f"http://{host}:{port}/"
    _console.print(f"serving [bold]{source}[/bold] at [bold]{url}[/bold]  (Ctrl-C to stop)")
    if not no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _console.print("\nstopped")
    finally:
        server.server_close()


@stats_app.command("summary")
def stats_summary(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
    area: Annotated[
        str | None,
        typer.Option("--area", help="Restrict to areas matching this substring."),
    ] = None,
) -> None:
    """Print database-wide counts: machines, points and sp/wv/tn data totals."""
    if not file.exists():
        raise _abort(f"file not found: {file}")
    try:
        with RbmReader(file) as reader:
            machines = collect_machine_stats(reader, area_filter=area)
    except RbmFileError as exc:
        raise _abort(str(exc)) from exc
    s = summarize(machines)

    table = Table(title=f"rbm stats — {file.name}", show_header=False, box=None)
    table.add_column(style="bold cyan")
    table.add_column(justify="right")
    table.add_row("areas", f"{s.n_areas:,}")
    table.add_row("machines", f"{s.n_machines:,}")
    table.add_row("machines with data", f"{s.n_machines_with_data:,}")
    table.add_row("measurement points", f"{s.n_points:,}")
    table.add_row("FFT spectra (sp)", f"{s.n_spectra:,}")
    table.add_row("waveforms (wv)", f"{s.n_waveforms:,}")
    table.add_row("trend readings (tn)", f"{s.n_trend_readings:,}")
    table.add_row("[bold]total data[/bold]", f"[bold]{s.total_samples:,}[/bold]")
    _console.print(table)


@stats_app.command("machines")
def stats_machines(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
    area: Annotated[
        str | None,
        typer.Option("--area", help="Restrict to areas matching this substring."),
    ] = None,
    sort: Annotated[
        str,
        typer.Option("--sort", help="Sort key: total | sp | wv | tn | name."),
    ] = "total",
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Show only the top N machines."),
    ] = None,
) -> None:
    """Print a per-machine table of sp/wv/tn data counts."""
    if not file.exists():
        raise _abort(f"file not found: {file}")
    try:
        with RbmReader(file) as reader:
            machines = collect_machine_stats(reader, area_filter=area)
    except RbmFileError as exc:
        raise _abort(str(exc)) from exc

    if sort == "total":
        machines.sort(key=lambda m: -m.total)
    elif sort == "sp":
        machines.sort(key=lambda m: -m.n_spectra)
    elif sort == "wv":
        machines.sort(key=lambda m: -m.n_waveforms)
    elif sort == "tn":
        machines.sort(key=lambda m: -m.n_trend_readings)
    elif sort == "name":
        machines.sort(key=lambda m: (m.area_short, m.equipment_short))
    else:
        raise _abort(f"invalid --sort {sort!r}; choose total, sp, wv, tn or name")
    shown = machines[:limit] if limit else machines

    table = Table(title=f"rbm stats machines — {file.name}")
    table.add_column("Area", style="cyan")
    table.add_column("Machine", style="bold")
    table.add_column("Pts", justify="right")
    table.add_column("sp", justify="right")
    table.add_column("wv", justify="right")
    table.add_column("tn", justify="right")
    table.add_column("Total", justify="right", style="bold")
    for m in shown:
        table.add_row(
            m.area_long,
            m.equipment_long,
            str(m.n_points),
            f"{m.n_spectra:,}",
            f"{m.n_waveforms:,}",
            f"{m.n_trend_readings:,}",
            f"{m.total:,}",
        )
    s = summarize(machines)
    table.add_section()
    table.add_row(
        f"TOTAL ({s.n_machines} machines)",
        "",
        f"{s.n_points:,}",
        f"{s.n_spectra:,}",
        f"{s.n_waveforms:,}",
        f"{s.n_trend_readings:,}",
        f"{s.total_samples:,}",
    )
    _console.print(table)
    if limit and len(machines) > limit:
        _console.print(f"[dim](showing top {limit} of {len(machines)})[/dim]")


@stats_app.command("points")
def stats_points(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
    equipment: Annotated[
        str,
        typer.Option("--equipment", help="Equipment long_name substring to drill into."),
    ],
    area: Annotated[
        str | None,
        typer.Option("--area", help="Restrict to areas matching this substring."),
    ] = None,
) -> None:
    """Print per-point sp/wv/tn counts for the machine(s) matching --equipment."""
    if not file.exists():
        raise _abort(f"file not found: {file}")
    needle = equipment.strip().lower()
    rows: list[tuple[str, str, int, int, int]] = []
    try:
        with RbmReader(file) as reader:
            for ar in walk_hierarchy(reader):
                if area and area.strip().lower() not in (
                    ar.long_name.lower() + " " + ar.short_code.lower()
                ):
                    continue
                for eq in ar.equipment:
                    if needle not in eq.long_name.lower():
                        continue
                    for pt in eq.points:
                        sp, wv, tn = count_point_samples(reader, pt)
                        rows.append((eq.long_name, pt.long_name, sp, wv, tn))
    except RbmFileError as exc:
        raise _abort(str(exc)) from exc

    if not rows:
        raise _abort(f"no equipment matched {equipment!r}")

    table = Table(title=f"rbm stats points — {equipment}")
    table.add_column("Machine", style="cyan")
    table.add_column("Point", style="bold")
    table.add_column("sp", justify="right")
    table.add_column("wv", justify="right")
    table.add_column("tn", justify="right")
    for eq_name, pt_name, sp, wv, tn in rows:
        table.add_row(eq_name, pt_name, f"{sp:,}", f"{wv:,}", f"{tn:,}")
    _console.print(table)
