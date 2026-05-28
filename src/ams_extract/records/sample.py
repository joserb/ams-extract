"""Parsers for FFT spectrum records (``vdps`` descriptor + ``vcps`` data).

Verified chain (per the 2026-05-28 sub-fase 3a reconnaissance against
M1H of AG-100, BUNGE)::

    pdcd.0x44 → vdps (first FFT spectrum, oldest)
                 │
                 ├── 0x14 → vdps (next FFT spectrum in time)
                 ├── 0x18 → vcps (first data record of this spectrum)
                 ├── 0x20 → float32 Fmax (Hz)
                 ├── 0x24 → u32 Unix timestamp UTC
                 ├── 0x2C → float32 CARGA % (load)
                 ├── 0x50 → u32 n_lines (nominal FFT bin count)
                 └── 0x78 → ASCII 8 bytes — units (e.g. "plg/segs")

    vcps holds 122 float32 LE consecutive amplitude bins at offsets
    0x18..0x1FF; the chain links via 0x14 to the next vcps, ending in 0.
    A spectrum's amplitude buffer is the concatenation of every vcps in
    the chain that descends from the spectrum's vdps.

Amplitude values are emitted *raw* — AMS displays them after applying
unit conversion (units field is typically "plg/segs"; the UI converts
to mm/seg when the analyst's profile is metric). Sub-fase 3b leaves
that scaling deferred.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from ams_extract.encoding import decode_string
from ams_extract.reader import RECORD_SIZE, RbmReader, decode_inner_pointer

VDPS_TAG = b"vdps"
VCPS_TAG = b"vcps"
TAG_OFFSET = 0x08

# vdps offsets
VDPS_NEXT_OFFSET = 0x14
VDPS_FIRST_VCPS_OFFSET = 0x18
VDPS_FMAX_OFFSET = 0x20
VDPS_TIMESTAMP_OFFSET = 0x24
VDPS_CARGA_OFFSET = 0x2C
VDPS_N_LINES_OFFSET = 0x50
VDPS_UNITS_OFFSET = 0x78
VDPS_UNITS_LENGTH = 8

# vcps offsets
VCPS_NEXT_OFFSET = 0x14
VCPS_DATA_OFFSET = 0x18
VCPS_DATA_FLOATS = (RECORD_SIZE - VCPS_DATA_OFFSET) // 4  # 122

# Safety caps to bound traversal of malformed chains.
VDPS_CHAIN_MAX_LENGTH = 4096
VCPS_CHAIN_MAX_LENGTH = 256


class SampleChainError(ValueError):
    """Raised when a record in a sample chain has an unexpected tag."""


@dataclass(frozen=True, slots=True)
class VdpsDescriptor:
    """Metadata for one FFT spectrum, decoded from a ``vdps`` record."""

    record_num: int
    timestamp_utc: datetime
    fmax_hz: float
    n_lines: int
    units: str
    carga_pct: float
    first_vcps: int | None
    next_vdps: int | None


def _check_tag(record: bytes, expected: bytes, record_num: int) -> None:
    tag = bytes(record[TAG_OFFSET : TAG_OFFSET + 4])
    if tag != expected:
        raise SampleChainError(
            f"record {record_num}: expected tag {expected!r}, got {tag!r}"
        )


def parse_vdps_descriptor(reader: RbmReader, vdps_record: int) -> VdpsDescriptor:
    """Decode one ``vdps`` record into a :class:`VdpsDescriptor`.

    Raises:
        SampleChainError: If the record's tag is not ``vdps``.
    """
    record = reader.read_record(vdps_record)
    _check_tag(record, VDPS_TAG, vdps_record)

    def _u32(offset: int) -> int:
        return struct.unpack_from("<I", record, offset)[0]

    def _f32(offset: int) -> float:
        return float(struct.unpack_from("<f", record, offset)[0])

    timestamp_raw = _u32(VDPS_TIMESTAMP_OFFSET)
    timestamp_utc = datetime.fromtimestamp(timestamp_raw, UTC)
    units_bytes = record[VDPS_UNITS_OFFSET : VDPS_UNITS_OFFSET + VDPS_UNITS_LENGTH]
    return VdpsDescriptor(
        record_num=vdps_record,
        timestamp_utc=timestamp_utc,
        fmax_hz=_f32(VDPS_FMAX_OFFSET),
        n_lines=_u32(VDPS_N_LINES_OFFSET),
        units=decode_string(units_bytes),
        carga_pct=_f32(VDPS_CARGA_OFFSET),
        first_vcps=decode_inner_pointer(_u32(VDPS_FIRST_VCPS_OFFSET)),
        next_vdps=decode_inner_pointer(_u32(VDPS_NEXT_OFFSET)),
    )


def walk_vdps_chain(
    reader: RbmReader, first_vdps: int
) -> Iterator[VdpsDescriptor]:
    """Yield each :class:`VdpsDescriptor` in the chain starting at ``first_vdps``.

    Chain follows ``vdps.0x14`` (+1-encoded), 0 = end. Detects cycles and
    bounds the walk at :data:`VDPS_CHAIN_MAX_LENGTH`.

    Raises:
        SampleChainError: If any record in the chain has the wrong tag
            or if the chain loops or exceeds the safety bound.
    """
    visited: set[int] = set()
    current: int | None = first_vdps
    for _ in range(VDPS_CHAIN_MAX_LENGTH):
        if current is None:
            return
        if current in visited:
            raise SampleChainError(
                f"vdps chain cycle detected at record {current}"
            )
        visited.add(current)
        descriptor = parse_vdps_descriptor(reader, current)
        yield descriptor
        current = descriptor.next_vdps
    raise SampleChainError(
        f"vdps chain exceeds {VDPS_CHAIN_MAX_LENGTH} records starting at {first_vdps}"
    )


def read_vcps_amplitudes(reader: RbmReader, first_vcps: int) -> np.ndarray:
    """Concatenate the float32 LE amplitudes from one vcps chain.

    Returns a 1-D ``np.ndarray`` of dtype ``float32`` whose length is
    ``122 * <chain length>`` — typically ~1586 for a BUNGE FFT spectrum
    (13 records of 122 floats), close to the nominal ``n_lines`` (1600).

    Raises:
        SampleChainError: If any record in the chain has the wrong tag
            or if the chain loops or exceeds the safety bound.
    """
    chunks: list[np.ndarray] = []
    visited: set[int] = set()
    current: int | None = first_vcps
    for _ in range(VCPS_CHAIN_MAX_LENGTH):
        if current is None:
            break
        if current in visited:
            raise SampleChainError(
                f"vcps chain cycle detected at record {current}"
            )
        visited.add(current)
        record = reader.read_record(current)
        _check_tag(record, VCPS_TAG, current)
        chunks.append(
            np.frombuffer(
                record,
                dtype=np.float32,
                count=VCPS_DATA_FLOATS,
                offset=VCPS_DATA_OFFSET,
            ).copy()
        )
        (next_stored,) = struct.unpack_from("<I", record, VCPS_NEXT_OFFSET)
        current = decode_inner_pointer(next_stored)
    else:
        raise SampleChainError(
            f"vcps chain exceeds {VCPS_CHAIN_MAX_LENGTH} records starting at {first_vcps}"
        )
    if not chunks:
        return np.empty(0, dtype=np.float32)
    return np.concatenate(chunks)
