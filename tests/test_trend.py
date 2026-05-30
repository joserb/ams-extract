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
    VDDT_COLUMN_COUNT_OFFSET,
    VDDT_FIRST_SLOT_OFFSET,
    VDDT_FIRST_TS_OFFSET,
    VDDT_NEXT_OFFSET,
    VDDT_SLOT_BANDS_OFFSET,
    VDDT_SLOT_MARKER,
    VDDT_SLOT_NEXT_TS_OFFSET,
    VDDT_SLOT_OVERALL_OFFSET,
    VDDT_SLOT_STRIDE,
    VDDT_TAG,
    VDDT_VELOCITY_COLUMN_COUNT,
    TrendChainError,
    TrendLayoutError,
    parse_vddt_record,
    walk_vddt_chain,
)

# A slot: (overall_raw, bands_raw[7], next_ts_raw).
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
    column_count: int = VDDT_VELOCITY_COLUMN_COUNT,
    write_marker: bool = True,
) -> bytes:
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = VDDT_TAG
    struct.pack_into("<I", record, VDDT_NEXT_OFFSET, next_vddt_stored)
    struct.pack_into("<I", record, VDDT_FIRST_TS_OFFSET, d0_raw)
    struct.pack_into("<I", record, VDDT_COLUMN_COUNT_OFFSET, column_count)
    for k, (overall, bands, next_ts) in enumerate(slots):
        base = VDDT_FIRST_SLOT_OFFSET + k * VDDT_SLOT_STRIDE
        if write_marker:
            record[base : base + len(VDDT_SLOT_MARKER)] = VDDT_SLOT_MARKER
        struct.pack_into("<f", record, base + VDDT_SLOT_OVERALL_OFFSET, overall)
        for i, b in enumerate(bands):
            struct.pack_into("<f", record, base + VDDT_SLOT_BANDS_OFFSET + i * 4, b)
        struct.pack_into("<I", record, base + VDDT_SLOT_NEXT_TS_OFFSET, next_ts)
    return bytes(record)


@pytest.fixture
def reader_factory(tmp_path: Path):
    def make(records: list[bytes]) -> RbmReader:
        rbm = tmp_path / "fixture.rbm"
        rbm.write_bytes(b"".join(records))
        return RbmReader(rbm)

    return make


# Three readings, dated 2013-02-28, 2013-04-24, 2013-06-25 (the first 3 gold
# rows of M1H AG-100). Each slot stores the NEXT reading's timestamp.
_FEB = 1362009600  # 2013-02-28 (d0)
_APR = 1366761600  # 2013-04-24
_JUN = 1372118400  # 2013-06-25
_BANDS = (8.05, 0.25, 1.23, 0.22, 0.92, 0.18, 7.27)


class TestParseVddtRecord:
    def test_off_by_one_date_rule(self, reader_factory) -> None:
        vddt = _make_vddt(
            d0_raw=_FEB,
            slots=[
                (1.58, _BANDS, _APR),  # dated d0 (Feb), stores Apr
                (1.60, _BANDS, _JUN),  # dated Apr, stores Jun
                (1.88, _BANDS, 0),  # dated Jun, no next
            ],
        )
        records = [_make_header(), vddt]
        with reader_factory(records) as reader:
            readings = parse_vddt_record(reader, 1)
        dates = [r.timestamp_utc for r in readings]
        assert dates == [
            datetime(2013, 2, 28, tzinfo=UTC),
            datetime(2013, 4, 24, tzinfo=UTC),
            datetime(2013, 6, 25, tzinfo=UTC),
        ]
        assert [round(r.overall_raw, 2) for r in readings] == [1.58, 1.60, 1.88]

    def test_keeps_raw_bands(self, reader_factory) -> None:
        vddt = _make_vddt(d0_raw=_FEB, slots=[(1.58, _BANDS, 0)])
        with reader_factory([_make_header(), vddt]) as reader:
            (reading,) = parse_vddt_record(reader, 1)
        assert reading.bands_raw == pytest.approx(_BANDS)

    def test_stops_at_first_missing_marker(self, reader_factory) -> None:
        # Only the first two slots carry a marker; the parser must stop there
        # even though more bytes follow.
        vddt = bytearray(
            _make_vddt(d0_raw=_FEB, slots=[(1.58, _BANDS, _APR), (1.60, _BANDS, 0)])
        )
        # Write a plausible-looking third slot WITHOUT a marker.
        base = VDDT_FIRST_SLOT_OFFSET + 2 * VDDT_SLOT_STRIDE
        struct.pack_into("<f", vddt, base + VDDT_SLOT_OVERALL_OFFSET, 9.99)
        with reader_factory([_make_header(), bytes(vddt)]) as reader:
            readings = parse_vddt_record(reader, 1)
        assert len(readings) == 2

    def test_stops_at_implausible_overall(self, reader_factory) -> None:
        vddt = _make_vddt(
            d0_raw=_FEB,
            slots=[(1.58, _BANDS, _APR), (1e30, _BANDS, 0)],  # garbage 2nd slot
        )
        with reader_factory([_make_header(), vddt]) as reader:
            readings = parse_vddt_record(reader, 1)
        assert len(readings) == 1

    def test_rejects_unsupported_column_count(self, reader_factory) -> None:
        vddt = _make_vddt(d0_raw=_FEB, slots=[(1.58, _BANDS, 0)], column_count=1)
        with (
            reader_factory([_make_header(), vddt]) as reader,
            pytest.raises(TrendLayoutError),
        ):
            parse_vddt_record(reader, 1)

    def test_rejects_missing_slot_marker(self, reader_factory) -> None:
        vddt = _make_vddt(d0_raw=_FEB, slots=[(1.58, _BANDS, 0)], write_marker=False)
        with (
            reader_factory([_make_header(), vddt]) as reader,
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
        vddt_a = _make_vddt(d0_raw=_FEB, slots=[(1.58, _BANDS, 0)], next_vddt_stored=3)
        vddt_b = _make_vddt(d0_raw=_JUN, slots=[(1.88, _BANDS, 0)], next_vddt_stored=0)
        with reader_factory([_make_header(), vddt_a, vddt_b]) as reader:
            assert list(walk_vddt_chain(reader, 1)) == [1, 2]

    def test_detects_cycle(self, reader_factory) -> None:
        # rec 1 points back to itself (+1-encoded 2 → rec 1)
        vddt = _make_vddt(d0_raw=_FEB, slots=[(1.58, _BANDS, 0)], next_vddt_stored=2)
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
