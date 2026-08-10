"""VibFrame conformance of this producer (Part 2 of t8-extract's workplan 03).

Three checks, cheapest first:

1. What this repo writes **passes the contract validator**
   (``vibframe-validate``), both through its API and through the installed
   CLI — the same command the non-Python producers use.
2. The **goldens** of ``vibsynth-contracts`` (one per origin) pass the
   validator and **round-trip** through this repo's writer: re-reading a
   golden and rewriting it with our schema preserves types and values, and
   its JSON documents re-enter the contract models without loss. That is the
   check that our writer and the contract have not drifted apart.
3. With the real database (``RBM_TEST_FILE``, marker ``integration``), a full
   ``rbm export`` passes the validator.

The **validator** is consumed only from here: ``rbm export`` writes against
the vendored contract subset (``export/vibframe_contract.py``) and never
imports ``vibsynth_contracts`` at runtime — that dependency is a test/CI
tool, not a runtime one.
"""

from __future__ import annotations

import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from typer.testing import CliRunner
from vibsynth_contracts.dataset import (
    DatasetInfo,
    MachineDoc,
    MetricCatalogDoc,
)
from vibsynth_contracts.validate import validate_dataset

from ams_extract.cli import app as rbm_app
from ams_extract.export.dataset import _write_parquet
from ams_extract.export.vibframe_contract import (
    DATASET_FILE,
    MACHINE_DOC_FILE,
    METRIC_CATALOG_FILE,
    SPECTRA_COLUMNS,
    SPECTRA_FILE,
    TRENDS_COLUMNS,
    TRENDS_FILE,
    WAVES_COLUMNS,
    WAVES_FILE,
    ColumnSpec,
    schema,
)

runner = CliRunner()

GOLDENS = Path(str(files("vibsynth_contracts") / "goldens"))
TABLES: tuple[tuple[str, tuple[ColumnSpec, ...]], ...] = (
    (TRENDS_FILE, TRENDS_COLUMNS),
    (SPECTRA_FILE, SPECTRA_COLUMNS),
    (WAVES_FILE, WAVES_COLUMNS),
)


def _golden_dirs() -> list[Path]:
    return sorted(p for p in GOLDENS.iterdir() if p.is_dir())


def _assert_clean(dataset: Path) -> None:
    report = validate_dataset(dataset)
    assert report.parquet_checked, "pyarrow missing: the validator skipped the parquet"
    assert report.errors == [], [issue.format() for issue in report.errors]
    assert report.warnings == [], [issue.format() for issue in report.warnings]


def _assert_golden_conformant(golden: Path) -> None:
    """Validate the real, canonical 0.2 goldens without source exceptions."""
    report = validate_dataset(golden)
    assert report.parquet_checked, "pyarrow missing: the validator skipped the parquet"
    assert report.errors == [], [issue.format() for issue in report.errors]
    assert report.warnings == [], [issue.format() for issue in report.warnings]


# -------------------------------------------------------- our export passes


def test_our_export_passes_the_validator(vibframe_dataset: Path) -> None:
    _assert_clean(vibframe_dataset)


def test_the_installed_cli_accepts_our_export(vibframe_dataset: Path) -> None:
    """The CLI, not the API: it is the conformance path of non-Python producers."""
    script = Path(sys.executable).parent / "vibframe-validate"
    argv = (
        [str(script)]
        if script.exists()
        else [sys.executable, "-m", "vibsynth_contracts.validate.cli"]
    )
    proc = subprocess.run(
        [*argv, str(vibframe_dataset), "--strict", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["ok"] and report["counts"]["error"] == 0


def test_required_columns_are_declared_non_nullable() -> None:
    """The alignment of workplan 06: required means non-nullable on disk too.

    ``columns.null-in-required`` is a validator error; declaring the field
    non-nullable turns it into a write-time failure here, and matches what
    t8-extract and vibsynth emit.
    """
    for _, columns in TABLES:
        pa_schema = schema(columns)
        for column in columns:
            assert pa_schema.field(column.name).nullable is not column.required


# ------------------------------------------------------------ goldens: valid


def test_there_is_a_golden_for_our_origin() -> None:
    assert (GOLDENS / "ams-rbm").is_dir()


@pytest.mark.parametrize("golden", _golden_dirs(), ids=lambda p: p.name)
def test_the_goldens_are_conformant(golden: Path) -> None:
    """Goldens are real 0.2 datasets; no test-only migration is permitted."""
    _assert_golden_conformant(golden)


# ------------------------------------------------------- goldens: round-trip


@pytest.mark.parametrize("golden", _golden_dirs(), ids=lambda p: p.name)
def test_the_goldens_round_trip_through_our_writer(golden: Path, tmp_path: Path) -> None:
    """Re-reading a golden and rewriting it with our schema loses nothing.

    All three origins on purpose: the parquet schema this repo derives from
    ``*_COLUMNS`` has to serve any producer, not just ours. Names, types and
    values are compared exactly; rewriting through our schema additionally
    proves that no golden carries a null in a required field.
    """
    seen = 0
    for partition in sorted(golden.glob("machine=*")):
        for name, columns in TABLES:
            original = pq.ParquetFile(partition / name).read()
            want = schema(columns)
            assert original.schema.names == want.names, f"{partition.name}/{name}"
            assert original.schema.types == want.types, f"{partition.name}/{name}"
            copy = tmp_path / f"{partition.name}-{name}"
            _write_parquet(original.to_pylist(), columns, copy)
            rewritten = pq.ParquetFile(copy).read()
            for column in want.names:
                assert (
                    rewritten.column(column).to_pylist() == original.column(column).to_pylist()
                ), f"{partition.name}/{name}:{column}"
            seen += 1
    assert seen == len(TABLES) * len(list(golden.glob("machine=*")))


@pytest.mark.parametrize("golden", _golden_dirs(), ids=lambda p: p.name)
def test_the_metric_catalogs_round_trip_through_the_model(golden: Path) -> None:
    """Each real golden carries the single JSON metric-catalog representation."""
    for partition in sorted(golden.glob("machine=*")):
        path = partition / METRIC_CATALOG_FILE
        catalog = MetricCatalogDoc.model_validate_json(path.read_text(encoding="utf-8"))
        assert catalog.schema_version == "0.2.0"
        assert not (partition / "metrics.parquet").exists()
        assert not (partition / "metric_catalog.parquet").exists()
        # AMS goldens may legitimately have no resolved FrequencyDef until the
        # separate +enrich stage runs; this conformance test must not invent
        # a frequency merely to make a non-empty assertion.


@pytest.mark.parametrize("golden", _golden_dirs(), ids=lambda p: p.name)
def test_the_golden_documents_round_trip_through_the_models(golden: Path) -> None:
    info = DatasetInfo.model_validate_json((golden / DATASET_FILE).read_text())
    assert DatasetInfo.model_validate_json(info.model_dump_json()) == info
    for partition in sorted(golden.glob("machine=*")):
        doc = MachineDoc.model_validate_json((partition / MACHINE_DOC_FILE).read_text())
        assert MachineDoc.model_validate_json(doc.model_dump_json()) == doc


# ------------------------------------------------------------ real database


@pytest.fixture
def real_export(real_rbm: Path, tmp_path: Path) -> Path:
    """One area of the real database exported by the CLI, end to end."""
    out = tmp_path / "dataset"
    result = runner.invoke(
        rbm_app,
        [
            "export",
            str(real_rbm),
            "--out",
            str(out),
            "--types",
            "fft,waveform,trend",
            "--areas",
            "DEPURADORA",
        ],
    )
    assert result.exit_code == 0, result.output
    return out


@pytest.mark.integration
def test_a_real_export_passes_the_validator(real_export: Path) -> None:
    """The end-to-end conformance claim of ``rbm export``."""
    _assert_clean(real_export)


@pytest.mark.integration
def test_a_real_export_fills_every_required_column(real_export: Path) -> None:
    """Nothing in the real database forces a required column to stay nullable:
    the export fills them all, so the schema can declare them non-nullable."""
    partitions = sorted(real_export.glob("machine=*"))
    assert partitions
    for partition in partitions:
        for name, columns in TABLES:
            table = pq.ParquetFile(partition / name).read()
            for column in columns:
                if column.required:
                    assert table.schema.field(column.name).nullable is False
                    assert table.column(column.name).null_count == 0, (
                        f"{partition.name}/{name}:{column.name}"
                    )
