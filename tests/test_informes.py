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
import re
from pathlib import Path
from typing import Any

import pytest

from ams_extract import __version__
from ams_extract.informes.consolidate import (
    FINDING_COLUMNS,
    OBSERVATION_COLUMNS,
    consolidated_rows,
    finding_rows,
    materialize_ground_truth,
    observation_rows,
    read_crosswalk,
)
from ams_extract.informes.parse import merge_analysis_overflow
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


def _rule_family(rule: str | None) -> str | None:
    """``"GT001v2"`` → ``"GT001"``.

    The regression fixture predates the ``vN`` suffix that versions the
    *reading* of a rule (workplan 11). What it protects is the label a text
    gets, not how the version of the rule that gave it travels.
    """
    return re.sub(r"v\d+$", "", rule) if rule else rule


def _signature(finding: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        _rule_family(finding[key]) if key == "mapping_rule" else finding[key]
        for key in FINDING_KEYS
    )


EXPECTED_RULE_CHANGES: dict[str, tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]] = {
    # text → (findings that appear, findings that vanish), as
    # (fault_group, fault_mode, rule family).
    "Debilidad estructural / Desequilibrio, excentricidad en polea.": (
        [("BELT", None, "GT025")],
        [("ELECTRICAL", "ELECTRICAL_ROTOR", "GT021")],
    ),
    "Desbalanceo - Debilidad estructural del motor.": (
        [("IMBALANCE", "IMBALANCE", "GT001")],
        [],
    ),
    "Desbalanceo en el rotor del ventilador posiblemente amplificado por debilidad en la "
    "estructura.Frecuencias de naturaleza eléctrica en el lado acoplado del motor.": (
        [("IMBALANCE", "IMBALANCE", "GT001")],
        [],
    ),
    "Desbalanceo en el rotor del ventilador posiblemente amplificado por debilidad en la "
    "estructura.Frecuencias de naturaleza eléctrica en el lado acoplado del motor. "
    "Lubricación mejorable en rodamientos del ventilador. Huelgo leve.": (
        [("IMBALANCE", "IMBALANCE", "GT001"), ("LOOSENESS", "LOOSENESS", "GT004")],
        [],
    ),
    "Se aprecia buen estado de lubricación de los rodamientos del conjunto. Se establece "
    "su buen estado y se vigilará su evolución.": (
        [],
        [("LUBRICATION", "BEARING_LUBRICATION", "GT011")],
    ),
    "-Debilidad estructural (seguimiento). -Posible suciedad y/o desgaste en la válvula": (
        [("OTHER", None, "GT026")],
        [],
    ),
    "-Deterioro del acoplamiento. - Debilidad estructural del motor.": (
        [("OTHER", None, "GT027")],
        [],
    ),
    "Debilidad estructural del conjunto. ALERTA. Desalineación y/o deterioro del "
    "acoplamiento.": (
        [("OTHER", None, "GT027")],
        [],
    ),
    "Debilidad estructural del conjunto. Desalineación y/o deterioro del acoplamiento.": (
        [("OTHER", None, "GT027")],
        [],
    ),
    "Existencia de bandas laterales que podrían estar relacionadas con un fallo de "
    "barras sueltas o rotas.": (
        [("ELECTRICAL", "ELECTRICAL_ROTOR", "GT028")],
        [("UNMAPPED", None, None)],
    ),
    "Linea 1 de refinería parada": ([], [("UNMAPPED", None, None)]),
    "Ruido en el acople.": (
        [("OTHER", None, "GT029")],
        [("UNMAPPED", None, None)],
    ),
}
"""Diferencias deliberadas respecto al destilado histórico 0.2.0."""


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
        assert findings[0]["mapping_rule"] == "GT001v2"
        assert findings[0]["fault_mode"] == "IMBALANCE"
        assert findings[0]["label_quality"] == "direct"
        assert findings[0]["source_text"] == "Desequilibrio del ventilador"

    def test_an_administrative_request_is_declared_not_dropped(self) -> None:
        findings = map_findings("Informar a Preditec si se ha intervenido")
        assert [f["fault_group"] for f in findings] == ["UNMAPPED"]
        assert findings[0]["label_quality"] == "unmapped"
        assert findings[0]["mapping_rule"] is None


class TestTheRulesTheCorpusDisproved:
    """The three readings the full read of the corpus denied (workplan 11).

    Every text here is verbatim from the BUNGE 2026 reports; the quotes are
    what workplan 10 cited when it could only paper over them with weights.
    """

    def test_the_analyst_also_writes_desbalanceo(self) -> None:
        # GT001 only knew «desequilibri», so the imbalance of this card
        # vanished from the document: the clause matched GT005 and nothing
        # said that the analyst had diagnosed an imbalance at all.
        findings = map_findings(
            "Desbalanceo en el rotor del ventilador posiblemente amplificado "
            "por debilidad en la estructura."
        )
        assert [(f["fault_group"], f["mapping_rule"]) for f in findings] == [
            ("IMBALANCE", "GT001v2"),
            ("STRUCTURE", "GT005"),
        ]
        assert map_findings("Desbalanceo.")[0]["fault_mode"] == "IMBALANCE"

    def test_desbalanceo_no_longer_falls_into_the_unmapped(self) -> None:
        findings = map_findings("Desbalanceo - Debilidad estructural del motor.")
        assert [f["fault_group"] for f in findings] == ["IMBALANCE", "STRUCTURE"]
        assert [f["weight"] for f in findings] == [0.5, 0.5]

    def test_good_lubrication_is_not_a_lubrication_fault(self) -> None:
        # GT011 read the word and ignored the sentence: this text says the
        # opposite of what the rule was claiming.
        assert map_findings("Se aprecia buen estado de lubricación de los rodamientos.") == []
        findings = map_findings(
            "Se aprecia buen estado de lubricación de los rodamientos del conjunto. "
            "Se establece su buen estado y se vigilará su evolución."
        )
        assert findings == []

    def test_the_veto_does_not_reach_the_lubrication_that_is_a_fault(self) -> None:
        # «Mejorable» is a fault and «Deficiente/Ineficiente» carry «eficiente»
        # inside: the veto has to read the word, not find it.
        for text in (
            "Lubricación mejorable en rodamientos del ventilador",
            "Mejorable estado de lubricación",
            "Mejor estado de lubricación",
            "Deficiente lubricación en rodamiento lado polea",
            "Ineficiente lubricación en rodamiento del punto 4 de la centrífuga",
            "Lubricación inadecuada en rodamientos de la bomba",
        ):
            assert [f["fault_group"] for f in map_findings(text)] == ["LUBRICATION"], text

    def test_an_eccentric_pulley_is_a_transmission_fault(self) -> None:
        # GT021 took every eccentricity to the electrical rotor without
        # looking at what was eccentric.
        findings = map_findings("Debilidad estructural / Desequilibrio, excentricidad en polea.")
        assert [(f["fault_group"], f["fault_mode"], f["mapping_rule"]) for f in findings] == [
            ("IMBALANCE", "IMBALANCE", "GT001v2"),
            ("STRUCTURE", "LOOSENESS", "GT005"),
            ("BELT", None, "GT025"),
        ]

    def test_a_bare_eccentricity_is_still_read_as_electrical(self) -> None:
        findings = map_findings("-Distorsión armónica proveniente del variador. -Excentricidad.")
        assert [(f["fault_group"], f["fault_mode"], f["mapping_rule"]) for f in findings] == [
            ("ELECTRICAL", None, "GT020"),
            ("ELECTRICAL", "ELECTRICAL_ROTOR", "GT021v2"),
        ]
        assert [f["mapping_rule"] for f in map_findings("Excentricidad en el rotor.")] == [
            "GT021v2"
        ]


class TestWorkplan16Rules:
    @pytest.mark.parametrize(
        ("text", "rule", "group", "mode"),
        [
            ("Posible suciedad y/o desgaste en la válvula", "GT026", "OTHER", None),
            ("Deterioro del acoplamiento", "GT027", "OTHER", None),
            (
                "Existencia de bandas laterales relacionadas con barras sueltas o rotas",
                "GT028",
                "ELECTRICAL",
                "ELECTRICAL_ROTOR",
            ),
            ("Ruido en el acople", "GT029", "OTHER", None),
            ("Huelgo leve", "GT004v2", "LOOSENESS", "LOOSENESS"),
        ],
    )
    def test_the_remaining_explicit_faults_are_mapped(
        self, text: str, rule: str, group: str, mode: str | None
    ) -> None:
        findings = map_findings(text)
        assert [(f["mapping_rule"], f["fault_group"], f["fault_mode"]) for f in findings] == [
            (rule, group, mode)
        ]

    def test_a_bearing_reference_near_coupling_does_not_become_a_coupling_fault(self) -> None:
        text = (
            "Lubricación mejorable en rodamiento de la bomba, lado opuesto al "
            "acoplamiento, así como posible deterioro incipiente en el mismo."
        )
        assert all(f["mapping_rule"] != "GT027" for f in map_findings(text))

    @pytest.mark.parametrize(
        "text",
        [
            "Estable",
            "Sin evolución en el último mes",
            "Se establece su buen estado",
            "No se aprecian trazas de fallo",
            "Linea 1 de refinería parada",
        ],
    )
    def test_inequivocal_state_clauses_do_not_become_findings(self, text: str) -> None:
        assert map_findings(text) == []
        assert status_from_text(text) is not None

    def test_a_stable_clause_does_not_hide_a_fault_clause(self) -> None:
        findings = map_findings("Debilidad estructural. Estable. Se establece su buen estado.")
        assert [f["mapping_rule"] for f in findings] == ["GT005"]
        assert findings[0]["weight"] == 1.0

    def test_administrative_requests_remain_explicitly_unmapped(self) -> None:
        for text in (
            "Informar a Preditec si se ha intervenido.",
            "Comentar a Preditec qué labores se han llevado a cabo.",
            "Revisar protección ventilador motor.",
        ):
            assert [f["label_quality"] for f in map_findings(text)] == ["unmapped"]


class TestAnalysisOverflow:
    def test_an_explicit_modality_is_recovered(self) -> None:
        assert merge_analysis_overflow(
            {"vibration": "Análisis vibratorio."},
            "Ultrasonidos: Ruido ultrasónico en el reductor.",
        ) == {
            "vibration": "Análisis vibratorio.",
            "ultrasound": "Ruido ultrasónico en el reductor.",
        }

    def test_an_unlabelled_paragraph_needs_one_lexical_anchor(self) -> None:
        assert merge_analysis_overflow(
            {"vibration": "Primera parte."},
            "En las firmas espectrales se observa una componente excitada.",
        ) == {
            "vibration": "Primera parte. En las firmas espectrales se observa una "
            "componente excitada."
        }

    def test_an_ambiguous_paragraph_is_not_assigned_by_position(self) -> None:
        original = {"vibration": "Primera parte."}
        assert (
            merge_analysis_overflow(original, "ACTUALIZACIÓN sin ancla de modalidad.")
            == original
        )


class TestWeights:
    def test_a_single_clause_takes_the_whole_mass(self) -> None:
        findings = map_findings("Desequilibrio del ventilador")
        assert [f["weight"] for f in findings] == [1.0]

    def test_the_clauses_split_the_mass_evenly(self) -> None:
        findings = map_findings("-Desequilibrio del ventilador. -Debilidad estructural.")
        assert [f["mapping_rule"] for f in findings] == ["GT001v2", "GT005"]
        assert [f["weight"] for f in findings] == [0.5, 0.5]

    def test_the_findings_of_one_clause_share_its_fraction(self) -> None:
        # First clause: two findings of 1/2 · 1/2; second clause: 1/2.
        findings = map_findings("Desalineación y cavitación. Desequilibrio.")
        assert [f["mapping_rule"] for f in findings] == ["GT001v2", "GT002", "GT015"]
        assert [f["weight"] for f in findings] == [0.5, 0.25, 0.25]

    def test_the_uncovered_clause_gives_its_mass_to_the_unmapped(self) -> None:
        findings = map_findings(
            "Desequilibrio del ventilador. Informar a Preditec si se ha intervenido."
        )
        assert [f["fault_group"] for f in findings] == ["IMBALANCE", "UNMAPPED"]
        assert [f["weight"] for f in findings] == [0.5, 0.5]

    def test_a_severity_marker_is_not_a_clause_of_judgement(self) -> None:
        # "ALERTA" is the machine's global label repeated inside the text: it
        # would otherwise carry a third of the mass to an unmapped finding.
        findings = map_findings("-Desequilibrio del ventilador. ALERTA. -Resonancia.")
        assert [f["fault_group"] for f in findings] == ["IMBALANCE", "STRUCTURE"]
        assert [f["weight"] for f in findings] == [0.5, 0.5]

    def test_a_healthy_clause_does_not_dilute_the_fault(self) -> None:
        findings = map_findings("-Falta de rigidez. -Rodamientos en buen estado.")
        assert [f["weight"] for f in findings] == [1.0]

    def test_the_same_label_from_two_clauses_adds_up(self) -> None:
        findings = map_findings(
            "Holguras rotacionales en el motor. Desequilibrio. Holguras en la bomba."
        )
        weights = {f["mapping_rule"]: f["weight"] for f in findings}
        # GT003 wins the merge over GT004 (lower rule index, same label) and
        # keeps both thirds.
        assert weights == {"GT003": 0.666667, "GT001v2": 0.333333}

    def test_the_rounded_mass_never_goes_over_one(self) -> None:
        for text in (
            "Desequilibrio. Resonancia. Cavitación.",
            "Desequilibrio. Resonancia. Cavitación. Correa. Engranaje. Rozamiento.",
            "Desalineación y cavitación y correa. Desequilibrio. Suciedad.",
        ):
            weights = [f["weight"] for f in map_findings(text)]
            assert sum(weights) <= 1.0
            assert all(0.0 < w <= 1.0 for w in weights)
            assert all(w == round(w, 6) for w in weights)

    def test_every_observation_weights_all_of_its_findings_or_none(
        self, regression_cases: list[dict[str, Any]]
    ) -> None:
        # The contract's all-or-none rule, over the whole corpus.
        for case in regression_cases:
            findings = map_findings(case["diagnosis_text"] or "")
            weighted = [f for f in findings if f["weight"] is not None]
            assert len(weighted) == len(findings)
            assert not findings or sum(f["weight"] for f in findings) <= 1.0


class TestRegressionAgainstTheStandaloneScript:
    def test_the_corpus_is_the_one_that_was_emitted(
        self, regression_cases: list[dict[str, Any]]
    ) -> None:
        assert len(regression_cases) == 251
        assert sum(case["observations"] for case in regression_cases) == 6_669

    def test_every_finding_removed_from_the_historical_reading_is_enumerated(
        self, regression_cases: list[dict[str, Any]]
    ) -> None:
        """Reading by clause may add; only a veto subtracts.

        The clause is a *finer* window than the whole text, so a rule that
        fired before has to fire on some clause — unless its match was
        straddling a clause boundary, which is the bug that reading fixed.
        The one deliberate exception is ``RULE_VETOES`` (workplan 11): a clause
        that says the opposite of what the rule reads loses it, and that is the
        whole point of the veto.
        """
        lost: list[tuple[str, str]] = []
        for case in regression_cases:
            text = case["diagnosis_text"] or ""
            got = {_signature(f)[1:] for f in map_findings(text)}
            for finding in case["findings"]:
                if tuple(finding[key] for key in FINDING_KEYS)[1:] not in got:
                    lost.append((text, str(finding["mapping_rule"])))
        assert sorted(rule for _text, rule in lost if rule != "None") == ["GT011", "GT021"]
        assert sorted(text for text, rule in lost if rule == "None") == [
            "Existencia de bandas laterales que podrían estar relacionadas con un fallo "
            "de barras sueltas o rotas.",
            "Linea 1 de refinería parada",
            "Ruido en el acople.",
        ]
        by_rule = dict((rule, text) for text, rule in lost if rule != "None")
        assert by_rule["GT011"].startswith("Se aprecia buen estado de lubricación")
        assert "excentricidad en polea" in by_rule["GT021"]

    def test_the_differences_are_the_ones_the_workplans_measured(
        self, regression_cases: list[dict[str, Any]]
    ) -> None:
        """Pinned diff against the 0.2.0 emission (workplans 09 §3 and 11).

        Of the 251 distinct texts of the corpus, 230 map identically; two gain
        the partial ``unmapped`` that measures the share of the judgement the
        rules do not cover; 7 move the ``matched_text`` of GT012, whose
        ``rodamiento.*deterior`` alternative used to match *across* clauses
        («rodamientos del conjunto. Posible deterioro»); and 5 are the texts
        the corrected rules through 0.5.0 read differently, pinned one by one
        in :data:`EXPECTED_RULE_CHANGES`.
        """
        identical = added_unmapped = moved_match = corrected = 0
        for case in regression_cases:
            text = case["diagnosis_text"] or ""
            expected = [tuple(f[key] for key in FINDING_KEYS) for f in case["findings"]]
            got = [_signature(f) for f in map_findings(text)]
            if got == expected:
                identical += 1
                continue
            appeared = [(f[2], f[1], f[4]) for f in got if f not in expected]
            vanished = [(f[2], f[1], f[4]) for f in expected if f not in got]
            if text in EXPECTED_RULE_CHANGES:
                corrected += 1
                assert (appeared, vanished) == EXPECTED_RULE_CHANGES[text], text
            elif vanished:
                assert all(rule == "GT012" for _g, _m, rule in vanished), f"{text!r}"
                moved_match += 1
            else:
                assert all(group == "UNMAPPED" for group, _m, _r in appeared), f"{text!r}"
                added_unmapped += 1
        assert (identical, added_unmapped, moved_match, corrected) == (230, 2, 7, 12)

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


class TestCompleteProjection:
    def test_row_carries_identity_origin_and_context(self) -> None:
        rows = observation_rows([_document([_observation()])])
        assert len(rows) == 1
        row = rows[0]
        assert set(OBSERVATION_COLUMNS) <= set(row)
        assert row["observation_id"] == "P2581115260126:AG100:vibration"
        assert row["origin"] == "inspection-report"
        assert row["alarm"] == 2
        assert row["rpm1"] == 1485.0
        assert row["n_findings"] == 1
        assert row["dataset_machine_id"] is None
        # The "+"-joined fault columns of 0.1 are gone: multiplicity lives in
        # findings.parquet by row count, n_findings is the cheap marker.
        assert "fault_modes" not in OBSERVATION_COLUMNS
        assert "fault_groups" not in OBSERVATION_COLUMNS

    def test_the_complete_projection_never_deduplicates(self) -> None:
        text = "Desequilibrio del ventilador"
        quoted = _observation(
            record_kind="retrospective",
            status="UNKNOWN",
            alarm=None,
            diagnosis_text=text,
            findings=map_findings(text),
            operating_context=None,
        )
        documents = [
            _document([quoted], document_id="P25/81115-260126", inspection_date="2026-01-26"),
            _document([quoted], document_id="P25/81115-250526", inspection_date="2026-05-25"),
        ]
        rows = observation_rows(documents)
        assert len(rows) == 2  # six monthly quotes would be six rows

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


class TestConsolidatedSelection:
    def test_primary_wins_over_a_retrospective_of_the_same_key(self) -> None:
        retrospective = _observation(
            observation_id="X:AG100:vibration:2026-01-26",
            record_kind="retrospective",
            status="UNKNOWN",
            alarm=None,
            diagnosis_text="Máquina parada",
            findings=[],
            operating_context=None,
        )
        complete = observation_rows([_document([retrospective, _observation()])])
        rows = consolidated_rows(complete)
        assert len(complete) == 2  # the complete projection keeps both
        assert len(rows) == 1
        assert rows[0]["record_kind"] == "primary"
        # Selection, not aggregation: the winner IS a row of the complete set.
        assert rows[0]["observation_id"] == "P2581115260126:AG100:vibration"

    def test_between_retrospectives_the_latest_report_wins(self) -> None:
        old = _document(
            [
                _observation(
                    record_kind="retrospective",
                    diagnosis_text="Desequilibrio del ventilador",
                    status="UNKNOWN",
                    alarm=None,
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
                    alarm=None,
                )
            ],
            document_id="P25/81115-250526",
            inspection_date="2026-05-25",
        )
        rows = consolidated_rows(observation_rows([old, new]))
        assert len(rows) == 1
        assert rows[0]["document_id"] == "P25/81115-250526"
        assert rows[0]["status"] == "STOPPED"

    def test_valid_to_is_the_next_observation_of_the_series(self) -> None:
        months = [
            _document(
                [_observation(observed_at=date, observation_id=f"o:{date}")],
                document_id=f"D-{date}",
                inspection_date=date,
            )
            for date in ("2026-01-26", "2026-02-23", "2026-04-27")
        ]
        rows = consolidated_rows(observation_rows(months))
        by_date = {row["observed_at"]: row for row in rows}
        # Exclusive ISO date of the next consolidated observation of the same
        # (origin, normalized_tag, modality); null = open validity. Never an
        # invented instant, never a 30-day cutoff.
        assert by_date["2026-01-26"]["valid_to"] == "2026-02-23"
        assert by_date["2026-02-23"]["valid_to"] == "2026-04-27"
        assert by_date["2026-04-27"]["valid_to"] is None

    def test_origins_never_compete_as_duplicates(self) -> None:
        analyst = _document([_observation()])
        system = _document(
            [_observation(observation_id="sys:AG100", status="ALERT", alarm=2)],
            origin="system-alarm",
            document_id="ams-gdnl:BUNGE",
            inspection_date=None,
        )
        rows = consolidated_rows(observation_rows([analyst, system]))
        # Same (tag, date, modality) but different origin: both survive.
        assert len(rows) == 2
        assert {row["origin"] for row in rows} == {"inspection-report", "system-alarm"}


class TestFindingsProjection:
    def test_one_row_per_finding_with_index_weight_and_keys(self) -> None:
        text = "-Desequilibrio del ventilador. -Debilidad estructural."
        rows = observation_rows(
            [_document([_observation(diagnosis_text=text, findings=map_findings(text))])],
            {"AG100": "MECLADOR_AGITADOR_AG_100"},
        )
        findings = finding_rows(rows)
        assert len(findings) == 2
        assert set(findings[0]) == set(FINDING_COLUMNS)
        assert [f["finding_index"] for f in findings] == [0, 1]
        assert [f["mapping_rule"] for f in findings] == ["GT001v2", "GT005"]
        assert [f["weight"] for f in findings] == [0.5, 0.5]
        assert all(f["observation_id"] == "P2581115260126:AG100:vibration" for f in findings)
        assert all(f["dataset_machine_id"] == "MECLADOR_AGITADOR_AG_100" for f in findings)
        assert all(f["source_text"] == text for f in findings)
        assert all(f["matched_text"] for f in findings)

    def test_a_healthy_observation_contributes_no_row(self) -> None:
        rows = observation_rows(
            [_document([_observation(diagnosis_text="Máquina parada", findings=[])])]
        )
        assert finding_rows(rows) == []

    def test_findings_project_from_the_complete_set(self) -> None:
        # 0.2 change of population: findings align 1:1 with observations.parquet.
        # A consumer that scores mass keeps only the winners by joining with
        # observations_consolidated.parquet — the dedup lives in one place.
        text = "Desequilibrio del ventilador"
        quoted = _observation(
            record_kind="retrospective",
            status="UNKNOWN",
            alarm=None,
            diagnosis_text=text,
            findings=map_findings(text),
            operating_context=None,
        )
        documents = [
            _document([quoted], document_id="P25/81115-260126", inspection_date="2026-01-26"),
            _document([quoted], document_id="P25/81115-250526", inspection_date="2026-05-25"),
        ]
        complete = observation_rows(documents)
        findings = finding_rows(complete)
        assert len(findings) == 2
        consolidated = consolidated_rows(complete)
        winners = {(row["document_id"], row["observation_id"]) for row in consolidated}
        assert len(winners) == 1
        surviving = [
            f for f in findings if (f["document_id"], f["observation_id"]) in winners
        ]
        assert len(surviving) == 1


class TestMaterialization:
    def _write_documents(self, gt_dir: Path, documents: list[dict[str, Any]]) -> None:
        gt_dir.mkdir(parents=True, exist_ok=True)
        for i, document in enumerate(documents):
            path = gt_dir / f"doc-{i}.diaggt.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def test_writes_the_three_projections_and_the_manifest(self, tmp_path: Path) -> None:
        import pyarrow.parquet as pq

        text = "-Desequilibrio. -Informar a Preditec si se ha intervenido."
        self._write_documents(
            tmp_path, [_document([_observation(diagnosis_text=text, findings=map_findings(text))])]
        )
        summary = materialize_ground_truth(tmp_path)
        assert [p.name for p in summary.written] == [
            "observations.parquet",
            "observations_consolidated.parquet",
            "findings.parquet",
            "materialization.json",
        ]
        observations = pq.read_table(summary.written[0])
        assert tuple(observations.column_names) == OBSERVATION_COLUMNS
        assert str(observations.schema.field("alarm").type) == "int8"
        assert str(observations.schema.field("source_page").type) == "int32"
        assert str(observations.schema.field("rpm1").type) == "float"
        assert str(observations.schema.field("n_findings").type) == "int32"
        consolidated = pq.read_table(summary.written[1])
        assert tuple(consolidated.column_names) == (*OBSERVATION_COLUMNS, "valid_to")
        findings = pq.read_table(summary.written[2])
        assert tuple(findings.column_names) == FINDING_COLUMNS
        assert str(findings.schema.field("weight").type) == "float"
        assert str(findings.schema.field("finding_index").type) == "int32"
        assert findings.column("fault_group").to_pylist() == ["IMBALANCE", "UNMAPPED"]

    def test_all_null_columns_keep_their_declared_type(self, tmp_path: Path) -> None:
        # The lethal 0.1 drift: pandas inference degraded all-null columns to
        # type `null` (6 physical schemas in the corpus). The explicit schema
        # writes the declared type even when the writer only saw nulls.
        import pyarrow.parquet as pq

        observation = _observation(
            operating_context=None, source_page=None, recommendation_text=None
        )
        self._write_documents(tmp_path, [_document([observation])])
        summary = materialize_ground_truth(tmp_path)
        table = pq.read_table(summary.written[0])
        assert str(table.schema.field("rpm1").type) == "float"
        assert str(table.schema.field("source_page").type) == "int32"
        assert table.column("source_page").null_count == 1

    def test_the_manifest_anchors_inputs_and_outputs(self, tmp_path: Path) -> None:
        import hashlib

        self._write_documents(tmp_path, [_document([_observation()])])
        summary = materialize_ground_truth(tmp_path)
        manifest = json.loads((tmp_path / "materialization.json").read_text(encoding="utf-8"))
        assert manifest["$schema_version"] == "0.2.0"
        assert manifest["kind"] == "gt_materialization"
        assert manifest["tool"] == f"ams-extract {__version__}"
        assert manifest["consolidation_policy"] == "dedup-primary-latest/1.0"
        assert [i["file"] for i in manifest["inputs"]] == ["doc-0.diaggt.json"]
        assert manifest["inputs"][0]["observations"] == 1
        by_name = {o["file"]: o for o in manifest["outputs"]}
        assert set(by_name) == {
            "observations.parquet",
            "observations_consolidated.parquet",
            "findings.parquet",
        }
        for output in by_name.values():
            digest = hashlib.sha256((tmp_path / output["file"]).read_bytes()).hexdigest()
            assert output["sha256"] == digest
        assert by_name["observations.parquet"]["rows"] == summary.observations

    def test_no_csv_is_written_and_legacy_views_are_retired(self, tmp_path: Path) -> None:
        self._write_documents(tmp_path, [_document([_observation()])])
        for legacy in (
            "observations.csv",
            "findings.csv",
            "observations_system.csv",
            "observations_system.parquet",
        ):
            (tmp_path / legacy).write_text("legacy", encoding="utf-8")
        materialize_ground_truth(tmp_path)
        assert [p.name for p in tmp_path.glob("*.csv")] == []
        assert not (tmp_path / "observations_system.parquet").exists()

    def test_the_manifest_validates_against_the_contract_model(self, tmp_path: Path) -> None:
        external = pytest.importorskip("vibsynth_contracts.diagnosis.external")
        self._write_documents(tmp_path, [_document([_observation()])])
        materialize_ground_truth(tmp_path)
        manifest = external.GTMaterialization.model_validate_json(
            (tmp_path / "materialization.json").read_bytes()
        )
        assert manifest.consolidation_policy == external.CONSOLIDATION_POLICY


class TestContractConformance:
    """The normative models of vibsynth-contracts are the schema (spec §7)."""

    def test_a_weighted_observation_validates_against_the_models(self) -> None:
        external = pytest.importorskip("vibsynth_contracts.diagnosis.external")
        text = "-Desequilibrio del ventilador. -Informar a Preditec si se ha intervenido."
        observation = _observation(diagnosis_text=text, findings=map_findings(text))
        model = external.DiagGTObservation.model_validate(observation)
        assert [f.weight for f in model.findings] == [0.5, 0.5]
        assert model.alarm == external.STATUS_ALARM["ALERT"]

    def test_the_findings_table_is_the_one_the_contract_models(self) -> None:
        external = pytest.importorskip("vibsynth_contracts.diagnosis.external")
        assert tuple(c.name for c in external.FINDINGS_COLUMNS) == FINDING_COLUMNS
        assert {c.name: c.dtype for c in external.FINDINGS_COLUMNS}["weight"] == "float32"

    def test_the_observations_table_is_the_one_the_contract_models(self) -> None:
        external = pytest.importorskip("vibsynth_contracts.diagnosis.external")
        assert tuple(c.name for c in external.OBSERVATIONS_COLUMNS) == OBSERVATION_COLUMNS
        theirs = {c.name: (c.dtype, c.required) for c in external.OBSERVATIONS_COLUMNS}
        from ams_extract.export.vibframe_contract import (
            OBSERVATIONS_COLUMNS as VENDORED,
        )

        ours = {c.name: (c.dtype, c.required) for c in VENDORED}
        assert ours == theirs
        consolidated = tuple(
            c.name for c in external.OBSERVATIONS_CONSOLIDATED_COLUMNS
        )
        assert consolidated == (*OBSERVATION_COLUMNS, "valid_to")

    def test_the_schema_version_is_the_one_the_models_declare(self) -> None:
        external = pytest.importorskip("vibsynth_contracts.diagnosis.external")
        from ams_extract.informes.rules import SCHEMA_VERSION

        assert SCHEMA_VERSION == external.DIAGGT_SCHEMA_VERSION



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
    # The root generation is the contextual LLM-weighted publication. Geometry
    # and deterministic rule output are anchored by the archived 0.4.0
    # generation, which is the direct output of ``build_document``.
    golden_path = (
        pdf_dir
        / "ground-truth"
        / "deterministic-0.4.0"
        / f"{Path(pdf_name).stem}.diaggt.json"
    )
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
    allowed_analysis_overflows = {
        ("CF.9110S1", "vibration"),
        ("LA.1249A2", "visual_inspection"),
        ("PM.4500", "visual_inspection"),
        ("TC.1523A2", "ultrasound"),
        ("PM.9700A", "visual_inspection"),
    }
    rule_fields = {"findings", "status", "alarm"}
    for emitted, expected in zip(document["observations"], golden["observations"], strict=True):
        # This golden is 0.4.0: rule-output changes are pinned by the 251-text
        # regression above. Here the archived document protects every other
        # field and enumerates the only geometric differences admitted.
        assert {k: v for k, v in emitted.items() if k not in rule_fields | {"analysis_text"}} == {
            k: v for k, v in expected.items() if k not in rule_fields | {"analysis_text"}
        }
        if emitted["analysis_text"] != expected["analysis_text"]:
            key = (emitted["machine"]["external_tag"], emitted["modality"])
            assert key in allowed_analysis_overflows
            if expected["analysis_text"]:
                assert emitted["analysis_text"].startswith(expected["analysis_text"])


@pytest.mark.integration
def test_the_known_analysis_overflows_are_recovered() -> None:
    """Los dos layouts reales que motivan workplan 16, anclados por texto."""
    import pdfplumber

    from ams_extract.informes.parse import parse_machine_page

    pdf_dir = _informes_dir()
    expected = [
        (
            "Informe Bunge Cartagena Marzo 2026.pdf",
            "CF.9110S1",
            "vibration",
            "acumulación de suciedad en el bowl de la centrífuga",
        ),
        (
            "Informe Bunge Cartagena Enero 2026.pdf",
            "TC.1523A2",
            "ultrasound",
            "ruido ultrasónico con excitación asíncrona a 127 Hz",
        ),
        (
            "Informe Bunge Cartagena Marzo 2026.pdf",
            "PM.4500",
            "visual_inspection",
            "Revisar bancada de emplazamiento del equipo, pata coja",
        ),
        (
            "Informe Bunge Cartagena Mayo 2026.pdf",
            "LA.1249A2",
            "visual_inspection",
            "Ruido mecánico en rodamiento del laminador, lado opuesto al acoplamiento",
        ),
    ]
    for filename, tag, modality, fragment in expected:
        with pdfplumber.open(pdf_dir / filename) as pdf:
            records = (parse_machine_page(page) for page in pdf.pages)
            machine = next(record for record in records if record and record["tag"] == tag)
        assert fragment in machine["analysis"][modality]
