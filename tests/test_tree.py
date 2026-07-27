"""Tests for the ``ams_extract.tree`` walkers (areas, waveforms)."""

from __future__ import annotations

import struct
from pathlib import Path

from ams_extract.models import Point
from ams_extract.reader import RECORD_SIZE, RbmReader
from ams_extract.records.point import VDPM_PDCD_POINTER_OFFSET, VDPM_TAG
from ams_extract.records.sample_index import (
    PDCD_TAG,
    PDCD_WAVEFORM_FIRST_VDFW_OFFSET,
)
from ams_extract.records.waveform import (
    TAG_OFFSET,
    VCFW_DATA_OFFSET,
    VCFW_DATA_SAMPLES,
    VCFW_NEXT_OFFSET,
    VCFW_TAG,
    VDFW_FIRST_VCFW_OFFSET,
    VDFW_N_SAMPLES_OFFSET,
    VDFW_SAMPLE_PERIOD_OFFSET,
    VDFW_SCALE_OFFSET,
    VDFW_TAG,
    VDFW_TIMESTAMP_OFFSET,
    VDFW_UNITS_OFFSET,
)
from ams_extract.tree import walk_areas, walk_waveforms


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


def _waveform_fixture(path: Path, *, nominal: int, vcfw_records: int) -> Path:
    """Write a minimal .rbm: header, vdpm -> pdcd -> vdfw -> vcfw chain."""
    header = bytearray(RECORD_SIZE)
    header[0x1C : 0x1C + 6] = b"MT4.00"

    vdpm = bytearray(RECORD_SIZE)
    vdpm[TAG_OFFSET : TAG_OFFSET + 4] = VDPM_TAG
    struct.pack_into("<I", vdpm, VDPM_PDCD_POINTER_OFFSET, 3)  # +1-encoded -> rec 2

    pdcd = bytearray(RECORD_SIZE)
    pdcd[TAG_OFFSET : TAG_OFFSET + 4] = PDCD_TAG
    struct.pack_into("<I", pdcd, PDCD_WAVEFORM_FIRST_VDFW_OFFSET, 4)  # -> rec 3

    vdfw = bytearray(RECORD_SIZE)
    vdfw[TAG_OFFSET : TAG_OFFSET + 4] = VDFW_TAG
    struct.pack_into("<I", vdfw, VDFW_FIRST_VCFW_OFFSET, 5)  # -> rec 4
    struct.pack_into("<f", vdfw, VDFW_SAMPLE_PERIOD_OFFSET, 1.0 / 2560.0)
    struct.pack_into("<f", vdfw, VDFW_SCALE_OFFSET, 2.0)
    struct.pack_into("<I", vdfw, VDFW_N_SAMPLES_OFFSET, nominal)
    struct.pack_into("<I", vdfw, VDFW_TIMESTAMP_OFFSET, 1582106570)
    vdfw[VDFW_UNITS_OFFSET : VDFW_UNITS_OFFSET + 3] = b"G's"

    records = [header, vdpm, pdcd, vdfw]
    for index in range(vcfw_records):
        vcfw = bytearray(RECORD_SIZE)
        vcfw[TAG_OFFSET : TAG_OFFSET + 4] = VCFW_TAG
        next_stored = 0 if index == vcfw_records - 1 else 4 + index + 2
        struct.pack_into("<I", vcfw, VCFW_NEXT_OFFSET, next_stored)
        for i in range(VCFW_DATA_SAMPLES):
            struct.pack_into("<h", vcfw, VCFW_DATA_OFFSET + 2 * i, index + 1)
        records.append(vcfw)

    rbm = path / "waveform.rbm"
    rbm.write_bytes(b"".join(bytes(r) for r in records))
    return rbm


class TestWalkWaveformsSynthetic:
    def test_n_samples_is_the_decoded_length_not_the_nominal(
        self, tmp_path: Path
    ) -> None:
        # AMS stores fewer samples than the nominal block (FORMAT §5.5), so
        # emitting vdfw.0x2C would contradict len(samples) and break the
        # VibFrame wave contract (n_samples == len(data)).
        rbm = _waveform_fixture(tmp_path, nominal=512, vcfw_records=2)
        point = Point(record_num=1, long_name="MOTOR", short_code="MOTOR")

        with RbmReader(rbm) as reader:
            waveforms = list(walk_waveforms(reader, point))

        assert len(waveforms) == 1
        wave = waveforms[0]
        assert wave.samples.size == 2 * VCFW_DATA_SAMPLES == 488
        assert wave.n_samples == wave.samples.size
        assert wave.nominal_n_samples == 512

    def test_n_samples_follows_a_buffer_longer_than_the_nominal(
        self, tmp_path: Path
    ) -> None:
        # The other direction: a nominal 4096 is stored in 17 records
        # (4148 samples), i.e. MORE than the nominal block.
        rbm = _waveform_fixture(tmp_path, nominal=4096, vcfw_records=17)
        point = Point(record_num=1, long_name="MOTOR", short_code="MOTOR")

        with RbmReader(rbm) as reader:
            wave = next(iter(walk_waveforms(reader, point)))

        assert wave.n_samples == wave.samples.size == 4148
        assert wave.nominal_n_samples == 4096
