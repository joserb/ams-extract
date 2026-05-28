"""Integration tests for the area walker against the real BUNGE database.

Gated on ``RBM_TEST_FILE``. Asserts the parser output matches the area list
visible in AMS Machinery Manager (verified by the user via screenshots).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ams_extract.reader import RbmReader
from ams_extract.tree import walk_areas, walk_hierarchy

pytestmark = pytest.mark.integration

EXPECTED_AREA_LONG_NAMES = (
    "CONTRA INCENDIOS",
    "EXTRACCION",
    "DEPURADORA",
    "IMPULSIÓN DE MAR",
    "NAVES",
    "PASILLO DE BOMBAS",
    "PELETIZACION",
    "PREPARACION",
    "REFINERIA",
    "CALDERAS",
    "FULL-FAT",
    "PARQUE TANQUES",
    "OBSOLETOS",
    "SERVICIOS",
    "OSMOSIS",
)
"""The 15 area long-names visible in the AMS UI for BUNGE, in walker order."""


def test_real_file_yields_fifteen_areas(real_rbm: Path) -> None:
    with RbmReader(real_rbm) as reader:
        areas = walk_areas(reader)
    assert len(areas) == 15
    assert tuple(a.long_name for a in areas) == EXPECTED_AREA_LONG_NAMES


def test_real_file_short_codes_unique(real_rbm: Path) -> None:
    with RbmReader(real_rbm) as reader:
        areas = walk_areas(reader)
    codes = [a.short_code for a in areas]
    assert len(set(codes)) == len(codes)


def test_real_file_includes_accented_name(real_rbm: Path) -> None:
    # Regression for the cp1252-aware name filter: 'IMPULSIÓN DE MAR'
    # contains 0xD3 ('Ó') and must be detected.
    with RbmReader(real_rbm) as reader:
        areas = walk_areas(reader)
    long_names = [a.long_name for a in areas]
    assert "IMPULSIÓN DE MAR" in long_names


# --- Phase 2b: full hierarchy walk ---

# Counts measured against BUNGE CARTAGENA marzo 2.0.rbm after the gicm
# 20-slot continuation fix. The earlier 12-slot model under-counted by
# 91 equipment (~26%) — the largest areas (EXTRACCION, PREPARACION,
# REFINERIA) had chunks with 13-20 equipment whose names spill over to
# the gicm's continuation record.
BUNGE_EQUIPMENT_COUNT = 347
BUNGE_TOTAL_POINTS = 5203
BUNGE_PEAKVUE_POINTS = 1198

BUNGE_EQUIPMENT_PER_AREA = {
    "CONTRA INCENDIOS": 4,
    "EXTRACCION": 53,
    "DEPURADORA": 28,
    "IMPULSIÓN DE MAR": 4,
    "NAVES": 18,
    "PASILLO DE BOMBAS": 5,
    "PELETIZACION": 10,
    "PREPARACION": 87,
    "REFINERIA": 90,
    "CALDERAS": 11,
    "FULL-FAT": 12,
    "PARQUE TANQUES": 5,
    "OBSOLETOS": 12,
    "SERVICIOS": 6,
    "OSMOSIS": 2,
}


def test_real_file_walk_hierarchy_counts(real_rbm: Path) -> None:
    with RbmReader(real_rbm) as reader:
        areas = walk_hierarchy(reader)
    assert len(areas) == 15
    equipment_count = sum(len(a.equipment) for a in areas)
    point_count = sum(len(eq.points) for a in areas for eq in a.equipment)
    assert equipment_count == BUNGE_EQUIPMENT_COUNT
    assert point_count == BUNGE_TOTAL_POINTS


def test_real_file_equipment_count_per_area(real_rbm: Path) -> None:
    # Catches a regression of the 12-vs-20 slot bug as soon as it
    # changes any area's count, not just the totals.
    with RbmReader(real_rbm) as reader:
        areas = walk_hierarchy(reader)
    actual = {a.long_name: len(a.equipment) for a in areas}
    assert actual == BUNGE_EQUIPMENT_PER_AREA


def test_real_file_peakvue_point_count_within_tolerance(real_rbm: Path) -> None:
    with RbmReader(real_rbm) as reader:
        areas = walk_hierarchy(reader)
    peakvue_count = sum(
        1
        for a in areas
        for eq in a.equipment
        for p in eq.points
        if "PEAKVUE" in p.long_name.upper()
    )
    # Stable measurement from the live walker — guard with an exact match so
    # an accidental regression in the chain walker (skipping gicm chunks,
    # losing a point, etc.) trips the test immediately.
    assert peakvue_count == BUNGE_PEAKVUE_POINTS


def test_real_file_contra_incendios_has_four_pumps(real_rbm: Path) -> None:
    # CONTRA INCENDIOS is the smallest, fully verified area: 4 firefighting
    # pumps. Using it as a stable spot-check for equipment-name decoding.
    with RbmReader(real_rbm) as reader:
        areas = walk_hierarchy(reader)
    by_name = {a.long_name: a for a in areas}
    contra = by_name["CONTRA INCENDIOS"]
    equipment_names = [eq.long_name for eq in contra.equipment]
    assert equipment_names == [
        "Bomba Centrifuga PM-0CI/1",
        "Bomba Centrifuga PM-0CI/2",
        "Bomba Centrifuga PM-0CI/3",
        "Bomba Centrifuga PM-JO/CI",
    ]


def test_real_file_first_equipment_point_names(real_rbm: Path) -> None:
    # Spot-check that the vdpm name field is decoded correctly.
    with RbmReader(real_rbm) as reader:
        areas = walk_hierarchy(reader)
    contra = next(a for a in areas if a.long_name == "CONTRA INCENDIOS")
    first_pump = contra.equipment[0]
    point_names = [p.long_name for p in first_pump.points]
    assert point_names[0] == "MOTOR LOA HORIZONTAL"
    # Several PEAKVUE points must appear — this validates that the trailing
    # ASCII padding is stripped correctly even for longer names.
    assert any("PEAKVUE" in name for name in point_names)


def test_real_file_depuradora_includes_expected_machines(real_rbm: Path) -> None:
    # DEPURADORA equipment list matches the user's AMS screenshot.
    # PM-501 is specifically the equipment that revealed the 12-vs-20
    # slot bug: it lives at slot 12 of chunk 0, so its name overflows to
    # the gicm's continuation record. Keep it in the asserted set so a
    # regression in the overflow reader trips this test.
    with RbmReader(real_rbm) as reader:
        areas = walk_hierarchy(reader)
    depuradora = next(a for a in areas if a.long_name == "DEPURADORA")
    names = {eq.long_name for eq in depuradora.equipment}
    for expected in (
        "MECLADOR AGITADOR AG-100",
        "CENTRIF HORIZONTAL CF-4900",
        "CENTRIF HORIZONTAL CF-5900",
        "Bomba Centrifuga PM-100",
        "Bomba Centrifuga PM-101",
        "Bomba Centrifuga PM-501",  # first equipment in the overflow region
        "Bomba Centrifuga PM-5502",  # last equipment in the overflow region
        "MOTOR REDUCTOR RAS-500",
        "Tornillo deshidr TRD.10100",
    ):
        assert expected in names, f"missing equipment in DEPURADORA: {expected!r}"
