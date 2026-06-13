"""Tests for the on-demand live viewer served straight from a .rbm.

The HTML builder is exercised with synthetic hierarchy objects (no I/O). The
end-to-end API + render path needs a real database, so it is gated on
``RBM_TEST_FILE`` like the other integration tests.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from urllib.request import urlopen

import pytest

from ams_extract.export.live_viewer import build_live_html, serve
from ams_extract.models import Area, Equipment, Point
from ams_extract.reader import RbmReader
from ams_extract.tree import point_sample_refs, walk_hierarchy

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _areas() -> list[Area]:
    pt = Point(record_num=100, long_name="MOTOR LA H", short_code="MOTOR_LA_H")
    eq = Equipment(
        record_num=42, long_name="BOMBA 1", short_code="BOMBA_1", points=(pt,)
    )
    return [
        Area(
            record_num=7,
            slot_index=0,
            long_name="EXTRACCIÓN",
            short_code="EXTRACCION",
            equipment=(eq,),
        )
    ]


def test_build_live_html_embeds_machines_lazily() -> None:
    html = build_live_html(_areas(), title="DB de prueba")
    assert "DB de prueba" in html
    assert "EXTRACCIÓN" in html
    # the machine carries its record number for the lazy /api/machine call
    assert 'data-eq="42"' in html
    assert "BOMBA 1" in html
    # points are NOT embedded — they load on demand
    assert "MOTOR LA H" not in html


def test_build_live_html_empty() -> None:
    assert "base de datos vacía" in build_live_html([])


@pytest.fixture
def real_rbm() -> Path:
    env = os.environ.get("RBM_TEST_FILE")
    if not env:
        pytest.skip("RBM_TEST_FILE not set; integration test skipped")
    path = Path(env)
    if not path.exists():
        pytest.skip(f"RBM_TEST_FILE missing: {path}")
    return path


def _find_fft_target(path: Path) -> tuple[int, int, int]:
    """Return ``(equipment_rec, point_rec, fft_sample_id)`` for some point."""
    with RbmReader(path) as reader:
        for area in walk_hierarchy(reader):
            for eq in area.equipment:
                for pt in eq.points:
                    refs = point_sample_refs(reader, pt, "fft")
                    if refs:
                        return eq.record_num, pt.record_num, refs[0].record_num
    pytest.skip("no point with FFT samples found in RBM_TEST_FILE")


@pytest.mark.integration
def test_live_serve_end_to_end(real_rbm: Path) -> None:
    eq_rec, pt_rec, sid = _find_fft_target(real_rbm)
    server = serve(real_rbm, host="127.0.0.1", port=0)
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"{base}/") as resp:
            page = resp.read().decode()
        assert "Visor RBM" in page and 'class="machine"' in page

        with urlopen(f"{base}/api/machine/{eq_rec}") as resp:
            points = json.loads(resp.read())["points"]
        assert any(p["rec"] == pt_rec for p in points)
        assert any(p["fft"] > 0 for p in points)

        with urlopen(f"{base}/api/point/{pt_rec}/fft") as resp:
            samples = json.loads(resp.read())["samples"]
        assert any(s["id"] == sid for s in samples)

        with urlopen(f"{base}/plot/{pt_rec}/fft/{sid}.png") as resp:
            body = resp.read()
        assert body.startswith(_PNG_MAGIC)
    finally:
        server.shutdown()
        server.server_close()
