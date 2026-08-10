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
    assert (sample_machine / "metric_catalog.json").exists()
    assert not (sample_machine / "metrics.parquet").exists()
    assert not (sample_machine / "metric_catalog.parquet").exists()
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


def test_export_machine_doc_carries_the_shaft_config(real_rbm: Path, tmp_path: Path) -> None:
    out = tmp_path / "dataset"
    _export_depuradora(real_rbm, out)

    machine_dir = _find_machine_dir(out, "AG-100")
    doc = json.loads((machine_dir / "machine.json").read_text(encoding="utf-8"))
    points = {p["name"]: p for p in doc["points"]}

    # The designations FORMAT §5.8 records for the pilot point, verbatim and
    # in slot order; its LA sibling differs in the first slot (per point, not
    # per machine), and the gearbox points declare none.
    assert points["MOTOR LOA HORIZONTAL"]["bearing_designations"] == ["6204", "6208"]
    assert points["MOTOR LA VERTICAL"]["bearing_designations"] == ["6205", "6208"]
    assert points["Reductor LA Horiz"]["bearing_designations"] == []
    # vdpm.0x164 in RPM, as stored: the 1 455 of FORMAT §5, on every point of
    # this single-shaft machine.
    assert all(p["nominal_speed_rpm"] == 1455.0 for p in doc["points"])
    # ams-extract declares what the .rbm holds; it resolves no definition, so
    # it writes neither a definition nor a provenance for one.
    assert "definition" not in doc["machine"]  # null-free 0.2 serialization
    assert "definition_provenance" not in doc["machine"]


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


def test_export_emits_machine_level_context_metrics(real_rbm: Path, tmp_path: Path) -> None:
    out = tmp_path / "dataset"
    _export_depuradora(real_rbm, out)

    machine_dir = _find_machine_dir(out, "AG-100")
    metric_rows = json.loads(
        (machine_dir / "metric_catalog.json").read_text(encoding="utf-8")
    )["metrics"]
    metrics = {m["metric_id"]: m for m in metric_rows}

    for metric_id, unit in (("speed", "Hz"), ("load", "%")):
        metric = metrics[metric_id]
        assert "point_id" not in metric  # null-free metric_catalog.json
        assert metric["statistic"] == "value"
        assert metric["signal_family"] == "non_vibration"
        assert metric["unit"] == unit
        assert "canonical_metric" not in metric  # labelled post-hoc (ADR-0011)

    trend_rows = pq.read_table(machine_dir / "trends.parquet").to_pylist()
    speeds = [r["value"] for r in trend_rows if r["metric_id"] == "speed"]
    assert speeds
    # AG-100 stores rpm=1455 (the 1455 nominal of ADR-0013) in every vdps
    # and vdfw capture -> 24.25 Hz; the analysis-vs-physical split of
    # ADR-0013 does not show up in this machine's stored captures.
    assert any(abs(v - 24.25) < 0.05 for v in speeds)
    assert all(0.0 < v < 100.0 for v in speeds)
    # Spectrum and waveform of the same point/timestamp share the rpm:
    # exact duplicates collapse, so 5 captures -> 5 speed readings for M1H.
    speed_keys = [(r["t"], r["value"]) for r in trend_rows if r["metric_id"] == "speed"]
    assert len(speed_keys) == len(set(speed_keys))
    loads = [r["value"] for r in trend_rows if r["metric_id"] == "load"]
    assert loads
    assert all(0.0 <= v <= 100.0 for v in loads)


def test_export_trend_m1h_matches_gold(real_rbm: Path, tmp_path: Path) -> None:
    out = tmp_path / "dataset"
    _export_depuradora(real_rbm, out, types="trend")

    machine_dir = _find_machine_dir(out, "AG-100")
    doc = json.loads((machine_dir / "machine.json").read_text(encoding="utf-8"))
    point = next(p for p in doc["points"] if p["name"] == "MOTOR LOA HORIZONTAL")

    metrics = json.loads(
        (machine_dir / "metric_catalog.json").read_text(encoding="utf-8")
    )["metrics"]
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

    # Named vddt bands resolved through the point's pdpa template
    # "Estandar 1500 rpm (S)" (FORMAT §5.8; M1H is band_count=7 throughout).
    band_metrics = {m["name"]: m for m in point_metrics if m["metric_id"].startswith("band_")}
    assert set(band_metrics) == {
        "Mp Wave",
        "SUBSINCRONO",
        "DESEQUILIBRIO",
        "DESALINEACION",
        "HOLGURAS",
        "11-40 X RPM",
        "1 - 20 KHz",
    }
    # HF band: raw acceleration RMS in G's with fixed Hz bounds (scale
    # validated against the AMS capture of PM-9101-A M1H, 2026-07-19).
    hf = band_metrics["1 - 20 KHz"]
    assert hf["unit"] == "g"
    assert hf["statistic"] == "spectrum_rms"
    assert hf["band_type"] == "single"
    assert hf["band_low_hz"] == pytest.approx(1000.0)
    assert hf["band_high_hz"] == pytest.approx(20000.0)
    assert band_metrics["Mp Wave"]["unit"] == "g"
    assert band_metrics["Mp Wave"]["statistic"] == "true_peak"
    assert band_metrics["Mp Wave"]["band_type"] == "none"
    assert band_metrics["SUBSINCRONO"]["unit"] == "mm/s"
    # Band edges from the template, in shaft orders (contiguous bands).
    assert band_metrics["SUBSINCRONO"]["band_low_order"] == pytest.approx(0.0)
    assert band_metrics["SUBSINCRONO"]["band_high_order"] == pytest.approx(0.7)
    assert band_metrics["HOLGURAS"]["band_low_order"] == pytest.approx(2.5)
    assert band_metrics["HOLGURAS"]["band_high_order"] == pytest.approx(10.5)
    assert band_metrics["11-40 X RPM"]["band_low_order"] == pytest.approx(10.5)
    assert band_metrics["11-40 X RPM"]["band_high_order"] == pytest.approx(40.5)
    assert "band_low_hz" not in band_metrics["SUBSINCRONO"]

    sub_rows = sorted(
        (r for r in trend_rows if r["metric_id"] == band_metrics["SUBSINCRONO"]["metric_id"]),
        key=lambda r: r["t"],
    )
    assert len(sub_rows) == 62
    # SUBSINCRONO crosses its C alarm at the trend peak (FORMAT §5.8: gold
    # alarm report "SUBSINCRONO - 1.986 mm/Seg - C Alarm").
    assert max(r["value"] for r in sub_rows) > 1.5

    # The derived alarm column follows the pdla thresholds of alarm set 5
    # ("Motor Horizontal P<300 kW (S)"): alert 1.4 mm/s, danger 2.2 mm/s.
    # Gold anchor: M1H turns C at ~1.44 and D at ~2.24 mm/s (ADR-0012).
    for row in sub_rows:
        expected = 0
        if row["value"] >= 1.4:
            expected = 2
        if row["value"] >= 2.2:
            expected = 3
        assert row["alarm"] == expected
    assert {r["alarm"] for r in sub_rows} == {0, 2, 3}

    # machine.path carries location levels only (the area), not the machine.
    assert doc["machine"]["path"] == ["DEPURADORA"]
