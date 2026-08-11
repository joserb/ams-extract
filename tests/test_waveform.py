"""Unit tests for the waveform parsers (``vdfw`` descriptor + ``vcfw`` data)."""

from __future__ import annotations

import struct
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from ams_extract.reader import RECORD_SIZE, RbmReader
from ams_extract.records.waveform import (
    TAG_OFFSET,
    VCFW_DATA_OFFSET,
    VCFW_DATA_SAMPLES,
    VCFW_NEXT_OFFSET,
    VCFW_TAG,
    VDFW_CARGA_OFFSET,
    VDFW_DATA_OFFSET,
    VDFW_DATA_SAMPLES,
    VDFW_FIRST_VCFW_OFFSET,
    VDFW_N_SAMPLES_OFFSET,
    VDFW_NEXT_OFFSET,
    VDFW_RPM_OFFSET,
    VDFW_SAMPLE_PERIOD_OFFSET,
    VDFW_SCALE_OFFSET,
    VDFW_TAG,
    VDFW_TIMESTAMP_OFFSET,
    VDFW_UNITS_LENGTH,
    VDFW_UNITS_OFFSET,
    WaveformChainError,
    assemble_waveform,
    parse_vdfw_descriptor,
    read_vcfw_samples,
    read_vdfw_samples,
    walk_vdfw_chain,
)


def _empty_record() -> bytearray:
    return bytearray(RECORD_SIZE)


def _make_header() -> bytes:
    record = _empty_record()
    record[0x1C : 0x1C + 6] = b"MT4.00"
    return bytes(record)


def _make_vdfw(
    *,
    timestamp_raw: int,
    n_samples: int,
    sample_period: float,
    rpm: float,
    units: bytes,
    carga_pct: float,
    first_vcfw_stored: int,
    next_vdfw_stored: int = 0,
    scale_factor: float = 1.0,
    samples: list[int] | None = None,
) -> bytes:
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = VDFW_TAG
    struct.pack_into("<I", record, VDFW_NEXT_OFFSET, next_vdfw_stored)
    struct.pack_into("<I", record, VDFW_FIRST_VCFW_OFFSET, first_vcfw_stored)
    struct.pack_into("<f", record, VDFW_SAMPLE_PERIOD_OFFSET, sample_period)
    struct.pack_into("<f", record, VDFW_SCALE_OFFSET, scale_factor)
    struct.pack_into("<I", record, VDFW_N_SAMPLES_OFFSET, n_samples)
    struct.pack_into("<I", record, VDFW_TIMESTAMP_OFFSET, timestamp_raw)
    struct.pack_into("<f", record, VDFW_RPM_OFFSET, rpm)
    struct.pack_into("<f", record, VDFW_CARGA_OFFSET, carga_pct)
    units_slot = bytearray(b" " * VDFW_UNITS_LENGTH)
    units_slot[: len(units)] = units
    record[VDFW_UNITS_OFFSET : VDFW_UNITS_OFFSET + VDFW_UNITS_LENGTH] = bytes(units_slot)
    for i, value in enumerate(samples or []):
        if i >= VDFW_DATA_SAMPLES:
            raise AssertionError(f"vdfw holds only {VDFW_DATA_SAMPLES} inline samples")
        struct.pack_into("<h", record, VDFW_DATA_OFFSET + i * 2, value)
    return bytes(record)


def _make_vcfw(
    *,
    samples: list[int],
    next_vcfw_stored: int = 0,
) -> bytes:
    if len(samples) > VCFW_DATA_SAMPLES:
        raise AssertionError(
            f"each vcfw holds {VCFW_DATA_SAMPLES} int16, got {len(samples)}"
        )
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = VCFW_TAG
    struct.pack_into("<I", record, VCFW_NEXT_OFFSET, next_vcfw_stored)
    for i, v in enumerate(samples):
        struct.pack_into("<h", record, VCFW_DATA_OFFSET + i * 2, v)
    return bytes(record)


@pytest.fixture
def reader_factory(tmp_path: Path):
    def make(records: list[bytes]) -> RbmReader:
        rbm = tmp_path / "fixture.rbm"
        rbm.write_bytes(b"".join(records))
        return RbmReader(rbm)

    return make


class TestParseVdfwDescriptor:
    def test_decodes_metadata_and_links(self, reader_factory) -> None:
        # 2020-02-19T10:02:50+00:00 UTC = 1582106570
        vdfw = _make_vdfw(
            timestamp_raw=1582106570,
            n_samples=512,
            sample_period=1.0 / 2560.0,
            rpm=1455.0,
            units=b"G's",
            carga_pct=100.0,
            first_vcfw_stored=11,  # → rec 10
            next_vdfw_stored=4,  # → rec 3
            scale_factor=3.7548e-05,
        )
        records = [_make_header(), vdfw] + [_empty_record()] * 20
        with reader_factory(records) as reader:
            desc = parse_vdfw_descriptor(reader, 1)
        assert desc.record_num == 1
        assert desc.timestamp_utc == datetime(2020, 2, 19, 10, 2, 50, tzinfo=UTC)
        assert desc.n_samples == 512
        assert desc.sample_period_s == pytest.approx(1.0 / 2560.0)
        assert desc.sample_rate_hz == pytest.approx(2560.0)
        assert desc.scale_factor == pytest.approx(3.7548e-05)
        assert desc.rpm == pytest.approx(1455.0)
        assert desc.units == "G's"
        assert desc.carga_pct == pytest.approx(100.0)
        assert desc.first_vcfw == 10
        assert desc.next_vdfw == 3

    def test_null_pointers_decode_to_none(self, reader_factory) -> None:
        vdfw = _make_vdfw(
            timestamp_raw=1_700_000_000,
            n_samples=256,
            sample_period=1.0 / 1280.0,
            rpm=0.0,
            units=b"G's",
            carga_pct=0.0,
            first_vcfw_stored=0,
            next_vdfw_stored=0,
        )
        records = [_make_header(), vdfw] + [_empty_record()] * 5
        with reader_factory(records) as reader:
            desc = parse_vdfw_descriptor(reader, 1)
        assert desc.first_vcfw is None
        assert desc.next_vdfw is None

    def test_zero_sample_period_yields_zero_rate(self, reader_factory) -> None:
        vdfw = _make_vdfw(
            timestamp_raw=1_700_000_000,
            n_samples=0,
            sample_period=0.0,
            rpm=0.0,
            units=b"G's",
            carga_pct=0.0,
            first_vcfw_stored=0,
        )
        records = [_make_header(), vdfw] + [_empty_record()] * 5
        with reader_factory(records) as reader:
            desc = parse_vdfw_descriptor(reader, 1)
        assert desc.sample_rate_hz == 0.0

    def test_rejects_record_with_wrong_tag(self, reader_factory) -> None:
        records = [_make_header(), _empty_record()]
        with reader_factory(records) as reader, pytest.raises(WaveformChainError):
            parse_vdfw_descriptor(reader, 1)


class TestWalkVdfwChain:
    def test_yields_each_descriptor_in_order(self, reader_factory) -> None:
        a = _make_vdfw(
            timestamp_raw=1571150677,  # 2019-10-15
            n_samples=512, sample_period=1.0 / 2560.0, rpm=1455.0,
            units=b"G's", carga_pct=100.0, first_vcfw_stored=11, next_vdfw_stored=3,
        )
        b = _make_vdfw(
            timestamp_raw=1573574259,  # 2019-11-12
            n_samples=512, sample_period=1.0 / 2560.0, rpm=1455.0,
            units=b"G's", carga_pct=100.0, first_vcfw_stored=12, next_vdfw_stored=4,
        )
        c = _make_vdfw(
            timestamp_raw=1576159620,  # 2019-12-12
            n_samples=512, sample_period=1.0 / 2560.0, rpm=1455.0,
            units=b"G's", carga_pct=100.0, first_vcfw_stored=13, next_vdfw_stored=0,
        )
        records = [_make_header(), a, b, c] + [_empty_record()] * 12
        with reader_factory(records) as reader:
            chain = list(walk_vdfw_chain(reader, 1))
        assert [d.record_num for d in chain] == [1, 2, 3]
        assert [d.timestamp_utc.month for d in chain] == [10, 11, 12]

    def test_detects_cycle(self, reader_factory) -> None:
        looped = _make_vdfw(
            timestamp_raw=1_700_000_000,
            n_samples=512, sample_period=1.0 / 2560.0, rpm=0.0,
            units=b"G's", carga_pct=0.0, first_vcfw_stored=0, next_vdfw_stored=2,
        )
        records = [_make_header(), looped] + [_empty_record()] * 5
        with reader_factory(records) as reader, pytest.raises(
            WaveformChainError, match="cycle"
        ):
            list(walk_vdfw_chain(reader, 1))


class TestReadVcfwSamples:
    def test_concatenates_full_chain_in_order(self, reader_factory) -> None:
        a_samples = [i - 100 for i in range(VCFW_DATA_SAMPLES)]
        b_samples = [i for i in range(VCFW_DATA_SAMPLES)]
        a = _make_vcfw(samples=a_samples, next_vcfw_stored=3)  # → rec 2
        b = _make_vcfw(samples=b_samples, next_vcfw_stored=0)
        records = [_make_header(), a, b] + [_empty_record()] * 12
        with reader_factory(records) as reader:
            data = read_vcfw_samples(reader, 1)
        assert data.dtype == np.float32
        assert data.shape == (2 * VCFW_DATA_SAMPLES,)
        assert data[0] == pytest.approx(-100.0)
        assert data[VCFW_DATA_SAMPLES] == pytest.approx(0.0)
        assert data[-1] == pytest.approx(VCFW_DATA_SAMPLES - 1)

    def test_decodes_signed_int16(self, reader_factory) -> None:
        only = _make_vcfw(samples=[-32768, -1, 0, 1, 32767])
        records = [_make_header(), only] + [_empty_record()] * 5
        with reader_factory(records) as reader:
            data = read_vcfw_samples(reader, 1)
        assert data.shape == (VCFW_DATA_SAMPLES,)
        assert data[0] == pytest.approx(-32768.0)
        assert data[1] == pytest.approx(-1.0)
        assert data[4] == pytest.approx(32767.0)
        assert data[5] == pytest.approx(0.0)  # unused slots are zero

    def test_rejects_record_with_wrong_tag(self, reader_factory) -> None:
        records = [_make_header(), _empty_record()]
        with reader_factory(records) as reader, pytest.raises(WaveformChainError):
            read_vcfw_samples(reader, 1)


class TestReadVdfwSamples:
    def test_decodes_the_150_inline_samples(self, reader_factory) -> None:
        expected = [i - 75 for i in range(VDFW_DATA_SAMPLES)]
        vdfw = _make_vdfw(
            timestamp_raw=1_700_000_000,
            n_samples=512,
            sample_period=1.0 / 2_560.0,
            rpm=1_455.0,
            units=b"G's",
            carga_pct=100.0,
            first_vcfw_stored=0,
            samples=expected,
        )
        with reader_factory([_make_header(), vdfw]) as reader:
            samples = read_vdfw_samples(reader, 1)
        assert samples.dtype == np.float32
        assert samples.tolist() == expected

    def test_rejects_record_with_wrong_tag(self, reader_factory) -> None:
        with reader_factory([_make_header(), _empty_record()]) as reader, pytest.raises(
            WaveformChainError
        ):
            read_vdfw_samples(reader, 1)


class TestAssembleWaveform:
    def test_prepends_descriptor_samples_and_drops_zero_padding(self) -> None:
        head = np.arange(1, 151, dtype=np.float32)
        continuation = np.concatenate(
            (np.arange(151, 513, dtype=np.float32), np.zeros(126, dtype=np.float32))
        )
        samples = assemble_waveform(head, continuation, 512)
        np.testing.assert_array_equal(samples, np.arange(1, 513, dtype=np.float32))

    def test_rejects_a_short_payload(self) -> None:
        with pytest.raises(WaveformChainError, match="shorter than nominal"):
            assemble_waveform(
                np.zeros(VDFW_DATA_SAMPLES, dtype=np.float32),
                np.zeros(100, dtype=np.float32),
                512,
            )

    def test_rejects_nonzero_values_past_the_nominal_length(self) -> None:
        with pytest.raises(WaveformChainError, match="non-zero samples"):
            assemble_waveform(
                np.zeros(VDFW_DATA_SAMPLES, dtype=np.float32),
                np.ones(488, dtype=np.float32),
                512,
            )
