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
    The amplitude array is the full spectrum: the low 78 bins from the
    ``vdps`` descriptor tail (0xC8..0x1FF) concatenated with the ``vcps``
    chain, truncated to ``n_lines`` (FORMAT §5.6). Bin ``i`` maps to
    frequency ``i * fmax_hz / n_lines``.

    Attributes:
        record_num: Zero-based record number of the ``vdps`` descriptor.
        point_record_num: Record number of the parent ``vdpm`` (point).
        timestamp_utc: Sample timestamp as decoded from ``vdps.0x24``.
        fmax_hz: Nominal Fmax in Hz, from ``vdps.0x20``.
        n_lines: Nominal FFT bin count, from ``vdps.0x50`` (= amplitude length).
        units: Display units — ``"mm/s"`` for the calibrated velocity
            spectrum (the common case), else the raw ``vdps.0x78`` string.
        rpm: Shaft speed in RPM, decoded from ``vdps.0x28`` (stored doubled).
        carga_pct: CARGA % field, from ``vdps.0x2C``.
        amplitude: Calibrated float32 amplitude buffer. For velocity
            spectra the raw values are scaled to mm/s (FORMAT §5.6);
            reproduces the AMS peak list within ~5% on 3 validated machines.
    """

    record_num: int
    point_record_num: int
    timestamp_utc: datetime
    fmax_hz: float
    n_lines: int
    units: str
    rpm: float
    carga_pct: float
    amplitude: NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class Waveform:
    """One time-domain waveform measured at a point.

    Reached through ``vdpm.0x10 → pdcd → 0x5C → vdfw → 0x18 → vcfw``.
    The samples array length is ``244 * <vcfw chain length>`` and does NOT
    equal the nominal block size stored in ``vdfw.0x2C`` (488 vs 512, 4148
    vs 4096): AMS writes ``nominal - 150`` real samples and rounds the
    storage up to whole 244-sample ``vcfw`` records, zero-padding the tail
    (FORMAT §5.5, ADR-0017). ``n_samples`` is therefore the length of
    ``samples`` — the nominal is kept apart in ``nominal_n_samples``.

    Attributes:
        record_num: Zero-based record number of the ``vdfw`` descriptor.
        point_record_num: Record number of the parent ``vdpm`` (point).
        timestamp_utc: Sample timestamp as decoded from ``vdfw.0x34``.
        n_samples: Length of ``samples``, i.e. what was actually decoded
            and is emitted. Every consumer derives the time axis from it
            (``n_samples / sample_rate_hz`` seconds).
        sample_rate_hz: Sample rate in Hz, derived from ``vdfw.0x24``
            (``1 / sample_period``).
        rpm: Shaft speed in RPM, from ``vdfw.0x38``.
        units: Units string as stored in ``vdfw.0x6C`` (e.g. ``"G's"``).
        carga_pct: CARGA % field, from ``vdfw.0x3C``.
        samples: Calibrated float32 sample buffer in ``units`` — the raw
            ``vcfw`` int16 counts multiplied by ``vdfw.0x28`` (scale
            factor). For M1H 19-feb-2020 this reproduces the AMS Pc/Pk
            values within 0.3% (FORMAT §5.5).
        nominal_n_samples: Acquisition block size as configured in AMS,
            verbatim from ``vdfw.0x2C`` (512, 4096…); ``None`` when the
            waveform was rebuilt from an exported table instead of a
            ``.rbm`` record. Documentary only — never a length.
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
    nominal_n_samples: int | None = None


@dataclass(frozen=True, slots=True)
class TrendBand:
    """One named ``vddt`` band series of a point's trend (FORMAT §5.7/§5.8).

    The band identity (name, frequency range, thresholds) comes from the
    point's shared analysis-parameter set (``pdpa``) and alarm-limit set
    (``pdla``). Mixed units per slot: "Mp Wave" is a raw acceleration peak
    in G's, spectral bands are velocities calibrated to mm/s
    (``raw * 25.4``) — each column validated 62/62 against the AMS
    per-band PLOTDATA gold for M1H AG-100, and the band values reproduce
    the root-sum-square of the raw spectrum bins inside ``[low, high)``
    (FORMAT §5.8).

    Attributes:
        name: Original AMS band label ("SUBSINCRONO", "Mp Wave", ...).
        units: Display units of ``values`` (``"mm/s"`` or ``"G's"``).
        timestamps_utc: Reading timestamps, oldest first. Only readings
            whose stored column count matches the point's current template
            contribute, so this can be shorter than the overall series.
        values: Calibrated band value per reading.
        low_order: Band low edge in shaft orders (order-scaled bands), else
            ``None``.
        high_order: Band high edge in shaft orders, else ``None``.
        low_hz: Band low edge in Hz (fixed-frequency bands), else ``None``.
        high_hz: Band high edge in Hz, else ``None``.
        alert: Alert (C) threshold in display units, or ``None`` if not
            configured.
        danger: Danger (D) threshold in display units, or ``None``.
        alarms: Derived alarm level per reading — 0 normal, 2 alert,
            3 danger (VibFrame scale) — computed from ``alert``/``danger``,
            NOT read from the (undecoded) per-slot flags. ``None`` per
            reading when the point has no thresholds for this slot.
    """

    name: str
    units: str
    timestamps_utc: tuple[datetime, ...]
    values: NDArray[np.float32]
    low_order: float | None = None
    high_order: float | None = None
    low_hz: float | None = None
    high_hz: float | None = None
    alert: float | None = None
    danger: float | None = None
    alarms: tuple[int | None, ...] = ()


@dataclass(frozen=True, slots=True)
class Trend:
    """The "Valores Globales" trend series for a point (overall RMS).

    Reached through ``vdpm.0x10 → pdcd → 0x3C → vddt → (chain via 0x10)``.
    Each ``vddt`` record holds a run of sample slots; the whole chain is
    flattened into the parallel ``timestamps_utc`` / ``overall`` arrays,
    oldest reading first (FORMAT §5.7, ADR-0006). The native unit comes
    from the point's primary FFT measurement: velocity points calibrate to
    mm/s, acceleration points (PeakVue / high-frequency) are raw G's.

    Attributes:
        record_num: Zero-based record number of the first ``vddt`` in the chain.
        point_record_num: Record number of the parent ``vdpm`` (point).
        units: Display units of ``overall`` — ``"mm/s"`` for velocity
            points, ``"G's"`` for acceleration points.
        timestamps_utc: Reading timestamps, one per element of ``overall``,
            oldest first. Decoded via the off-by-one date rule (FORMAT §5.7).
        overall: Calibrated overall value per reading — ``raw * 25.4`` →
            mm/s for velocity (validated 47/47 against the AMS PLOTDATA gold
            for M1H AG-100), raw G's for acceleration (validated 147/147
            against the "Lista Ptos de Tendc" gold for DT-0070 M1P,
            ADR-0014).
        bands: Named band series decoded through the point's analysis
            parameter set (``pdpa``, FORMAT §5.8); empty when the point has
            no resolvable template or no reading matches its column count.
        alert: Overall alert (C) threshold in display units (from the
            point's ``pdla`` alarm limit set), or ``None``.
        danger: Overall danger (D) threshold in display units, or ``None``.
        alarms: Derived alarm level per overall reading (0 normal, 2 alert,
            3 danger; ``None`` when no thresholds are configured). Same
            derived-not-stored caveat as :attr:`TrendBand.alarms`.
    """

    record_num: int
    point_record_num: int
    units: str
    timestamps_utc: tuple[datetime, ...]
    overall: NDArray[np.float32]
    bands: tuple[TrendBand, ...] = ()
    alert: float | None = None
    danger: float | None = None
    alarms: tuple[int | None, ...] = ()
