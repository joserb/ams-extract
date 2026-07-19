"""Unit tests for the per-point sample-index parser (``pdcd``)."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from ams_extract.reader import RECORD_SIZE, RbmReader
from ams_extract.records.sample_index import (
    PDCD_ALARM_SET_INDEX_OFFSET,
    PDCD_ANALYSIS_SET_INDEX_OFFSET,
    PDCD_FFT_FIRST_VDPS_OFFSET,
    PDCD_FFT_LAST_VDPS_OFFSET,
    PDCD_TAG,
    PDCD_WAVEFORM_FIRST_OFFSET,
    PDCD_WAVEFORM_FIRST_VDFW_OFFSET,
    PDCD_WAVEFORM_LAST_VDFW_OFFSET,
    TAG_OFFSET,
    SampleIndexError,
    parse_pdcd_links,
)


def _empty_record() -> bytearray:
    return bytearray(RECORD_SIZE)


def _make_header() -> bytes:
    record = _empty_record()
    record[0x1C : 0x1C + 6] = b"MT4.00"
    return bytes(record)


def _make_pdcd(
    *,
    fft_first_stored: int = 0,
    fft_last_stored: int = 0,
    waveform_first_stored: int = 0,
    waveform_first_vdfw_stored: int = 0,
    waveform_last_vdfw_stored: int = 0,
    analysis_set_index: int = 0,
    alarm_set_index: int = 0,
) -> bytes:
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = PDCD_TAG
    struct.pack_into("<H", record, PDCD_ANALYSIS_SET_INDEX_OFFSET, analysis_set_index)
    struct.pack_into("<H", record, PDCD_ALARM_SET_INDEX_OFFSET, alarm_set_index)
    struct.pack_into("<I", record, PDCD_FFT_FIRST_VDPS_OFFSET, fft_first_stored)
    struct.pack_into("<I", record, PDCD_FFT_LAST_VDPS_OFFSET, fft_last_stored)
    struct.pack_into("<I", record, PDCD_WAVEFORM_FIRST_OFFSET, waveform_first_stored)
    struct.pack_into(
        "<I", record, PDCD_WAVEFORM_FIRST_VDFW_OFFSET, waveform_first_vdfw_stored
    )
    struct.pack_into(
        "<I", record, PDCD_WAVEFORM_LAST_VDFW_OFFSET, waveform_last_vdfw_stored
    )
    return bytes(record)


@pytest.fixture
def reader_factory(tmp_path: Path):
    def make(records: list[bytes]) -> RbmReader:
        rbm = tmp_path / "fixture.rbm"
        rbm.write_bytes(b"".join(records))
        return RbmReader(rbm)

    return make


class TestParsePdcdLinks:
    def test_decodes_each_pointer_with_plus_one(self, reader_factory) -> None:
        # Stored values are zero-based record numbers + 1.
        pdcd = _make_pdcd(
            fft_first_stored=11,
            fft_last_stored=42,
            waveform_first_stored=7,
            waveform_first_vdfw_stored=21,
            waveform_last_vdfw_stored=30,
        )
        records = [_make_header(), pdcd] + [_empty_record()] * 50
        with reader_factory(records) as reader:
            links = parse_pdcd_links(reader, 1)
        assert links.record_num == 1
        assert links.fft_first_vdps == 10
        assert links.fft_last_vdps == 41
        assert links.waveform_first == 6
        assert links.waveform_first_vdfw == 20
        assert links.waveform_last_vdfw == 29

    def test_returns_none_for_null_pointers(self, reader_factory) -> None:
        pdcd = _make_pdcd()  # all zero -> all None
        records = [_make_header(), pdcd] + [_empty_record()] * 10
        with reader_factory(records) as reader:
            links = parse_pdcd_links(reader, 1)
        assert links.fft_first_vdps is None
        assert links.fft_last_vdps is None
        assert links.waveform_first is None
        assert links.waveform_first_vdfw is None
        assert links.waveform_last_vdfw is None
        assert links.analysis_set_index == 0
        assert links.alarm_set_index == 0

    def test_reads_parameter_set_indexes(self, reader_factory) -> None:
        # The set indexes are plain u16 values (not +1-encoded pointers):
        # M1H AG-100 carries (1, 5) = Estandar 1500 rpm (S) / Motor
        # Horizontal P<300 kW (S) — FORMAT §5.8.
        pdcd = _make_pdcd(analysis_set_index=1, alarm_set_index=5)
        records = [_make_header(), pdcd] + [_empty_record()] * 10
        with reader_factory(records) as reader:
            links = parse_pdcd_links(reader, 1)
        assert links.analysis_set_index == 1
        assert links.alarm_set_index == 5

    def test_rejects_record_with_wrong_tag(self, reader_factory) -> None:
        records = [_make_header(), _empty_record()]  # rec 1 has no pdcd tag
        with reader_factory(records) as reader, pytest.raises(SampleIndexError):
            parse_pdcd_links(reader, 1)
