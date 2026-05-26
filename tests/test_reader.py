"""Tests for ``ams_extract.reader.RbmReader``."""

from __future__ import annotations

from pathlib import Path

import pytest

from ams_extract.reader import RECORD_SIZE, RbmFileError, RbmReader


class TestRbmReader:
    def test_opens_and_reports_size_and_count(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader:
            assert reader.size == reader.record_count * RECORD_SIZE
            assert reader.record_count == 16

    def test_read_record_returns_exactly_512_bytes(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader:
            data = reader.read_record(0)
            assert len(data) == RECORD_SIZE

    def test_read_record_negative_raises(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader, pytest.raises(IndexError):
            reader.read_record(-1)

    def test_read_record_past_end_raises(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader, pytest.raises(IndexError):
            reader.read_record(reader.record_count)

    def test_read_u32_little_endian(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader:
            # The synthetic fixture writes area-chain pointer = 1 at 0xDC.
            assert reader.read_u32(0, 0xDC) == 1

    def test_rejects_non_multiple_of_record_size(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.rbm"
        bad.write_bytes(b"\x00" * (RECORD_SIZE + 5))
        with pytest.raises(RbmFileError, match="not a multiple"):
            RbmReader(bad)

    def test_rejects_empty_file(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.rbm"
        empty.write_bytes(b"")
        with pytest.raises(RbmFileError, match="empty"):
            RbmReader(empty)

    def test_context_manager_closes(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader:
            reader.read_record(0)
        with pytest.raises(ValueError, match="closed"):
            reader.read_record(0)
