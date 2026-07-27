"""Integration test for ``rbm extract`` against the real BUNGE database.

Gated on ``RBM_TEST_FILE``. The target is M1H (MOTOR LOA HORIZONTAL)
of MECLADOR AGITADOR AG-100 in DEPURADORA, whose 5 FFT timestamps and
acquisition parameters (Fmax=1000 Hz, n_lines=1600, units=plg/segs)
were verified against AMS screenshots during sub-fase 3a.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest
from typer.testing import CliRunner

from ams_extract.cli import app as rbm_app
from ams_extract.reader import RbmReader
from ams_extract.records.waveform import VCFW_DATA_SAMPLES, VDFW_TAIL_NOT_STORED
from ams_extract.tree import (
    walk_hierarchy,
    walk_spectra,
    walk_trends,
    walk_waveforms,
)

pytestmark = pytest.mark.integration

runner = CliRunner()

# M1H gold timestamps in chronological order (oldest → newest). The CLI
# emits in the same order, so index 0 is the oldest spectrum.
M1H_GOLD_TIMESTAMPS = [
    "20191015_144437",
    "20191112_155739",
    "20191212_140700",
    "20200121_113020",
    "20200219_100250",
]


def test_extract_three_m1h_spectra_writes_parquet_and_png(
    real_rbm: Path, tmp_path: Path
) -> None:
    out_dir = tmp_path / "samples"
    result = runner.invoke(
        rbm_app,
        [
            "extract",
            str(real_rbm),
            "--point", "MOTOR LOA HORIZONTAL",
            "--equipment", "AG-100",
            "--type", "fft",
            "--limit", "3",
            "--out", str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output

    parquet_files = sorted(out_dir.glob("*fft*.parquet"))
    png_files = sorted(out_dir.glob("*fft*.png"))
    assert len(parquet_files) == 3
    assert len(png_files) == 3

    # Filenames embed the chronological index + UTC timestamp; the first
    # three written are the three oldest spectra of M1H.
    for path, expected_ts in zip(parquet_files, M1H_GOLD_TIMESTAMPS[:3], strict=True):
        assert expected_ts in path.name, (
            f"expected timestamp {expected_ts} in {path.name}"
        )


def test_extract_parquet_payload_is_plausible(
    real_rbm: Path, tmp_path: Path
) -> None:
    out_dir = tmp_path / "samples"
    result = runner.invoke(
        rbm_app,
        [
            "extract",
            str(real_rbm),
            "--point", "MOTOR LOA HORIZONTAL",
            "--equipment", "AG-100",
            "--type", "fft",
            "--limit", "1",
            "--out", str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output

    parquet = next(out_dir.glob("*fft*.parquet"))
    table = pq.read_table(parquet)
    row = table.to_pylist()[0]

    assert row["sample_type"] == "FFT"
    assert row["fmax_hz"] == pytest.approx(1000.0)
    assert row["n_lines"] == 1600
    # Velocity spectra are calibrated to mm/s (FORMAT §5.6).
    assert row["units"] == "mm/s"
    assert row["carga_pct"] == pytest.approx(100.0)

    # Full spectrum = low band (vdps tail) + vcps chain, truncated to n_lines.
    amplitude = np.array(row["amplitude"], dtype=np.float32)
    assert amplitude.shape == (1600,)
    assert np.isfinite(amplitude).all()
    assert amplitude.std() > 0.0, "spectrum is constant; data was not actually decoded"
    assert (amplitude > 0).any(), "no positive amplitudes; suspicious"


# AMS "Lista de Picos" for AG-100 M1H velocity FFT 2020-02-19 (Hz -> mm/s).
# A representative spread of low-, mid- and high-frequency peaks; the low
# ones (<49 Hz) live in the vdps tail and the highest exercise the chain.
_AG100_M1H_20200219_VEL_GOLD = [
    (14.68, 5.059),
    (24.44, 1.796),
    (48.92, 1.370),
    (146.73, 0.750),
    (584.79, 0.364),
    (884.67, 0.240),
]


def test_extract_fft_payload_matches_ams_gold(real_rbm: Path, tmp_path: Path) -> None:
    # The calibrated velocity spectrum must reproduce the AMS peak list:
    # full reconstruction (low band + chain) + x48.5 scale -> mm/s, with
    # bin i at i*Fmax/n_lines (FORMAT §5.6). Validated to ~5% on 3 machines;
    # allow 15% here to absorb screenshot-reading + bin-rounding error.
    out_dir = tmp_path / "samples"
    result = runner.invoke(
        rbm_app,
        [
            "extract",
            str(real_rbm),
            "--point", "MOTOR LOA HORIZONTAL",
            "--equipment", "AG-100",
            "--type", "fft",
            "--limit", "5",
            "--out", str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output

    newest = next(out_dir.glob("*fft*20200219*.parquet"))
    row = pq.read_table(newest).to_pylist()[0]
    assert row["units"] == "mm/s"
    amplitude = np.array(row["amplitude"], dtype=np.float32)
    bin_width = row["fmax_hz"] / row["n_lines"]

    for freq_hz, ams_mms in _AG100_M1H_20200219_VEL_GOLD:
        bin_index = round(freq_hz / bin_width)
        ours = float(amplitude[bin_index])
        assert ours == pytest.approx(ams_mms, rel=0.15), (
            f"{freq_hz} Hz: decoded {ours:.3f} mm/s vs AMS {ams_mms:.3f}"
        )


# AMS PeakVue "Lista de Picos" for PM-6901-A M2P (MOTOR LA VERTICAL PEAKVUE),
# CALDERAS, 2024-01-24 (Hz -> G's RMS). Acceleration uses the same low-band +
# chain reconstruction but a different scale (no inch->mm; RMS). Dominant peak
# at 199.79 Hz = 0.907 G.
_PM6901_M2P_PEAKVUE_GOLD = [
    (25.92, 0.135),
    (179.83, 0.160),
    (199.79, 0.907),
    (400.20, 0.116),
    (599.84, 0.105),
    (800.18, 0.231),
]


def test_peakvue_acceleration_matches_ams_gold(real_rbm: Path) -> None:
    # Acceleration (G's) spectra calibrate to G's via ACCEL_SCALE_G; validate
    # the full reconstruction reproduces the AMS PeakVue peak list within 15%.
    with RbmReader(real_rbm) as reader:
        point = next(
            p
            for area in walk_hierarchy(reader)
            if "CALDERAS" in area.long_name
            for eq in area.equipment
            if "PM-6901-A" in eq.long_name
            for p in eq.points
            if p.long_name == "MOTOR LA VERTICAL PEAKVUE"
        )
        spectrum = next(
            s
            for s in walk_spectra(reader, point)
            if s.timestamp_utc.strftime("%Y-%m-%d") == "2024-01-24"
        )

    assert spectrum.units == "G's"
    assert spectrum.amplitude.shape == (1600,)
    bin_width = spectrum.fmax_hz / spectrum.n_lines
    for freq_hz, ams_g in _PM6901_M2P_PEAKVUE_GOLD:
        ours = float(spectrum.amplitude[round(freq_hz / bin_width)])
        assert ours == pytest.approx(ams_g, rel=0.15), (
            f"{freq_hz} Hz: decoded {ours:.3f} G vs AMS {ams_g:.3f}"
        )


# AMS HF "Lista de Picos" for PM-6901-B M1F (MOTOR LOA ALTA FRECUENCIA),
# CALDERAS, 2024-01-25 (Hz -> G's RMS). Fmax 6000 (bin width 3.75 Hz) — the
# same x1.30 acceleration scale as PeakVue, on a different frequency grid.
_PM6901B_M1F_HF_GOLD = [
    (459.79, 0.0487),
    (919.57, 0.0706),
    (1072.8, 0.142),
    (1187.4, 0.0859),
    (1223.9, 0.142),
    (1378.8, 0.152),
    (4131.4, 0.0129),
]


def test_hf_acceleration_matches_ams_gold(real_rbm: Path) -> None:
    # High-frequency (fmax 6000) acceleration uses the same G's calibration
    # as PeakVue; validate the reconstruction against the AMS peak list.
    with RbmReader(real_rbm) as reader:
        point = next(
            p
            for area in walk_hierarchy(reader)
            if "CALDERAS" in area.long_name
            for eq in area.equipment
            if "PM-6901-B" in eq.long_name
            for p in eq.points
            if "ALTA FRECUENCIA" in p.long_name and "LOA" in p.long_name
        )
        spectrum = next(
            s
            for s in walk_spectra(reader, point)
            if s.timestamp_utc.strftime("%Y-%m-%d") == "2024-01-25"
        )

    assert spectrum.units == "G's"
    assert spectrum.fmax_hz == pytest.approx(6000.0)
    bin_width = spectrum.fmax_hz / spectrum.n_lines
    for freq_hz, ams_g in _PM6901B_M1F_HF_GOLD:
        ours = float(spectrum.amplitude[round(freq_hz / bin_width)])
        assert ours == pytest.approx(ams_g, rel=0.15), (
            f"{freq_hz} Hz: decoded {ours:.3f} G vs AMS {ams_g:.3f}"
        )


def test_extract_errors_when_point_is_ambiguous(
    real_rbm: Path, tmp_path: Path
) -> None:
    # "MOTOR LOA HORIZONTAL" matches many points across the hierarchy;
    # without --equipment the CLI should refuse to pick one and exit 2.
    out_dir = tmp_path / "samples"
    result = runner.invoke(
        rbm_app,
        [
            "extract",
            str(real_rbm),
            "--point", "MOTOR LOA HORIZONTAL",
            "--limit", "1",
            "--out", str(out_dir),
        ],
    )
    assert result.exit_code == 2
    assert "ambiguous" in result.output


def test_extract_five_m1h_waveforms_writes_parquet_and_png(
    real_rbm: Path, tmp_path: Path
) -> None:
    out_dir = tmp_path / "samples"
    result = runner.invoke(
        rbm_app,
        [
            "extract",
            str(real_rbm),
            "--point", "MOTOR LOA HORIZONTAL",
            "--equipment", "AG-100",
            "--type", "waveform",
            "--limit", "5",
            "--out", str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output

    parquet_files = sorted(out_dir.glob("*waveform*.parquet"))
    png_files = sorted(out_dir.glob("*waveform*.png"))
    assert len(parquet_files) == 5
    assert len(png_files) == 5

    # Filenames embed the chronological index + UTC timestamp; M1H has the
    # same 5 acquisition dates for waveform as for FFT.
    for path, expected_ts in zip(parquet_files, M1H_GOLD_TIMESTAMPS, strict=True):
        assert expected_ts in path.name, (
            f"expected timestamp {expected_ts} in {path.name}"
        )


def test_extract_waveform_payload_matches_ams_gold(
    real_rbm: Path, tmp_path: Path
) -> None:
    # The 2020-02-19 waveform is the newest (chronological index 4). AMS
    # reports Pc(+)=0.483 G and Pk(-)=-0.510 G; applying the vdfw.0x28
    # scale factor must reproduce those within 2% (FORMAT §5.5).
    out_dir = tmp_path / "samples"
    result = runner.invoke(
        rbm_app,
        [
            "extract",
            str(real_rbm),
            "--point", "MOTOR LOA HORIZONTAL",
            "--equipment", "AG-100",
            "--type", "waveform",
            "--limit", "5",
            "--out", str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output

    newest = next(out_dir.glob("*waveform*20200219*.parquet"))
    row = pq.read_table(newest).to_pylist()[0]

    assert row["sample_type"] == "WAVEFORM"
    assert row["sample_rate_hz"] == pytest.approx(2560.0)
    # The stored length, not the nominal 512 block (FORMAT §5.5, ADR-0017).
    assert row["n_samples"] == 488
    assert row["rpm"] == pytest.approx(1455.0, rel=0.01)
    assert row["units"] == "G's"

    samples = np.array(row["samples"], dtype=np.float32)
    assert samples.shape == (488,)
    assert row["n_samples"] == len(row["samples"])
    assert np.isfinite(samples).all()
    assert samples.max() == pytest.approx(0.483, abs=0.02)
    assert samples.min() == pytest.approx(-0.510, abs=0.02)


# AMS PLOTDATA "Valore Globale" for AG-100 M1H, the overall RMS velocity
# trend (mm/s) read top-to-bottom — the first 47 of 62 readings. The gold
# the vddt layout was cracked against (FORMAT §5.7, ADR-0006).
_M1H_TREND_GOLD_MM_S = (
    1.58, 1.60, 1.88, 1.37, 2.24, 3.22, 2.10, 1.38, 2.08, 2.16, 6.54, 4.62,
    4.51, 14.64, 6.98, 2.80, 5.53, 9.98, 6.54, 6.51, 9.56, 9.23, 11.40, 7.44,
    6.91, 7.73, 4.79, 3.29, 3.34, 10.90, 15.54, 6.49, 7.68, 9.26, 15.34, 15.25,
    18.05, 6.01, 36.43, 5.92, 4.34, 5.74, 3.10, 8.72, 4.05, 11.89, 15.24,
)


def test_trend_overall_matches_ams_gold(real_rbm: Path) -> None:
    # The vddt "Valores Globales" trend for M1H must reproduce the AMS
    # PLOTDATA table exactly (overall in mm/s = raw x 25.4), including the
    # off-by-one date rule and the duplicate reading on 2017-07-13.
    with RbmReader(real_rbm) as reader:
        point = next(
            p
            for area in walk_hierarchy(reader)
            if "DEPURADORA" in area.long_name
            for eq in area.equipment
            if "AG-100" in eq.long_name
            for p in eq.points
            if p.long_name == "MOTOR LOA HORIZONTAL"
        )
        trend = next(walk_trends(reader, point))

    assert trend.units == "mm/s"
    assert len(trend.overall) == len(trend.timestamps_utc)
    assert len(trend.overall) >= len(_M1H_TREND_GOLD_MM_S)

    for i, gold in enumerate(_M1H_TREND_GOLD_MM_S):
        assert float(trend.overall[i]) == pytest.approx(gold, abs=0.02), (
            f"reading {i} ({trend.timestamps_utc[i]:%Y-%m-%d}): "
            f"decoded {float(trend.overall[i]):.2f} vs gold {gold:.2f}"
        )

    # First reading dated from the record's d0; the 36.43 peak falls on the
    # 2017-07-13 duplicate (two readings share that date).
    assert trend.timestamps_utc[0].strftime("%Y-%m-%d") == "2013-02-28"
    assert trend.timestamps_utc[38].strftime("%Y-%m-%d") == "2017-07-13"
    assert float(trend.overall[38]) == pytest.approx(36.43, abs=0.02)


# AMS "Lista Ptos de Tendc" for DT-0070 M1P (Motor Lado Libre Peakvue),
# "Valore Globale (RMSAceleración en G-s)" — all 147 readings, top-to-bottom,
# 17-ene-13 .. 25-mar-26. Validated against the AMS export 2026-07-20 with a
# max deviation of 0.00005 (the report's own 4-decimal rounding): the raw
# vddt overall IS the plotted G's value, scale 1 (ADR-0014).
_M1P_TREND_GOLD_G = (
    0.2923, 0.6540, 0.2624, 0.2867, 0.2807, 0.2280, 0.0540, 0.1277,
    0.2544, 0.1094, 0.1601, 0.1191, 0.1613, 0.2423, 0.1125, 0.3773,
    0.3842, 0.0781, 0.2747, 0.9212, 0.5234, 0.1399, 0.1138, 0.0948,
    0.6105, 0.7677, 0.5187, 0.2928, 0.1938, 0.2448, 0.2438, 0.7515,
    0.6700, 0.5320, 0.3246, 0.2551, 0.0982, 0.1158, 0.1560, 0.1393,
    0.1655, 0.1480, 0.1384, 0.1378, 0.0854, 0.0984, 0.0795, 0.1034,
    0.0846, 0.0771, 0.0747, 0.1802, 0.0878, 0.0731, 0.0744, 0.0775,
    0.0667, 0.0739, 0.0698, 0.0730, 0.0720, 0.0906, 0.1130, 0.1014,
    0.1482, 0.0807, 0.0749, 0.0770, 0.0940, 0.0796, 0.1273, 0.1008,
    0.0840, 0.1186, 0.0712, 0.0798, 0.1198, 0.1706, 0.1850, 0.1832,
    0.1821, 0.1053, 0.2373, 0.3345, 0.2859, 0.1454, 0.1089, 0.3141,
    0.1822, 0.1107, 0.2327, 0.2111, 0.1119, 0.1384, 0.7271, 0.1468,
    0.1704, 0.1336, 0.2831, 0.1181, 0.1382, 0.3662, 0.2226, 0.1259,
    0.2541, 0.3750, 0.0652, 0.1662, 0.2602, 0.3314, 0.3639, 0.8158,
    0.3335, 0.2696, 0.1385, 0.7298, 0.2896, 0.7532, 0.2222, 0.4571,
    0.4829, 0.2021, 0.5526, 0.1421, 0.1352, 0.5340, 0.0975, 0.1003,
    0.5635, 0.0917, 0.0844, 0.0871, 0.0744, 0.0840, 0.0741, 0.0707,
    0.0772, 0.6053, 0.0353, 0.0213, 0.1021, 0.1225, 0.1522, 0.0596,
    0.1486, 0.0848, 0.1846,
)


def test_peakvue_trend_overall_matches_ams_gold(real_rbm: Path) -> None:
    # Acceleration (PeakVue) trends must reproduce the AMS "Lista Ptos de
    # Tendc" table exactly: the overall is raw G's, scale 1 — no x25.4.
    with RbmReader(real_rbm) as reader:
        point = next(
            p
            for area in walk_hierarchy(reader)
            if area.long_name.startswith("EXTRACCION")
            for eq in area.equipment
            if "DT-0070" in eq.long_name
            for p in eq.points
            if p.long_name == "Motor Lado Libre Peakvue"
        )
        trend = next(walk_trends(reader, point))

    assert trend.units == "G's"
    assert len(trend.overall) == len(_M1P_TREND_GOLD_G) == 147

    for i, gold in enumerate(_M1P_TREND_GOLD_G):
        assert float(trend.overall[i]) == pytest.approx(gold, abs=0.0001), (
            f"reading {i} ({trend.timestamps_utc[i]:%Y-%m-%d}): "
            f"decoded {float(trend.overall[i]):.4f} vs gold {gold:.4f}"
        )

    assert trend.timestamps_utc[0].strftime("%Y-%m-%d") == "2013-01-17"
    assert trend.timestamps_utc[-1].strftime("%Y-%m-%d") == "2026-03-25"
    # The series peak sits on 2014-08-05 (matches the AMS plot).
    assert trend.timestamps_utc[19].strftime("%Y-%m-%d") == "2014-08-05"

    # Overall thresholds from the "Peakvue HP 1kHz (P)" pdla set, in G's —
    # the ALERTA/Falla lines on the AMS plot.
    assert trend.alert == pytest.approx(1.5)
    assert trend.danger == pytest.approx(3.0)

    # The "Peakvue HP 1000 Hz (P)" template carries one band: Mp Wave, a raw
    # acceleration peak in G's with its own 8/12 G's thresholds.
    assert [b.name for b in trend.bands] == ["Mp Wave"]
    mp_wave = trend.bands[0]
    assert mp_wave.units == "G's"
    assert mp_wave.alert == pytest.approx(8.0)
    assert mp_wave.danger == pytest.approx(12.0)


def test_waveform_n_samples_is_the_stored_length_not_the_nominal(
    real_rbm: Path,
) -> None:
    # VibFrame requires n_samples == len(data). AMS stores `nominal - 150`
    # real samples rounded up to whole 244-sample vcfw records, so the two
    # never coincide: 512 -> 488 stored, 4096 -> 4148 (FORMAT §5.5).
    with RbmReader(real_rbm) as reader:
        points = [
            p
            for area in walk_hierarchy(reader)
            if "DEPURADORA" in area.long_name
            for eq in area.equipment
            if "AG-100" in eq.long_name
            for p in eq.points
        ]
        waveforms = [w for point in points for w in walk_waveforms(reader, point)]

    assert waveforms, "expected waveforms for AG-100"
    for w in waveforms:
        assert w.n_samples == w.samples.size
        assert w.nominal_n_samples is not None
        # Stored length: whole vcfw records covering the real payload.
        payload = w.nominal_n_samples - VDFW_TAIL_NOT_STORED
        expected = -(-payload // VCFW_DATA_SAMPLES) * VCFW_DATA_SAMPLES
        assert w.n_samples == expected
        # The tail past the payload is zero padding, never signal.
        assert not w.samples[payload:].any()


def test_velocity_waveform_calibrated_to_mm_s(real_rbm: Path) -> None:
    # Velocity waveforms (vdfw units plg/segs / in/sec) must be converted to
    # mm/s (x25.4), like the velocity FFT/trend — not leaked in inches/sec.
    with RbmReader(real_rbm) as reader:
        point = next(
            p
            for area in walk_hierarchy(reader)
            if "CONTRA INCENDIOS" in area.long_name
            for eq in area.equipment
            if "PM-0CI/1" in eq.long_name
            for p in eq.points
            if p.long_name == "MOTOR LOA HORIZONTAL"
        )
        waveforms = list(walk_waveforms(reader, point))

    assert waveforms, "expected velocity waveforms for this point"
    assert all(w.units == "mm/s" for w in waveforms)
    # Sanity: a calibrated velocity waveform peak is well above the raw in/s
    # magnitude (which would be < ~1); mm/s peaks are a few-to-tens.
    assert max(abs(float(w.samples.max())) for w in waveforms) > 1.0
