"""Parsers for the equipment → point chain (``gipm`` / ``vdpm``).

Verified chain (per ADR-0003)::

    Equipment (gdcm)
      └─ gipm record   (one per equipment; pointer at gdcm offset 0x14)
          └─ u32 LE pointer table at 0x1C0 (up to GIPM_MAX_POINTS entries),
             each entry stores ``vdpm_record_b0 + 1``. A zero terminates.
              └─ vdpm record   (one per point; long_name at 0x18, 32 bytes)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ams_extract.encoding import decode_string
from ams_extract.reader import RECORD_SIZE, RbmReader, decode_inner_pointer

# --- gipm (equipment's points list) ---
GIPM_TAG = b"gipm"
GIPM_POINTERS_OFFSET = 0x1C0
GIPM_MAX_POINTS = (RECORD_SIZE - GIPM_POINTERS_OFFSET) // 4
"""Maximum point pointers one ``gipm`` record can hold (BUNGE: 16)."""

# --- vdpm (point) ---
VDPM_TAG = b"vdpm"
VDPM_NAME_OFFSET = 0x18
VDPM_NAME_LENGTH = 32
VDPM_PDCD_POINTER_OFFSET = 0x10
"""Offset of the +1-encoded pointer to the point's ``pdcd`` sample index."""

VDPM_BEARING_COUNT_OFFSET = 0x7D
"""u8 with how many of the bearing slots are filled (0-7)."""

VDPM_BEARING_OFFSET = 0x7E
VDPM_BEARING_SLOT_SIZE = 14
VDPM_BEARING_SLOTS = 7
"""Seven 14-byte space-padded designation slots, ``0x07E``-``0x0E0``."""

BEARING_UNSET = "INDEFINID"
"""Sentinel AMS writes in every unused designation slot (*indefinido*)."""

VDPM_NOMINAL_RPM_OFFSET = 0x164
"""float32 LE with the point's configured (nominal) shaft speed, in RPM."""

TAG_OFFSET = 0x08


class PointChainError(ValueError):
    """Raised when a record in the point chain has an unexpected tag."""


@dataclass(frozen=True, slots=True)
class PointRecord:
    """A point reachable from a ``gipm`` table entry."""

    record_num: int
    long_name: str
    slot_index: int


def _check_tag(record: bytes, expected: bytes, record_num: int) -> None:
    tag = bytes(record[TAG_OFFSET : TAG_OFFSET + 4])
    if tag != expected:
        raise PointChainError(
            f"record {record_num}: expected tag {expected!r}, got {tag!r}"
        )


def parse_gipm_point_records(
    reader: RbmReader, gipm_record: int
) -> list[int]:
    """Return the ``vdpm`` record numbers referenced by a ``gipm`` record.

    The pointer table at offset ``GIPM_POINTERS_OFFSET`` is read in order
    until a null pointer is hit (end-of-list sentinel). Returned record
    numbers are zero-based.

    Raises:
        PointChainError: If the record's tag is not ``gipm``.
    """
    record = reader.read_record(gipm_record)
    _check_tag(record, GIPM_TAG, gipm_record)

    pointers: list[int] = []
    for i in range(GIPM_MAX_POINTS):
        ptr_off = GIPM_POINTERS_OFFSET + i * 4
        (stored,) = struct.unpack_from("<I", record, ptr_off)
        vdpm = decode_inner_pointer(stored)
        if vdpm is None:
            break
        pointers.append(vdpm)
    return pointers


def parse_vdpm_point(reader: RbmReader, vdpm_record: int) -> PointRecord:
    """Decode the ``vdpm`` record at ``vdpm_record`` into a :class:`PointRecord`.

    Raises:
        PointChainError: If the record's tag is not ``vdpm``.
    """
    record = reader.read_record(vdpm_record)
    _check_tag(record, VDPM_TAG, vdpm_record)
    name_bytes = record[VDPM_NAME_OFFSET : VDPM_NAME_OFFSET + VDPM_NAME_LENGTH]
    return PointRecord(
        record_num=vdpm_record,
        long_name=decode_string(name_bytes),
        slot_index=0,
    )


def parse_vdpm_bearings(reader: RbmReader, vdpm_record: int) -> tuple[str, ...]:
    """Return the bearing designations configured for this point.

    AMS keeps seven 14-byte space-padded slots at ``VDPM_BEARING_OFFSET`` and
    the number of filled ones in the byte just before them; every unfilled
    slot holds the literal ``BEARING_UNSET``. The count is honoured rather
    than scanning for the sentinel — in the whole Bunge database (5 203
    points) the two agree slot for slot, which is what pins the layout down.

    The strings are free text typed by the analyst, so they come back raw:
    plain ISO numbers (``6204``, ``23248``), designations with a maker
    (``SKF 6308``, ``FAG 22220``) or a suffix (``6205/2Z``, ``22218 EKC3``),
    and the odd non-designation (``RED``). Normalizing them against a bearing
    catalogue is the enricher's job, not the parser's.

    Only 1 520 of the 5 203 Bunge points (149 of 342 machines) declare any;
    an empty tuple is the normal case, not an error.

    Raises:
        PointChainError: If the record's tag is not ``vdpm``.
    """
    record = reader.read_record(vdpm_record)
    _check_tag(record, VDPM_TAG, vdpm_record)
    count = min(record[VDPM_BEARING_COUNT_OFFSET], VDPM_BEARING_SLOTS)
    designations: list[str] = []
    for i in range(count):
        start = VDPM_BEARING_OFFSET + i * VDPM_BEARING_SLOT_SIZE
        raw = decode_string(record[start : start + VDPM_BEARING_SLOT_SIZE])
        if raw and raw != BEARING_UNSET:
            designations.append(raw)
    return tuple(designations)


def parse_vdpm_nominal_rpm(reader: RbmReader, vdpm_record: int) -> float | None:
    """Return the point's configured (nominal) shaft speed in RPM.

    This is the speed the analyst declared for the shaft this point sits on —
    the plate speed, or the one propagated through the gearbox ratios (the
    Toaster gearbox DT-0070 declares 1 500 RPM on the motor and 32, 30 and 9.6
    on its successive shafts). AMS pre-fills the analysis RPM of a new
    measurement with it: it equals ``vdps.0x28`` (gold-verified in ADR-0013)
    in 134 183 of the 137 270 Bunge spectra, the rest being machines where the
    analyst typed the speed actually measured.

    ``None`` is returned for a non-positive value; every Bunge point has one
    (9-3 000 RPM, 114 distinct values), so that is a guard, not a known case.

    Raises:
        PointChainError: If the record's tag is not ``vdpm``.
    """
    record = reader.read_record(vdpm_record)
    _check_tag(record, VDPM_TAG, vdpm_record)
    (rpm,) = struct.unpack_from("<f", record, VDPM_NOMINAL_RPM_OFFSET)
    if rpm <= 0.0:
        return None
    return float(rpm)


def parse_vdpm_pdcd_pointer(reader: RbmReader, vdpm_record: int) -> int | None:
    """Return the ``pdcd`` record this point's samples are indexed under.

    Returns ``None`` if the pointer is null (the point has no sample
    index — exceptional, but observed for placeholder/template points).

    Raises:
        PointChainError: If the record's tag is not ``vdpm``.
    """
    record = reader.read_record(vdpm_record)
    _check_tag(record, VDPM_TAG, vdpm_record)
    (stored,) = struct.unpack_from("<I", record, VDPM_PDCD_POINTER_OFFSET)
    return decode_inner_pointer(stored)
