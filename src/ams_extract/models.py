"""Domain models for the AMS hierarchy.

Frozen, slotted dataclasses for memory efficiency and immutability.
``Equipment`` and ``Point`` were placeholders in Phase 2a; Phase 2b
populates them from the equipment- and point-record chains discovered in
ADR-0003 (``gdts`` → ``gicm`` → ``gdcm`` → ``gipm`` → ``vdpm``).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Point:
    """A measurement point on an equipment.

    Attributes:
        record_num: Zero-based record number of the ``vdpm`` record that
            defines this point.
        long_name: Human-readable name as stored in the ``vdpm`` record
            (cp1252 decoded, trailing space/NUL stripped).
        short_code: Sanitized, filesystem-safe identifier for this point.
    """

    record_num: int
    long_name: str
    short_code: str


@dataclass(frozen=True, slots=True)
class Equipment:
    """An equipment (machine) within an area.

    Attributes:
        record_num: Zero-based record number of the ``gdcm`` record that
            defines this equipment instance.
        long_name: Equipment name as stored in the parent ``gicm`` record's
            name slot (cp1252 decoded, trailing space/NUL stripped).
        short_code: Sanitized, filesystem-safe identifier for this equipment.
        points: Points belonging to this equipment, in walker order.
    """

    record_num: int
    long_name: str
    short_code: str
    points: tuple[Point, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Area:
    """A site area: the top level of the hierarchy.

    Attributes:
        record_num: Record number where this area's name slot lives
            (either the prefix-list or the simple-list area record).
        slot_index: Index of the 32-byte slot within ``record_num`` (0-based).
        long_name: Human-readable name as stored in the RBM (cp1252 decoded).
        short_code: Sanitized, filesystem-safe identifier for this area.
        equipment: Equipment belonging to this area, in walker order.
            Empty for areas whose ``gdts`` / ``gicm`` chain could not be
            walked (logged as a warning by the walker).
    """

    record_num: int
    slot_index: int
    long_name: str
    short_code: str
    equipment: tuple[Equipment, ...] = field(default_factory=tuple)
