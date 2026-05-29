"""Domain models for the AMS hierarchy.

Frozen, slotted dataclasses for memory efficiency and immutability.
``Equipment`` and ``Point`` were placeholders in Phase 2a; Phase 2b
populates them from the equipment- and point-record chains discovered in
ADR-0003 (``gdts`` → ``gicm`` → ``gdcm`` → ``gipm`` → ``vdpm``).
``Spectrum`` is added in sub-fase 3b for FFT samples reached through the
``vdpm.0x10 → pdcd → vdps → vcps`` chain. ``Waveform`` is added in
sub-fase 5b for time-domain samples reached through the parallel
``pdcd → 0x5C → vdfw → vcfw`` chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


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


@dataclass(frozen=True, slots=True)
class Spectrum:
    """One FFT spectrum measured at a point.

    Reached through ``vdpm.0x10 → pdcd → 0x44 → vdps → 0x18 → vcps``.
    The amplitude array length is ``122 * <vcps chain length>`` —
    typically ~1586 in BUNGE for the nominal ``n_lines = 1600``;
    reconciliation of those 14 trailing bins is still open (FORMAT §5.5).

    Attributes:
        record_num: Zero-based record number of the ``vdps`` descriptor.
        point_record_num: Record number of the parent ``vdpm`` (point).
        timestamp_utc: Sample timestamp as decoded from ``vdps.0x24``.
        fmax_hz: Nominal Fmax in Hz, from ``vdps.0x20``.
        n_lines: Nominal FFT bin count, from ``vdps.0x50``.
        units: Units string as stored in ``vdps.0x78`` (e.g. ``"plg/segs"``).
        carga_pct: CARGA % field, from ``vdps.0x2C``.
        amplitude: Raw float32 amplitude buffer from the ``vcps`` chain.
    """

    record_num: int
    point_record_num: int
    timestamp_utc: datetime
    fmax_hz: float
    n_lines: int
    units: str
    carga_pct: float
    amplitude: NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class Waveform:
    """One time-domain waveform measured at a point.

    Reached through ``vdpm.0x10 → pdcd → 0x5C → vdfw → 0x18 → vcfw``.
    The samples array length is ``244 * <vcfw chain length>`` — typically
    ~488 in BUNGE for the nominal ``n_samples = 512``; reconciliation of
    those trailing samples is still open (FORMAT §5.5).

    Attributes:
        record_num: Zero-based record number of the ``vdfw`` descriptor.
        point_record_num: Record number of the parent ``vdpm`` (point).
        timestamp_utc: Sample timestamp as decoded from ``vdfw.0x34``.
        n_samples: Nominal sample count, from ``vdfw.0x2C``.
        sample_rate_hz: Sample rate in Hz, derived from ``vdfw.0x24``
            (``1 / sample_period``).
        rpm: Shaft speed in RPM, from ``vdfw.0x38``.
        units: Units string as stored in ``vdfw.0x6C`` (e.g. ``"G's"``).
        carga_pct: CARGA % field, from ``vdfw.0x3C``.
        samples: Calibrated float32 sample buffer in ``units`` — the raw
            ``vcfw`` int16 counts multiplied by ``vdfw.0x28`` (scale
            factor). For M1H 19-feb-2020 this reproduces the AMS Pc/Pk
            values within 0.3% (FORMAT §5.5).
    """

    record_num: int
    point_record_num: int
    timestamp_utc: datetime
    n_samples: int
    sample_rate_hz: float
    rpm: float
    units: str
    carga_pct: float
    samples: NDArray[np.float32]
