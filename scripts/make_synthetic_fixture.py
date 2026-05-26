"""Generate the minimal synthetic .rbm fixture used by unit tests.

The generated file mirrors what we've verified in `BUNGE CARTAGENA marzo 2.0.rbm`
at the smallest scale that exercises the parsers:

- **Record 0**: valid header (MT4.00 signature, gddh tag, GUID, description,
  candidate timestamp, primary area-chain pointer at 0xDC, secondary
  area-chain pointer at 0xE4).
- **Record 1**: "simple list" area record — three 32-byte name slots at
  offsets 0x00, 0x20, 0x40, then padding. Plus a fake "short-code list"
  slot at offset 0x180 that should be skipped by the parser heuristic.
- **Record 2**: "prefixed list" area record — opaque binary prefix
  (timestamp + 'gits' tag + pointers) up to 0xBF, then two 32-byte name
  slots at 0xC0 and 0xE0.
- **Records 3-15**: zeroed padding so the file holds 16 records total.

Total areas: 5. Re-run from the project root and commit the regenerated
fixture::

    uv run python scripts/make_synthetic_fixture.py
"""

from __future__ import annotations

import struct
from pathlib import Path

from ams_extract.reader import RECORD_SIZE

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "synthetic_minimal.rbm"
)
TOTAL_RECORDS = 16
SYNTHETIC_TIMESTAMP = 1_577_836_800  # 2020-01-01T00:00:00Z
SYNTHETIC_DESCRIPTION = b"SYNTHETIC FIXTURE - PHASES 0-2"
PRIMARY_AREA_RECORD = 1
SECONDARY_AREA_RECORD = 2

SIMPLE_AREA_NAMES = (b"AREA_ALPHA", b"AREA_BETA", b"AREA_GAMMA")
"""Three short area names placed at slots 0-2 of record 1."""

SIMPLE_AREA_SHORT_CODE_LIST = b"AAAA BBBB CCCC"
"""Concatenated short-code list placed at slot 12 of record 1 (parser should skip)."""

PREFIXED_AREA_NAMES = (b"AREA_DELTA", b"AREA_OMEGA")
"""Two names placed at slots 6-7 of record 2, after an opaque prefix region."""


def _pack_name_slot(name: bytes) -> bytes:
    """Place ``name`` left-aligned in a 32-byte slot, space-padded."""
    if len(name) > 32:
        raise ValueError(f"name {name!r} exceeds 32-byte slot width")
    buf = bytearray(b" " * 32)
    buf[: len(name)] = name
    return bytes(buf)


def _build_header() -> bytes:
    record = bytearray(RECORD_SIZE)
    record[0x00:0x04] = bytes.fromhex("76059f3c")
    record[0x04:0x08] = bytes.fromhex("01000e00")
    record[0x08:0x0C] = b"gddh"
    record[0x0C:0x1C] = bytes(range(16))
    record[0x1C:0x22] = b"MT4.00"
    struct.pack_into("<I", record, 0x2C, SYNTHETIC_TIMESTAMP)

    description_field = bytearray(b" " * 40)
    description_field[: len(SYNTHETIC_DESCRIPTION)] = SYNTHETIC_DESCRIPTION
    record[0x58:0x80] = bytes(description_field)

    struct.pack_into("<I", record, 0xDC, PRIMARY_AREA_RECORD)
    struct.pack_into("<I", record, 0xE4, SECONDARY_AREA_RECORD)
    return bytes(record)


def _build_simple_area_record() -> bytes:
    """Layout: three name slots at the start, then a short-code list at slot 12."""
    record = bytearray(b"\x00" * RECORD_SIZE)
    for i, name in enumerate(SIMPLE_AREA_NAMES):
        start = i * 32
        record[start : start + 32] = _pack_name_slot(name)
    # Slot 12 (offset 0x180): concatenated short-code list — heuristic skip target.
    record[0x180:0x180 + 32] = _pack_name_slot(SIMPLE_AREA_SHORT_CODE_LIST)
    return bytes(record)


def _build_prefixed_area_record() -> bytes:
    """Opaque prefix at 0x00-0xBF, name slots at 0xC0 and 0xE0."""
    record = bytearray(b"\x00" * RECORD_SIZE)
    # Opaque prefix: timestamp, gits tag, a couple of pointers — all binary
    # so the name-detection heuristic skips it.
    struct.pack_into("<I", record, 0x00, SYNTHETIC_TIMESTAMP)
    record[0x04:0x08] = bytes.fromhex("02000e00")
    record[0x08:0x0C] = b"gits"
    struct.pack_into("<I", record, 0x10, 100)
    struct.pack_into("<I", record, 0x14, 200)
    # Two area names at slots 6 and 7.
    record[0xC0:0xC0 + 32] = _pack_name_slot(PREFIXED_AREA_NAMES[0])
    record[0xE0:0xE0 + 32] = _pack_name_slot(PREFIXED_AREA_NAMES[1])
    return bytes(record)


def main() -> None:
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = _build_header()
    area_simple = _build_simple_area_record()
    area_prefixed = _build_prefixed_area_record()
    padding = bytes(RECORD_SIZE * (TOTAL_RECORDS - 3))
    FIXTURE_PATH.write_bytes(header + area_simple + area_prefixed + padding)
    print(f"wrote {FIXTURE_PATH} ({FIXTURE_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
