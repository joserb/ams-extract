"""Tests for ``ams_extract.tree.walk_areas``."""

from __future__ import annotations

from pathlib import Path

from ams_extract.reader import RbmReader
from ams_extract.tree import walk_areas


class TestWalkAreasSynthetic:
    def test_collects_five_areas_from_both_records(
        self, synthetic_rbm: Path
    ) -> None:
        with RbmReader(synthetic_rbm) as reader:
            areas = walk_areas(reader)
        long_names = [a.long_name for a in areas]
        assert long_names == [
            "AREA_ALPHA",
            "AREA_BETA",
            "AREA_GAMMA",
            "AREA_DELTA",
            "AREA_OMEGA",
        ]

    def test_short_codes_are_unique_and_sanitized(
        self, synthetic_rbm: Path
    ) -> None:
        with RbmReader(synthetic_rbm) as reader:
            areas = walk_areas(reader)
        codes = [a.short_code for a in areas]
        assert len(set(codes)) == len(codes), "short codes must be unique"
        assert all(code.replace("_", "").isalnum() for code in codes)

    def test_ordering_is_by_record_then_slot(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader:
            areas = walk_areas(reader)
        keys = [(a.record_num, a.slot_index) for a in areas]
        assert keys == sorted(keys)

    def test_handles_duplicate_pointers_without_double_counting(
        self, tmp_path: Path
    ) -> None:
        # Build a fixture where primary and secondary pointers both target
        # record 1 — the walker should not emit the same area twice.
        from ams_extract.reader import RECORD_SIZE

        record0 = bytearray(b"\x00" * RECORD_SIZE)
        record0[0x1C:0x22] = b"MT4.00"
        # both pointers -> record 1
        record0[0xDC:0xE0] = (1).to_bytes(4, "little")
        record0[0xE4:0xE8] = (1).to_bytes(4, "little")

        record1 = bytearray(b"\x00" * RECORD_SIZE)
        record1[0:32] = b"AREA_ONE" + b" " * 24

        path = tmp_path / "dup.rbm"
        path.write_bytes(bytes(record0) + bytes(record1))

        with RbmReader(path) as reader:
            areas = walk_areas(reader)
        assert [a.long_name for a in areas] == ["AREA_ONE"]
