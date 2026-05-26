"""Typer entrypoint for the ``rbm-dev`` binary (developer tooling)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ams_extract.logging_setup import LogFormat, LogLevel, configure_logging
from ams_extract.reader import RECORD_SIZE, RbmFileError, RbmReader

app = typer.Typer(
    name="rbm-dev",
    help="Developer tooling for exploring the .rbm binary format.",
    no_args_is_help=True,
    add_completion=False,
)

_console = Console()


def _not_implemented(command: str) -> None:
    """Emit a user-visible 'not implemented yet' notice and exit cleanly."""
    _console.print(f"[yellow]rbm-dev {command}[/yellow]: not implemented yet (Phase 0 stub).")
    raise typer.Exit(code=0)


def _abort(message: str) -> typer.Exit:
    """Print an error message in red and return a non-zero ``typer.Exit``."""
    _console.print(f"[red]error:[/red] {message}")
    return typer.Exit(code=1)


def _hex_dump(data: bytes, *, base_offset: int = 0) -> str:
    """Format a bytes buffer as a classic 16-column hex + ASCII dump."""
    lines: list[str] = []
    for i in range(0, len(data), 16):
        row = data[i : i + 16]
        hex_part = " ".join(f"{b:02x}" for b in row).ljust(47)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        lines.append(f"{base_offset + i:08x}  {hex_part}  |{ascii_part}|")
    return "\n".join(lines)


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
    _ = strict


@app.command("scan")
def scan(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
    tags: Annotated[
        bool,
        typer.Option("--tags", help="Report 4-char tag frequencies across the file."),
    ] = False,
) -> None:
    """Walk the file bottom-up and report aggregate statistics."""
    _ = file, tags
    _not_implemented("scan")


@app.command("dump-record")
def dump_record(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
    rec: Annotated[int, typer.Option("--rec", help="Record number to dump (zero-based).")],
) -> None:
    """Print the hex + ASCII representation of a single 512-byte record."""
    if not file.exists():
        raise _abort(f"file not found: {file}")
    try:
        with RbmReader(file) as reader:
            data = reader.read_record(rec)
    except (RbmFileError, IndexError) as exc:
        raise _abort(str(exc)) from exc

    base_offset = rec * RECORD_SIZE
    _console.print(
        f"[bold]record {rec}[/bold]  (file offset 0x{base_offset:x}, "
        f"{RECORD_SIZE} bytes)"
    )
    _console.print(_hex_dump(data, base_offset=base_offset))


@app.command("follow-chain")
def follow_chain(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
    from_: Annotated[int, typer.Option("--from", help="Starting record number (zero-based).")],
    at_offset: Annotated[
        int,
        typer.Option(
            "--at-offset",
            help="Byte offset within each record holding the next-pointer (u32 LE).",
        ),
    ] = 0,
    max_steps: Annotated[
        int,
        typer.Option("--max-steps", help="Cap on chain length, to bound cyclic chains."),
    ] = 32,
) -> None:
    """Walk a linked-list chain reading a u32 LE next-pointer from each record.

    Stops when the read next-pointer is 0 (chain end), equals a previously
    visited record (cycle), points outside the file, or after ``--max-steps``
    hops.
    """
    if not file.exists():
        raise _abort(f"file not found: {file}")
    try:
        with RbmReader(file) as reader:
            visited: list[int] = []
            seen: set[int] = set()
            current = from_
            for _ in range(max_steps):
                if current < 0 or current >= reader.record_count:
                    _console.print(
                        f"[yellow]record {current} out of file range[/yellow]"
                    )
                    break
                if current in seen:
                    _console.print(
                        f"[yellow]cycle detected at record {current}[/yellow]"
                    )
                    break
                seen.add(current)
                visited.append(current)
                next_record = reader.read_u32(current, at_offset)
                _console.print(
                    f"  record {current:>8}  ->  next = {next_record} "
                    f"(0x{next_record:08x})"
                )
                if next_record == 0:
                    _console.print("[yellow]reached null pointer (0)[/yellow]")
                    break
                current = next_record
            else:
                _console.print(
                    f"[yellow]reached --max-steps={max_steps} cap[/yellow]"
                )
            _console.print(f"[bold]visited {len(visited)} records[/bold]")
    except (RbmFileError, IndexError) as exc:
        raise _abort(str(exc)) from exc
