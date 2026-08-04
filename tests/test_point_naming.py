"""Tests for :mod:`ams_extract.point_naming` and its real-corpus coverage."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from ams_extract.point_naming import (
    PointPlacement,
    parse_point_name,
    point_direction,
    point_location,
)
from ams_extract.reader import RbmReader
from ams_extract.tree import walk_hierarchy

CORPUS_FILE = Path(__file__).parent / "fixtures" / "bunge_point_names.json"
"""Every distinct point name of the real Bunge Cartagena database, with the
number of points carrying it and the placement the rules must produce."""


@pytest.fixture(scope="module")
def corpus() -> dict[str, Any]:
    return json.loads(CORPUS_FILE.read_text(encoding="utf-8"))


class TestSideAbbreviations:
    """``LA`` / ``LOA`` / ``LCA``, the dominant convention in the database."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("MOTOR LA HORIZONTAL", "DE"),
            ("MOTOR LOA VERTICAL PEAKVUE", "NDE"),
            ("Reductor LCA Horiz (P)", "NDE"),
            ("Reductor Eje Entrada LA Peakvue", "DE"),
            ("Reductor Eje Salida LOA  Peakv", "NDE"),
        ],
    )
    def test_the_abbreviation_fixes_the_side(self, name: str, expected: str) -> None:
        assert point_location(name) == expected

    def test_the_abbreviation_must_be_a_whole_token(self) -> None:
        # "LAMINADOR" starts with LA and "Salida" contains it; neither is a side.
        assert point_location("LAMINADOR HORIZONTAL") is None
        assert point_location("Reductor Eje Salida Vertical") is None


class TestSidePhrases:
    """``Lado Acople`` / ``Lado Libre`` / ``Lado (Op) Motor`` and their cuts."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Motor Lado Acople Vertical", "DE"),
            ("Reductor Lado Acople [HF]", "DE"),
            ("Motor Lado Libre Peakvue", "NDE"),
            ("Eje Entrada Lado Motor Horiz", "DE"),
            ("Eje Entrad Lado Op Motor Vert", "NDE"),
            ("Eje Entrada Lado Op Motor (P)", "NDE"),
            ("Rodillo Traccion Lad Op Mot (P)", "NDE"),
            ("Rodillo Traccion Lado Motor (P)", "DE"),
            ("Eje interm Lado Libre Horizontal", "NDE"),
        ],
    )
    def test_the_phrase_fixes_the_side(self, name: str, expected: str) -> None:
        assert point_location(name) == expected

    def test_the_opposite_side_wins_over_the_motor_it_names(self) -> None:
        # "Lado Op Motor" contains "Motor": the NDE phrase is checked first.
        assert point_location("Eje Entrad Lado Op Motor Axial") == "NDE"


class TestUndeclaredSide:
    """Names that simply do not say which bearing they measure."""

    @pytest.mark.parametrize(
        "name",
        [
            "Campana Vertical",
            "Eje Entrada Horizontal",
            "Reductor Entrada Axial",
            "1º Eje Rodam Sup  Peakv 1000Hz",
            "Reductor Eje 2 Rodam Inf Horiz",
            "CONSUMO INTENSIDAD (A)",
        ],
    )
    def test_no_side_is_invented(self, name: str) -> None:
        assert point_location(name) is None

    def test_contradictory_evidence_resolves_to_none(self) -> None:
        assert point_location("MOTOR LA Y LOA HORIZONTAL") is None
        assert point_location("Motor LA Lado Libre Vertical") is None


class TestDirection:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("MOTOR LOA HORIZONTAL", "H"),
            ("MOTOR LA VERTICAL", "V"),
            ("MOTOR LA AXIAL", "A"),
            # Truncations forced by the 32-byte name field.
            ("Reductor LA Horiz", "H"),
            ("Reductor Eje Salida LOA Horizont", "H"),
            ("Reductor Eje Interm LA Horizonta", "H"),
            ("Reductor Eje Entrada LA Vert", "V"),
            ("Reductor Eje Salida LA Verti (P)", "V"),
            # Acquisition suffixes glued to the direction word.
            ("Reductor LA Horiz(P)", "H"),
            ("Reductor Eje Entr Vert (Varilla)", "V"),
            # Accented / mistyped names still normalize.
            ("Eje Entradaç Horizontal", "H"),
        ],
    )
    def test_the_direction_word_is_matched_by_prefix(self, name: str, expected: str) -> None:
        assert point_direction(name) == expected

    @pytest.mark.parametrize(
        "name",
        [
            "MOTOR LOA ALTA FRECUENCIA (HF)",
            "MOTOR LOA ALTA RESOLUCION (HR)",
            "Motor Lado Acople Peakvue",
            "Reductor Lado Motor [HF]",
            "Reductor Eje Entrada LA (HF)",
            # "(A)" is not the axial token.
            "CONSUMO INTENSIDAD (A)",
        ],
    )
    def test_an_acquisition_suffix_is_not_a_direction(self, name: str) -> None:
        assert point_direction(name) is None

    def test_two_directions_in_one_name_resolve_to_none(self) -> None:
        assert point_direction("MOTOR LA HORIZONTAL Y VERTICAL") is None


class TestParsePointName:
    def test_it_returns_both_fields(self) -> None:
        assert parse_point_name("BOMBA LOA VERTICAL PEAKVUE") == PointPlacement(
            location="NDE", direction="V"
        )

    def test_an_empty_name_declares_nothing(self) -> None:
        assert parse_point_name("") == PointPlacement(location=None, direction=None)


class TestRealCorpus:
    """The 232 distinct names of the 5 203 real points, one golden per name."""

    def test_the_corpus_is_the_whole_database(self, corpus: dict[str, Any]) -> None:
        assert corpus["distinct_names"] == len(corpus["names"]) == 232
        assert sum(e["points"] for e in corpus["names"]) == corpus["total_points"] == 5203

    def test_every_name_resolves_to_its_golden_placement(self, corpus: dict[str, Any]) -> None:
        wrong = [
            (e["name"], e["location"], e["direction"], parse_point_name(e["name"]))
            for e in corpus["names"]
            if parse_point_name(e["name"]) != PointPlacement(e["location"], e["direction"])
        ]
        assert not wrong

    def test_the_measured_coverage_does_not_regress(self, corpus: dict[str, Any]) -> None:
        total = corpus["total_points"]
        located = sum(e["points"] for e in corpus["names"] if e["location"])
        directed = sum(e["points"] for e in corpus["names"] if e["direction"])
        both = sum(e["points"] for e in corpus["names"] if e["location"] and e["direction"])
        # Exact figures of workplan 07; what is missing are names that carry
        # no placement at all, so these are ceilings for these rules, not
        # thresholds to chase.
        assert (located, directed, both) == (5108, 4220, 4169)
        assert (located / total, directed / total) == pytest.approx((0.9817, 0.8111), abs=1e-4)

    def test_only_the_contract_vocabulary_is_emitted(self, corpus: dict[str, Any]) -> None:
        placements = [parse_point_name(e["name"]) for e in corpus["names"]]
        assert {p.location for p in placements} <= {"DE", "NDE", None}
        assert {p.direction for p in placements} <= {"H", "V", "A", None}

    @pytest.mark.integration
    def test_the_corpus_still_matches_the_real_database(
        self, real_rbm: Path, corpus: dict[str, Any]
    ) -> None:
        """The committed fixture is the name inventory of the real .rbm."""
        with RbmReader(real_rbm) as reader:
            areas = walk_hierarchy(reader)
        counted = Counter(
            point.long_name for area in areas for eq in area.equipment for point in eq.points
        )
        assert counted == Counter({e["name"]: e["points"] for e in corpus["names"]})
