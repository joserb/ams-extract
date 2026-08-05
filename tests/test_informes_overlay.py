"""Tests for the contextual weight overlay (``rbm informes-weights``).

The overlay is the auditable half of workplan 10: a versioned file of
judgements that an LLM wrote after reading the corpus, and an applier that
turns those judgements into the second generation of the DiagGT documents.
What is protected here is the applier — that it refuses a stale or illegal
overlay, that the arithmetic lands on exactly 1, and that everything it is not
supposed to touch comes out untouched — plus the shipped Bunge overlay itself,
which has to load and be legal without needing the 5,8 MB corpus.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from ams_extract.informes.overlay import (
    ApplyReport,
    OverlayError,
    apply_overlay,
    finding_key,
    load_overlay,
)
from ams_extract.informes.rules import map_findings

OVERLAYS_DIR = Path(__file__).parent.parent / "overlays"
BUNGE_OVERLAY = OVERLAYS_DIR / "bunge-cartagena-2026.weights-llm.overlay.json"

PAIR = "-Desequilibrio del ventilador. -Debilidad estructural del motor."
WITH_UNMAPPED = "-Debilidad estructural. -Posible desgaste en la válvula."


def _document(*texts: str) -> dict[str, Any]:
    """A DiagGT document with one observation per diagnosis text."""
    return {
        "$schema_version": "0.1.5",
        "kind": "diagnosis_ground_truth",
        "provenance": {
            "origin": "inspection-report",
            "provider": "Preditec",
            "document_id": "P25/81115-260126",
            "source_ref": "Informe.pdf",
            "source_sha256": "7d32098930e5a2953810c293af0e80b61fa4b6a79775f061052c239481bd16d0",
            "inspection_date": "2026-01-26",
            "analysts": ["MIGUEL ANGEL SIMARRO"],
            "extractor": "informes-gt-extract 0.3.0",
            "extracted_at": "2026-08-04T21:57:16+00:00",
            "extraction_method": "pdf_text_parse",
        },
        "machines_stopped": [],
        "machines_not_measured": [],
        "observations": [
            {
                "observation_id": f"P2581115260126:AG100:vibration:{index}",
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
                "diagnosis_text": text,
                "analysis_text": None,
                "recommendation_text": None,
                "findings": map_findings(text),
                "operating_context": None,
                "source_page": 12,
            }
            for index, text in enumerate(texts)
        ],
    }


def _overlay_file(tmp_path: Path, *judgements: dict[str, Any], **head: Any) -> Path:
    payload: dict[str, Any] = {
        "$overlay_version": "0.1.0",
        "kind": "diaggt_weight_overlay",
        "extractor": "informes-gt-weights-llm 0.1.0",
        "extraction_method": "llm",
        "judgements": list(judgements),
    }
    payload.update(head)
    path = tmp_path / "overlay.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _judgement(text: str, **scores: float) -> dict[str, Any]:
    keys = [finding_key(f) for f in map_findings(text)]
    lookup = {key.replace(":", "_").replace("-", "x"): key for key in keys}
    return {
        "diagnosis_text": text,
        "observations": 1,
        "rationale": "por el test",
        "findings": [
            {"finding": lookup[name], "score": score} for name, score in scores.items()
        ],
    }


class TestFindingKey:
    def test_the_key_is_the_label_a_human_can_read(self) -> None:
        findings = map_findings(PAIR)
        assert [finding_key(f) for f in findings] == [
            "IMBALANCE:IMBALANCE",
            "STRUCTURE:LOOSENESS",
        ]

    def test_a_group_finding_has_no_mode_in_its_key(self) -> None:
        assert finding_key(map_findings("Desalineación.")[0]) == "MISALIGNMENT:-"


class TestLoading:
    def test_a_foreign_file_is_not_an_overlay(self, tmp_path: Path) -> None:
        path = tmp_path / "x.json"
        path.write_text('{"kind": "diagnosis_ground_truth"}', encoding="utf-8")
        with pytest.raises(OverlayError, match="kind"):
            load_overlay(path)

    def test_a_future_series_is_refused(self, tmp_path: Path) -> None:
        path = _overlay_file(tmp_path, **{"$overlay_version": "0.2.0"})
        with pytest.raises(OverlayError, match="serie"):
            load_overlay(path)

    def test_a_finding_without_mass_is_left_out_of_the_split(self, tmp_path: Path) -> None:
        path = _overlay_file(
            tmp_path, _judgement(PAIR, IMBALANCE_IMBALANCE=1, STRUCTURE_LOOSENESS=0)
        )
        with pytest.raises(OverlayError, match="puntuación"):
            load_overlay(path)

    def test_the_same_text_cannot_be_judged_twice(self, tmp_path: Path) -> None:
        judgement = _judgement(PAIR, IMBALANCE_IMBALANCE=1, STRUCTURE_LOOSENESS=1)
        path = _overlay_file(tmp_path, judgement, copy.deepcopy(judgement))
        with pytest.raises(OverlayError, match="dos juicios"):
            load_overlay(path)


class TestRemapValidation:
    """A judgement may rescue an ``unmapped``; it may not rewrite a rule."""

    def _with_remap(self, tmp_path: Path, source: str, target: dict[str, Any]) -> Path:
        judgement = _judgement(WITH_UNMAPPED, STRUCTURE_LOOSENESS=2, UNMAPPED_x=1)
        judgement["remap"] = [{"from": source, "to": target, "why": "el test"}]
        return _overlay_file(tmp_path, judgement)

    def test_only_an_unmapped_finding_can_be_remapped(self, tmp_path: Path) -> None:
        path = self._with_remap(
            tmp_path,
            "STRUCTURE:LOOSENESS",
            {"fault_group": "OTHER", "fault_mode": None, "label_quality": "group"},
        )
        with pytest.raises(OverlayError, match="re-mapeo sale de un finding"):
            load_overlay(path)

    def test_a_judgement_never_claims_a_direct_mapping(self, tmp_path: Path) -> None:
        path = self._with_remap(
            tmp_path,
            "UNMAPPED:-",
            {
                "fault_group": "IMBALANCE",
                "fault_mode": "IMBALANCE",
                "label_quality": "direct",
            },
        )
        with pytest.raises(OverlayError, match="label_quality"):
            load_overlay(path)

    def test_a_remap_cannot_land_back_on_unmapped(self, tmp_path: Path) -> None:
        path = self._with_remap(
            tmp_path,
            "UNMAPPED:-",
            {"fault_group": "UNMAPPED", "fault_mode": None, "label_quality": "group"},
        )
        with pytest.raises(OverlayError, match="fault_group"):
            load_overlay(path)

    def test_group_quality_and_a_concrete_mode_contradict_each_other(
        self, tmp_path: Path
    ) -> None:
        path = self._with_remap(
            tmp_path,
            "UNMAPPED:-",
            {
                "fault_group": "BEARING",
                "fault_mode": "BEARING_OUTER",
                "label_quality": "group",
            },
        )
        with pytest.raises(OverlayError, match="se contradicen"):
            load_overlay(path)

    def test_a_remap_of_a_finding_nobody_scored_is_a_stale_overlay(
        self, tmp_path: Path
    ) -> None:
        judgement = _judgement(PAIR, IMBALANCE_IMBALANCE=1, STRUCTURE_LOOSENESS=1)
        judgement["remap"] = [
            {
                "from": "UNMAPPED:-",
                "to": {"fault_group": "OTHER", "fault_mode": None, "label_quality": "group"},
            }
        ]
        path = _overlay_file(tmp_path, judgement)
        with pytest.raises(OverlayError, match="no está entre los findings"):
            load_overlay(path)


class TestApplying:
    def test_the_scores_become_a_share_that_adds_up_to_one(self, tmp_path: Path) -> None:
        overlay = load_overlay(
            _overlay_file(
                tmp_path, _judgement(PAIR, IMBALANCE_IMBALANCE=3, STRUCTURE_LOOSENESS=2)
            )
        )
        result = apply_overlay(_document(PAIR), overlay, ApplyReport())
        weights = [f["weight"] for f in result["observations"][0]["findings"]]
        assert weights == [0.6, 0.4]
        assert sum(weights) == 1.0

    def test_equal_scores_reproduce_the_deterministic_split(self, tmp_path: Path) -> None:
        text = "Desequilibrio. Resonancia. Cavitación."
        judgement = _judgement(
            text, IMBALANCE_IMBALANCE=2, STRUCTURE_RESONANCE=2, FLOW_CAVITATION=2
        )
        overlay = load_overlay(_overlay_file(tmp_path, judgement))
        result = apply_overlay(_document(text), overlay, ApplyReport())
        assert [f["weight"] for f in result["observations"][0]["findings"]] == [
            f["weight"] for f in map_findings(text)
        ]

    def test_the_rounded_share_never_goes_over_one(self, tmp_path: Path) -> None:
        text = "Desequilibrio. Resonancia. Cavitación."
        judgement = _judgement(
            text, IMBALANCE_IMBALANCE=1, STRUCTURE_RESONANCE=1, FLOW_CAVITATION=1
        )
        overlay = load_overlay(_overlay_file(tmp_path, judgement))
        result = apply_overlay(_document(text), overlay, ApplyReport())
        weights = [f["weight"] for f in result["observations"][0]["findings"]]
        assert sum(weights) <= 1.0
        assert all(w == round(w, 6) for w in weights)

    def test_a_remap_rescues_the_unmapped_without_a_rule(self, tmp_path: Path) -> None:
        judgement = _judgement(WITH_UNMAPPED, STRUCTURE_LOOSENESS=2, UNMAPPED_x=1)
        judgement["remap"] = [
            {
                "from": "UNMAPPED:-",
                "to": {
                    "fault_group": "OTHER",
                    "fault_mode": None,
                    "label_quality": "group",
                    "matched_text": "desgaste en la válvula",
                },
                "why": "el desgaste de la válvula es un fallo, sin FaultMode canónico",
            }
        ]
        overlay = load_overlay(_overlay_file(tmp_path, judgement))
        report = ApplyReport()
        result = apply_overlay(_document(WITH_UNMAPPED), overlay, report)
        rescued = result["observations"][0]["findings"][1]
        assert rescued["fault_group"] == "OTHER"
        assert rescued["fault_mode"] is None
        assert rescued["label_quality"] == "group"
        assert rescued["mapping_rule"] is None
        assert rescued["matched_text"] == "desgaste en la válvula"
        assert rescued["source_text"] == WITH_UNMAPPED
        assert report.remapped == 1

    def test_a_lone_finding_needs_no_judgement(self, tmp_path: Path) -> None:
        overlay = load_overlay(_overlay_file(tmp_path))
        report = ApplyReport()
        result = apply_overlay(_document("Desequilibrio."), overlay, report)
        assert [f["weight"] for f in result["observations"][0]["findings"]] == [1.0]
        assert report.single_finding == 1

    def test_a_split_is_judged_whole_or_not_at_all(self, tmp_path: Path) -> None:
        overlay = load_overlay(_overlay_file(tmp_path))
        with pytest.raises(OverlayError, match="ningún juicio"):
            apply_overlay(_document(PAIR), overlay, ApplyReport())

    def test_a_stale_overlay_stops_the_pass(self, tmp_path: Path) -> None:
        judgement = _judgement(PAIR, IMBALANCE_IMBALANCE=1, STRUCTURE_LOOSENESS=1)
        judgement["findings"][1]["finding"] = "BEARING:-"
        overlay = load_overlay(_overlay_file(tmp_path, judgement))
        with pytest.raises(OverlayError, match="desfasado"):
            apply_overlay(_document(PAIR), overlay, ApplyReport())

    def test_a_judgement_nobody_claims_is_reported(self, tmp_path: Path) -> None:
        overlay = load_overlay(
            _overlay_file(
                tmp_path, _judgement(PAIR, IMBALANCE_IMBALANCE=1, STRUCTURE_LOOSENESS=1)
            )
        )
        report = ApplyReport()
        apply_overlay(_document("Desequilibrio."), overlay, report)
        assert report.unused(overlay) == [PAIR]


class TestWhatDoesNotChange:
    def test_the_provenance_of_the_pdf_survives_the_pass(self, tmp_path: Path) -> None:
        overlay = load_overlay(_overlay_file(tmp_path))
        document = _document("Desequilibrio.")
        result = apply_overlay(document, overlay, ApplyReport())
        before, after = document["provenance"], result["provenance"]
        volatile = {"extractor", "extracted_at", "extraction_method"}
        assert {k: v for k, v in after.items() if k not in volatile} == {
            k: v for k, v in before.items() if k not in volatile
        }
        assert after["source_sha256"] == before["source_sha256"]
        assert after["extraction_method"] == "llm"
        assert after["extractor"] == "informes-gt-weights-llm 0.1.0"

    def test_the_deterministic_generation_is_not_mutated(self, tmp_path: Path) -> None:
        overlay = load_overlay(
            _overlay_file(
                tmp_path, _judgement(PAIR, IMBALANCE_IMBALANCE=3, STRUCTURE_LOOSENESS=2)
            )
        )
        document = _document(PAIR)
        untouched = copy.deepcopy(document)
        apply_overlay(document, overlay, ApplyReport())
        assert document == untouched

    def test_nothing_but_the_weight_moves_in_a_finding(self, tmp_path: Path) -> None:
        overlay = load_overlay(
            _overlay_file(
                tmp_path, _judgement(PAIR, IMBALANCE_IMBALANCE=3, STRUCTURE_LOOSENESS=2)
            )
        )
        document = _document(PAIR)
        result = apply_overlay(document, overlay, ApplyReport())
        for before, after in zip(
            document["observations"][0]["findings"],
            result["observations"][0]["findings"],
            strict=True,
        ):
            assert {k: v for k, v in after.items() if k != "weight"} == {
                k: v for k, v in before.items() if k != "weight"
            }


class TestContractConformance:
    def test_a_reweighted_observation_validates_against_the_models(
        self, tmp_path: Path
    ) -> None:
        external = pytest.importorskip("vibsynth_contracts.diagnosis.external")
        judgement = _judgement(WITH_UNMAPPED, STRUCTURE_LOOSENESS=3, UNMAPPED_x=1)
        judgement["remap"] = [
            {
                "from": "UNMAPPED:-",
                "to": {
                    "fault_group": "OTHER",
                    "fault_mode": None,
                    "label_quality": "group",
                },
            }
        ]
        overlay = load_overlay(_overlay_file(tmp_path, judgement))
        result = apply_overlay(_document(WITH_UNMAPPED), overlay, ApplyReport())
        model = external.DiagGTObservation.model_validate(result["observations"][0])
        assert [f.weight for f in model.findings] == [0.75, 0.25]
        assert sum(f.weight or 0 for f in model.findings) == 1.0

    def test_the_llm_method_is_in_the_contract_vocabulary(self) -> None:
        external = pytest.importorskip("vibsynth_contracts.diagnosis.external")
        from ams_extract.informes.overlay import LLM_EXTRACTION_METHOD

        assert LLM_EXTRACTION_METHOD in external.ExtractionMethod.__args__


class TestTheBungeOverlay:
    """The judgement shipped with the repo: it has to load and be legal."""

    @pytest.fixture(scope="class")
    def bunge(self):
        return load_overlay(BUNGE_OVERLAY)

    def test_it_covers_the_corpus_it_was_written_for(self, bunge) -> None:
        assert len(bunge.judgements) == 135
        assert sum(j.observations for j in bunge.judgements.values()) == 422
        assert bunge.extraction_method == "llm"

    def test_every_share_adds_up_to_exactly_one(self, bunge) -> None:
        for judgement in bunge.judgements.values():
            weights = judgement.weights()
            assert sum(weights) == pytest.approx(1.0, abs=1e-9)
            assert all(0.0 < w <= 1.0 for w in weights)

    def test_every_remap_leaves_an_unmapped_for_a_real_group(self, bunge) -> None:
        remaps = [r for j in bunge.judgements.values() for r in j.remaps]
        # 5 desde la adenda 0.1.1: el re-mapeo de «Desbalanceo» sobra porque
        # GT001v2 casa ya el sinónimo y no queda un `unmapped` que rescatar.
        # Un re-mapeo es el parche que se retira cuando la regla se arregla.
        assert len(remaps) == 5
        assert all(remap.why for remap in remaps), "a judgement without a reason is not auditable"
        assert {r.fault_group for r in remaps} == {"OTHER", "ELECTRICAL", "LOOSENESS"}

    def test_the_scores_live_in_the_declared_scale(self, bunge) -> None:
        scale = {"0.25", "0.5", "1", "1.5", "2", "3"}
        used = {str(float(score)).rstrip("0").rstrip(".") for j in bunge.judgements.values()
                for _, score in j.scores}
        assert used <= scale, f"scores outside the declared scale: {used - scale}"
