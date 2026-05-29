"""Tests for the dataset orchestration and the ``rbm export`` command.

The committed synthetic fixture has areas but no equipment/points/samples,
so it exercises the layout (hierarchy.json + empty manifest + zero-sample
summary) without needing the real database.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
from typer.testing import CliRunner

from ams_extract.cli import app as rbm_app
from ams_extract.export.dataset import export_dataset
from ams_extract.export.manifest import MANIFEST_SCHEMA

runner = CliRunner()


class TestExportDataset:
    def test_writes_hierarchy_and_empty_manifest(
        self, synthetic_rbm: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "dataset"
        summary = export_dataset(
            synthetic_rbm,
            out,
            types={"fft", "waveform"},
            show_progress=False,
        )

        hierarchy = out / "hierarchy.json"
        manifest = out / "manifest.parquet"
        assert hierarchy.exists()
        assert manifest.exists()

        document = json.loads(hierarchy.read_text(encoding="utf-8"))
        assert document["meta"]["area_count"] == 5

        table = pq.read_table(manifest)
        assert table.num_rows == 0
        assert table.schema.equals(MANIFEST_SCHEMA)

        # No equipment in the synthetic fixture -> nothing to export.
        assert summary.areas == 5
        assert summary.equipment_total == 0
        assert summary.fft_samples == 0
        assert summary.waveform_samples == 0
        assert summary.parquet_files == 0

    def test_area_filter_selects_subset(
        self, synthetic_rbm: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "dataset"
        summary = export_dataset(
            synthetic_rbm,
            out,
            types={"fft"},
            area_filter={"AREA_ALPHA"},
            show_progress=False,
        )
        assert summary.areas == 1


class TestRbmExportCommand:
    def test_export_synthetic_succeeds(
        self, synthetic_rbm: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "dataset"
        result = runner.invoke(
            rbm_app,
            ["export", str(synthetic_rbm), "--out", str(out), "--types", "fft"],
        )
        assert result.exit_code == 0, result.output
        assert "wrote dataset" in result.output
        assert (out / "hierarchy.json").exists()
        assert (out / "manifest.parquet").exists()

    def test_unknown_type_exits_nonzero(
        self, synthetic_rbm: Path, tmp_path: Path
    ) -> None:
        result = runner.invoke(
            rbm_app,
            [
                "export",
                str(synthetic_rbm),
                "--out",
                str(tmp_path / "ds"),
                "--types",
                "bogus",
            ],
        )
        assert result.exit_code == 1
        assert "unknown sample type" in result.output

    def test_missing_file_exits_nonzero(self, tmp_path: Path) -> None:
        result = runner.invoke(
            rbm_app,
            ["export", str(tmp_path / "missing.rbm"), "--out", str(tmp_path / "ds")],
        )
        assert result.exit_code == 1
        assert "error" in result.output.lower()
