"""Unit tests for the FFT sample parsers (``vdps`` + ``vcps``)."""

from __future__ import annotations

import struct
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from ams_extract.reader import RECORD_SIZE, RbmReader
from ams_extract.records.sample import (
    TAG_OFFSET,
    VCPS_DATA_FLOATS,
    VCPS_DATA_OFFSET,
    VCPS_NEXT_OFFSET,
    VCPS_TAG,
    VDPS_CARGA_OFFSET,
    VDPS_FIRST_VCPS_OFFSET,
    VDPS_FMAX_OFFSET,
    VDPS_LOW_BAND_FLOATS,
    VDPS_LOW_BAND_OFFSET,
    VDPS_N_LINES_OFFSET,
    VDPS_NEXT_OFFSET,
    VDPS_RPM_X2_OFFSET,
    VDPS_TAG,
    VDPS_TIMESTAMP_OFFSET,
    VDPS_UNITS_LENGTH,
    VDPS_UNITS_OFFSET,
    SampleChainError,
    assemble_spectrum,
    parse_vdps_descriptor,
    read_vcps_amplitudes,
    read_vdps_low_band,
    walk_vdps_chain,
)


def _empty_record() -> bytearray:
    return bytearray(RECORD_SIZE)


def _make_header() -> bytes:
    record = _empty_record()
    record[0x1C : 0x1C + 6] = b"MT4.00"
    return bytes(record)


def _make_vdps(
    *,
    timestamp_raw: int,
    fmax_hz: float,
    n_lines: int,
    units: bytes,
    carga_pct: float,
    first_vcps_stored: int,
    rpm: float = 0.0,
    next_vdps_stored: int = 0,
    low_band: list[float] | None = None,
) -> bytes:
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = VDPS_TAG
    struct.pack_into("<I", record, VDPS_NEXT_OFFSET, next_vdps_stored)
    struct.pack_into("<I", record, VDPS_FIRST_VCPS_OFFSET, first_vcps_stored)
    struct.pack_into("<f", record, VDPS_FMAX_OFFSET, fmax_hz)
    struct.pack_into("<I", record, VDPS_TIMESTAMP_OFFSET, timestamp_raw)
    struct.pack_into("<f", record, VDPS_RPM_X2_OFFSET, rpm * 2.0)
    struct.pack_into("<f", record, VDPS_CARGA_OFFSET, carga_pct)
    struct.pack_into("<I", record, VDPS_N_LINES_OFFSET, n_lines)
    units_slot = bytearray(b" " * VDPS_UNITS_LENGTH)
    units_slot[: len(units)] = units
    record[VDPS_UNITS_OFFSET : VDPS_UNITS_OFFSET + VDPS_UNITS_LENGTH] = bytes(units_slot)
    if low_band is not None:
        for i, v in enumerate(low_band):
            struct.pack_into("<f", record, VDPS_LOW_BAND_OFFSET + i * 4, v)
    return bytes(record)


def _make_vcps(
    *,
    amplitudes: list[float],
    next_vcps_stored: int = 0,
) -> bytes:
    if len(amplitudes) > VCPS_DATA_FLOATS:
        raise AssertionError(f"each vcps holds {VCPS_DATA_FLOATS} floats, got {len(amplitudes)}")
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = VCPS_TAG
    struct.pack_into("<I", record, VCPS_NEXT_OFFSET, next_vcps_stored)
    for i, v in enumerate(amplitudes):
        struct.pack_into("<f", record, VCPS_DATA_OFFSET + i * 4, v)
    return bytes(record)


@pytest.fixture
def reader_factory(tmp_path: Path):
    def make(records: list[bytes]) -> RbmReader:
        rbm = tmp_path / "fixture.rbm"
        rbm.write_bytes(b"".join(records))
        return RbmReader(rbm)

    return make


class TestParseVdpsDescriptor:
    def test_decodes_metadata_and_links(self, reader_factory) -> None:
        # 2020-01-21T11:30:20+00:00 UTC = 1579606220
        vdps = _make_vdps(
            timestamp_raw=1579606220,
            fmax_hz=1000.0,
            n_lines=1600,
            units=b"plg/segs",
            rpm=1455.0,
            carga_pct=100.0,
            first_vcps_stored=11,  # → rec 10
            next_vdps_stored=4,  # → rec 3
        )
        records = [_make_header(), vdps] + [_empty_record()] * 20
        with reader_factory(records) as reader:
            desc = parse_vdps_descriptor(reader, 1)
        assert desc.record_num == 1
        assert desc.timestamp_utc == datetime(2020, 1, 21, 11, 30, 20, tzinfo=UTC)
        assert desc.fmax_hz == pytest.approx(1000.0)
        assert desc.n_lines == 1600
        assert desc.units == "plg/segs"
        assert desc.rpm == pytest.approx(1455.0)
        assert desc.carga_pct == pytest.approx(100.0)
        assert desc.first_vcps == 10
        assert desc.next_vdps == 3

    def test_null_pointers_decode_to_none(self, reader_factory) -> None:
        vdps = _make_vdps(
            timestamp_raw=1_700_000_000,
            fmax_hz=200.0,
            n_lines=400,
            units=b"g",
            carga_pct=0.0,
            first_vcps_stored=0,
            next_vdps_stored=0,
        )
        records = [_make_header(), vdps] + [_empty_record()] * 5
        with reader_factory(records) as reader:
            desc = parse_vdps_descriptor(reader, 1)
        assert desc.first_vcps is None
        assert desc.next_vdps is None

    def test_rejects_record_with_wrong_tag(self, reader_factory) -> None:
        records = [_make_header(), _empty_record()]
        with reader_factory(records) as reader, pytest.raises(SampleChainError):
            parse_vdps_descriptor(reader, 1)


class TestWalkVdpsChain:
    def test_yields_each_descriptor_in_order(self, reader_factory) -> None:
        # Three vdps linked oldest → newer via 0x14 (stored +1).
        a = _make_vdps(
            timestamp_raw=1571150677,  # 2019-10-15
            fmax_hz=1000.0,
            n_lines=1600,
            units=b"plg/segs",
            carga_pct=100.0,
            first_vcps_stored=11,
            next_vdps_stored=3,
        )
        b = _make_vdps(
            timestamp_raw=1573574259,  # 2019-11-12
            fmax_hz=1000.0,
            n_lines=1600,
            units=b"plg/segs",
            carga_pct=100.0,
            first_vcps_stored=12,
            next_vdps_stored=4,
        )
        c = _make_vdps(
            timestamp_raw=1576159620,  # 2019-12-12
            fmax_hz=1000.0,
            n_lines=1600,
            units=b"plg/segs",
            carga_pct=100.0,
            first_vcps_stored=13,
            next_vdps_stored=0,
        )
        records = [_make_header(), a, b, c] + [_empty_record()] * 12
        with reader_factory(records) as reader:
            chain = list(walk_vdps_chain(reader, 1))
        assert [d.record_num for d in chain] == [1, 2, 3]
        assert [d.timestamp_utc.year for d in chain] == [2019, 2019, 2019]
        assert [d.timestamp_utc.month for d in chain] == [10, 11, 12]

    def test_detects_cycle(self, reader_factory) -> None:
        # vdps at rec 1 points back to itself (stored +1 = 2).
        looped = _make_vdps(
            timestamp_raw=1_700_000_000,
            fmax_hz=1000.0,
            n_lines=1600,
            units=b"g",
            carga_pct=0.0,
            first_vcps_stored=0,
            next_vdps_stored=2,
        )
        records = [_make_header(), looped] + [_empty_record()] * 5
        with reader_factory(records) as reader, pytest.raises(SampleChainError, match="cycle"):
            list(walk_vdps_chain(reader, 1))


class TestReadVcpsAmplitudes:
    def test_concatenates_full_chain_in_order(self, reader_factory) -> None:
        # Chain of three vcps, each carrying a unique pattern. The full
        # output should be the concatenation in chain order.
        a_floats = [float(i) for i in range(VCPS_DATA_FLOATS)]
        b_floats = [float(1000 + i) for i in range(VCPS_DATA_FLOATS)]
        c_floats = [float(2000 + i) for i in range(VCPS_DATA_FLOATS)]
        a = _make_vcps(amplitudes=a_floats, next_vcps_stored=3)  # → rec 2
        b = _make_vcps(amplitudes=b_floats, next_vcps_stored=4)  # → rec 3
        c = _make_vcps(amplitudes=c_floats, next_vcps_stored=0)
        records = [_make_header(), a, b, c] + [_empty_record()] * 12
        with reader_factory(records) as reader:
            data = read_vcps_amplitudes(reader, 1)
        assert data.dtype == np.float32
        assert data.shape == (3 * VCPS_DATA_FLOATS,)
        assert data[0] == pytest.approx(0.0)
        assert data[VCPS_DATA_FLOATS] == pytest.approx(1000.0)
        assert data[2 * VCPS_DATA_FLOATS] == pytest.approx(2000.0)
        assert data[-1] == pytest.approx(2000.0 + VCPS_DATA_FLOATS - 1)

    def test_single_record_chain(self, reader_factory) -> None:
        only = _make_vcps(amplitudes=[1.5, 2.5, 3.5])
        records = [_make_header(), only] + [_empty_record()] * 5
        with reader_factory(records) as reader:
            data = read_vcps_amplitudes(reader, 1)
        # All 122 slots are emitted — unused ones are zero.
        assert data.shape == (VCPS_DATA_FLOATS,)
        assert data[0] == pytest.approx(1.5)
        assert data[3] == pytest.approx(0.0)

    def test_rejects_record_with_wrong_tag(self, reader_factory) -> None:
        records = [_make_header(), _empty_record()]
        with reader_factory(records) as reader, pytest.raises(SampleChainError):
            read_vcps_amplitudes(reader, 1)


class TestReadVdpsLowBand:
    def test_reads_78_low_bins_from_descriptor_tail(self, reader_factory) -> None:
        low = [float(i) for i in range(VDPS_LOW_BAND_FLOATS)]
        vdps = _make_vdps(
            timestamp_raw=1_700_000_000,
            fmax_hz=1000.0,
            n_lines=1600,
            units=b"plg/segs",
            carga_pct=100.0,
            first_vcps_stored=0,
            low_band=low,
        )
        records = [_make_header(), vdps] + [_empty_record()] * 3
        with reader_factory(records) as reader:
            band = read_vdps_low_band(reader, 1)
        assert band.dtype == np.float32
        assert band.shape == (VDPS_LOW_BAND_FLOATS,)  # 78
        assert band[0] == pytest.approx(0.0)
        assert band[-1] == pytest.approx(VDPS_LOW_BAND_FLOATS - 1)

    def test_rejects_record_with_wrong_tag(self, reader_factory) -> None:
        records = [_make_header(), _empty_record()]
        with reader_factory(records) as reader, pytest.raises(SampleChainError):
            read_vdps_low_band(reader, 1)


class TestAssembleSpectrum:
    def test_concatenates_low_band_then_chain_and_truncates(self) -> None:
        low = np.arange(VDPS_LOW_BAND_FLOATS, dtype=np.float32)
        chain = np.arange(100, 100 + 1586, dtype=np.float32)
        full = assemble_spectrum(low, chain, n_lines=1600)
        assert full.shape == (1600,)
        assert full.dtype == np.float32
        # Low band occupies bins 0..77, chain starts at bin 78.
        assert full[0] == pytest.approx(0.0)
        assert full[VDPS_LOW_BAND_FLOATS] == pytest.approx(100.0)
        # 78 + 1586 = 1664 truncated to 1600 (last 64 chain bins dropped).
        assert full[-1] == pytest.approx(100.0 + (1600 - VDPS_LOW_BAND_FLOATS) - 1)

    def test_short_buffers_are_not_padded(self) -> None:
        low = np.array([1.0, 2.0], dtype=np.float32)
        chain = np.array([3.0, 4.0], dtype=np.float32)
        full = assemble_spectrum(low, chain, n_lines=1600)
        # Fewer than n_lines available -> return what we have, no padding.
        assert full.tolist() == [1.0, 2.0, 3.0, 4.0]
