"""Tests for ``ams_extract.naming``."""

from __future__ import annotations

from ams_extract.naming import NameSanitizer, sanitize


class TestBasicSanitize:
    def test_strips_accents(self) -> None:
        assert sanitize("IMPULSIÓN DE MAR") == "IMPULSION_DE_MAR"

    def test_replaces_spaces(self) -> None:
        assert sanitize("PARQUE TANQUES") == "PARQUE_TANQUES"

    def test_collapses_repeated_separators(self) -> None:
        assert sanitize("A -- B / C") == "A_B_C"

    def test_strips_leading_trailing_underscores(self) -> None:
        assert sanitize("---HELLO---") == "HELLO"

    def test_empty_input_yields_placeholder(self) -> None:
        assert sanitize("") == "unnamed"
        assert sanitize("   ") == "unnamed"
        assert sanitize("////") == "unnamed"

    def test_truncates_to_max_length(self) -> None:
        long_name = "A" * 200
        result = sanitize(long_name)
        assert len(result) == 64

    def test_preserves_hyphen_aware_naming(self) -> None:
        # Hyphens collapse to underscore — FULL-FAT -> FULL_FAT.
        assert sanitize("FULL-FAT") == "FULL_FAT"


class TestSanitizerCollision:
    def test_first_collision_gets_numeric_suffix(self) -> None:
        s = NameSanitizer()
        assert s.sanitize("AREA X") == "AREA_X"
        assert s.sanitize("AREA X") == "AREA_X_1"
        assert s.sanitize("AREA X") == "AREA_X_2"

    def test_unrelated_names_unaffected(self) -> None:
        s = NameSanitizer()
        assert s.sanitize("ALPHA") == "ALPHA"
        assert s.sanitize("BETA") == "BETA"
        assert s.sanitize("ALPHA") == "ALPHA_1"

    def test_accented_collision_after_normalization(self) -> None:
        # 'EXTRACCIÓN' and 'EXTRACCION' collide post-normalization.
        s = NameSanitizer()
        assert s.sanitize("EXTRACCIÓN") == "EXTRACCION"
        assert s.sanitize("EXTRACCION") == "EXTRACCION_1"
