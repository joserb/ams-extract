"""Typer entrypoint for the ``rbm-dev`` binary (developer tooling)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ams_extract.logging_setup import LogFormat, LogLevel, configure_logging

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
    rec: Annotated[int, typer.Option("--rec", help="Record number to dump.")],
) -> None:
    """Print the hex + ASCII representation of a single 512-byte record."""
    _ = file, rec
    _not_implemented("dump-record")


@app.command("follow-chain")
def follow_chain(
    file: Annotated[Path, typer.Argument(help="Path to a .rbm database file.")],
    from_: Annotated[int, typer.Option("--from", help="Starting record number for the chain.")],
) -> None:
    """Follow a linked-list chain of records starting at the given record."""
    _ = file, from_
    _not_implemented("follow-chain")
