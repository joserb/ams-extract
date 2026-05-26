"""Tests for ``ams_extract.export.json_tree``."""

from __future__ import annotations

import json
from pathlib import Path

from ams_extract.export.json_tree import (
    PHASE_LABEL,
    SCHEMA_VERSION,
    build_tree_document,
    write_tree_json,
)
from ams_extract.reader import RbmReader
from ams_extract.tree import walk_areas


class TestBuildTreeDocument:
    def test_meta_block(self, synthetic_rbm: Path) -> None:
        with RbmReader(synthetic_rbm) as reader:
            areas = walk_areas(reader)
            document = build_tree_document(reader, areas, source_path=synthetic_rbm)
        meta = document["meta"]
        assert meta["schema_version"] == SCHEMA_VERSION
        assert meta["phase"] == PHASE_LABEL
        assert meta["source"] == str(synthetic_rbm)
        assert meta["signature"] == "MT4.00"
        assert meta["area_count"] == 5
        assert meta["equipment_count"] == 0
        assert meta["point_count"] == 0

    def test_areas_block_has_phase2b_placeholders(
        self, synthetic_rbm: Path
    ) -> None:
        with RbmReader(synthetic_rbm) as reader:
            areas = walk_areas(reader)
            document = build_tree_document(reader, areas, source_path=synthetic_rbm)
        for area_dict in document["areas"]:
            assert area_dict["equipment"] == []
            assert {"record_num", "slot_index", "long_name", "short_code"} <= set(
                area_dict
            )


class TestWriteTreeJson:
    def test_writes_utf8_json_roundtrips(
        self, synthetic_rbm: Path, tmp_path: Path
    ) -> None:
        with RbmReader(synthetic_rbm) as reader:
            areas = walk_areas(reader)
            document = build_tree_document(reader, areas, source_path=synthetic_rbm)
        out = tmp_path / "subdir" / "tree.json"
        write_tree_json(document, out)
        assert out.exists()
        reloaded = json.loads(out.read_text(encoding="utf-8"))
        assert reloaded["meta"]["area_count"] == 5
        assert len(reloaded["areas"]) == 5

    def test_preserves_non_ascii_in_names(self, tmp_path: Path) -> None:
        document = {
            "meta": {"schema_version": SCHEMA_VERSION, "phase": PHASE_LABEL},
            "areas": [
                {
                    "record_num": 69,
                    "slot_index": 9,
                    "long_name": "IMPULSIÓN DE MAR",
                    "short_code": "IMPULSION_DE_MAR",
                    "equipment": [],
                }
            ],
        }
        out = tmp_path / "tree.json"
        write_tree_json(document, out)
        text = out.read_text(encoding="utf-8")
        assert "IMPULSIÓN" in text  # ensure_ascii=False was used
