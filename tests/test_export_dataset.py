"""Tests for the VibFrame orchestration and the ``rbm export`` command."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from ams_extract.cli import app as rbm_app
from ams_extract.export.dataset import (
    _build_machine_doc,
    _spectrum_row,
    _waveform_row,
    export_dataset,
)
from ams_extract.models import Equipment, Point, Spectrum, Waveform

runner = CliRunner()


class TestExportDataset:
    def test_normalizes_units_speed_and_single_configuration(self) -> None:
        point = Point(record_num=1, long_name="MOTOR", short_code="MOTOR")
        spectrum = Spectrum(
            record_num=2,
            point_record_num=point.record_num,
            timestamp_utc=datetime(2020, 1, 1, tzinfo=UTC),
            fmax_hz=1_000.0,
            n_lines=4,
            units="G's",
            rpm=1_500.0,
            carga_pct=0.0,
            amplitude=np.zeros(4, dtype=np.float32),
        )
        waveform = Waveform(
            record_num=3,
            point_record_num=point.record_num,
            timestamp_utc=datetime(2020, 1, 1, tzinfo=UTC),
            n_samples=4,
            sample_rate_hz=1_000.0,
            rpm=1_500.0,
            units="G's",
            carga_pct=0.0,
            samples=np.zeros(4, dtype=np.float32),
        )
        equipment = Equipment(record_num=4, long_name="BOMBA", short_code="PUMP", points=(point,))

        spectrum_row = _spectrum_row(spectrum, point)
        waveform_row = _waveform_row(waveform, point)
        machine_doc = _build_machine_doc(
            source_path="fixture.rbm",
            extracted_at=datetime(2020, 1, 1, tzinfo=UTC),
            area_long="AREA",
            equipment=equipment,
            proc_modes=[],
        )

        assert spectrum_row["unit"] == waveform_row["unit"] == "g"
        assert spectrum_row["speed_hz"] == waveform_row["speed_hz"] == 25.0
        assert machine_doc["config_generations"] == []

    def test_machine_doc_validates_against_optional_vibframe_contract(self) -> None:
        contracts = pytest.importorskip("vibsynth_contracts.dataset")
        point = Point(record_num=1, long_name="MOTOR", short_code="MOTOR")
        equipment = Equipment(record_num=2, long_name="BOMBA", short_code="PUMP", points=(point,))
        document = _build_machine_doc(
            source_path="fixture.rbm",
            extracted_at=datetime(2020, 1, 1, tzinfo=UTC),
            area_long="AREA",
            equipment=equipment,
            proc_modes=[],
        )

        contracts.MachineDoc.model_validate(document)

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
