"""Tests for the inventory model and the HTML inventory renderer."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ams_extract.export.html_report import render_inventory_html, write_inventory_html
from ams_extract.reader import RbmReader
from ams_extract.report import (
    AreaInventory,
    InventoryReport,
    MachineInventory,
    collect_inventory,
)
from ams_extract.tree import TypeSummary


def _ts(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)


def _machine(
    name: str,
    *,
    sp: TypeSummary | None = None,
    wv: TypeSummary | None = None,
    tn: TypeSummary | None = None,
    area: str = "AREA 1",
) -> MachineInventory:
    empty = TypeSummary.empty()
    return MachineInventory(
        area_short=area,
        area_long=area,
        equipment_short=name,
        equipment_long=name,
        n_points=2,
        spectra=sp or empty,
        waveforms=wv or empty,
        trend=tn or empty,
    )


def _report(*machines: MachineInventory) -> InventoryReport:
    area = AreaInventory(
        short_code="AREA 1", long_name="AREA 1", machines=tuple(machines)
    )
    return InventoryReport(
        source="BUNGE.rbm", signature="MT4.00", description="Preditec", areas=(area,)
    )


class TestTypeSummary:
    def test_of_tracks_min_max(self) -> None:
        s = TypeSummary.of([_ts(2021, 5, 1), _ts(2020, 1, 1), _ts(2022, 3, 3)])
        assert s.count == 3
        assert s.first == _ts(2020, 1, 1)
        assert s.last == _ts(2022, 3, 3)

    def test_empty(self) -> None:
        s = TypeSummary.empty()
        assert s.count == 0 and s.first is None and s.last is None
        assert TypeSummary.of([]) == s


class TestInventoryTotals:
    def test_aggregates_across_machines(self) -> None:
        m1 = _machine("M1", sp=TypeSummary.of([_ts(2020, 1, 1), _ts(2021, 1, 1)]))
        m2 = _machine("M2", sp=TypeSummary.of([_ts(2019, 6, 1)]))
        report = _report(m1, m2)
        assert report.n_machines == 2
        assert report.n_areas == 1
        assert report.spectra.count == 3
        # widened date span across both machines
        assert report.spectra.first == _ts(2019, 6, 1)
        assert report.spectra.last == _ts(2021, 1, 1)


class TestRenderInventoryHtml:
    def test_contains_structure_and_counts(self) -> None:
        m = _machine(
            "Bomba PM-01",
            sp=TypeSummary.of([_ts(2020, 1, 1), _ts(2021, 2, 2)]),
            wv=TypeSummary.of([_ts(2020, 1, 1)]),
        )
        html = render_inventory_html(_report(m))
        assert "<!DOCTYPE html>" in html
        assert "<details" in html  # collapsible tree
        assert 'id="filter"' in html  # search box + script
        assert "Bomba PM-01" in html
        assert "2020-01-01" in html
        assert "2021-02-02" in html
        assert "Preditec" in html  # description in header

    def test_escapes_names(self) -> None:
        m = _machine("<script>alert(1)</script>")
        html = render_inventory_html(_report(m))
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_zero_counts_render_dash(self) -> None:
        html = render_inventory_html(_report(_machine("Empty M")))
        assert "Empty M" in html
        assert "—" in html  # empty date span placeholder

    def test_write_creates_file(self, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "report.html"
        write_inventory_html(_report(_machine("M1")), out)
        assert out.exists()
        assert out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


# --- Integration: real BUNGE database (gated on RBM_TEST_FILE) ---

pytestmark_integration = pytest.mark.integration


@pytest.fixture
def real_rbm() -> Path:
    env = os.environ.get("RBM_TEST_FILE")
    if not env:
        pytest.skip("RBM_TEST_FILE not set; integration test skipped")
    path = Path(env)
    if not path.exists():
        pytest.skip(f"RBM_TEST_FILE missing: {path}")
    return path


@pytest.mark.integration
def test_collect_inventory_real(real_rbm: Path) -> None:
    with RbmReader(real_rbm) as reader:
        report = collect_inventory(reader, source_path=real_rbm)
    assert report.n_areas > 0
    assert report.n_machines > 0
    # at least one machine should carry some data with a real date range
    with_data = [
        m
        for a in report.areas
        for m in a.machines
        if m.total > 0
    ]
    assert with_data, "expected at least one machine with data"
    html = render_inventory_html(report)
    assert "<details" in html and report.areas[0].long_name in html
