"""Database inventory: per-machine sample counts and date ranges.

Backs the ``rbm report`` HTML inventory. Like :mod:`ams_extract.stats` it
walks the hierarchy and tallies the sample chains without reading any
amplitude/sample payloads (see
:func:`ams_extract.tree.point_sample_summary`), but it additionally keeps
the first/last timestamp of each sample type so the report can show the
date span of each measurement type per machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ams_extract.models import Area, Equipment
from ams_extract.reader import RbmReader
from ams_extract.records.header import parse_header
from ams_extract.stats import filter_areas  # reuse the stats area filter
from ams_extract.tree import TypeSummary, point_sample_summary, walk_hierarchy


def _merge(a: TypeSummary, b: TypeSummary) -> TypeSummary:
    """Combine two per-type summaries (sum counts, widen the date range)."""
    firsts = [t for t in (a.first, b.first) if t is not None]
    lasts = [t for t in (a.last, b.last) if t is not None]
    return TypeSummary(
        count=a.count + b.count,
        first=min(firsts) if firsts else None,
        last=max(lasts) if lasts else None,
    )


@dataclass(frozen=True, slots=True)
class MachineInventory:
    """Per-type counts and date ranges for one equipment (machine)."""

    area_short: str
    area_long: str
    equipment_short: str
    equipment_long: str
    n_points: int
    spectra: TypeSummary
    waveforms: TypeSummary
    trend: TypeSummary

    @property
    def total(self) -> int:
        return self.spectra.count + self.waveforms.count + self.trend.count


@dataclass(frozen=True, slots=True)
class AreaInventory:
    """One area (location) and the machines it holds, in walker order."""

    short_code: str
    long_name: str
    machines: tuple[MachineInventory, ...]

    @property
    def total(self) -> int:
        return sum(m.total for m in self.machines)


@dataclass(frozen=True, slots=True)
class InventoryReport:
    """Whole-database inventory: metadata + the area/machine tree."""

    source: str | None
    signature: str
    description: str
    areas: tuple[AreaInventory, ...]

    @property
    def n_areas(self) -> int:
        return len(self.areas)

    @property
    def n_machines(self) -> int:
        return sum(len(a.machines) for a in self.areas)

    @property
    def n_points(self) -> int:
        return sum(m.n_points for a in self.areas for m in a.machines)

    @property
    def spectra(self) -> TypeSummary:
        out = TypeSummary.empty()
        for area in self.areas:
            for m in area.machines:
                out = _merge(out, m.spectra)
        return out

    @property
    def waveforms(self) -> TypeSummary:
        out = TypeSummary.empty()
        for area in self.areas:
            for m in area.machines:
                out = _merge(out, m.waveforms)
        return out

    @property
    def trend(self) -> TypeSummary:
        out = TypeSummary.empty()
        for area in self.areas:
            for m in area.machines:
                out = _merge(out, m.trend)
        return out


def _machine_inventory(
    reader: RbmReader, area: Area, equipment: Equipment
) -> MachineInventory:
    """Aggregate every point of ``equipment`` into one :class:`MachineInventory`."""
    spectra = TypeSummary.empty()
    waveforms = TypeSummary.empty()
    trend = TypeSummary.empty()
    for point in equipment.points:
        s = point_sample_summary(reader, point)
        spectra = _merge(spectra, s.spectra)
        waveforms = _merge(waveforms, s.waveforms)
        trend = _merge(trend, s.trend)
    return MachineInventory(
        area_short=area.short_code,
        area_long=area.long_name,
        equipment_short=equipment.short_code,
        equipment_long=equipment.long_name,
        n_points=len(equipment.points),
        spectra=spectra,
        waveforms=waveforms,
        trend=trend,
    )


def collect_inventory(
    reader: RbmReader,
    *,
    area_filter: str | None = None,
    source_path: Path | str | None = None,
) -> InventoryReport:
    """Build the database inventory by walking the hierarchy once.

    ``area_filter`` is a case-insensitive substring match on each area's
    ``long_name`` / ``short_code`` (``None`` selects all), mirroring
    :func:`ams_extract.stats.collect_machine_stats`.
    """
    header = parse_header(reader)
    areas: list[AreaInventory] = []
    for area in filter_areas(walk_hierarchy(reader), area_filter):
        machines = tuple(
            _machine_inventory(reader, area, eq) for eq in area.equipment
        )
        areas.append(
            AreaInventory(
                short_code=area.short_code,
                long_name=area.long_name,
                machines=machines,
            )
        )
    return InventoryReport(
        source=str(source_path) if source_path is not None else None,
        signature=header.signature,
        description=header.description,
        areas=tuple(areas),
    )
