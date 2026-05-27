"""Parsers for the area → equipment chain (``gdts`` / ``gicm`` / ``gdcm``).

Verified chain (per ADR-0003, against ``BUNGE CARTAGENA marzo 2.0.rbm``)::

    Area
      └─ gdts record   (one per area; from the prefix-list area record's
                        gdts-pointer table at offset 0x10)
          └─ gicm record   (first in a singly-linked list, pointer at
                            gdts offset 0x18; the last one is mirrored at
                            gdts offset 0x1C as a convenience)
              ├─ up to GICM_MAX_EQUIPMENT slots, each with:
              │     • a u32 LE pointer at 0x10 + i*4 to a gdcm record
              │     • a 28-byte name slot at 0xB0 + i*28
              ├─ a "next gicm" pointer at offset 0x0C; areas with more
              │   than 12 equipment chain via that field, terminated by 0
              └─ ... follows to the next gicm in the chain

A ``gdcm`` record is the equipment instance — it carries the pointer to
the equipment's ``gipm`` (points list) record at offset 0x14.

All pointers walked through this module are stored "+1" so that ``0``
encodes the end-of-list sentinel; ``decode_inner_pointer`` handles that.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ams_extract.encoding import decode_string
from ams_extract.reader import RECORD_SIZE, RbmReader, decode_inner_pointer

# --- gdts (area → equipment-chain intermediate) ---
GDTS_TAG = b"gdts"
GDTS_GICM_POINTER_OFFSET = 0x18

# --- gicm (area's equipment list with names) ---
GICM_TAG = b"gicm"
GICM_NEXT_POINTER_OFFSET = 0x0C
"""Offset of the "next ``gicm`` in chain" pointer (0 = end-of-chain)."""
GICM_GDCM_POINTERS_OFFSET = 0x10
GICM_NAMES_OFFSET = 0xB0
GICM_NAME_SLOT_SIZE = 28
GICM_MAX_EQUIPMENT = (RECORD_SIZE - GICM_NAMES_OFFSET) // GICM_NAME_SLOT_SIZE
"""Maximum equipment slots one ``gicm`` record can hold (BUNGE: 12).

Areas with more than this many equipment chain via :data:`GICM_NEXT_POINTER_OFFSET`.
"""
GICM_CHAIN_MAX_LENGTH = 256
"""Defensive cap on the length of a ``gicm`` chain to bound cycles."""

# --- gdcm (equipment instance) ---
GDCM_TAG = b"gdcm"
GDCM_GIPM_POINTER_OFFSET = 0x14

TAG_OFFSET = 0x08
"""Every typed record stores its 4-char tag at offset 0x08."""


class EquipmentChainError(ValueError):
    """Raised when a record in the equipment chain has an unexpected tag."""


@dataclass(frozen=True, slots=True)
class EquipmentSlot:
    """One entry in a ``gicm`` record: a name plus a ``gdcm`` pointer."""

    long_name: str
    gdcm_record: int
    slot_index: int


def _check_tag(record: bytes, expected: bytes, record_num: int) -> None:
    tag = bytes(record[TAG_OFFSET : TAG_OFFSET + 4])
    if tag != expected:
        raise EquipmentChainError(
            f"record {record_num}: expected tag {expected!r}, got {tag!r}"
        )


def parse_gdts_gicm_pointer(reader: RbmReader, gdts_record: int) -> int | None:
    """Return the zero-based ``gicm`` record number from a ``gdts`` record.

    Returns ``None`` if the ``gicm`` pointer is null (the area has no
    equipment list).

    Raises:
        EquipmentChainError: If the record's tag is not ``gdts``.
    """
    record = reader.read_record(gdts_record)
    _check_tag(record, GDTS_TAG, gdts_record)
    (stored,) = struct.unpack_from("<I", record, GDTS_GICM_POINTER_OFFSET)
    return decode_inner_pointer(stored)


def _parse_single_gicm_slots(
    record: bytes, gicm_record: int
) -> tuple[list[EquipmentSlot], int | None]:
    """Decode one ``gicm`` record into its equipment slots + next-chain pointer.

    Returns ``(slots, next_gicm)`` where ``next_gicm`` is the zero-based
    record number of the next ``gicm`` in the chain or ``None`` if this is
    the last gicm. The slot index is recorded relative to ``gicm_record``
    so that callers building cross-record indices can disambiguate.
    """
    slots: list[EquipmentSlot] = []
    for i in range(GICM_MAX_EQUIPMENT):
        ptr_off = GICM_GDCM_POINTERS_OFFSET + i * 4
        (stored,) = struct.unpack_from("<I", record, ptr_off)
        gdcm = decode_inner_pointer(stored)
        if gdcm is None:
            break
        name_off = GICM_NAMES_OFFSET + i * GICM_NAME_SLOT_SIZE
        name_bytes = record[name_off : name_off + GICM_NAME_SLOT_SIZE]
        slots.append(
            EquipmentSlot(
                long_name=decode_string(name_bytes),
                gdcm_record=gdcm,
                slot_index=i,
            )
        )
    (next_stored,) = struct.unpack_from("<I", record, GICM_NEXT_POINTER_OFFSET)
    return slots, decode_inner_pointer(next_stored)


def parse_gicm_equipment_slots(
    reader: RbmReader, gicm_record: int
) -> list[EquipmentSlot]:
    """Return every equipment slot in the ``gicm`` chain starting at ``gicm_record``.

    Areas with more than :data:`GICM_MAX_EQUIPMENT` equipment chain via
    the "next gicm" pointer at offset :data:`GICM_NEXT_POINTER_OFFSET`.
    This function follows that linked list, in order, accumulating all
    slots. Visited gicm records are tracked so a cyclic chain terminates
    instead of spinning forever, and the chain length is hard-capped by
    :data:`GICM_CHAIN_MAX_LENGTH`.

    Raises:
        EquipmentChainError: If any record's tag is not ``gicm``.
    """
    slots: list[EquipmentSlot] = []
    visited: set[int] = set()
    current: int | None = gicm_record
    for _ in range(GICM_CHAIN_MAX_LENGTH):
        if current is None:
            break
        if current in visited:
            raise EquipmentChainError(
                f"gicm chain cycle detected at record {current}"
            )
        visited.add(current)
        record = reader.read_record(current)
        _check_tag(record, GICM_TAG, current)
        chunk, current = _parse_single_gicm_slots(record, current)
        slots.extend(chunk)
    else:
        raise EquipmentChainError(
            f"gicm chain exceeds {GICM_CHAIN_MAX_LENGTH} records"
            f" starting at {gicm_record}"
        )
    return slots


def parse_gdcm_gipm_pointer(reader: RbmReader, gdcm_record: int) -> int | None:
    """Return the zero-based ``gipm`` record number from a ``gdcm`` record.

    Returns ``None`` if the ``gipm`` pointer is null (the equipment has no
    points list).

    Raises:
        EquipmentChainError: If the record's tag is not ``gdcm``.
    """
    record = reader.read_record(gdcm_record)
    _check_tag(record, GDCM_TAG, gdcm_record)
    (stored,) = struct.unpack_from("<I", record, GDCM_GIPM_POINTER_OFFSET)
    return decode_inner_pointer(stored)
