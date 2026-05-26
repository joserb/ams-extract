"""Generate the minimal synthetic .rbm fixture used by unit tests.

The generated file currently covers Phase 1 needs: a valid record 0 with
signature ``MT4.00``, GUID, description, candidate timestamp and an area
chain pointer, plus zeroed padding records so the file holds more than one
record. Later phases will extend this script with synthetic area / equipment
/ point / sample records.

Re-run from the project root (with the package installed) and commit the
regenerated fixture::

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
SYNTHETIC_DESCRIPTION = b"SYNTHETIC FIXTURE - PHASE 1"
SYNTHETIC_AREA_POINTER = 1


def _build_header() -> bytes:
    record = bytearray(RECORD_SIZE)
    record[0x00:0x04] = bytes.fromhex("76059f3c")
    record[0x04:0x08] = bytes.fromhex("01000e00")
    record[0x08:0x0C] = b"gddh"
    record[0x0C:0x1C] = bytes(range(16))
    record[0x1C:0x22] = b"MT4.00"
    struct.pack_into("<I", record, 0x2C, SYNTHETIC_TIMESTAMP)

    # 40-byte description field, space-padded.
    description_field = bytearray(b" " * 40)
    description_field[: len(SYNTHETIC_DESCRIPTION)] = SYNTHETIC_DESCRIPTION
    record[0x58:0x80] = bytes(description_field)

    struct.pack_into("<I", record, 0xDC, SYNTHETIC_AREA_POINTER)
    return bytes(record)


def main() -> None:
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = _build_header()
    padding = bytes(RECORD_SIZE * (TOTAL_RECORDS - 1))
    FIXTURE_PATH.write_bytes(header + padding)
    print(f"wrote {FIXTURE_PATH} ({FIXTURE_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
