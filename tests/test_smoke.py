"""Smoke tests for Phase 0: package imports and CLIs surface their subcommands."""

from __future__ import annotations

from typer.testing import CliRunner

import ams_extract
from ams_extract.cli import app as rbm_app
from ams_extract.cli_dev import app as rbm_dev_app

runner = CliRunner()


def test_package_has_version() -> None:
    assert isinstance(ams_extract.__version__, str)
    assert ams_extract.__version__


def test_rbm_help_lists_user_subcommands() -> None:
    result = runner.invoke(rbm_app, ["--help"])
    assert result.exit_code == 0, result.output
    for command in ("info", "tree", "extract", "export"):
        assert command in result.output


def test_rbm_dev_help_lists_dev_subcommands() -> None:
    result = runner.invoke(rbm_dev_app, ["--help"])
    assert result.exit_code == 0, result.output
    for command in ("scan", "dump-record", "follow-chain"):
        assert command in result.output


def test_rbm_extract_errors_on_missing_file() -> None:
    # extract is implemented in sub-fase 3b; it now aborts cleanly on a
    # missing file instead of returning the Phase 0 stub message.
    result = runner.invoke(rbm_app, ["extract", "nonexistent.rbm", "--point", "X"])
    assert result.exit_code == 1
    assert "file not found" in result.output
