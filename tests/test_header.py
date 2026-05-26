"""Tests for ``ams_extract.records.header``."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ams_extract.reader import RECORD_SIZE, RbmFileError, RbmReader
from ams_extract.records.header import (
    AREA_CHAIN_POINTER_OFFSET,
    SIGNATURE_BYTES,
    SIGNATURE_OFFSET,
    parse_header,
)


class TestParseHeaderSynthetic:
    def test_signature(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader:
            header = parse_header(reader)
        assert header.signature == "MT4.00"

    def test_description(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader:
            header = parse_header(reader)
        assert header.description == "SYNTHETIC FIXTURE - PHASE 1"

    def test_db_tag(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader:
            header = parse_header(reader)
        assert header.db_tag == "gddh"

    def test_guid_length(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader:
            header = parse_header(reader)
        assert len(header.guid) == 16

    def test_timestamp_decodes_to_known_date(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader:
            header = parse_header(reader)
        assert header.timestamp == datetime(2020, 1, 1, tzinfo=UTC)

    def test_area_chain_pointer(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader:
            header = parse_header(reader)
        assert header.area_chain_first_record == 1


class TestParseHeaderErrors:
    def test_bad_signature_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.rbm"
        record = bytearray(RECORD_SIZE)
        record[SIGNATURE_OFFSET : SIGNATURE_OFFSET + len(SIGNATURE_BYTES)] = b"XXXXXX"
        bad.write_bytes(bytes(record))
        with RbmReader(bad) as reader, pytest.raises(RbmFileError, match="signature"):
            parse_header(reader)

    def test_timestamp_outside_window_returns_none(self, tmp_path: Path) -> None:
        bad = tmp_path / "ts.rbm"
        record = bytearray(RECORD_SIZE)
        record[SIGNATURE_OFFSET : SIGNATURE_OFFSET + len(SIGNATURE_BYTES)] = SIGNATURE_BYTES
        # leave timestamp = 0 (epoch); 0 is outside the plausibility window
        bad.write_bytes(bytes(record))
        with RbmReader(bad) as reader:
            header = parse_header(reader)
        assert header.timestamp is None

    def test_offsets_constants_match_layout(self) -> None:
        # Smoke check: signature is at 0x1C and area-chain pointer is in the
        # second half of the record; if these drift the header parser is wrong.
        assert SIGNATURE_OFFSET == 0x1C
        assert AREA_CHAIN_POINTER_OFFSET >= 0x80
