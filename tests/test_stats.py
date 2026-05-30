"""Tests for the sample-count statistics (``rbm stats``)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ams_extract.reader import RbmReader
from ams_extract.stats import MachineStats, collect_machine_stats, summarize


def _machine(area: str, eq: str, sp: int, wv: int, tn: int, pts: int = 3) -> MachineStats:
    return MachineStats(
        area_short=area,
        area_long=area,
        equipment_short=eq,
        equipment_long=eq,
        n_points=pts,
        n_spectra=sp,
        n_waveforms=wv,
        n_trend_readings=tn,
    )


class TestSummarize:
    def test_aggregates_totals(self) -> None:
        machines = [
            _machine("A", "m1", 10, 8, 5),
            _machine("A", "m2", 0, 0, 0),
            _machine("B", "m3", 4, 4, 2),
        ]
        s = summarize(machines)
        assert s.n_areas == 2
        assert s.n_machines == 3
        assert s.n_machines_with_data == 2  # m2 has none
        assert s.n_points == 9
        assert s.n_spectra == 14
        assert s.n_waveforms == 12
        assert s.n_trend_readings == 7
        assert s.total_samples == 33

    def test_machine_total_property(self) -> None:
        assert _machine("A", "m", 5, 5, 62).total == 72

    def test_empty(self) -> None:
        s = summarize([])
        assert s.n_machines == 0 and s.total_samples == 0


# --- Integration: real BUNGE database (gated on RBM_TEST_FILE) ---

pytest_integration = pytest.mark.integration


@pytest.fixture
def real_rbm() -> Path:
    env = os.environ.get("RBM_TEST_FILE")
    if not env:
        pytest.skip("RBM_TEST_FILE not set; integration test skipped")
    path = Path(env)
    if not path.exists():
        pytest.skip(f"RBM_TEST_FILE points to a missing path: {path}")
    return path


@pytest_integration
def test_real_counts_match_export(real_rbm: Path) -> None:
    # The stats counters must agree with what `rbm export` emits.
    with RbmReader(real_rbm) as reader:
        machines = collect_machine_stats(reader)
    s = summarize(machines)
    assert s.n_machines == 347
    assert s.n_machines_with_data == 311
    assert s.n_points == 5203
    assert s.n_spectra == 137270
    assert s.n_waveforms == 137208


@pytest_integration
def test_real_m1h_point_counts(real_rbm: Path) -> None:
    from ams_extract.tree import count_point_samples, walk_hierarchy

    with RbmReader(real_rbm) as reader:
        point = next(
            p
            for area in walk_hierarchy(reader)
            if "DEPURADORA" in area.long_name
            for eq in area.equipment
            if "AG-100" in eq.long_name
            for p in eq.points
            if p.long_name == "MOTOR LOA HORIZONTAL"
        )
        sp, wv, tn = count_point_samples(reader, point)
    assert (sp, wv, tn) == (5, 5, 62)
