"""Integration tests for the area walker against the real BUNGE database.

Gated on ``RBM_TEST_FILE``. Asserts the parser output matches the area list
visible in AMS Machinery Manager (verified by the user via screenshots).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ams_extract.reader import RbmReader
from ams_extract.tree import walk_areas

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
