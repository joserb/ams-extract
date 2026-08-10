"""Tests for the DiagGT export of AMS's stored alarms (``rbm alarms``).

Covers the TAG extraction, the status/finding mapping and the shape of the
document, and validates it against the normative Pydantic models of
vibsynth-contracts when they are installed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ams_extract.export.diag_gt import (
    DIAGGT_FILE_SUFFIX,
    DIAGGT_SCHEMA_VERSION,
    EXTRACTION_METHOD,
    _findings,
    _observation,
    machine_tag,
    normalize_tag,
    write_alarm_ground_truth,
)
from ams_extract.models import AlarmNote, Area, Equipment, Point

AREA = Area(
    record_num=69,
    slot_index=0,
    long_name="DEPURADORA",
    short_code="DEPURADORA",
)
EQUIPMENT = Equipment(
    record_num=300,
    long_name="MECLADOR AGITADOR AG-100",
    short_code="MECLADOR_AGITADOR_AG_100",
)
POINT = Point(record_num=301, long_name="MOTOR LOA HORIZONTAL", short_code="M1H")


def _note(**overrides: object) -> AlarmNote:
    base = {
        "point_record_num": POINT.record_num,
        "record_num": 336_985,
        "status_record_num": 336_983,
        "measured_at_utc": datetime(2020, 2, 19, 7, 23, 54, tzinfo=UTC),
        "severity": 15,
        "user": "Administrator",
        "text": "Stored Parameter Analysis\nSUBSINCRONO - 1.986 mm/Seg -  C Alarm",
        "band": "SUBSINCRONO",
        "value": 1.986,
        "units": "mm/s",
        "level": "C",
        "alert": 1.4,
        "danger": 2.2,
        "limit_set": "Motor Horizontal P<300 kW (S)",
        "unit_consistent": True,
        "coherent": True,
    }
    base.update(overrides)
    return AlarmNote(**base)  # type: ignore[arg-type]


class TestMachineTag:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("MECLADOR AGITADOR AG-100", "AG-100"),
            ("Bomba Centrifuga PM-0CI/1", "PM-0CI/1"),
            ("TRANSPORTE BANDA TB-1105-A", "TB-1105-A"),
            ("Bomba Centrifuga PM-0001.1", "PM-0001.1"),
            ("AGITADOR AG.9764 A", "AG.9764 A"),
            ("MEZCLADOR", None),
            ("AGITADOR", None),
        ],
    )
    def test_extracts_the_plant_tag(self, name: str, expected: str | None) -> None:
        assert machine_tag(name) == expected

    def test_normalization_matches_the_report_crosswalk(self) -> None:
        # The analyst reports write "AG.100" and AMS "AG-100": the
        # normalized form is the join key of both ground truths.
        assert normalize_tag("AG-100") == normalize_tag("AG.100") == "AG100"
        assert normalize_tag("PM-0CI/1") == "PM0CI1"


class TestFindings:
    def test_fault_named_band_maps_weakly(self) -> None:
        findings = _findings(_note(band="DESEQUILIBRIO"))
        assert len(findings) == 1
        assert findings[0]["fault_mode"] == "IMBALANCE"
        assert findings[0]["fault_group"] == "IMBALANCE"
        assert findings[0]["label_quality"] == "weak"
        assert findings[0]["mapping_rule"] == "GT050"

    def test_group_only_band_leaves_the_mode_null(self) -> None:
        findings = _findings(_note(band="DESALINEACION"))
        assert findings[0]["fault_mode"] is None
        assert findings[0]["fault_group"] == "MISALIGNMENT"
        assert findings[0]["label_quality"] == "group"

    def test_bands_without_fault_semantics_are_unmapped_not_dropped(self) -> None:
        for band in ("SUBSINCRONO", "OVERALL VALUE", "Mp Wave", "1 - 20 KHz"):
            findings = _findings(_note(band=band))
            assert len(findings) == 1
            assert findings[0]["fault_group"] == "UNMAPPED"
            assert findings[0]["label_quality"] == "unmapped"
            assert findings[0]["matched_text"] == band


class TestObservation:
    def test_alert_observation_carries_verbatim_and_ids(self) -> None:
        observation = _observation(AREA, EQUIPMENT, POINT, _note(), "ams-gdnl:BUNGE")
        assert observation is not None
        assert observation["status"] == "ALERT"
        assert observation["alarm"] == 2
        assert observation["status_source_label"] == "C Alarm"
        assert observation["observed_at"] == "2020-02-19"
        assert observation["record_kind"] == "primary"
        assert observation["diagnosis_text"].endswith("SUBSINCRONO - 1.986 mm/Seg -  C Alarm")
        assert observation["machine"]["external_tag"] == "AG-100"
        assert observation["machine"]["normalized_tag"] == "AG100"
        assert observation["machine"]["dataset_machine_id"] == "MECLADOR_AGITADOR_AG_100"
        assert observation["observation_id"] == (
            "ams-gdnl:BUNGE:MECLADOR_AGITADOR_AG_100:M1H:vibration:2020-02-19"
        )
        assert "1.4" in observation["analysis_text"]
        assert "M1H" in observation["analysis_text"]

    def test_danger_maps_to_alarm_three(self) -> None:
        note = _note(level="D", severity=55, value=3.5, alert=1.4, danger=2.2)
        observation = _observation(AREA, EQUIPMENT, POINT, note, "doc")
        assert observation is not None
        assert observation["status"] == "DANGER"
        assert observation["alarm"] == 3

    def test_note_without_date_is_not_emitted(self) -> None:
        assert _observation(AREA, EQUIPMENT, POINT, _note(measured_at_utc=None), "d") is None


def _document(observations: list[dict[str, object]]) -> dict[str, object]:
    return {
        "$schema_version": DIAGGT_SCHEMA_VERSION,
        "kind": "diagnosis_ground_truth",
        "provenance": {
            "origin": "system-alarm",
            "provider": "AMS Machinery Manager (Emerson)",
            "document_id": "ams-gdnl:BUNGE",
            "document_title": "Alarmas almacenadas por AMS",
            "source_ref": "BUNGE.rbm",
            "source_sha256": "a" * 64,
            "client": "BUNGE",
            "plant": "CARTAGENA",
            "inspection_date": None,
            "measurement_period": {"from": "2020-02-19", "to": "2020-02-19"},
            "routes": [],
            "analysts": [],
            "reviewers": [],
            "extractor": "ams-extract 0.0.0",
            "extracted_at": "2026-07-27T00:00:00Z",
            "extraction_method": EXTRACTION_METHOD,
        },
        "machines_stopped": [],
        "machines_not_measured": [],
        "observations": observations,
    }


class TestDocument:
    def test_validates_against_the_contracts_models(self) -> None:
        external = pytest.importorskip("vibsynth_contracts.diagnosis.external")
        observation = _observation(AREA, EQUIPMENT, POINT, _note(), "ams-gdnl:BUNGE")
        assert observation is not None
        document = external.DiagGTDocument.model_validate(_document([observation]))
        assert document.provenance.origin == "system-alarm"
        # Spec 0.1.2: decoding the gdnl record is a deterministic read of a
        # structured source, not a parse of free text.
        assert document.provenance.extraction_method == "structured_read"
        assert len(document.observations) == 1
        emitted = document.observations[0]
        assert emitted.status == "ALERT"
        assert emitted.alarm == external.STATUS_ALARM["ALERT"]
        assert emitted.dataset_machine_id == "MECLADOR_AGITADOR_AG_100"

    def test_writes_only_the_document(self, tmp_path: Path) -> None:
        # Since 0.2 the system-alarm family consolidates into the same
        # normative projections as everyone else (origin column keeps the
        # judgements apart); no observations_system.* side files are emitted.
        observation = _observation(AREA, EQUIPMENT, POINT, _note(), "ams-gdnl:BUNGE")
        assert observation is not None
        document = _document([observation])
        written = write_alarm_ground_truth(document, tmp_path, stem="BUNGE")
        assert written == [tmp_path / f"BUNGE{DIAGGT_FILE_SUFFIX}"]
        assert not (tmp_path / "observations_system.parquet").exists()
        assert not (tmp_path / "observations_system.csv").exists()
        reloaded = json.loads(written[0].read_text(encoding="utf-8"))
        assert reloaded["provenance"]["origin"] == "system-alarm"
        assert len(reloaded["observations"]) == 1

    def test_the_document_materializes_through_the_shared_projections(
        self, tmp_path: Path
    ) -> None:
        import pyarrow.parquet as pq

        from ams_extract.informes.consolidate import materialize_ground_truth

        observation = _observation(AREA, EQUIPMENT, POINT, _note(), "ams-gdnl:BUNGE")
        assert observation is not None
        write_alarm_ground_truth(_document([observation]), tmp_path, stem="BUNGE")
        summary = materialize_ground_truth(tmp_path)
        assert summary.observations == 1
        table = pq.read_table(tmp_path / "observations.parquet")
        row = table.to_pylist()[0]
        assert row["origin"] == "system-alarm"
        assert row["dataset_machine_id"] == "MECLADOR_AGITADOR_AG_100"
        assert row["alarm"] == 2
        assert row["n_findings"] == 1
        findings = pq.read_table(tmp_path / "findings.parquet").to_pylist()
        assert [f["fault_group"] for f in findings] == ["UNMAPPED"]
