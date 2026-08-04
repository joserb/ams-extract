"""Unit tests for the point-chain parsers (gipm / vdpm)."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from ams_extract.reader import RECORD_SIZE, RbmReader
from ams_extract.records.point import (
    BEARING_UNSET,
    GIPM_MAX_POINTS,
    GIPM_POINTERS_OFFSET,
    GIPM_TAG,
    TAG_OFFSET,
    VDPM_BEARING_COUNT_OFFSET,
    VDPM_BEARING_OFFSET,
    VDPM_BEARING_SLOT_SIZE,
    VDPM_BEARING_SLOTS,
    VDPM_NAME_LENGTH,
    VDPM_NAME_OFFSET,
    VDPM_NOMINAL_RPM_OFFSET,
    VDPM_TAG,
    PointChainError,
    parse_gipm_point_records,
    parse_vdpm_bearings,
    parse_vdpm_nominal_rpm,
    parse_vdpm_point,
)
from ams_extract.tree import walk_hierarchy


def _empty_record() -> bytearray:
    return bytearray(RECORD_SIZE)


def _make_header() -> bytes:
    record = _empty_record()
    record[0x1C : 0x1C + 6] = b"MT4.00"
    return bytes(record)


def _make_gipm(pointers_stored: list[int]) -> bytes:
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = GIPM_TAG
    for i, ptr in enumerate(pointers_stored):
        struct.pack_into("<I", record, GIPM_POINTERS_OFFSET + i * 4, ptr)
    return bytes(record)


def _make_vdpm(
    name: bytes,
    *,
    bearings: list[bytes] | None = None,
    bearing_count: int | None = None,
    nominal_rpm: float | None = None,
) -> bytes:
    """Build a ``vdpm`` record the way AMS lays one out.

    Unset bearing slots get the ``INDEFINID`` sentinel, exactly as in the
    real database; ``bearing_count`` overrides the count byte so the
    "count wins over content" behaviour can be exercised.
    """
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = VDPM_TAG
    slot = bytearray(b" " * VDPM_NAME_LENGTH)
    slot[: len(name)] = name
    record[VDPM_NAME_OFFSET : VDPM_NAME_OFFSET + VDPM_NAME_LENGTH] = bytes(slot)

    filled = bearings or []
    for i in range(VDPM_BEARING_SLOTS):
        text = filled[i] if i < len(filled) else BEARING_UNSET.encode("cp1252")
        padded = bytearray(b" " * VDPM_BEARING_SLOT_SIZE)
        padded[: len(text)] = text
        start = VDPM_BEARING_OFFSET + i * VDPM_BEARING_SLOT_SIZE
        record[start : start + VDPM_BEARING_SLOT_SIZE] = bytes(padded)
    record[VDPM_BEARING_COUNT_OFFSET] = (
        len(filled) if bearing_count is None else bearing_count
    )

    if nominal_rpm is not None:
        struct.pack_into("<f", record, VDPM_NOMINAL_RPM_OFFSET, nominal_rpm)
    return bytes(record)


@pytest.fixture
def reader_factory(tmp_path: Path):
    def make(records: list[bytes]) -> RbmReader:
        rbm = tmp_path / "fixture.rbm"
        rbm.write_bytes(b"".join(records))
        return RbmReader(rbm)

    return make


class TestParseGipmPointRecords:
    def test_decodes_each_pointer_to_zero_based_record(
        self, reader_factory
    ) -> None:
        # 3 point pointers stored as +1 -> base-0 records 9, 19, 29.
        gipm = _make_gipm(pointers_stored=[10, 20, 30])
        records = [_make_header(), gipm] + [_empty_record()] * 30
        with reader_factory(records) as reader:
            assert parse_gipm_point_records(reader, 1) == [9, 19, 29]

    def test_stops_at_first_null_pointer(self, reader_factory) -> None:
        gipm = _make_gipm(pointers_stored=[10, 0, 30])
        records = [_make_header(), gipm] + [_empty_record()] * 30
        with reader_factory(records) as reader:
            assert parse_gipm_point_records(reader, 1) == [9]

    def test_reads_up_to_max_capacity(self, reader_factory) -> None:
        # Saturating the table at the documented capacity ensures we don't
        # silently truncate at a smaller, accidental bound.
        pointers = list(range(1, GIPM_MAX_POINTS + 1))
        gipm = _make_gipm(pointers_stored=pointers)
        records = [_make_header(), gipm] + [_empty_record()] * GIPM_MAX_POINTS
        with reader_factory(records) as reader:
            assert parse_gipm_point_records(reader, 1) == list(
                range(GIPM_MAX_POINTS)
            )

    def test_rejects_record_with_wrong_tag(self, reader_factory) -> None:
        records = [_make_header(), _empty_record()] + [_empty_record()] * 14
        with reader_factory(records) as reader, pytest.raises(PointChainError):
            parse_gipm_point_records(reader, 1)


class TestParseVdpmPoint:
    def test_decodes_point_name_and_records_record_num(
        self, reader_factory
    ) -> None:
        vdpm = _make_vdpm(b"MOTOR LA HORIZONTAL")
        records = [_make_header(), vdpm] + [_empty_record()] * 14
        with reader_factory(records) as reader:
            point = parse_vdpm_point(reader, 1)
        assert point.record_num == 1
        assert point.long_name == "MOTOR LA HORIZONTAL"

    def test_strips_trailing_padding(self, reader_factory) -> None:
        # Name field is exactly VDPM_NAME_LENGTH bytes but only the prefix
        # is meaningful; the rest is space-padding that must be stripped.
        vdpm = _make_vdpm(b"BOMBA LA VERTICAL PEAKVUE")
        records = [_make_header(), vdpm] + [_empty_record()] * 14
        with reader_factory(records) as reader:
            point = parse_vdpm_point(reader, 1)
        # No trailing whitespace.
        assert point.long_name == point.long_name.rstrip()
        assert point.long_name == "BOMBA LA VERTICAL PEAKVUE"

    def test_rejects_record_with_wrong_tag(self, reader_factory) -> None:
        records = [_make_header(), _empty_record()] + [_empty_record()] * 14
        with reader_factory(records) as reader, pytest.raises(PointChainError):
            parse_vdpm_point(reader, 1)


class TestParseVdpmBearings:
    """``vdpm.0x07E`` — the seven designation slots and their count byte."""

    def test_reads_the_filled_slots_in_order(self, reader_factory) -> None:
        # AG-100 MOTOR LOA HORIZONTAL, the gold of FORMAT §5.8.
        vdpm = _make_vdpm(b"MOTOR LOA HORIZONTAL", bearings=[b"6204", b"6208"])
        records = [_make_header(), vdpm] + [_empty_record()] * 14
        with reader_factory(records) as reader:
            assert parse_vdpm_bearings(reader, 1) == ("6204", "6208")

    def test_a_point_without_bearings_returns_empty(self, reader_factory) -> None:
        # 3 683 of the 5 203 Bunge points: the normal case, not an error.
        vdpm = _make_vdpm(b"MOTOR LA VERTICAL")
        records = [_make_header(), vdpm] + [_empty_record()] * 14
        with reader_factory(records) as reader:
            assert parse_vdpm_bearings(reader, 1) == ()

    def test_free_text_designations_come_back_raw(self, reader_factory) -> None:
        # Makers, suffixes and the odd non-designation, all seen in Bunge.
        vdpm = _make_vdpm(
            b"Reductor Eje Entrada Horiz",
            bearings=[b"RED", b"QJ322N2", b"SKF 6308", b"6205/2Z", b"22218 EKC3"],
        )
        records = [_make_header(), vdpm] + [_empty_record()] * 14
        with reader_factory(records) as reader:
            assert parse_vdpm_bearings(reader, 1) == (
                "RED",
                "QJ322N2",
                "SKF 6308",
                "6205/2Z",
                "22218 EKC3",
            )

    def test_the_count_byte_bounds_the_read(self, reader_factory) -> None:
        # Slots past the count are sentinel-filled in Bunge; honour the count
        # even if a stale designation survived in a slot behind it.
        vdpm = _make_vdpm(
            b"MOTOR LOA HORIZONTAL",
            bearings=[b"6204", b"6208", b"6309"],
            bearing_count=2,
        )
        records = [_make_header(), vdpm] + [_empty_record()] * 14
        with reader_factory(records) as reader:
            assert parse_vdpm_bearings(reader, 1) == ("6204", "6208")

    def test_a_count_over_the_slot_table_is_clamped(self, reader_factory) -> None:
        vdpm = _make_vdpm(b"MOTOR", bearings=[b"6204"], bearing_count=200)
        records = [_make_header(), vdpm] + [_empty_record()] * 14
        with reader_factory(records) as reader:
            assert parse_vdpm_bearings(reader, 1) == ("6204",)

    def test_the_sentinel_is_never_returned(self, reader_factory) -> None:
        vdpm = _make_vdpm(b"MOTOR", bearings=[b"6204"], bearing_count=VDPM_BEARING_SLOTS)
        records = [_make_header(), vdpm] + [_empty_record()] * 14
        with reader_factory(records) as reader:
            assert parse_vdpm_bearings(reader, 1) == ("6204",)

    def test_rejects_record_with_wrong_tag(self, reader_factory) -> None:
        records = [_make_header(), _empty_record()] + [_empty_record()] * 14
        with reader_factory(records) as reader, pytest.raises(PointChainError):
            parse_vdpm_bearings(reader, 1)


class TestParseVdpmNominalRpm:
    """``vdpm.0x164`` — the configured shaft speed, in RPM."""

    @pytest.mark.parametrize("rpm", [1455.0, 2900.0, 32.0, 9.6, 3000.0])
    def test_reads_the_float32_as_rpm(self, reader_factory, rpm: float) -> None:
        vdpm = _make_vdpm(b"MOTOR LOA HORIZONTAL", nominal_rpm=rpm)
        records = [_make_header(), vdpm] + [_empty_record()] * 14
        with reader_factory(records) as reader:
            assert parse_vdpm_nominal_rpm(reader, 1) == pytest.approx(rpm)

    def test_the_field_is_little_endian_float32(self, reader_factory) -> None:
        # The exact bytes of AG-100's 1 455 RPM, straight out of the database.
        record = bytearray(_make_vdpm(b"MOTOR LOA HORIZONTAL"))
        record[VDPM_NOMINAL_RPM_OFFSET : VDPM_NOMINAL_RPM_OFFSET + 4] = bytes(
            (0x00, 0xE0, 0xB5, 0x44)
        )
        records = [_make_header(), bytes(record)] + [_empty_record()] * 14
        with reader_factory(records) as reader:
            assert parse_vdpm_nominal_rpm(reader, 1) == 1455.0

    @pytest.mark.parametrize("rpm", [0.0, -1.0])
    def test_a_non_positive_speed_is_no_speed(self, reader_factory, rpm: float) -> None:
        vdpm = _make_vdpm(b"MOTOR", nominal_rpm=rpm)
        records = [_make_header(), vdpm] + [_empty_record()] * 14
        with reader_factory(records) as reader:
            assert parse_vdpm_nominal_rpm(reader, 1) is None

    def test_rejects_record_with_wrong_tag(self, reader_factory) -> None:
        records = [_make_header(), _empty_record()] + [_empty_record()] * 14
        with reader_factory(records) as reader, pytest.raises(PointChainError):
            parse_vdpm_nominal_rpm(reader, 1)


@pytest.mark.integration
class TestVdpmPointConfigOnTheRealDatabase:
    """The two decodes against BUNGE CARTAGENA and its AMS golds."""

    @staticmethod
    def _points(reader: RbmReader) -> dict[tuple[str, str], int]:
        """Record number by (equipment, point) name, for the named golds."""
        return {
            (equipment.long_name, point.long_name): point.record_num
            for area in walk_hierarchy(reader)
            for equipment in area.equipment
            for point in equipment.points
        }

    @staticmethod
    def _every_point(reader: RbmReader) -> list[int]:
        """Every point record of the database (names repeat; records don't)."""
        return [
            point.record_num
            for area in walk_hierarchy(reader)
            for equipment in area.equipment
            for point in equipment.points
        ]

    def test_the_pilot_point_carries_its_documented_bearings(self, real_rbm: Path) -> None:
        # FORMAT §5.8 records 6204/6208 for AG-100; the LA points of the same
        # motor differ in the first slot, so the field is per point, not per
        # machine.
        with RbmReader(real_rbm) as reader:
            points = self._points(reader)
            loa = points[("MECLADOR AGITADOR AG-100", "MOTOR LOA HORIZONTAL")]
            la = points[("MECLADOR AGITADOR AG-100", "MOTOR LA VERTICAL")]
            assert parse_vdpm_bearings(reader, loa) == ("6204", "6208")
            assert parse_vdpm_bearings(reader, la) == ("6205", "6208")

    def test_the_nominal_speed_matches_the_ams_screenshot(self, real_rbm: Path) -> None:
        # ADR-0013's gold: AMS shows "RPM = 2900,0 (48,33 Hz)" for PM-9101-A
        # M1H, and 1 455 for the AG-100 pilot of FORMAT §5.
        with RbmReader(real_rbm) as reader:
            points = self._points(reader)
            pm9101 = points[("Bomba Centrifuga PM-9101-A", "MOTOR LOA HORIZONTAL")]
            ag100 = points[("MECLADOR AGITADOR AG-100", "MOTOR LOA HORIZONTAL")]
            assert parse_vdpm_nominal_rpm(reader, pm9101) == 2900.0
            assert parse_vdpm_nominal_rpm(reader, ag100) == 1455.0

    def test_every_point_declares_a_speed_and_a_consistent_bearing_count(
        self, real_rbm: Path
    ) -> None:
        with RbmReader(real_rbm) as reader:
            record_nums = self._every_point(reader)
            speeds = [parse_vdpm_nominal_rpm(reader, n) for n in record_nums]
            bearings = [parse_vdpm_bearings(reader, n) for n in record_nums]
            counts = [reader.read_record(n)[VDPM_BEARING_COUNT_OFFSET] for n in record_nums]

        # Every one of the 5 203 points has a nominal speed, 9-3 000 RPM.
        assert len(record_nums) == 5203
        assert all(rpm is not None and 9.0 <= rpm <= 3000.0 for rpm in speeds)
        # The count byte and the sentinel agree slot for slot: no designation
        # is dropped and none is invented.
        assert [len(b) for b in bearings] == counts
        assert sum(1 for b in bearings if b) == 1520
