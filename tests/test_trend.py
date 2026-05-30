"""Unit tests for the trend parser (``vddt`` — Valores Globales series)."""

from __future__ import annotations

import struct
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ams_extract.reader import RECORD_SIZE, RbmReader
from ams_extract.records.trend import (
    TAG_OFFSET,
    VDDT_BAND_COUNT_OFFSET,
    VDDT_FIRST_SLOT_OFFSET,
    VDDT_FIRST_TS_OFFSET,
    VDDT_NEXT_OFFSET,
    VDDT_SLOT_BANDS_OFFSET,
    VDDT_SLOT_OVERALL_OFFSET,
    VDDT_TAG,
    TrendChainError,
    TrendLayoutError,
    parse_vddt_record,
    walk_vddt_chain,
)

# A slot: (overall_raw, bands_raw, next_ts_raw). len(bands) must equal band_count.
Slot = tuple[float, Sequence[float], int]


def _empty_record() -> bytearray:
    return bytearray(RECORD_SIZE)


def _make_header() -> bytes:
    record = _empty_record()
    record[0x1C : 0x1C + 6] = b"MT4.00"
    return bytes(record)


def _make_vddt(
    *,
    d0_raw: int,
    slots: Sequence[Slot],
    next_vddt_stored: int = 0,
    band_count: int = 7,
) -> bytes:
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = VDDT_TAG
    struct.pack_into("<I", record, VDDT_NEXT_OFFSET, next_vddt_stored)
    struct.pack_into("<I", record, VDDT_FIRST_TS_OFFSET, d0_raw)
    struct.pack_into("<I", record, VDDT_BAND_COUNT_OFFSET, band_count)
    ts_offset = VDDT_SLOT_BANDS_OFFSET + band_count * 4
    stride = ts_offset + 4 + 1
    for k, (overall, bands, next_ts) in enumerate(slots):
        if len(bands) != band_count:
            raise AssertionError(f"slot {k}: expected {band_count} bands")
        base = VDDT_FIRST_SLOT_OFFSET + k * stride
        record[base : base + 4] = b"\xff\xff\xff\x00"  # per-slot flags
        struct.pack_into("<f", record, base + VDDT_SLOT_OVERALL_OFFSET, overall)
        for i, b in enumerate(bands):
            struct.pack_into("<f", record, base + VDDT_SLOT_BANDS_OFFSET + i * 4, b)
        struct.pack_into("<I", record, base + ts_offset, next_ts)
    return bytes(record)


@pytest.fixture
def reader_factory(tmp_path: Path):
    def make(records: list[bytes]) -> RbmReader:
        rbm = tmp_path / "fixture.rbm"
        rbm.write_bytes(b"".join(records))
        return RbmReader(rbm)

    return make


# Three readings dated 2013-02-28, 2013-04-24, 2013-06-25 (the first 3 gold
# rows of M1H AG-100). Each slot stores the NEXT reading's timestamp.
_FEB = 1362009600  # 2013-02-28 (d0)
_APR = 1366761600  # 2013-04-24
_JUN = 1372118400  # 2013-06-25
_BANDS7 = (8.05, 0.25, 1.23, 0.22, 0.92, 0.18, 7.27)


class TestParseVddtRecord:
    def test_off_by_one_date_rule(self, reader_factory) -> None:
        vddt = _make_vddt(
            d0_raw=_FEB,
            slots=[
                (1.58, _BANDS7, _APR),  # dated d0 (Feb), stores Apr
                (1.60, _BANDS7, _JUN),  # dated Apr, stores Jun
                (1.88, _BANDS7, 0),  # dated Jun, no next → last
            ],
        )
        with reader_factory([_make_header(), vddt]) as reader:
            readings = parse_vddt_record(reader, 1)
        assert [r.timestamp_utc for r in readings] == [
            datetime(2013, 2, 28, tzinfo=UTC),
            datetime(2013, 4, 24, tzinfo=UTC),
            datetime(2013, 6, 25, tzinfo=UTC),
        ]
        assert [round(r.overall_raw, 2) for r in readings] == [1.58, 1.60, 1.88]

    def test_keeps_raw_bands(self, reader_factory) -> None:
        vddt = _make_vddt(d0_raw=_FEB, slots=[(1.58, _BANDS7, 0)])
        with reader_factory([_make_header(), vddt]) as reader:
            (reading,) = parse_vddt_record(reader, 1)
        assert reading.bands_raw == pytest.approx(_BANDS7)

    def test_handles_other_band_counts(self, reader_factory) -> None:
        # The stride is derived from the band count, so a 4-band record (a
        # different configuration era within a point) decodes the same way.
        bands4 = (8.0, 0.2, 1.2, 0.9)
        vddt = _make_vddt(
            d0_raw=_FEB,
            slots=[(4.05, bands4, _APR), (1.20, bands4, 0)],
            band_count=4,
        )
        with reader_factory([_make_header(), vddt]) as reader:
            readings = parse_vddt_record(reader, 1)
        assert [round(r.overall_raw, 2) for r in readings] == [4.05, 1.20]
        assert [r.timestamp_utc for r in readings] == [
            datetime(2013, 2, 28, tzinfo=UTC),
            datetime(2013, 4, 24, tzinfo=UTC),
        ]
        assert len(readings[0].bands_raw) == 4

    def test_stops_at_zero_next_ts(self, reader_factory) -> None:
        # A trailing zeroed slot must not be read as a reading.
        vddt = _make_vddt(d0_raw=_FEB, slots=[(1.58, _BANDS7, 0)])
        with reader_factory([_make_header(), vddt]) as reader:
            readings = parse_vddt_record(reader, 1)
        assert len(readings) == 1

    def test_stops_at_implausible_overall(self, reader_factory) -> None:
        vddt = _make_vddt(
            d0_raw=_FEB,
            slots=[(1.58, _BANDS7, _APR), (1e30, _BANDS7, 0)],  # garbage 2nd
        )
        with reader_factory([_make_header(), vddt]) as reader:
            readings = parse_vddt_record(reader, 1)
        assert len(readings) == 1

    def test_rejects_implausible_band_count(self, reader_factory) -> None:
        vddt = _make_vddt(d0_raw=_FEB, slots=[(1.58, _BANDS7, 0)])
        broken = bytearray(vddt)
        struct.pack_into("<I", broken, VDDT_BAND_COUNT_OFFSET, 0)
        with (
            reader_factory([_make_header(), bytes(broken)]) as reader,
            pytest.raises(TrendLayoutError),
        ):
            parse_vddt_record(reader, 1)

    def test_rejects_wrong_tag(self, reader_factory) -> None:
        with (
            reader_factory([_make_header(), _empty_record()]) as reader,
            pytest.raises(TrendChainError),
        ):
            parse_vddt_record(reader, 1)


class TestWalkVddtChain:
    def test_follows_chain_to_end(self, reader_factory) -> None:
        # rec 1 → rec 2 → end (next pointers are +1-encoded)
        vddt_a = _make_vddt(d0_raw=_FEB, slots=[(1.58, _BANDS7, 0)], next_vddt_stored=3)
        vddt_b = _make_vddt(d0_raw=_JUN, slots=[(1.88, _BANDS7, 0)], next_vddt_stored=0)
        with reader_factory([_make_header(), vddt_a, vddt_b]) as reader:
            assert list(walk_vddt_chain(reader, 1)) == [1, 2]

    def test_detects_cycle(self, reader_factory) -> None:
        # rec 1 points back to itself (+1-encoded 2 → rec 1)
        vddt = _make_vddt(d0_raw=_FEB, slots=[(1.58, _BANDS7, 0)], next_vddt_stored=2)
        with (
            reader_factory([_make_header(), vddt]) as reader,
            pytest.raises(TrendChainError),
        ):
            list(walk_vddt_chain(reader, 1))

    def test_raises_on_wrong_tag(self, reader_factory) -> None:
        with (
            reader_factory([_make_header(), _empty_record()]) as reader,
            pytest.raises(TrendChainError),
        ):
            list(walk_vddt_chain(reader, 1))
