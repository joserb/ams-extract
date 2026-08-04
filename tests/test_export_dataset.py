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
    _add_proc_mode,
    _band_metric_row,
    _band_trend_rows,
    _build_machine_doc,
    _context_metric_row,
    _context_trend_rows,
    _metric_row,
    _spectrum_row,
    _trend_rows,
    _waveform_row,
    export_dataset,
)
from ams_extract.models import Equipment, Point, Spectrum, Trend, TrendBand, Waveform

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
        # Location levels only: the machine is its own level in the viewers.
        assert machine_doc["machine"]["path"] == ["AREA"]

    def test_point_docs_carry_the_placement_read_off_the_name(self) -> None:
        points = (
            Point(record_num=1, long_name="MOTOR LOA HORIZONTAL", short_code="M1H"),
            Point(record_num=2, long_name="Reductor Lado Libre Peakvue", short_code="R1P"),
            Point(record_num=3, long_name="Campana Peakvue", short_code="C1P"),
        )
        equipment = Equipment(record_num=4, long_name="BOMBA", short_code="PUMP", points=points)

        machine_doc = _build_machine_doc(
            source_path="fixture.rbm",
            extracted_at=datetime(2020, 1, 1, tzinfo=UTC),
            area_long="AREA",
            equipment=equipment,
            proc_modes=[],
        )

        assert [(p["location"], p["direction"]) for p in machine_doc["points"]] == [
            ("NDE", "H"),  # side and direction both declared
            ("NDE", None),  # PeakVue point: side only
            (None, None),  # neither: nothing is invented
        ]
        # The rest of the PointDoc has no counterpart in the .rbm.
        assert all(p["sensor"] is None and p["speed_source"] is None for p in machine_doc["points"])

    def test_wave_row_n_samples_matches_the_emitted_array(self) -> None:
        # VibFrame derives the time axis from t + i / sample_rate_hz, so
        # n_samples must be len(data); the AMS nominal block (512 for these
        # 488 stored samples) is documentary only (FORMAT §5.5, ADR-0017).
        point = Point(record_num=1, long_name="MOTOR", short_code="MOTOR")
        waveform = Waveform(
            record_num=3,
            point_record_num=point.record_num,
            timestamp_utc=datetime(2020, 1, 1, tzinfo=UTC),
            n_samples=488,
            sample_rate_hz=2_560.0,
            rpm=1_455.0,
            units="G's",
            carga_pct=0.0,
            samples=np.zeros(488, dtype=np.float32),
            nominal_n_samples=512,
        )

        row = _waveform_row(waveform, point)

        assert row["n_samples"] == len(row["data"]) == 488

    def test_wave_proc_mode_keeps_the_length_and_notes_the_nominal(self) -> None:
        modes: dict[tuple[str, str], dict[str, object]] = {}
        _add_proc_mode(
            modes,
            point_id="MOTOR",
            mode_id="WAVE_ACC_2560",
            signal_family="acceleration",
            sample_rate_hz=2_560.0,
            n_samples=488,
            nominal_n_samples=512,
        )
        _add_proc_mode(
            modes,
            point_id="MOTOR",
            mode_id="VEL_1000",
            signal_family="velocity",
            fmax_hz=1_000.0,
            lines=1_600,
        )

        wave_mode = modes[("MOTOR", "WAVE_ACC_2560")]
        assert wave_mode["n_samples"] == 488
        assert "512" in str(wave_mode["notes"]) and "488" in str(wave_mode["notes"])
        # Spectrum modes carry no sample count and keep the plain note.
        assert "acquisition block" not in str(modes[("MOTOR", "VEL_1000")]["notes"])

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


def _make_band(name: str, units: str, **kwargs) -> TrendBand:
    return TrendBand(
        name=name,
        units=units,
        timestamps_utc=(datetime(2020, 1, 1, tzinfo=UTC),),
        values=np.asarray([1.5], dtype=np.float32),
        **kwargs,
    )


class TestBandExport:
    point = Point(record_num=1, long_name="MOTOR LOA HORIZONTAL", short_code="M1H")

    def test_velocity_band_descriptor_with_order_bounds(self) -> None:
        # Bounds come from the point's pdpa template (FORMAT §5.8):
        # SUBSINCRONO is 0-0.7 shaft orders in the Estandar templates.
        band = _make_band("SUBSINCRONO", "mm/s", low_order=0.0, high_order=0.7)
        row = _band_metric_row(band, self.point)
        assert row["metric_id"] == "band_subsincrono__M1H"
        assert row["name"] == "SUBSINCRONO"
        assert row["path"] == "M1H:SUBSINCRONO"
        assert row["statistic"] == "spectrum_rms"
        assert row["detector"] == "rms"
        assert row["signal_family"] == "velocity"
        assert row["unit"] == "mm/s"
        assert row["band_type"] == "single"
        assert row["band_low_order"] == 0.0
        assert row["band_high_order"] == pytest.approx(0.7)
        assert row["band_low_hz"] is None
        assert row["band_high_hz"] is None

    def test_fixed_hz_band_descriptor(self) -> None:
        # FALLO ELECTRIC is a fixed 99.8-100.2 Hz band in the HR template.
        band = _make_band("FALLO ELECTRIC", "mm/s", low_hz=99.8, high_hz=100.2)
        row = _band_metric_row(band, self.point)
        assert row["band_type"] == "single"
        assert row["band_low_hz"] == pytest.approx(99.8)
        assert row["band_high_hz"] == pytest.approx(100.2)
        assert row["band_low_order"] is None
        assert row["band_high_order"] is None

    def test_band_without_resolved_bounds_has_band_type_none(self) -> None:
        row = _band_metric_row(_make_band("SUBSINCRONO", "mm/s"), self.point)
        assert row["band_type"] == "none"
        assert row["band_low_order"] is None

    def test_hf_acceleration_band_is_spectral_rms_not_peak(self) -> None:
        # "1 - 20 KHz" (tipo 0x04): RMS de aceleración con límites Hz fijos,
        # crudo en G's (validado contra captura AMS de PM-9101-A M1H).
        band = _make_band("1 - 20 KHz", "G's", low_hz=1000.0, high_hz=20000.0)
        row = _band_metric_row(band, self.point)
        assert row["metric_id"] == "band_1_20_khz__M1H"
        assert row["statistic"] == "spectrum_rms"
        assert row["detector"] == "rms"
        assert row["signal_family"] == "acceleration"
        assert row["unit"] == "g"
        assert row["band_type"] == "single"
        assert row["band_low_hz"] == 1000.0
        assert row["band_high_hz"] == 20000.0

    def test_mp_wave_is_an_acceleration_peak_not_a_band(self) -> None:
        row = _band_metric_row(_make_band("Mp Wave", "G's"), self.point)
        assert row["metric_id"] == "band_mp_wave__M1H"
        assert row["statistic"] == "true_peak"
        assert row["detector"] == "peak"
        assert row["signal_family"] == "acceleration"
        assert row["unit"] == "g"
        assert row["band_type"] == "none"

    def test_band_trend_rows(self) -> None:
        band = _make_band("HOLGURAS", "mm/s")
        rows = _band_trend_rows(band, self.point)
        assert len(rows) == 1
        assert rows[0]["metric_id"] == "band_holguras__M1H"
        assert rows[0]["value"] == pytest.approx(1.5)
        assert rows[0]["t"] == 1_577_836_800_000_000  # 2020-01-01 UTC in µs
        assert rows[0]["config_id"] == ""
        assert rows[0]["alarm"] is None  # no thresholds resolved

    def test_band_trend_rows_carry_derived_alarm(self) -> None:
        # alarm is DERIVED from the pdla thresholds (0/2/3), never read
        # from the undecoded per-slot flags (ADR-0012).
        band = _make_band("HOLGURAS", "mm/s", alert=1.4, danger=2.2, alarms=(2,))
        rows = _band_trend_rows(band, self.point)
        assert rows[0]["alarm"] == 2


def _make_trend(units: str) -> Trend:
    return Trend(
        record_num=10,
        point_record_num=1,
        units=units,
        timestamps_utc=(datetime(2020, 1, 1, tzinfo=UTC),),
        overall=np.asarray([0.5], dtype=np.float32),
    )


class TestTrendMetricDescriptor:
    def test_velocity_trend_descriptor(self) -> None:
        point = Point(record_num=1, long_name="MOTOR LOA HORIZONTAL", short_code="M1H")
        row = _metric_row(_make_trend("mm/s"), point)
        assert row["metric_id"] == "overall_velocity_rms__M1H"
        assert row["name"] == "overall_velocity_rms"
        assert row["path"] == "M1H:overall_velocity_rms"
        assert row["signal_family"] == "velocity"
        assert row["unit"] == "mm/s"

    def test_acceleration_trend_descriptor(self) -> None:
        # PeakVue/HF overall trends are raw G's (validated 147/147 against
        # the "Lista Ptos de Tendc" gold of DT-0070 M1P, ADR-0014).
        point = Point(
            record_num=1, long_name="Motor Lado Libre Peakvue", short_code="M1P"
        )
        trend = _make_trend("G's")
        row = _metric_row(trend, point)
        assert row["metric_id"] == "overall_acceleration_rms__M1P"
        assert row["name"] == "overall_acceleration_rms"
        assert row["path"] == "M1P:overall_acceleration_rms"
        assert row["signal_family"] == "acceleration"
        assert row["unit"] == "g"
        assert row["statistic"] == "spectrum_rms"
        assert row["detector"] == "rms"
        assert _trend_rows(trend, point)[0]["metric_id"] == (
            "overall_acceleration_rms__M1P"
        )


class TestContextMetrics:
    def test_speed_descriptor_is_machine_level_and_reserved(self) -> None:
        row = _context_metric_row("speed", "AG-100")
        assert row["metric_id"] == "speed"  # literal reserved id, no point suffix
        assert row["point_id"] is None
        assert row["name"] == "speed"
        assert row["path"] == "AG-100:speed"
        assert row["statistic"] == "value"
        assert row["signal_family"] == "non_vibration"
        assert row["unit"] == "Hz"
        assert row["band_type"] == "none"
        # Canonical labelling is a t8-mapper post-process (ADR-0011).
        assert row["canonical_metric"] is None
        assert row["proxy_quality"] is None
        assert row["mapping_rule"] is None

    def test_load_descriptor_unit_is_percent(self) -> None:
        row = _context_metric_row("load", "DT-0070")
        assert row["metric_id"] == "load"
        assert row["path"] == "DT-0070:load"
        assert row["unit"] == "%"
        assert row["point_id"] is None

    def test_speed_is_analysis_rpm_over_60_and_load_as_is(self) -> None:
        rows = _context_trend_rows([(1_000, 2920.0, 75.0)])
        by_metric = {r["metric_id"]: r for r in rows}
        assert by_metric["speed"]["value"] == pytest.approx(2920.0 / 60.0)
        assert by_metric["load"]["value"] == 75.0
        for row in rows:
            assert row["t"] == 1_000
            assert row["alarm"] is None
            assert row["config_id"] == ""

    def test_rpm_zero_or_negative_emits_no_speed_but_keeps_load(self) -> None:
        rows = _context_trend_rows([(1_000, 0.0, 0.0), (2_000, -1.0, 100.0)])
        assert [r["metric_id"] for r in rows] == ["load", "load"]
        # 0.0 and 100.0 are valid load readings, emitted as-is.
        assert [r["value"] for r in rows] == [0.0, 100.0]

    def test_exact_duplicates_collapse_across_captures(self) -> None:
        # Spectrum and waveform of the same point/timestamp share the rpm:
        # one reading per (t, metric, value), not per capture.
        capture = (1_000, 1500.0, 50.0)
        rows = _context_trend_rows([capture, capture])
        assert len(rows) == 2
        assert {r["metric_id"] for r in rows} == {"speed", "load"}

    def test_distinct_values_at_same_timestamp_are_kept(self) -> None:
        # Analysis RPM can differ between captures (ADR-0013): keep both.
        rows = _context_trend_rows([(1_000, 2920.0, 50.0), (1_000, 1455.0, 50.0)])
        speeds = sorted(r["value"] for r in rows if r["metric_id"] == "speed")
        assert speeds == [pytest.approx(1455.0 / 60.0), pytest.approx(2920.0 / 60.0)]
        assert sum(1 for r in rows if r["metric_id"] == "load") == 1


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
