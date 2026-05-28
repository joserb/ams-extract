"""Unit tests for the equipment-chain parsers (gdts / gicm / gdcm)."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from ams_extract.reader import RECORD_SIZE, RbmReader
from ams_extract.records.equipment import (
    GDCM_GIPM_POINTER_OFFSET,
    GDCM_TAG,
    GDTS_GICM_POINTER_OFFSET,
    GDTS_TAG,
    GICM_CONTINUATION_NAMES_OFFSET,
    GICM_GDCM_POINTERS_OFFSET,
    GICM_MAX_SLOTS_PER_CHUNK,
    GICM_NAME_SLOT_SIZE,
    GICM_NAMES_IN_HEADER_RECORD,
    GICM_NAMES_OFFSET,
    GICM_NEXT_POINTER_OFFSET,
    GICM_TAG,
    TAG_OFFSET,
    EquipmentChainError,
    parse_gdcm_gipm_pointer,
    parse_gdts_gicm_pointer,
    parse_gicm_equipment_slots,
)


def _empty_record() -> bytearray:
    """Return a 512-byte zero buffer suitable for a synthetic record."""
    return bytearray(RECORD_SIZE)


def _make_gdts(gicm_pointer_stored: int) -> bytes:
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = GDTS_TAG
    struct.pack_into("<I", record, GDTS_GICM_POINTER_OFFSET, gicm_pointer_stored)
    return bytes(record)


def _make_gicm(
    *,
    gdcm_pointers_stored: list[int],
    names: list[bytes],
    next_pointer_stored: int = 0,
) -> list[bytes]:
    """Build the 1-or-2 physical records that make up one logical gicm chunk.

    Returns a list of 512-byte records: just the gicm record when there
    are ≤12 names, or the gicm record + its continuation record when
    there are 13-20 names.
    """
    if len(gdcm_pointers_stored) > GICM_MAX_SLOTS_PER_CHUNK:
        raise AssertionError(
            f"a gicm chunk holds at most {GICM_MAX_SLOTS_PER_CHUNK} slots"
        )
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = GICM_TAG
    struct.pack_into(
        "<I", record, GICM_NEXT_POINTER_OFFSET, next_pointer_stored
    )
    for i, ptr in enumerate(gdcm_pointers_stored):
        struct.pack_into(
            "<I", record, GICM_GDCM_POINTERS_OFFSET + i * 4, ptr
        )
    for i, name in enumerate(names[:GICM_NAMES_IN_HEADER_RECORD]):
        off = GICM_NAMES_OFFSET + i * GICM_NAME_SLOT_SIZE
        slot = bytearray(b" " * GICM_NAME_SLOT_SIZE)
        slot[: len(name)] = name
        record[off : off + GICM_NAME_SLOT_SIZE] = bytes(slot)

    overflow = names[GICM_NAMES_IN_HEADER_RECORD:]
    if not overflow:
        return [bytes(record)]
    continuation = _empty_record()
    for i, name in enumerate(overflow):
        off = GICM_CONTINUATION_NAMES_OFFSET + i * GICM_NAME_SLOT_SIZE
        slot = bytearray(b" " * GICM_NAME_SLOT_SIZE)
        slot[: len(name)] = name
        continuation[off : off + GICM_NAME_SLOT_SIZE] = bytes(slot)
    return [bytes(record), bytes(continuation)]


def _make_gdcm(gipm_pointer_stored: int) -> bytes:
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = GDCM_TAG
    struct.pack_into("<I", record, GDCM_GIPM_POINTER_OFFSET, gipm_pointer_stored)
    return bytes(record)


def _make_header() -> bytes:
    """Minimal valid header — needed because RbmReader doesn't accept arbitrary files,
    but the tests for equipment parsers don't actually go through the header."""
    record = _empty_record()
    record[0x1C : 0x1C + 6] = b"MT4.00"
    return bytes(record)


def _write_records(path: Path, records: list[bytes]) -> None:
    if any(len(r) != RECORD_SIZE for r in records):
        raise AssertionError("all synthetic records must be exactly 512 bytes")
    path.write_bytes(b"".join(records))


@pytest.fixture
def reader_factory(tmp_path: Path):
    def make(records: list[bytes]) -> RbmReader:
        rbm = tmp_path / "fixture.rbm"
        _write_records(rbm, records)
        return RbmReader(rbm)

    return make


class TestParseGdtsGicmPointer:
    def test_returns_zero_based_record_number_from_stored_plus_one(
        self, reader_factory
    ) -> None:
        # gdts at record 1 stores +1 pointer = 5 -> base-0 record 4
        records = [_make_header(), _make_gdts(gicm_pointer_stored=5)]
        records += [_empty_record()] * 4
        with reader_factory(records) as reader:
            assert parse_gdts_gicm_pointer(reader, 1) == 4

    def test_returns_none_for_null_pointer(self, reader_factory) -> None:
        records = [_make_header(), _make_gdts(gicm_pointer_stored=0)]
        with reader_factory(records) as reader:
            assert parse_gdts_gicm_pointer(reader, 1) is None

    def test_rejects_record_with_wrong_tag(self, reader_factory) -> None:
        records = [_make_header(), _empty_record()]  # record 1 has no gdts tag
        with reader_factory(records) as reader, pytest.raises(EquipmentChainError):
            parse_gdts_gicm_pointer(reader, 1)


class TestParseGicmEquipmentSlots:
    def test_returns_each_filled_slot_with_decoded_name(
        self, reader_factory
    ) -> None:
        gicm = _make_gicm(
            gdcm_pointers_stored=[10, 11, 12],
            names=[b"PUMP-01", b"PUMP-02", b"FAN-01"],
        )
        records = [_make_header(), *gicm]
        records += [_empty_record()] * 14
        with reader_factory(records) as reader:
            slots = parse_gicm_equipment_slots(reader, 1)
        assert [s.gdcm_record for s in slots] == [9, 10, 11]
        assert [s.long_name for s in slots] == ["PUMP-01", "PUMP-02", "FAN-01"]
        assert [s.slot_index for s in slots] == [0, 1, 2]

    def test_stops_at_first_null_gdcm_pointer(self, reader_factory) -> None:
        gicm = _make_gicm(
            gdcm_pointers_stored=[10, 0, 12],
            names=[b"A", b"B", b"C"],
        )
        records = [_make_header(), *gicm] + [_empty_record()] * 14
        with reader_factory(records) as reader:
            slots = parse_gicm_equipment_slots(reader, 1)
        assert len(slots) == 1
        assert slots[0].long_name == "A"

    def test_reads_overflow_names_from_continuation_record(
        self, reader_factory
    ) -> None:
        # 15 equipment in one logical chunk: 12 names in the gicm record,
        # 3 more in the immediately following physical record.
        gicm = _make_gicm(
            gdcm_pointers_stored=[100 + i for i in range(15)],
            names=[f"EQ-{i:02d}".encode() for i in range(15)],
        )
        assert len(gicm) == 2  # gicm header + 1 continuation record
        records = [_make_header(), *gicm] + [_empty_record()] * 13
        with reader_factory(records) as reader:
            slots = parse_gicm_equipment_slots(reader, 1)
        assert len(slots) == 15
        assert slots[0].long_name == "EQ-00"
        assert slots[11].long_name == "EQ-11"
        # The next three names live in the continuation record.
        assert slots[12].long_name == "EQ-12"
        assert slots[14].long_name == "EQ-14"
        assert [s.slot_index for s in slots] == list(range(15))

    def test_follows_next_gicm_chain(self, reader_factory) -> None:
        # gicm at record 1 has the maximum 20 slots in a single chunk
        # (uses a continuation record at record 2), next-pointer to a
        # second gicm at record 3 (stored +1 = 4) with 3 more slots.
        first = _make_gicm(
            gdcm_pointers_stored=[i + 100 for i in range(GICM_MAX_SLOTS_PER_CHUNK)],
            names=[f"EQ-{i:02d}".encode() for i in range(GICM_MAX_SLOTS_PER_CHUNK)],
            next_pointer_stored=4,
        )
        assert len(first) == 2
        second = _make_gicm(
            gdcm_pointers_stored=[200, 201, 202],
            names=[b"EXTRA-1", b"EXTRA-2", b"EXTRA-3"],
        )
        records = [_make_header(), *first, *second] + [_empty_record()] * 12
        with reader_factory(records) as reader:
            slots = parse_gicm_equipment_slots(reader, 1)
        assert len(slots) == GICM_MAX_SLOTS_PER_CHUNK + 3
        assert slots[GICM_MAX_SLOTS_PER_CHUNK].long_name == "EXTRA-1"
        assert slots[-1].long_name == "EXTRA-3"

    def test_detects_gicm_chain_cycle(self, reader_factory) -> None:
        # gicm at record 1 points back to itself (stored +1 = 2),
        # so the chain walker must error rather than spin forever.
        looped = _make_gicm(
            gdcm_pointers_stored=[10],
            names=[b"LOOP"],
            next_pointer_stored=2,
        )
        records = [_make_header(), *looped] + [_empty_record()] * 14
        with reader_factory(records) as reader, pytest.raises(
            EquipmentChainError, match="cycle"
        ):
            parse_gicm_equipment_slots(reader, 1)


class TestParseGdcmGipmPointer:
    def test_returns_zero_based_record_number(self, reader_factory) -> None:
        # gdcm at record 1 stores +1 pointer = 7 -> base-0 record 6
        records = [_make_header(), _make_gdcm(gipm_pointer_stored=7)]
        records += [_empty_record()] * 14
        with reader_factory(records) as reader:
            assert parse_gdcm_gipm_pointer(reader, 1) == 6

    def test_returns_none_for_null_pointer(self, reader_factory) -> None:
        records = [_make_header(), _make_gdcm(gipm_pointer_stored=0)]
        with reader_factory(records) as reader:
            assert parse_gdcm_gipm_pointer(reader, 1) is None
