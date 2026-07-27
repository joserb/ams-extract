"""Parsers for time-domain waveform records (``vdfw`` descriptor + ``vcfw`` data).

Verified chain (per the 2026-05-29 sub-fase 5a reconnaissance against
M1H of AG-100, BUNGE)::

    pdcd.0x5C → vdfw (first waveform descriptor, oldest)
                 │
                 ├── 0x14 → vdfw (next waveform descriptor in time)
                 ├── 0x18 → vcfw (first data record of this waveform)
                 ├── 0x24 → float32 sample_period (seconds; 1/sample_rate)
                 ├── 0x28 → float32 scale_factor (display units per int16 count)
                 ├── 0x2C → u32 n_samples (nominal sample count)
                 ├── 0x34 → u32 Unix timestamp UTC
                 ├── 0x38 → float32 RPM
                 ├── 0x3C → float32 CARGA % (load)
                 └── 0x6C → ASCII 8 bytes — units (e.g. "G's")

    vcfw holds 244 int16 LE consecutive samples at offsets 0x18..0x1FF;
    the chain links via 0x14 to the next vcfw, ending in 0. A waveform's
    sample buffer is the concatenation of every vcfw in the chain that
    descends from the waveform's vdfw.

    The buffer length is NOT ``n_samples``: AMS stores ``n_samples - 150``
    real samples and rounds the storage up to whole 244-sample records,
    zero-padding the tail. Hence 512 → 2 records → 488 stored (362 real)
    and 4096 → 17 records → 4148 stored (3946 real). Verified over the
    137 208 waveforms of BUNGE, every nominal size (FORMAT §5.5,
    ADR-0017). ``n_samples`` is the acquisition block AMS was configured
    for; the emitted length is always ``len(samples)``.

Unlike the FFT amplitudes (whose calibration is still open, FORMAT §5.6),
the waveform calibration is solved: multiplying the raw int16 counts by
``vdfw.0x28`` (``scale_factor``) yields the displayed units. For M1H
19-feb-2020 this reproduces AMS Pc(+)=0.483 G / Pk(-)=-0.510 G within
0.3% (see FORMAT §5.5). :func:`read_vcfw_samples` returns the raw counts;
:func:`ams_extract.tree.walk_waveforms` applies ``scale_factor`` so the
:class:`~ams_extract.models.Waveform` carries calibrated samples.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from ams_extract.encoding import decode_string
from ams_extract.reader import RECORD_SIZE, RbmReader, decode_inner_pointer

VDFW_TAG = b"vdfw"
VCFW_TAG = b"vcfw"
TAG_OFFSET = 0x08

# vdfw offsets
VDFW_NEXT_OFFSET = 0x14
VDFW_FIRST_VCFW_OFFSET = 0x18
VDFW_SAMPLE_PERIOD_OFFSET = 0x24
VDFW_SCALE_OFFSET = 0x28
VDFW_N_SAMPLES_OFFSET = 0x2C
"""Nominal acquisition block size (2.56 x FFT lines), not the stored length."""

VDFW_TAIL_NOT_STORED = 150
"""Samples of the nominal block AMS never writes (FORMAT §5.5, ADR-0017).

The stored buffer holds ``n_samples - 150`` real samples, padded with
zeros up to the 244-sample ``vcfw`` record boundary. Documented, not
applied: trimming the emitted array to the real payload would change the
data and needs its own AMS gold.
"""
VDFW_TIMESTAMP_OFFSET = 0x34
VDFW_RPM_OFFSET = 0x38
VDFW_CARGA_OFFSET = 0x3C
VDFW_UNITS_OFFSET = 0x6C
VDFW_UNITS_LENGTH = 8

# vcfw offsets
VCFW_NEXT_OFFSET = 0x14
VCFW_DATA_OFFSET = 0x18
VCFW_DATA_SAMPLES = (RECORD_SIZE - VCFW_DATA_OFFSET) // 2  # 244 int16 LE

# Velocity waveforms are stored (after the vdfw.0x28 scale) in inches/sec;
# AMS displays mm/s. Pure inch->mm conversion, same factor as the velocity
# trend (and distinct from the FFT's 48.5, which folds in window terms).
WAVEFORM_VELOCITY_SCALE_MM_S = 25.4

# Safety caps to bound traversal of malformed chains.
VDFW_CHAIN_MAX_LENGTH = 4096
VCFW_CHAIN_MAX_LENGTH = 256


class WaveformChainError(ValueError):
    """Raised when a record in a waveform chain has an unexpected tag."""


@dataclass(frozen=True, slots=True)
class VdfwDescriptor:
    """Metadata for one waveform, decoded from a ``vdfw`` record."""

    record_num: int
    timestamp_utc: datetime
    n_samples: int
    sample_period_s: float
    sample_rate_hz: float
    scale_factor: float
    rpm: float
    units: str
    carga_pct: float
    first_vcfw: int | None
    next_vdfw: int | None


def _check_tag(record: bytes, expected: bytes, record_num: int) -> None:
    tag = bytes(record[TAG_OFFSET : TAG_OFFSET + 4])
    if tag != expected:
        raise WaveformChainError(
            f"record {record_num}: expected tag {expected!r}, got {tag!r}"
        )


def parse_vdfw_descriptor(reader: RbmReader, vdfw_record: int) -> VdfwDescriptor:
    """Decode one ``vdfw`` record into a :class:`VdfwDescriptor`.

    Raises:
        WaveformChainError: If the record's tag is not ``vdfw``.
    """
    record = reader.read_record(vdfw_record)
    _check_tag(record, VDFW_TAG, vdfw_record)

    def _u32(offset: int) -> int:
        return struct.unpack_from("<I", record, offset)[0]

    def _f32(offset: int) -> float:
        return float(struct.unpack_from("<f", record, offset)[0])

    timestamp_raw = _u32(VDFW_TIMESTAMP_OFFSET)
    timestamp_utc = datetime.fromtimestamp(timestamp_raw, UTC)
    sample_period = _f32(VDFW_SAMPLE_PERIOD_OFFSET)
    sample_rate = 1.0 / sample_period if sample_period > 0.0 else 0.0
    units_bytes = record[VDFW_UNITS_OFFSET : VDFW_UNITS_OFFSET + VDFW_UNITS_LENGTH]
    return VdfwDescriptor(
        record_num=vdfw_record,
        timestamp_utc=timestamp_utc,
        n_samples=_u32(VDFW_N_SAMPLES_OFFSET),
        sample_period_s=sample_period,
        sample_rate_hz=sample_rate,
        scale_factor=_f32(VDFW_SCALE_OFFSET),
        rpm=_f32(VDFW_RPM_OFFSET),
        units=decode_string(units_bytes),
        carga_pct=_f32(VDFW_CARGA_OFFSET),
        first_vcfw=decode_inner_pointer(_u32(VDFW_FIRST_VCFW_OFFSET)),
        next_vdfw=decode_inner_pointer(_u32(VDFW_NEXT_OFFSET)),
    )


def walk_vdfw_chain(reader: RbmReader, first_vdfw: int) -> Iterator[VdfwDescriptor]:
    """Yield each :class:`VdfwDescriptor` in the chain starting at ``first_vdfw``.

    Chain follows ``vdfw.0x14`` (+1-encoded), 0 = end. Detects cycles and
    bounds the walk at :data:`VDFW_CHAIN_MAX_LENGTH`.

    Raises:
        WaveformChainError: If any record in the chain has the wrong tag
            or if the chain loops or exceeds the safety bound.
    """
    visited: set[int] = set()
    current: int | None = first_vdfw
    for _ in range(VDFW_CHAIN_MAX_LENGTH):
        if current is None:
            return
        if current in visited:
            raise WaveformChainError(
                f"vdfw chain cycle detected at record {current}"
            )
        visited.add(current)
        descriptor = parse_vdfw_descriptor(reader, current)
        yield descriptor
        current = descriptor.next_vdfw
    raise WaveformChainError(
        f"vdfw chain exceeds {VDFW_CHAIN_MAX_LENGTH} records starting at {first_vdfw}"
    )


def read_vcfw_samples(reader: RbmReader, first_vcfw: int) -> np.ndarray:
    """Concatenate the int16 LE samples from one vcfw chain.

    Returns a 1-D ``np.ndarray`` of dtype ``float32`` (int16 samples cast
    up so downstream plotting/scaling never has to worry about overflow)
    whose length is ``244 * <chain length>`` — 488 for the typical BUNGE
    waveform (2 records of 244 samples). The chain length is
    ``ceil((nominal - 150) / 244)``, so the buffer can be shorter (488 for
    a nominal 512) or longer (4148 for a nominal 4096) than the nominal
    block; the tail past ``nominal - 150`` is zero padding (FORMAT §5.5).

    Raises:
        WaveformChainError: If any record in the chain has the wrong tag
            or if the chain loops or exceeds the safety bound.
    """
    chunks: list[np.ndarray] = []
    visited: set[int] = set()
    current: int | None = first_vcfw
    for _ in range(VCFW_CHAIN_MAX_LENGTH):
        if current is None:
            break
        if current in visited:
            raise WaveformChainError(
                f"vcfw chain cycle detected at record {current}"
            )
        visited.add(current)
        record = reader.read_record(current)
        _check_tag(record, VCFW_TAG, current)
        chunks.append(
            np.frombuffer(
                record,
                dtype="<i2",
                count=VCFW_DATA_SAMPLES,
                offset=VCFW_DATA_OFFSET,
            ).astype(np.float32)
        )
        (next_stored,) = struct.unpack_from("<I", record, VCFW_NEXT_OFFSET)
        current = decode_inner_pointer(next_stored)
    else:
        raise WaveformChainError(
            f"vcfw chain exceeds {VCFW_CHAIN_MAX_LENGTH} records starting at {first_vcfw}"
        )
    if not chunks:
        return np.empty(0, dtype=np.float32)
    return np.concatenate(chunks)
