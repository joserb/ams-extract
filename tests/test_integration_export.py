"""Integration test for ``rbm export`` against the real BUNGE database.

Gated on ``RBM_TEST_FILE``. Exports only the DEPURADORA area (which holds
MECLADOR AGITADOR AG-100) to keep the run bounded, then checks the dataset
layout and that M1H's 5 FFT + 5 waveform samples land in the manifest and
in the per-equipment Parquet files.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest
from typer.testing import CliRunner

from ams_extract.cli import app as rbm_app

pytestmark = pytest.mark.integration

runner = CliRunner()


def _export_depuradora(real_rbm: Path, out: Path) -> None:
    result = runner.invoke(
        rbm_app,
        [
            "export",
            str(real_rbm),
            "--out", str(out),
            "--types", "fft,waveform",
            "--areas", "DEPURADORA",
        ],
    )
    assert result.exit_code == 0, result.output


def test_export_depuradora_layout(real_rbm: Path, tmp_path: Path) -> None:
    out = tmp_path / "dataset"
    _export_depuradora(real_rbm, out)

    assert (out / "hierarchy.json").exists()
    assert (out / "manifest.parquet").exists()
    # Hive partition for the single exported area.
    area_dir = out / "samples" / "area=DEPURADORA"
    assert area_dir.is_dir()
    assert list(area_dir.glob("*__fft.parquet")), "no FFT parquet files emitted"
    assert list(area_dir.glob("*__waveform.parquet")), "no waveform parquet files"


def test_export_m1h_samples_present_in_manifest(
    real_rbm: Path, tmp_path: Path
) -> None:
    out = tmp_path / "dataset"
    _export_depuradora(real_rbm, out)

    manifest = pq.read_table(out / "manifest.parquet").to_pylist()
    m1h = [
        r
        for r in manifest
        if r["point_long_name"] == "MOTOR LOA HORIZONTAL"
        and "AG-100" in (r["equipment_long_name"] or "")
    ]
    fft = [r for r in m1h if r["sample_type"] == "FFT"]
    waveform = [r for r in m1h if r["sample_type"] == "WAVEFORM"]
    assert len(fft) == 5, f"expected 5 M1H FFT rows, got {len(fft)}"
    assert len(waveform) == 5, f"expected 5 M1H waveform rows, got {len(waveform)}"

    # The manifest path must point at a file that actually exists and holds
    # the same number of rows for that equipment+type.
    fft_path = out / fft[0]["parquet_path"]
    assert fft_path.exists(), fft_path
    fft_table = pq.read_table(fft_path).to_pylist()
    m1h_in_file = [
        r for r in fft_table if r["point_long_name"] == "MOTOR LOA HORIZONTAL"
    ]
    assert len(m1h_in_file) == 5

    # Manifest carries no amplitude arrays (it is a pure index).
    assert "amplitude" not in manifest[0]
    assert fft[0]["fmax_hz"] == pytest.approx(1000.0)


def test_export_parallel_matches_serial(real_rbm: Path, tmp_path: Path) -> None:
    serial = tmp_path / "serial"
    parallel = tmp_path / "parallel"
    _export_depuradora(real_rbm, serial)

    result = runner.invoke(
        rbm_app,
        [
            "export",
            str(real_rbm),
            "--out", str(parallel),
            "--types", "fft,waveform",
            "--areas", "DEPURADORA",
            "--parallel", "2",
        ],
    )
    assert result.exit_code == 0, result.output

    serial_rows = pq.read_table(serial / "manifest.parquet").num_rows
    parallel_rows = pq.read_table(parallel / "manifest.parquet").num_rows
    assert serial_rows == parallel_rows
    assert serial_rows > 0
