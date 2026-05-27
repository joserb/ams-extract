"""Parser for area-chain records.

Two distinct layouts have been observed in `BUNGE CARTAGENA marzo 2.0.rbm`:

- **Simple list** (record 70 in BUNGE): up to 16 slots of 32 bytes each
  starting at offset 0. The first 5 slots hold area names; the rest are
  blank (ASCII spaces).
- **Prefixed list** (record 69 in BUNGE): a header-like preamble at offsets
  0x00-0xBF (timestamp, ``gits`` tag, pointer table, float-ish bytes) and
  then 10 slots of 32 bytes each starting at offset 0xC0; the first 9 are
  populated with area names.

Rather than commit to either layout, the parser scans every 32-byte aligned
slot in the record (16 slots total) and returns those that look like names:
non-empty, printable ASCII, containing at least one letter. This catches
both layouts without needing layout detection, and is robust to the small
amount of garbage that occasionally appears in unused slots.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass

from ams_extract.encoding import decode_string
from ams_extract.reader import RECORD_SIZE, RbmReader, decode_inner_pointer

SLOT_SIZE = 32
"""Width of a single area-name slot, in bytes."""

SLOTS_PER_RECORD = RECORD_SIZE // SLOT_SIZE
"""Maximum number of 32-byte slots that fit in a 512-byte record."""

PREFIXED_LIST_TAG = b"gits"
"""Tag at offset 0x08 identifying a prefix-list area record."""

GDTS_POINTER_TABLE_OFFSET = 0x10
"""Start of the area→gdts pointer table inside a prefix-list area record."""

GDTS_POINTER_TABLE_MAX_ENTRIES = 20
"""Slot count of the gdts pointer table (0x10..0x60 in the prefix-list record).

Entries past the last real area are zero-padded (end-of-list sentinel).
"""


@dataclass(frozen=True, slots=True)
class AreaSlot:
    """A single area name found in an area-chain record."""

    record_num: int
    slot_index: int
    name: str


def _looks_like_name(slot: bytes) -> bool:
    """Return True if ``slot`` looks like a 32-byte name field with padding.

    Accepts any byte ``>= 0x20`` except DEL (``0x7F``) — this allows cp1252
    accented characters like ``Ó`` (``0xD3``) found in names such as
    ``IMPULSIÓN DE MAR``. The slot must contain at least one ASCII letter
    after stripping padding so we don't pick up records made entirely of
    high-bit byte sequences.
    """
    stripped = slot.rstrip(b" \x00")
    if len(stripped) < 2:
        return False
    if any(b < 0x20 or b == 0x7F for b in stripped):
        return False
    return any((0x41 <= b <= 0x5A) or (0x61 <= b <= 0x7A) for b in stripped)


def parse_area_record(reader: RbmReader, record_num: int) -> list[AreaSlot]:
    """Return every area-name slot found in record ``record_num``.

    Scans 32-byte slots in order; before the first match, non-name slots are
    skipped (this is the "prefix header" region of the record-69-style layout).
    After the first match, the scan stops at the next non-name slot — this
    avoids picking up trailing slots that hold concatenated short-code lists
    (observed in BUNGE's record 70 slots 12-13) rather than real area names.
    """
    record = reader.read_record(record_num)
    return list(_iter_area_slots(record, record_num))


def _iter_area_slots(record: bytes, record_num: int) -> Iterator[AreaSlot]:
    found_any = False
    for slot_index in range(SLOTS_PER_RECORD):
        start = slot_index * SLOT_SIZE
        slot = record[start : start + SLOT_SIZE]
        if _looks_like_name(slot):
            found_any = True
            yield AreaSlot(
                record_num=record_num,
                slot_index=slot_index,
                name=decode_string(slot),
            )
        elif found_any:
            return


def is_prefixed_list_record(reader: RbmReader, record_num: int) -> bool:
    """Return True if record ``record_num`` is a prefix-list area record.

    The prefix-list layout is identified by the ``gits`` tag at offset 0x08.
    """
    record = reader.read_record(record_num)
    return bytes(record[0x08:0x0C]) == PREFIXED_LIST_TAG


def parse_gdts_pointer_table(reader: RbmReader, record_num: int) -> list[int]:
    """Return the area→gdts pointer table from a prefix-list area record.

    Reads up to :data:`GDTS_POINTER_TABLE_MAX_ENTRIES` u32 LE values from
    offset :data:`GDTS_POINTER_TABLE_OFFSET` and stops at the first
    end-of-list sentinel (``0``). Each returned value is the zero-based
    record number of a ``gdts`` record (the area's equipment-chain head),
    obtained by applying :func:`~ams_extract.reader.decode_inner_pointer`.
    """
    record = reader.read_record(record_num)
    pointers: list[int] = []
    for i in range(GDTS_POINTER_TABLE_MAX_ENTRIES):
        (stored,) = struct.unpack_from(
            "<I", record, GDTS_POINTER_TABLE_OFFSET + i * 4
        )
        decoded = decode_inner_pointer(stored)
        if decoded is None:
            break
        pointers.append(decoded)
    return pointers
