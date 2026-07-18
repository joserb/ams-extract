"""Integration tests for ``rbm export`` VibFrame output."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from typer.testing import CliRunner

from ams_extract.cli import app as rbm_app

pytestmark = pytest.mark.integration

runner = CliRunner()


def _export_depuradora(real_rbm: Path, out: Path, types: str = "fft,waveform") -> None:
    result = runner.invoke(
        rbm_app,
        [
            "export",
            str(real_rbm),
            "--out",
            str(out),
            "--types",
            types,
            "--areas",
            "DEPURADORA",
        ],
    )
    assert result.exit_code == 0, result.output


def _find_machine_dir(out: Path, machine_name_substring: str) -> Path:
    for machine_json in out.glob("machine=*/machine.json"):
        doc = json.loads(machine_json.read_text(encoding="utf-8"))
        if machine_name_substring in doc["machine"]["name"]:
            return machine_json.parent
    raise AssertionError(f"machine not found: {machine_name_substring}")


def test_export_depuradora_layout(real_rbm: Path, tmp_path: Path) -> None:
    out = tmp_path / "dataset"
    _export_depuradora(real_rbm, out)

    assert (out / "dataset.json").exists()
    assert (out / "report.html").exists()
    machine_dirs = list(out.glob("machine=*"))
    assert machine_dirs, "no machine asset directories emitted"
    sample_machine = machine_dirs[0]
    assert (sample_machine / "machine.json").exists()
    assert (sample_machine / "metrics.parquet").exists()
    assert (sample_machine / "spectra.parquet").exists()
    assert (sample_machine / "waves.parquet").exists()
    assert (sample_machine / "trends.parquet").exists()


def test_export_m1h_samples_present_in_asset_tables(real_rbm: Path, tmp_path: Path) -> None:
    out = tmp_path / "dataset"
    _export_depuradora(real_rbm, out)

    machine_dir = _find_machine_dir(out, "AG-100")
    doc = json.loads((machine_dir / "machine.json").read_text(encoding="utf-8"))
    point = next(p for p in doc["points"] if p["name"] == "MOTOR LOA HORIZONTAL")

    spectra = pq.read_table(machine_dir / "spectra.parquet").to_pylist()
    waves = pq.read_table(machine_dir / "waves.parquet").to_pylist()
    m1h_fft = [r for r in spectra if r["point_id"] == point["id"]]
    m1h_waves = [r for r in waves if r["point_id"] == point["id"]]

    assert len(m1h_fft) == 5
    assert len(m1h_waves) == 5
    assert m1h_fft[0]["fmax_hz"] == pytest.approx(1000.0)
    assert m1h_fft[0]["unit"] == "mm/s"
    assert len(m1h_fft[0]["data"]) == 1600


def test_export_parallel_matches_serial(real_rbm: Path, tmp_path: Path) -> None:
    serial = tmp_path / "serial"
    parallel = tmp_path / "parallel"
    _export_depuradora(real_rbm, serial)

    result = runner.invoke(
        rbm_app,
        [
            "export",
            str(real_rbm),
            "--out",
            str(parallel),
            "--types",
            "fft,waveform",
            "--areas",
            "DEPURADORA",
            "--parallel",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output

    serial_rows = sum(
        pq.read_table(path).num_rows for path in serial.glob("machine=*/spectra.parquet")
    )
    parallel_rows = sum(
        pq.read_table(path).num_rows for path in parallel.glob("machine=*/spectra.parquet")
    )
    assert serial_rows == parallel_rows
    assert serial_rows > 0


def test_export_trend_m1h_matches_gold(real_rbm: Path, tmp_path: Path) -> None:
    out = tmp_path / "dataset"
    _export_depuradora(real_rbm, out, types="trend")

    machine_dir = _find_machine_dir(out, "AG-100")
    doc = json.loads((machine_dir / "machine.json").read_text(encoding="utf-8"))
    point = next(p for p in doc["points"] if p["name"] == "MOTOR LOA HORIZONTAL")

    metrics = pq.read_table(machine_dir / "metrics.parquet").to_pylist()
    point_metrics = [m for m in metrics if m["point_id"] == point["id"]]
    metric = next(m for m in point_metrics if m["name"] == "overall_velocity_rms")
    assert metric["unit"] == "mm/s"

    trend_rows = pq.read_table(machine_dir / "trends.parquet").to_pylist()
    rows = sorted(
        (r for r in trend_rows if r["metric_id"] == metric["metric_id"]),
        key=lambda r: r["t"],
    )
    assert len(rows) == 62
    assert rows[0]["value"] == pytest.approx(1.58, abs=0.02)
    assert max(r["value"] for r in rows) == pytest.approx(36.43, abs=0.02)

    # Named vddt bands (velocity template; M1H is band_count=7 throughout).
    band_metrics = {m["name"]: m for m in point_metrics if m["metric_id"].startswith("band_")}
    assert set(band_metrics) == {
        "Mp Wave",
        "SUBSINCRONO",
        "DESEQUILIBRIO",
        "DESALINEACION",
        "HOLGURAS",
        "11-40 X RPM",
    }
    assert band_metrics["Mp Wave"]["unit"] == "g"
    assert band_metrics["Mp Wave"]["statistic"] == "true_peak"
    assert band_metrics["SUBSINCRONO"]["unit"] == "mm/s"
    assert band_metrics["11-40 X RPM"]["band_low_order"] == 11.0

    sub_rows = [r for r in trend_rows if r["metric_id"] == band_metrics["SUBSINCRONO"]["metric_id"]]
    assert len(sub_rows) == 62
    # SUBSINCRONO crosses its C alarm at the trend peak (FORMAT §5.8: gold
    # alarm report "SUBSINCRONO - 1.986 mm/Seg - C Alarm").
    assert max(r["value"] for r in sub_rows) > 1.5

    # machine.path carries location levels only (the area), not the machine.
    assert doc["machine"]["path"] == ["DEPURADORA"]
