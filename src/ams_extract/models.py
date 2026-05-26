"""Domain models for the AMS hierarchy.

Frozen, slotted dataclasses for memory efficiency and immutability. Equipment
and Point are placeholders for Phase 2b — see ``docs/PLAN.md`` §5 Fase 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Area:
    """A site area: the top level of the hierarchy.

    Attributes:
        record_num: Record number where this area's name slot lives.
        slot_index: Index of the 32-byte slot within ``record_num`` (0-based).
        long_name: Human-readable name as stored in the RBM (cp1252 decoded).
        short_code: Sanitized, filesystem-safe identifier for this area.
        equipment: Equipment belonging to this area. Empty in Phase 2 —
            populated by the Phase 2b walker once the equipment chain is
            understood.
    """

    record_num: int
    slot_index: int
    long_name: str
    short_code: str
    equipment: tuple[Equipment, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Equipment:
    """An equipment (machine) within an area. Phase 2b placeholder."""

    record_num: int
    long_name: str
    short_code: str
    points: tuple[Point, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Point:
    """A measurement point on an equipment. Phase 2b placeholder."""

    record_num: int
    long_name: str
    short_code: str
