"""The inferred-bearing input file is arithmetic, and arithmetic can be checked.

``overlays/bunge-cartagena-2026.bearings-llm.input.json`` is geometry an LLM
inferred for the standard bearings the ecosystem catalog does not carry
(workplan 11). It is consumed by another repo's tool (``vibsynth-machines
enrich --input``), so what this repo can protect is what the file *claims*:
that every entry is a bearing whose fault orders come out consistent.

The identity ``BPFO + BPFI = Z`` holds for any geometry, so it is not a proof
that the geometry is right — it is the check that catches a typo in a number
nobody would otherwise read again.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

INPUT_FILE = Path(__file__).resolve().parents[1] / "overlays" / (
    "bunge-cartagena-2026.bearings-llm.input.json"
)


def _orders(entry: dict[str, Any]) -> dict[str, float]:
    """The four fault orders of a geometry, as the enricher computes them."""
    z = entry["n_balls"]
    ratio = entry["d_ball_mm"] / entry["d_pitch_mm"] * math.cos(
        math.radians(entry["contact_angle_deg"])
    )
    return {
        "BPFO": z / 2 * (1 - ratio),
        "BPFI": z / 2 * (1 + ratio),
        "BSF": entry["d_pitch_mm"] / (2 * entry["d_ball_mm"]) * (1 - ratio**2),
        "FTF": (1 - ratio) / 2,
    }


@pytest.fixture(scope="module")
def bearings() -> dict[str, dict[str, Any]]:
    document = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    assert set(document) == {"bearings"}, "the enricher forbids any other top-level key"
    return document["bearings"]


class TestInferredBearings:
    def test_every_entry_is_geometry_not_a_promise(
        self, bearings: dict[str, dict[str, Any]]
    ) -> None:
        assert bearings
        for key, entry in bearings.items():
            assert entry["model"] == key, key
            assert entry["n_balls"] >= 3, key
            assert 0 < entry["d_ball_mm"] < entry["d_pitch_mm"], key
            assert entry["contact_angle_deg"] == 0.0, key

    def test_the_orders_pass_the_sanity_check(
        self, bearings: dict[str, dict[str, Any]]
    ) -> None:
        for key, entry in bearings.items():
            orders = _orders(entry)
            # A ball passes either race once per revolution of the cage
            # relative to the other one: the two counts add up to Z.
            assert orders["BPFO"] + orders["BPFI"] == pytest.approx(entry["n_balls"]), key
            # The cage always turns slower than half the shaft.
            assert 0 < orders["FTF"] < 0.5, key
            assert 1.0 < orders["BSF"] < entry["n_balls"] / 2, key

    def test_the_declared_orders_are_the_ones_the_geometry_gives(
        self, bearings: dict[str, dict[str, Any]]
    ) -> None:
        # `_orders` is documentation, and documentation that drifts is worse
        # than none: it is what a reader compares against the catalog.
        for key, entry in bearings.items():
            computed = _orders(entry)
            for role, value in entry["_orders"].items():
                assert value == pytest.approx(computed[role], abs=5e-5), f"{key}:{role}"

    def test_every_entry_says_where_it_comes_from(
        self, bearings: dict[str, dict[str, Any]]
    ) -> None:
        for key, entry in bearings.items():
            assert entry["_provenance"] == "llm-inference", key
            assert entry["_basis"], key
            # The designation as AMS spells it, which is what the enricher
            # normalises to this key.
            assert entry["_designations"], key
            assert any(key in text.upper() for text in entry["_designations"]), key

    def test_the_bore_and_od_are_the_pitch_diameter_it_declares(
        self, bearings: dict[str, dict[str, Any]]
    ) -> None:
        for key, entry in bearings.items():
            bore, outer = entry["_bore_od_mm"]
            assert bore < outer, key
            assert entry["d_pitch_mm"] == pytest.approx((bore + outer) / 2), key
            assert entry["d_ball_mm"] == pytest.approx(0.3175 * (outer - bore), abs=0.005), key
