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
    PROC_MODE_NOTES,
    MetricCatalogCollisionError,
    ModeRegistry,
    _band_metric_row,
    _band_trend_rows,
    _build_machine_doc,
    _context_metric_row,
    _context_trend_rows,
    _insert_metric_row,
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
            mode_definitions=[],
            mode_bindings=[],
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
            mode_definitions=[],
            mode_bindings=[],
        )

        assert [(p["location"], p["direction"]) for p in machine_doc["points"]] == [
            ("NDE", "H"),  # side and direction both declared
            ("NDE", None),  # PeakVue point: side only
            (None, None),  # neither: nothing is invented
        ]
        # The rest of the PointDoc has no counterpart in the .rbm.
        assert all(p["sensor"] is None and p["speed_source"] is None for p in machine_doc["points"])

    def test_point_docs_carry_the_shaft_config_the_rbm_declares(self) -> None:
        # vdpm.0x07E / 0x164 go out verbatim: the free text the analyst typed
        # and the speed as stored, in RPM. Normalizing designations against a
        # catalogue belongs to the enricher, not to this extractor.
        points = (
            Point(
                record_num=1,
                long_name="MOTOR LOA HORIZONTAL",
                short_code="M1H",
                bearing_designations=("6204", "6208"),
                nominal_speed_rpm=1_455.0,
            ),
            Point(
                record_num=2,
                long_name="Reductor Lado Libre Peakvue",
                short_code="R1P",
                bearing_designations=("SKF 6308", "22218 EKC3", "RED"),
                nominal_speed_rpm=9.6,
            ),
            Point(record_num=3, long_name="Campana Peakvue", short_code="C1P"),
        )
        equipment = Equipment(record_num=4, long_name="BOMBA", short_code="PUMP", points=points)

        machine_doc = _build_machine_doc(
            source_path="fixture.rbm",
            extracted_at=datetime(2020, 1, 1, tzinfo=UTC),
            area_long="AREA",
            equipment=equipment,
            mode_definitions=[],
            mode_bindings=[],
        )

        docs = machine_doc["points"]
        assert [p["bearing_designations"] for p in docs] == [
            ["6204", "6208"],  # slot order preserved
            ["SKF 6308", "22218 EKC3", "RED"],  # maker, suffix and non-designation, untouched
            [],  # a point that declares none emits an empty list, not null
        ]
        assert [p["nominal_speed_rpm"] for p in docs] == [1_455.0, 9.6, None]
        # Unknown speed is null, never 0: a zero would read as a stopped shaft.
        assert docs[2]["nominal_speed_rpm"] is None
        # AMS declares the fields; it does not resolve them into a definition,
        # so the machine carries no definition and no provenance for one.
        assert machine_doc["machine"]["definition"] is None
        assert "definition_provenance" not in machine_doc["machine"]

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

    def test_mode_registry_defines_by_effective_shape_and_notes_the_nominal(self) -> None:
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
        spectrum = Spectrum(
            record_num=2,
            point_record_num=point.record_num,
            timestamp_utc=datetime(2020, 1, 1, tzinfo=UTC),
            fmax_hz=1_000.0,
            n_lines=1_600,
            units="mm/s",
            rpm=1_455.0,
            carga_pct=0.0,
            amplitude=np.zeros(1_600, dtype=np.float32),
        )

        modes = ModeRegistry()
        wave_id = modes.waveform_mode(waveform, point)
        spec_id = modes.spectrum_mode(spectrum, point)

        definitions = {d["definition_id"]: d for d in modes.mode_definitions()}
        assert wave_id.startswith("md-") and spec_id.startswith("md-")
        # AMS blocks are waveform-only or spectrum-only; the emitted length is
        # the definition's, and the nominal AMS block lives in the binding note.
        assert definitions[wave_id]["waveform"]["n_samples"] == 488
        assert "spectrum" not in definitions[wave_id]
        assert definitions[spec_id]["spectrum"]["lines"] == 1_600
        assert "waveform" not in definitions[spec_id]
        bindings = {b["proc_mode_id"]: b for b in modes.mode_bindings()}
        wave_binding = bindings["WAVE_ACC_2560"]
        assert wave_binding["definition_id"] == wave_id
        assert "512" in wave_binding["notes"] and "488" in wave_binding["notes"]
        assert bindings["VEL_1000"]["notes"] == PROC_MODE_NOTES

    def test_mode_registry_splits_the_same_tag_by_effective_shape(self) -> None:
        # The AMS multi-shape case (workplan 08 §6-d): the synthetic tag stays
        # verbatim and every shape gets its own definition and binding.
        point = Point(record_num=1, long_name="MOTOR", short_code="MOTOR")

        def _spectrum(lines: int) -> Spectrum:
            return Spectrum(
                record_num=2,
                point_record_num=point.record_num,
                timestamp_utc=datetime(2020, 1, 1, tzinfo=UTC),
                fmax_hz=2_000.0,
                n_lines=lines,
                units="mm/s",
                rpm=1_455.0,
                carga_pct=0.0,
                amplitude=np.zeros(lines, dtype=np.float32),
            )

        modes = ModeRegistry()
        ids = {modes.spectrum_mode(_spectrum(lines), point) for lines in (1_600, 3_200, 6_400)}
        assert len(ids) == 3
        assert modes.spectrum_mode(_spectrum(1_600), point) in ids  # dedup by shape
        bindings = modes.mode_bindings()
        assert len(bindings) == 3
        assert {b["proc_mode_id"] for b in bindings} == {"VEL_2000"}
        assert {b["definition_id"] for b in bindings} == ids
        assert len(modes.mode_definitions()) == 3

    def test_machine_doc_validates_against_optional_vibframe_contract(self) -> None:
        contracts = pytest.importorskip("vibsynth_contracts.dataset")
        point = Point(
            record_num=1,
            long_name="MOTOR",
            short_code="MOTOR",
            bearing_designations=("SKF 6308",),
            nominal_speed_rpm=1_455.0,
        )
        equipment = Equipment(record_num=2, long_name="BOMBA", short_code="PUMP", points=(point,))
        document = _build_machine_doc(
            source_path="fixture.rbm",
            extracted_at=datetime(2020, 1, 1, tzinfo=UTC),
            area_long="AREA",
            equipment=equipment,
            mode_definitions=[],
            mode_bindings=[],
        )

        doc = contracts.MachineDoc.model_validate(document)

        # The contract keeps the shaft config as declared (PointDoc fields of
        # vibsynth-contracts workplan 04): nothing is normalized on the way in.
        assert doc.points[0].bearing_designations == ["SKF 6308"]
        assert doc.points[0].nominal_speed_rpm == 1_455.0

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
        assert document["schema_version"] == "0.2.0"
        assert document["generator"].startswith("ams-extract")
        # Nobody said where the dataset hangs, so nothing is claimed: an
        # absent `path` and `path: []` say different things.
        assert "path" not in document

        # No equipment in the synthetic fixture -> nothing to export.
        assert summary.areas == 5
        assert summary.equipment_total == 0
        assert summary.fft_samples == 0
        assert summary.waveform_samples == 0
        assert summary.parquet_files == 0

    def test_dataset_path_survives_a_re_export(
        self, synthetic_rbm: Path, tmp_path: Path
    ) -> None:
        """The grouping level above the dataset, emitted instead of restored.

        Before this, ``dataset.json:path`` was typed in by whoever curated the
        dataset and every re-export wiped it (workplan 08).
        """
        out = tmp_path / "dataset"
        for _ in range(2):
            export_dataset(
                synthetic_rbm,
                out,
                types={"fft"},
                dataset_path=["Bunge Cartagena"],
                show_progress=False,
            )
            document = json.loads((out / "dataset.json").read_text(encoding="utf-8"))
            assert document["path"] == ["Bunge Cartagena"]

    def test_dataset_path_keeps_the_order_of_the_levels(
        self, synthetic_rbm: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "dataset"
        export_dataset(
            synthetic_rbm,
            out,
            types={"fft"},
            dataset_path=("Bunge", "Cartagena"),
            show_progress=False,
        )
        document = json.loads((out / "dataset.json").read_text(encoding="utf-8"))
        # Outermost first, and composed with MachineInfo.path downstream.
        assert document["path"] == ["Bunge", "Cartagena"]
        contracts = pytest.importorskip("vibsynth_contracts.dataset")
        assert contracts.DatasetInfo.model_validate(document).path == ["Bunge", "Cartagena"]

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


class TestMetricCatalogConsolidation:
    point = Point(record_num=1, long_name="MOTOR LOA HORIZONTAL", short_code="M1H")

    def test_rejects_same_slug_with_different_band_calculation(self) -> None:
        # The raw tag, its slug and mapper label all collide, but the bands
        # are different calculations and must never silently overwrite each
        # other.
        first = _band_metric_row(
            _make_band("SUBSINCRONO", "mm/s", low_order=0.0, high_order=0.7),
            self.point,
        )
        second = _band_metric_row(
            _make_band("SUBSINCRONO", "mm/s", low_order=0.7, high_order=1.0),
            self.point,
        )
        second["canonical_metric"] = first["canonical_metric"] = "same-tag"

        rows: dict[tuple[str, str], dict[str, object]] = {}
        _insert_metric_row(rows, first)

        with pytest.raises(
            MetricCatalogCollisionError,
            match=r"band_low_order.*band_high_order",
        ) as exc_info:
            _insert_metric_row(rows, second)

        message = str(exc_info.value)
        assert "band_subsincrono__M1H" in message
        assert "config_id=''" in message
        assert rows[(first["metric_id"], first["config_id"])] is first

    def test_deduplicates_identical_calculation_despite_label_and_mapper_changes(self) -> None:
        first = _band_metric_row(
            _make_band("Sub-síncrono", "mm/s", low_order=0.0, high_order=0.7),
            self.point,
        )
        duplicate = _band_metric_row(
            _make_band("Sub síncrono", "mm/s", low_order=0.0, high_order=0.7),
            self.point,
        )
        duplicate.update(
            name="different source tag",
            path="different:human:path",
            canonical_metric="velocity_band",
            proxy_quality="direct",
            mapping_rule="TEST",
        )
        # These three fields are set-like in MetricDescriptor. Reordering them
        # (including repeated values) cannot create a second calculation.
        first.update(
            harmonic_orders=[1, 2, 2],
            additional_frequency_refs=["gear", "shaft", "gear"],
            flags=["reversed", "multi_band", "reversed"],
        )
        duplicate.update(
            harmonic_orders=[2, 1, 2],
            additional_frequency_refs=["gear", "gear", "shaft"],
            flags=["multi_band", "reversed", "reversed"],
        )
        # Missing means the MetricDescriptor default, not a different
        # calculation from the explicit false emitted by AMS today.
        duplicate.pop("integrate")

        rows: dict[tuple[str, str], dict[str, object]] = {}
        _insert_metric_row(rows, first)
        _insert_metric_row(rows, duplicate)

        assert list(rows.values()) == [first]


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

    def test_export_keeps_curated_sidecars(self, synthetic_rbm: Path, tmp_path: Path) -> None:
        """VibFrame forbids deleting ``ground-truth/`` and ``analysis/``."""
        out = tmp_path / "dataset"
        (out / "ground-truth").mkdir(parents=True)
        (out / "analysis" / "diaggt-contrast").mkdir(parents=True)
        labels = out / "ground-truth" / "informe.diaggt.json"
        labels.write_text('{"observations": []}', encoding="utf-8")
        layer = out / "analysis" / "diaggt-contrast" / "layer.json"
        layer.write_text('{"layer_id": "diaggt-contrast"}', encoding="utf-8")
        stale = out / "machine=GONE"
        stale.mkdir()
        (stale / "machine.json").write_text("{}", encoding="utf-8")

        result = runner.invoke(
            rbm_app,
            ["export", str(synthetic_rbm), "--out", str(out), "--types", "fft"],
        )
        assert result.exit_code == 0, result.output
        assert (out / "dataset.json").exists()
        assert labels.read_text(encoding="utf-8") == '{"observations": []}'
        assert layer.read_text(encoding="utf-8") == '{"layer_id": "diaggt-contrast"}'
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
