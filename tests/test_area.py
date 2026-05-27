"""Tests for ``ams_extract.records.area``."""

from __future__ import annotations

from pathlib import Path

from ams_extract.reader import RECORD_SIZE, RbmReader
from ams_extract.records.area import (
    SLOT_SIZE,
    SLOTS_PER_RECORD,
    _looks_like_name,
    is_prefixed_list_record,
    parse_area_record,
    parse_gdts_pointer_table,
)


class TestLooksLikeName:
    def test_accepts_ascii_padded_name(self) -> None:
        slot = b"FULL-FAT" + b" " * 24
        assert _looks_like_name(slot) is True

    def test_accepts_cp1252_accented_name(self) -> None:
        # 0xD3 = 'Ó' in cp1252 — must be accepted.
        slot = b"IMPULSI\xd3N DE MAR" + b" " * 17
        assert _looks_like_name(slot) is True

    def test_rejects_empty_slot(self) -> None:
        assert _looks_like_name(b" " * SLOT_SIZE) is False
        assert _looks_like_name(b"\x00" * SLOT_SIZE) is False

    def test_rejects_control_bytes(self) -> None:
        slot = b"HELLO\x01WORLD" + b" " * 21
        assert _looks_like_name(slot) is False

    def test_rejects_pure_digits_or_punctuation(self) -> None:
        slot = b"1234567890" + b" " * 22
        assert _looks_like_name(slot) is False

    def test_rejects_single_letter(self) -> None:
        slot = b"A" + b" " * 31
        assert _looks_like_name(slot) is False


class TestParseAreaRecord:
    def test_simple_layout_extracts_three_areas(self, synthetic_rbm: Path) -> None:
        # Record 1 in the synthetic fixture holds three areas at slots 0-2.
        with RbmReader(synthetic_rbm) as reader:
            slots = parse_area_record(reader, 1)
        assert [s.slot_index for s in slots] == [0, 1, 2]
        assert [s.name for s in slots] == ["AREA_ALPHA", "AREA_BETA", "AREA_GAMMA"]

    def test_simple_layout_skips_trailing_short_code_slot(
        self, synthetic_rbm: Path
    ) -> None:
        # Slot 12 of record 1 holds a fake short-code list ("AAAA BBBB ...").
        # The "stop after first non-name slot following a found slot" heuristic
        # must skip it.
        with RbmReader(synthetic_rbm) as reader:
            slots = parse_area_record(reader, 1)
        assert all(s.slot_index < 12 for s in slots)
        assert "AAAA" not in {s.name for s in slots}

    def test_prefixed_layout_skips_binary_prefix(self, synthetic_rbm: Path) -> None:
        # Record 2 has binary header bytes in slots 0-5, names at slots 6-7.
        with RbmReader(synthetic_rbm) as reader:
            slots = parse_area_record(reader, 2)
        assert [s.slot_index for s in slots] == [6, 7]
        assert [s.name for s in slots] == ["AREA_DELTA", "AREA_OMEGA"]

    def test_slot_geometry_invariants(self) -> None:
        assert SLOT_SIZE == 32
        assert SLOTS_PER_RECORD * SLOT_SIZE == RECORD_SIZE


class TestIsPrefixedListRecord:
    def test_record_2_in_fixture_is_prefixed_list(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader:
            assert is_prefixed_list_record(reader, 2) is True

    def test_record_1_in_fixture_is_simple_list(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader:
            assert is_prefixed_list_record(reader, 1) is False


class TestParseGdtsPointerTable:
    def test_returns_decoded_zero_based_record_numbers(
        self, synthetic_rbm: Path
    ) -> None:
        # The synthetic prefix-list record stores two "+1" pointers
        # (100 and 200) — decoded to base-0 records 99 and 199.
        with RbmReader(synthetic_rbm) as reader:
            pointers = parse_gdts_pointer_table(reader, 2)
        assert pointers == [99, 199]
