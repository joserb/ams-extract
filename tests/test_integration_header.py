"""Integration tests against a real .rbm database.

Gated on the ``RBM_TEST_FILE`` environment variable, which should point to
a real client .rbm file (e.g. BUNGE_CARTAGENA_marzo_2.0.rbm). The real file
is never committed; these tests are skipped when the variable is unset.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ams_extract.reader import RECORD_SIZE, RbmReader
from ams_extract.records.header import parse_header

pytestmark = pytest.mark.integration


def test_real_header_signature_and_description(real_rbm: Path) -> None:
    with RbmReader(real_rbm) as reader:
        header = parse_header(reader)
    assert header.signature == "MT4.00"
    assert "Preditec" in header.description, (
        f"expected 'Preditec' substring in description, got {header.description!r}"
    )


def test_real_header_pointer_targets_plausible_area_record(real_rbm: Path) -> None:
    with RbmReader(real_rbm) as reader:
        header = parse_header(reader)
        assert 0 < header.area_chain_first_record < reader.record_count, (
            "area-chain first-record pointer is out of range: "
            f"{header.area_chain_first_record}"
        )
        record = reader.read_record(header.area_chain_first_record)

    # The first slot should look like a 32-byte ASCII name padded with spaces.
    first_slot = record[:32]
    leading = first_slot.rstrip(b" \x00")
    assert leading, "first 32 bytes of the area record are blank"
    assert all(32 <= b < 127 for b in leading), (
        f"first area slot has non-ASCII bytes: {leading!r}"
    )


def test_real_file_is_512_aligned(real_rbm: Path) -> None:
    with RbmReader(real_rbm) as reader:
        assert reader.size % RECORD_SIZE == 0
        assert reader.record_count > 1
