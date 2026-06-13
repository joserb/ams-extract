"""Database statistics: per-machine and database-wide sample counts.

Tallies how many FFT spectra, waveforms and trend readings each equipment
(machine) holds, by walking the hierarchy and counting the sample chains
without reading any amplitude/sample payloads (see
:func:`ams_extract.tree.count_point_samples`). Backs the ``rbm stats``
command group.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ams_extract.models import Area
from ams_extract.reader import RbmReader
from ams_extract.tree import count_point_samples, walk_hierarchy


@dataclass(frozen=True, slots=True)
class MachineStats:
    """Sample counts for one equipment (machine)."""

    area_short: str
    area_long: str
    equipment_short: str
    equipment_long: str
    n_points: int
    n_spectra: int
    n_waveforms: int
    n_trend_readings: int

    @property
    def total(self) -> int:
        return self.n_spectra + self.n_waveforms + self.n_trend_readings


@dataclass(frozen=True, slots=True)
class DatabaseStats:
    """Database-wide aggregate of a list of :class:`MachineStats`."""

    n_areas: int
    n_machines: int
    n_machines_with_data: int
    n_points: int
    n_spectra: int
    n_waveforms: int
    n_trend_readings: int

    @property
    def total_samples(self) -> int:
        return self.n_spectra + self.n_waveforms + self.n_trend_readings


def filter_areas(areas: Iterable[Area], area_filter: str | None) -> list[Area]:
    """Return areas whose long_name/short_code contains ``area_filter`` (ci)."""
    area_list = list(areas)
    if not area_filter:
        return area_list
    needle = area_filter.strip().lower()
    return [
        a
        for a in area_list
        if needle in a.long_name.lower() or needle in a.short_code.lower()
    ]


def collect_machine_stats(
    reader: RbmReader,
    *,
    area_filter: str | None = None,
    equipment_filter: str | None = None,
) -> list[MachineStats]:
    """Return per-machine sample counts, in walker order.

    ``area_filter`` / ``equipment_filter`` are case-insensitive substring
    matches on the respective long_name / short_code; ``None`` selects all.
    """
    eq_needle = equipment_filter.strip().lower() if equipment_filter else None
    stats: list[MachineStats] = []
    for area in filter_areas(walk_hierarchy(reader), area_filter):
        for eq in area.equipment:
            if eq_needle is not None and eq_needle not in eq.long_name.lower():
                continue
            sp = wv = tn = 0
            for point in eq.points:
                psp, pwv, ptn = count_point_samples(reader, point)
                sp += psp
                wv += pwv
                tn += ptn
            stats.append(
                MachineStats(
                    area_short=area.short_code,
                    area_long=area.long_name,
                    equipment_short=eq.short_code,
                    equipment_long=eq.long_name,
                    n_points=len(eq.points),
                    n_spectra=sp,
                    n_waveforms=wv,
                    n_trend_readings=tn,
                )
            )
    return stats


def summarize(machines: list[MachineStats]) -> DatabaseStats:
    """Aggregate a list of :class:`MachineStats` into a :class:`DatabaseStats`."""
    areas = {m.area_short for m in machines}
    return DatabaseStats(
        n_areas=len(areas),
        n_machines=len(machines),
        n_machines_with_data=sum(1 for m in machines if m.total > 0),
        n_points=sum(m.n_points for m in machines),
        n_spectra=sum(m.n_spectra for m in machines),
        n_waveforms=sum(m.n_waveforms for m in machines),
        n_trend_readings=sum(m.n_trend_readings for m in machines),
    )
