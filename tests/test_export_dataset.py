"""Tests for the VibDataset orchestration and the ``rbm export`` command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ams_extract.cli import app as rbm_app
from ams_extract.export.dataset import export_dataset

runner = CliRunner()


class TestExportDataset:
    def test_writes_dataset_doc_and_report(self, synthetic_rbm: Path, tmp_path: Path) -> None:
        out = tmp_path / "dataset"
        summary = export_dataset(
            synthetic_rbm,
            out,
            types={"fft", "waveform"},
            show_progress=False,
        )

        dataset_json = out / "dataset.json"
        report = out / "report.html"
        assert dataset_json.exists()
        assert report.exists()

        document = json.loads(dataset_json.read_text(encoding="utf-8"))
        assert document["schema_version"] == "0.1.0"
        assert document["generator"].startswith("ams-extract")

        # No equipment in the synthetic fixture -> nothing to export.
        assert summary.areas == 5
        assert summary.equipment_total == 0
        assert summary.fft_samples == 0
        assert summary.waveform_samples == 0
        assert summary.parquet_files == 0

    def test_area_filter_selects_subset(self, synthetic_rbm: Path, tmp_path: Path) -> None:
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
    def test_export_synthetic_succeeds(self, synthetic_rbm: Path, tmp_path: Path) -> None:
        out = tmp_path / "dataset"
        result = runner.invoke(
            rbm_app,
            ["export", str(synthetic_rbm), "--out", str(out), "--types", "fft"],
        )
        assert result.exit_code == 0, result.output
        assert "wrote dataset" in result.output
        assert (out / "dataset.json").exists()
        assert (out / "report.html").exists()

    def test_export_clears_existing_output_dir(self, synthetic_rbm: Path, tmp_path: Path) -> None:
        out = tmp_path / "dataset"
        out.mkdir()
        stale = out / "manifest.parquet"
        stale.write_text("legacy", encoding="utf-8")

        result = runner.invoke(
            rbm_app,
            ["export", str(synthetic_rbm), "--out", str(out), "--types", "fft"],
        )
        assert result.exit_code == 0, result.output
        assert (out / "dataset.json").exists()
        assert not stale.exists()

    def test_unknown_type_exits_nonzero(self, synthetic_rbm: Path, tmp_path: Path) -> None:
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
