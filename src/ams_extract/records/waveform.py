"""Parsers for time-domain waveform records (``vdfw`` descriptor + ``vcfw`` data).

Verified chain (metadata from the 2026-05-29 sub-fase 5a reconnaissance and
payload layout corrected on 2026-08-12 against all BUNGE waveforms)::

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

    The first 150 int16 LE samples live in the descriptor itself, at
    ``vdfw.0xD4..0x1FF``. The continuation lives in ``vcfw`` records: each
    holds 244 int16 LE samples at offsets 0x18..0x1FF and links via 0x14 to
    the next record. AMS rounds that continuation up to whole records and
    zero-pads only the physical tail.

    Therefore the waveform is
    ``concat(vdfw[0xD4:0x200], vcfw_chain)[:n_samples]``. For a nominal 512
    block this is 150 descriptor samples + 362 continuation samples; the 126
    remaining values in the second vcfw are padding. Verified structurally
    over all 137 208 BUNGE waveforms and every nominal size (FORMAT §5.5,
    ADR-0020, superseding ADR-0017).

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
"""Complete waveform length (2.56 x FFT lines), including descriptor data."""
VDFW_TIMESTAMP_OFFSET = 0x34
VDFW_RPM_OFFSET = 0x38
VDFW_CARGA_OFFSET = 0x3C
VDFW_UNITS_OFFSET = 0x6C
VDFW_UNITS_LENGTH = 8
VDFW_DATA_OFFSET = 0xD4
VDFW_DATA_SAMPLES = (RECORD_SIZE - VDFW_DATA_OFFSET) // 2  # 150 int16 LE

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


def read_vdfw_samples(reader: RbmReader, vdfw_record: int) -> np.ndarray:
    """Return the first 150 raw waveform samples stored in ``vdfw``.

    The descriptor tail ``0xD4..0x1FF`` is not metadata or padding: it is the
    first part of the time signal, exactly 150 int16 LE counts. The returned
    float32 array is still uncalibrated; callers apply ``vdfw.0x28`` after
    assembling it with the continuation chain.
    """
    record = reader.read_record(vdfw_record)
    _check_tag(record, VDFW_TAG, vdfw_record)
    return np.frombuffer(
        record,
        dtype="<i2",
        count=VDFW_DATA_SAMPLES,
        offset=VDFW_DATA_OFFSET,
    ).astype(np.float32)


def read_vcfw_samples(reader: RbmReader, first_vcfw: int) -> np.ndarray:
    """Concatenate the continuation counts from one ``vcfw`` chain.

    Returns a 1-D ``np.ndarray`` of dtype ``float32`` (int16 samples cast
    up so downstream plotting/scaling never has to worry about overflow)
    whose length is ``244 * <chain length>``. Only the first
    ``n_samples - 150`` counts are signal; the rest of the last physical
    record is zero padding. Use :func:`assemble_waveform` with the 150 counts
    returned by :func:`read_vdfw_samples` to recover the complete block.

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


def assemble_waveform(
    descriptor_samples: np.ndarray,
    continuation_samples: np.ndarray,
    n_samples: int,
) -> np.ndarray:
    """Assemble and validate one complete nominal waveform buffer.

    ``descriptor_samples`` precede the ``vcfw`` continuation. Any values past
    ``n_samples`` must be physical zero-padding; non-zero overflow is rejected
    instead of silently discarding data from an unknown layout variant.
    """
    if n_samples < 0:
        raise WaveformChainError(f"negative waveform sample count: {n_samples}")
    if descriptor_samples.size != VDFW_DATA_SAMPLES:
        raise WaveformChainError(
            "vdfw descriptor sample block has wrong length: "
            f"{descriptor_samples.size} != {VDFW_DATA_SAMPLES}"
        )
    full = np.concatenate((descriptor_samples, continuation_samples)).astype(
        np.float32, copy=False
    )
    if full.size < n_samples:
        raise WaveformChainError(
            f"waveform payload shorter than nominal: {full.size} < {n_samples}"
        )
    padding = full[n_samples:]
    if np.any(padding):
        raise WaveformChainError(
            f"waveform has {int(np.count_nonzero(padding))} non-zero samples "
            f"past nominal length {n_samples}"
        )
    return full[:n_samples].copy()
