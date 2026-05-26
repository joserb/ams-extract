"""Parser for the database header (record 0) of a .rbm file.

Header layout verified against ``BUNGE CARTAGENA marzo 2.0.rbm``. Many fields
are still tentative; the parser only commits to what we have confirmed and
exposes raw bytes for the rest so callers can experiment without re-parsing.

Verified field map (record 0)::

    0x00  4 bytes   header_marker (likely checksum)
    0x04  4 bytes   version_marker (e.g. 01 00 0e 00)
    0x08  4 bytes   tag "gddh"  (database-header tag, ASCII)
    0x0C  16 bytes  guid / hash
    0x1C  6 bytes   signature  "MT4.00"
    0x22  ...       reserved / unknown
    0x2C  4 bytes   u32 LE     candidate timestamp (epoch seconds)
    0x40  24 bytes  reserved / unknown
    0x58  40 bytes  description (cp1252, space-padded)
    0x80  ...       field-label strings ("CARGA PORCENTAJE", "AREA", "EQUIPO")
    0xDC  4 bytes   u32 LE     first record in the area chain
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import UTC, datetime

from ams_extract.encoding import decode_string
from ams_extract.reader import RECORD_SIZE, RbmFileError, RbmReader

SIGNATURE_OFFSET = 0x1C
SIGNATURE_BYTES = b"MT4.00"
DESCRIPTION_OFFSET = 0x58
DESCRIPTION_LENGTH = 0x28  # 40 bytes
TIMESTAMP_OFFSET = 0x2C
GUID_OFFSET = 0x0C
GUID_LENGTH = 16
DB_TAG_OFFSET = 0x08
DB_TAG_LENGTH = 4
VERSION_MARKER_OFFSET = 0x04
VERSION_MARKER_LENGTH = 4
AREA_CHAIN_POINTER_OFFSET = 0xDC


@dataclass(frozen=True, slots=True)
class Header:
    """Parsed view of record 0 (the database header)."""

    signature: str
    """Format signature, expected to be ``MT4.00``."""

    version_marker: bytes
    """4 raw bytes at offset 0x04 — interpretation still tentative."""

    db_tag: str
    """4-character tag at offset 0x08 — typically ``gddh``."""

    guid: bytes
    """16 raw bytes at offset 0x0C — likely a database GUID or hash."""

    description: str
    """Human-readable description string at offset 0x58 (40 bytes, cp1252)."""

    timestamp_raw: int
    """Raw little-endian u32 at offset 0x2C — candidate epoch-seconds timestamp."""

    area_chain_first_record: int
    """Record number where the first area-chain record lives (zero-based)."""

    @property
    def timestamp(self) -> datetime | None:
        """Best-effort interpretation of :attr:`timestamp_raw` as UTC epoch seconds.

        Returns ``None`` when the raw value falls outside a plausible 1990-2100
        window, which signals that the field is not (only) a Unix timestamp.
        """
        # Plausible Unix timestamp window: 1990-01-01 .. 2100-01-01
        if 631_152_000 <= self.timestamp_raw <= 4_102_444_800:
            return datetime.fromtimestamp(self.timestamp_raw, tz=UTC)
        return None


def parse_header(reader: RbmReader) -> Header:
    """Parse record 0 of the given reader and return a :class:`Header`.

    Raises:
        RbmFileError: If the signature does not match ``MT4.00``.
    """
    record = reader.read_record(0)
    if len(record) != RECORD_SIZE:
        raise RbmFileError(f"record 0 is {len(record)} bytes; expected {RECORD_SIZE}")

    signature_bytes = record[SIGNATURE_OFFSET : SIGNATURE_OFFSET + len(SIGNATURE_BYTES)]
    if signature_bytes != SIGNATURE_BYTES:
        raise RbmFileError(
            f"bad signature: {signature_bytes!r}; expected {SIGNATURE_BYTES!r}"
        )

    description = decode_string(
        record[DESCRIPTION_OFFSET : DESCRIPTION_OFFSET + DESCRIPTION_LENGTH]
    )
    db_tag = decode_string(record[DB_TAG_OFFSET : DB_TAG_OFFSET + DB_TAG_LENGTH])
    version_marker = bytes(
        record[VERSION_MARKER_OFFSET : VERSION_MARKER_OFFSET + VERSION_MARKER_LENGTH]
    )
    guid = bytes(record[GUID_OFFSET : GUID_OFFSET + GUID_LENGTH])
    (timestamp_raw,) = struct.unpack_from("<I", record, TIMESTAMP_OFFSET)
    (area_chain_first_record,) = struct.unpack_from("<I", record, AREA_CHAIN_POINTER_OFFSET)

    return Header(
        signature=signature_bytes.decode("ascii"),
        version_marker=version_marker,
        db_tag=db_tag,
        guid=guid,
        description=description,
        timestamp_raw=int(timestamp_raw),
        area_chain_first_record=int(area_chain_first_record),
    )
