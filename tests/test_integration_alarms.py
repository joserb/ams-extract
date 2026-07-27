"""Integration tests for the alarm notes and their DiagGT export.

Gated on ``RBM_TEST_FILE``. Locks the BUNGE numbers registered in
``docs/VERIFICATION.md`` (FORMAT §5.9): 4 970 notes over 5 203 points,
991 alarms, **991/991 coherent** with the point's ``pdla`` thresholds and
973 emitted as ground truth (18 skipped for a unit-code disagreement).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ams_extract.cli import app as rbm_app
from ams_extract.export.diag_gt import build_alarm_ground_truth
from ams_extract.reader import RbmReader
from ams_extract.records.pdpa import ParamSetIndex
from ams_extract.tree import walk_alarm_note, walk_hierarchy

pytestmark = pytest.mark.integration

runner = CliRunner()

EXPECTED_NOTES = 4_970
EXPECTED_ALARMS = 991
EXPECTED_EMITTED = 973
EXPECTED_UNIT_MISMATCH = 18
EXPECTED_MACHINES = 235
EXPECTED_ALERT = 461
EXPECTED_DANGER = 512


class TestAlarmNotesOnRealFile:
    def test_m1h_note_matches_its_pdla_thresholds(self, real_rbm: Path) -> None:
        with RbmReader(real_rbm) as reader:
            param_sets = ParamSetIndex.load(reader)
            point = next(
                p
                for area in walk_hierarchy(reader)
                for equipment in area.equipment
                if "AG-100" in equipment.long_name
                for p in equipment.points
                if p.long_name == "MOTOR LOA HORIZONTAL"
            )
            note = walk_alarm_note(reader, point, param_sets)
        assert note is not None
        # M1H's stored verdict is the calm one, dated by its last sample
        # (2020-02-19, the gold spectrum of FORMAT §5.3).
        assert not note.in_alarm
        assert note.severity == 0
        assert note.text.splitlines()[-1] == "NO en Alarma"
        assert note.measured_at_utc is not None
        assert note.measured_at_utc.date().isoformat() == "2020-02-19"

    def test_every_parsed_alarm_agrees_with_its_thresholds(self, real_rbm: Path) -> None:
        notes = alarms = coherent = unit_mismatch = severity_agreement = 0
        with RbmReader(real_rbm) as reader:
            param_sets = ParamSetIndex.load(reader)
            for area in walk_hierarchy(reader):
                for equipment in area.equipment:
                    for point in equipment.points:
                        note = walk_alarm_note(reader, point, param_sets)
                        if note is None:
                            continue
                        notes += 1
                        if not note.in_alarm:
                            continue
                        alarms += 1
                        coherent += int(note.coherent is True)
                        unit_mismatch += int(not note.unit_consistent)
                        severity_agreement += int(note.severity_level == note.level)
        assert notes == EXPECTED_NOTES
        assert alarms == EXPECTED_ALARMS
        # The cross-check that validates the decode: the value of every
        # alarm falls where its C/D level says it should.
        assert coherent == EXPECTED_ALARMS
        # And the severity index agrees with the level parsed from the text.
        assert severity_agreement == EXPECTED_ALARMS
        assert unit_mismatch == EXPECTED_UNIT_MISMATCH


class TestAlarmGroundTruthOnRealFile:
    def test_document_counts_and_validity(self, real_rbm: Path) -> None:
        with RbmReader(real_rbm) as reader:
            document, summary = build_alarm_ground_truth(
                reader, source_path=real_rbm, client="BUNGE", plant="CARTAGENA"
            )
        assert summary.alarms == EXPECTED_ALARMS
        assert summary.emitted == EXPECTED_EMITTED
        assert summary.skipped_unit_mismatch == EXPECTED_UNIT_MISMATCH
        assert summary.skipped_incoherent == 0
        assert summary.coherent_pct == pytest.approx(100.0)
        assert summary.machines == EXPECTED_MACHINES
        assert (summary.alert, summary.danger) == (EXPECTED_ALERT, EXPECTED_DANGER)
        assert document["provenance"]["origin"] == "system-alarm"
        assert len(document["observations"]) == EXPECTED_EMITTED
        # Every observation resolves to a machine= partition of the export.
        assert all(
            obs["machine"]["dataset_machine_id"] for obs in document["observations"]
        )

        external = pytest.importorskip("vibsynth_contracts.diagnosis.external")
        parsed = external.DiagGTDocument.model_validate(document)
        assert len(parsed.observations) == EXPECTED_EMITTED

    def test_cli_writes_the_document(self, real_rbm: Path, tmp_path: Path) -> None:
        result = runner.invoke(
            rbm_app,
            [
                "--log-level",
                "error",
                "alarms",
                str(real_rbm),
                "--out",
                str(tmp_path),
                "--name",
                "alarms",
                "--skip-hash",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads((tmp_path / "alarms.diaggt.json").read_text(encoding="utf-8"))
        assert len(payload["observations"]) == EXPECTED_EMITTED
        assert payload["provenance"]["source_sha256"] is None
