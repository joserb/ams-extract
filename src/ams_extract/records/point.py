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
