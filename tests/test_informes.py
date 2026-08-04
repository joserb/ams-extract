"""Tests for the DiagGT extractor of inspection reports (``rbm informes``).

The regression fixture ``informes_gt_findings.json`` is the distillate of the
6 BUNGE 2026 documents emitted on 2026-07-28 by the standalone script
(``informes-gt-extract 0.2.0``): every distinct ``diagnosis_text`` of the
corpus with the findings that version gave it. The PDFs (49-73 MB) and the
5,8 MB of JSON stay out of the repo; what is protected here is the layer this
package owns — the mapping — text by text.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from ams_extract.informes.consolidate import (
    OBSERVATION_COLUMNS,
    observation_rows,
    read_crosswalk,
    write_observations,
)
from ams_extract.informes.rules import (
    FINDING_RULES,
    clauses,
    map_findings,
    map_status,
    norm_tag,
    status_from_text,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FINDING_KEYS = ("matched_text", "fault_mode", "fault_group", "label_quality", "mapping_rule")


def _signature(finding: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(finding[key] for key in FINDING_KEYS)


@pytest.fixture(scope="module")
def regression_cases() -> list[dict[str, Any]]:
    fixture = FIXTURES_DIR / "informes_gt_findings.json"
    return json.loads(fixture.read_text(encoding="utf-8"))["cases"]


class TestVocabulary:
    def test_status_labels_project_to_the_vibframe_alarm_scale(self) -> None:
        assert map_status("Bueno") == ("OK", 0)
        assert map_status("Seguimiento") == ("WATCH", 1)
        assert map_status("Alerta") == ("ALERT", 2)
        assert map_status("Peligro") == ("DANGER", 3)
        assert map_status("Parada") == ("STOPPED", None)
        assert map_status("") == ("UNKNOWN", None)

    def test_tag_normalization_matches_the_alarm_ground_truth(self) -> None:
        assert norm_tag("AG.100") == "AG100"
        assert norm_tag("PM-0CI/1") == "PM0CI1"

    def test_every_rule_id_lives_in_the_gt_namespace(self) -> None:
        assert [rule[0] for rule in FINDING_RULES] == sorted(r[0] for r in FINDING_RULES)
        assert all(rule[0].startswith("GT") for rule in FINDING_RULES)

    def test_group_quality_implies_no_concrete_mode(self) -> None:
        # Invariant of the normative model (DiagGTFinding): "group" declares
        # that the source does not name a mode, so fault_mode must be null.
        for _rule, _pattern, fault_mode, _group, quality in FINDING_RULES:
            assert (quality == "group") == (fault_mode is None)


class TestClauses:
    def test_the_analyst_writes_a_list_of_clauses(self) -> None:
        assert clauses("-Falta de rigidez. -Rodamientos en buen estado.") == [
            "Falta de rigidez",
            "Rodamientos en buen estado",
        ]

    def test_a_text_of_only_status_clauses_declares_status(self) -> None:
        assert status_from_text("Máquina parada") == ("STOPPED", None)
        assert status_from_text("Equipo en buen estado") == ("OK", 0)

    def test_one_fault_clause_is_enough_to_lose_the_status(self) -> None:
        # v0.1 searched the whole text and a healthy clause threw away the
        # faults of the others (spec §3.3).
        assert status_from_text("-Falta de rigidez. -Rodamientos en buen estado.") is None


class TestMapFindings:
    def test_healthy_text_produces_no_finding(self) -> None:
        assert map_findings("Máquina en buen estado") == []
        assert map_findings("") == []

    def test_fault_text_carries_the_rule_and_the_verbatim(self) -> None:
        findings = map_findings("Desequilibrio del ventilador")
        assert len(findings) == 1
        assert findings[0]["mapping_rule"] == "GT001"
        assert findings[0]["fault_mode"] == "IMBALANCE"
        assert findings[0]["label_quality"] == "direct"
        assert findings[0]["source_text"] == "Desequilibrio del ventilador"

    def test_unrecognized_fault_text_is_declared_not_dropped(self) -> None:
        findings = map_findings("Posible suciedad en la válvula")
        assert [f["fault_group"] for f in findings] == ["UNMAPPED"]
        assert findings[0]["label_quality"] == "unmapped"
        assert findings[0]["mapping_rule"] is None


class TestRegressionAgainstTheStandaloneScript:
    def test_the_corpus_is_the_one_that_was_emitted(
        self, regression_cases: list[dict[str, Any]]
    ) -> None:
        assert len(regression_cases) == 251
        assert sum(case["observations"] for case in regression_cases) == 6_669

    def test_every_diagnosis_text_maps_the_way_it_did(
        self, regression_cases: list[dict[str, Any]]
    ) -> None:
        differences: list[str] = []
        for case in regression_cases:
            text = case["diagnosis_text"] or ""
            expected = [tuple(f[key] for key in FINDING_KEYS) for f in case["findings"]]
            got = [_signature(f) for f in map_findings(text)]
            if got != expected:
                differences.append(f"{text!r}\n  was {expected}\n  now {got}")
        assert not differences, "\n".join(differences)

    def test_the_source_text_is_the_verbatim_of_the_diagnosis(
        self, regression_cases: list[dict[str, Any]]
    ) -> None:
        for case in regression_cases:
            text = case["diagnosis_text"] or ""
            for finding in map_findings(text):
                assert finding["source_text"] == text.strip()


def _document(observations: list[dict[str, Any]], **provenance: Any) -> dict[str, Any]:
    base = {
        "document_id": "P25/81115-260126",
        "inspection_date": "2026-01-26",
        "origin": "inspection-report",
    }
    base.update(provenance)
    return {"provenance": base, "observations": observations}


def _observation(**overrides: Any) -> dict[str, Any]:
    observation: dict[str, Any] = {
        "observation_id": "P2581115260126:AG100:vibration",
        "record_kind": "primary",
        "machine": {
            "external_tag": "AG.100",
            "external_name": "MECLADOR AGITADOR",
            "normalized_tag": "AG100",
            "area_code": "DEP",
            "area_name": "DEPURADORA",
            "dataset_machine_id": None,
        },
        "modality": "vibration",
        "observed_at": "2026-01-26",
        "status": "ALERT",
        "status_source_label": "Alerta",
        "alarm": 2,
        "global_status_label": "ALERTA",
        "diagnosis_text": "Desequilibrio del ventilador",
        "analysis_text": None,
        "recommendation_text": None,
        "findings": map_findings("Desequilibrio del ventilador"),
        "operating_context": {"rpm1": 1485.0, "rpm2": None, "power_kw": 7.5},
        "source_page": 26,
    }
    observation.update(overrides)
    return observation


class TestConsolidation:
    def test_row_carries_the_flat_multilabel_and_the_context(self) -> None:
        rows = observation_rows([_document([_observation()])])
        assert len(rows) == 1
        row = rows[0]
        assert set(OBSERVATION_COLUMNS) <= set(row)
        assert row["fault_modes"] == "IMBALANCE"
        assert row["fault_groups"] == "IMBALANCE"
        assert row["alarm"] == 2
        assert row["rpm1"] == 1485.0
        assert row["dataset_machine_id"] is None

    def test_unmapped_never_reaches_the_flat_fault_groups(self) -> None:
        rows = observation_rows(
            [
                _document(
                    [
                        _observation(
                            diagnosis_text="Ruido raro",
                            findings=map_findings("Ruido raro"),
                        )
                    ]
                )
            ]
        )
        assert rows[0]["fault_groups"] is None
        assert rows[0]["fault_modes"] is None

    def test_primary_wins_over_a_retrospective_of_the_same_key(self) -> None:
        retrospective = _observation(
            observation_id="X:AG100:vibration:2026-01-26",
            record_kind="retrospective",
            status="UNKNOWN",
            diagnosis_text="Máquina parada",
            findings=[],
            operating_context=None,
        )
        rows = observation_rows([_document([retrospective, _observation()])])
        assert len(rows) == 1
        assert rows[0]["record_kind"] == "primary"

    def test_between_retrospectives_the_latest_report_wins(self) -> None:
        old = _document(
            [
                _observation(
                    record_kind="retrospective",
                    diagnosis_text="Desequilibrio del ventilador",
                    status="UNKNOWN",
                )
            ],
            document_id="P25/81115-260126",
            inspection_date="2026-01-26",
        )
        new = _document(
            [
                _observation(
                    record_kind="retrospective",
                    diagnosis_text="Máquina parada",
                    findings=[],
                    status="STOPPED",
                )
            ],
            document_id="P25/81115-250526",
            inspection_date="2026-05-25",
        )
        rows = observation_rows([old, new])
        assert len(rows) == 1
        assert rows[0]["document_id"] == "P25/81115-250526"
        assert rows[0]["status"] == "STOPPED"

    def test_crosswalk_is_projected_onto_the_join_column(self, tmp_path: Path) -> None:
        (tmp_path / "crosswalk.csv").write_text(
            "normalized_tag,dataset_machine_id,match_rule\n"
            "AG100,MECLADOR_AGITADOR_AG_100,CW001\n"
            "PM9645B,,\n",
            encoding="utf-8",
        )
        crosswalk = read_crosswalk(tmp_path)
        assert crosswalk == {"AG100": "MECLADOR_AGITADOR_AG_100"}
        rows = observation_rows([_document([_observation()])], crosswalk)
        assert rows[0]["dataset_machine_id"] == "MECLADOR_AGITADOR_AG_100"

    def test_a_missing_crosswalk_is_not_an_error(self, tmp_path: Path) -> None:
        assert read_crosswalk(tmp_path) == {}

    def test_writes_parquet_and_csv_with_the_spec_columns(self, tmp_path: Path) -> None:
        import pyarrow.parquet as pq

        rows = observation_rows([_document([_observation()])])
        written = write_observations(rows, tmp_path)
        assert [p.name for p in written] == ["observations.parquet", "observations.csv"]
        table = pq.read_table(written[0])
        assert tuple(table.column_names) == OBSERVATION_COLUMNS
        assert table.num_rows == 1
        assert str(table.schema.field("alarm").type) == "int8"
        header = written[1].read_text(encoding="utf-8").splitlines()[0]
        assert header == ",".join(OBSERVATION_COLUMNS)


def _informes_dir() -> Path:
    """Directory of report PDFs, or skip. Opt-in like ``RBM_TEST_FILE``."""
    env_path = os.environ.get("INFORMES_TEST_DIR")
    if not env_path:
        pytest.skip("INFORMES_TEST_DIR not set; integration test skipped")
    path = Path(env_path)
    if not path.is_dir():
        pytest.skip(f"INFORMES_TEST_DIR points to a missing directory: {path}")
    return path


def _report_pdfs() -> list[str]:
    env_path = os.environ.get("INFORMES_TEST_DIR")
    return sorted(p.name for p in Path(env_path).glob("*.pdf")) if env_path else []


@pytest.mark.integration
@pytest.mark.parametrize("pdf_name", _report_pdfs())
def test_the_geometry_reproduces_the_published_document(pdf_name: str) -> None:
    """Re-read a real report and compare it with the DiagGT next to it.

    The layout (two columns, continuation pages, captions, anchor invariant)
    can only be checked against the PDFs, so this test is opt-in. The golden
    is the document published in ``<informes>/ground-truth/``; everything but
    the provenance of the *extraction* (when it ran, with what version) has to
    come out identical.
    """
    from ams_extract.informes.parse import ExtractionReport, build_document

    pdf_dir = _informes_dir()
    golden_path = pdf_dir / "ground-truth" / f"{Path(pdf_name).stem}.diaggt.json"
    if not golden_path.exists():
        pytest.skip(f"no published DiagGT next to {pdf_name}")

    report = ExtractionReport()
    document = build_document(pdf_dir / pdf_name, report)
    golden = json.loads(golden_path.read_text(encoding="utf-8"))

    assert report.anchors_ok, f"anchor invariant broken: {report.anchor_mismatch}"
    volatile = {"extracted_at", "extractor"}
    assert {k: v for k, v in document["provenance"].items() if k not in volatile} == {
        k: v for k, v in golden["provenance"].items() if k not in volatile
    }
    assert document["machines_stopped"] == golden["machines_stopped"]
    assert document["machines_not_measured"] == golden["machines_not_measured"]
    assert len(document["observations"]) == len(golden["observations"])
    for emitted, expected in zip(document["observations"], golden["observations"], strict=True):
        assert emitted == expected
