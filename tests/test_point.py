"""Unit tests for the point-chain parsers (gipm / vdpm)."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from ams_extract.reader import RECORD_SIZE, RbmReader
from ams_extract.records.point import (
    GIPM_MAX_POINTS,
    GIPM_POINTERS_OFFSET,
    GIPM_TAG,
    TAG_OFFSET,
    VDPM_NAME_LENGTH,
    VDPM_NAME_OFFSET,
    VDPM_TAG,
    PointChainError,
    parse_gipm_point_records,
    parse_vdpm_point,
)


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


def _make_vdpm(name: bytes) -> bytes:
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = VDPM_TAG
    slot = bytearray(b" " * VDPM_NAME_LENGTH)
    slot[: len(name)] = name
    record[VDPM_NAME_OFFSET : VDPM_NAME_OFFSET + VDPM_NAME_LENGTH] = bytes(slot)
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
