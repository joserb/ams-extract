"""Top-down walker over the .rbm hierarchy.

Phase 2a: :func:`walk_areas` reads just the area-chain pointers from the
header and returns the list of areas, leaving ``Area.equipment`` empty.

Phase 2b: :func:`walk_hierarchy` extends the walk by following each area's
``gdts`` → ``gicm`` → ``gdcm`` → ``gipm`` → ``vdpm`` chain (see
``docs/DECISIONS.md`` ADR-0003) and returns areas with their equipment and
points populated. The walker never aborts on per-record errors — broken
chains are logged and skipped so an exporter can still produce partial
output.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import structlog

from ams_extract.models import (
    Area,
    Equipment,
    Point,
    Spectrum,
    Trend,
    TrendBand,
    Waveform,
)
from ams_extract.naming import NameSanitizer
from ams_extract.reader import RbmReader
from ams_extract.records.area import (
    AreaSlot,
    is_prefixed_list_record,
    parse_area_record,
    parse_gdts_pointer_table,
)
from ams_extract.records.equipment import (
    EquipmentChainError,
    parse_gdcm_gipm_pointer,
    parse_gdts_gicm_pointer,
    parse_gicm_equipment_slots,
)
from ams_extract.records.header import (
    AREA_CHAIN_SECONDARY_POINTER_OFFSET,
    parse_header,
)
from ams_extract.records.point import (
    PointChainError,
    parse_gipm_point_records,
    parse_vdpm_pdcd_pointer,
    parse_vdpm_point,
)
from ams_extract.records.sample import (
    ACCEL_SCALE_G,
    ACCEL_UNITS_RAW,
    VELOCITY_SCALE_MM_S,
    VELOCITY_UNITS_CALIBRATED,
    VELOCITY_UNITS_RAW,
    SampleChainError,
    assemble_spectrum,
    read_vcps_amplitudes,
    read_vdps_low_band,
    walk_vdps_chain,
)
from ams_extract.records.sample_index import (
    PdcdLinks,
    SampleIndexError,
    parse_pdcd_links,
)
from ams_extract.records.trend import (
    TREND_VELOCITY_SCALE_MM_S,
    TrendChainError,
    TrendLayoutError,
    parse_vddt_record,
    walk_vddt_chain,
)
from ams_extract.records.waveform import (
    WAVEFORM_VELOCITY_SCALE_MM_S,
    WaveformChainError,
    read_vcfw_samples,
    walk_vdfw_chain,
)

_log = structlog.get_logger(__name__)


def walk_areas(reader: RbmReader) -> list[Area]:
    """Return every area reachable from the header pointers, deduped and sorted.

    Areas are returned in canonical order: by record number, then by slot
    index. Short codes are guaranteed unique via the deterministic suffixing
    rules of :class:`~ams_extract.naming.NameSanitizer`.
    """
    header = parse_header(reader)
    secondary = reader.read_u32(0, AREA_CHAIN_SECONDARY_POINTER_OFFSET)

    pointers: list[int] = []
    for ptr, label in (
        (header.area_chain_first_record, "primary"),
        (secondary, "secondary"),
    ):
        if ptr == 0:
            continue
        if ptr >= reader.record_count:
            _log.warning(
                "area_chain_pointer_out_of_range",
                label=label,
                pointer=ptr,
                record_count=reader.record_count,
            )
            continue
        if ptr in pointers:
            continue
        pointers.append(ptr)

    slots: list[AreaSlot] = []
    for ptr in pointers:
        slots.extend(parse_area_record(reader, ptr))

    slots.sort(key=lambda s: (s.record_num, s.slot_index))
    sanitizer = NameSanitizer()
    return [
        Area(
            record_num=slot.record_num,
            slot_index=slot.slot_index,
            long_name=slot.name,
            short_code=sanitizer.sanitize(slot.name),
        )
        for slot in slots
    ]


def _collect_area_chain_records(reader: RbmReader) -> list[int]:
    """Return the area-chain record numbers reachable from the header pointers."""
    header = parse_header(reader)
    secondary = reader.read_u32(0, AREA_CHAIN_SECONDARY_POINTER_OFFSET)
    pointers: list[int] = []
    for ptr in (header.area_chain_first_record, secondary):
        if ptr == 0 or ptr >= reader.record_count or ptr in pointers:
            continue
        pointers.append(ptr)
    return pointers


def _find_prefixed_list_record(
    reader: RbmReader, area_chain_records: list[int]
) -> int | None:
    """Return the prefix-list area record number, or ``None`` if not present.

    The prefix-list record carries the area→gdts pointer table; the
    "simple list" record has no such table.
    """
    for rec in area_chain_records:
        if is_prefixed_list_record(reader, rec):
            return rec
    return None


def _walk_points_for_equipment(
    reader: RbmReader, gdcm_record: int, equipment_name: str
) -> tuple[Point, ...]:
    """Resolve the points list for a single equipment."""
    try:
        gipm_record = parse_gdcm_gipm_pointer(reader, gdcm_record)
    except (EquipmentChainError, IndexError) as exc:
        _log.warning(
            "gdcm_parse_failed",
            equipment=equipment_name,
            gdcm_record=gdcm_record,
            error=str(exc),
        )
        return ()
    if gipm_record is None:
        _log.info(
            "equipment_has_no_points_list",
            equipment=equipment_name,
            gdcm_record=gdcm_record,
        )
        return ()

    try:
        vdpm_records = parse_gipm_point_records(reader, gipm_record)
    except (PointChainError, IndexError) as exc:
        _log.warning(
            "gipm_parse_failed",
            equipment=equipment_name,
            gipm_record=gipm_record,
            error=str(exc),
        )
        return ()

    point_sanitizer = NameSanitizer()
    points: list[Point] = []
    for vdpm in vdpm_records:
        try:
            point = parse_vdpm_point(reader, vdpm)
        except (PointChainError, IndexError) as exc:
            _log.warning(
                "vdpm_parse_failed",
                equipment=equipment_name,
                vdpm_record=vdpm,
                error=str(exc),
            )
            continue
        points.append(
            Point(
                record_num=point.record_num,
                long_name=point.long_name,
                short_code=point_sanitizer.sanitize(point.long_name),
            )
        )
    return tuple(points)


def _walk_equipment_for_area(
    reader: RbmReader,
    area: Area,
    gdts_record: int,
    sanitizer: NameSanitizer,
) -> tuple[Equipment, ...]:
    """Walk the equipment + point chain rooted at ``gdts_record``.

    Per-record failures are logged and skipped so they never abort the
    walk of sibling areas or equipment.
    """
    try:
        gicm_record = parse_gdts_gicm_pointer(reader, gdts_record)
    except (EquipmentChainError, IndexError) as exc:
        _log.warning(
            "gdts_parse_failed",
            area=area.long_name,
            gdts_record=gdts_record,
            error=str(exc),
        )
        return ()
    if gicm_record is None:
        _log.info(
            "area_has_no_equipment_list",
            area=area.long_name,
            gdts_record=gdts_record,
        )
        return ()

    try:
        slots = parse_gicm_equipment_slots(reader, gicm_record)
    except (EquipmentChainError, IndexError) as exc:
        _log.warning(
            "gicm_parse_failed",
            area=area.long_name,
            gicm_record=gicm_record,
            error=str(exc),
        )
        return ()

    equipment: list[Equipment] = []
    for slot in slots:
        points = _walk_points_for_equipment(reader, slot.gdcm_record, slot.long_name)
        equipment.append(
            Equipment(
                record_num=slot.gdcm_record,
                long_name=slot.long_name,
                short_code=sanitizer.sanitize(slot.long_name),
                points=points,
            )
        )
    return tuple(equipment)


def walk_hierarchy(reader: RbmReader) -> list[Area]:
    """Return every area populated with its equipment and points.

    Combines :func:`walk_areas` with a follow-the-pointers walk of each
    area's equipment and point chains. The area→gdts mapping comes from
    the prefix-list area record's pointer table; areas without a
    corresponding gdts pointer are returned with empty equipment.

    Walker order matches :func:`walk_areas`. Equipment within an area and
    points within an equipment are emitted in their on-disk slot order.
    """
    areas = walk_areas(reader)
    if not areas:
        return areas

    chain_records = _collect_area_chain_records(reader)
    prefixed_record = _find_prefixed_list_record(reader, chain_records)
    if prefixed_record is None:
        _log.warning(
            "no_prefixed_list_record_found",
            area_chain_records=chain_records,
        )
        return areas

    gdts_pointers = parse_gdts_pointer_table(reader, prefixed_record)
    if len(gdts_pointers) != len(areas):
        _log.warning(
            "gdts_pointer_count_mismatch",
            gdts_count=len(gdts_pointers),
            area_count=len(areas),
        )

    sanitizer = NameSanitizer()
    populated: list[Area] = []
    for index, area in enumerate(areas):
        if index >= len(gdts_pointers):
            populated.append(area)
            continue
        equipment = _walk_equipment_for_area(
            reader, area, gdts_pointers[index], sanitizer
        )
        populated.append(
            Area(
                record_num=area.record_num,
                slot_index=area.slot_index,
                long_name=area.long_name,
                short_code=area.short_code,
                equipment=equipment,
            )
        )
    return populated


def _resolve_pdcd_links(reader: RbmReader, point: Point) -> PdcdLinks | None:
    """Resolve ``point``'s ``pdcd`` sample-index links, or ``None``.

    Walks ``vdpm.0x10 → pdcd`` and parses the chain heads. Per-record
    failures (bad tag, missing pointer) are logged and surface as ``None``
    so callers yield zero samples rather than aborting.
    """
    try:
        pdcd_record = parse_vdpm_pdcd_pointer(reader, point.record_num)
    except PointChainError as exc:
        _log.warning(
            "vdpm_pdcd_pointer_parse_failed",
            point=point.long_name,
            vdpm_record=point.record_num,
            error=str(exc),
        )
        return None
    if pdcd_record is None:
        _log.info(
            "point_has_no_sample_index",
            point=point.long_name,
            vdpm_record=point.record_num,
        )
        return None

    try:
        return parse_pdcd_links(reader, pdcd_record)
    except SampleIndexError as exc:
        _log.warning(
            "pdcd_parse_failed",
            point=point.long_name,
            pdcd_record=pdcd_record,
            error=str(exc),
        )
        return None


def walk_spectra(reader: RbmReader, point: Point) -> Iterator[Spectrum]:
    """Yield every FFT spectrum recorded for ``point``, oldest first.

    Walks ``vdpm.0x10 → pdcd → 0x44 → vdps → (chain via 0x14)`` and, for
    each ``vdps``, reads its full ``vcps`` data chain into a numpy array.
    Per-spectrum failures are logged and the walk continues; a missing
    pdcd or first-vdps yields zero spectra.
    """
    links = _resolve_pdcd_links(reader, point)
    if links is None:
        return

    if links.fft_first_vdps is None:
        _log.info(
            "point_has_no_fft_chain",
            point=point.long_name,
            pdcd_record=links.record_num,
        )
        return

    try:
        descriptors = list(walk_vdps_chain(reader, links.fft_first_vdps))
    except SampleChainError as exc:
        _log.warning(
            "vdps_chain_failed",
            point=point.long_name,
            first_vdps=links.fft_first_vdps,
            error=str(exc),
        )
        return

    for desc in descriptors:
        if desc.first_vcps is None:
            _log.warning(
                "vdps_missing_vcps_chain",
                point=point.long_name,
                vdps_record=desc.record_num,
            )
            continue
        try:
            low_band = read_vdps_low_band(reader, desc.record_num)
            chain = read_vcps_amplitudes(reader, desc.first_vcps)
        except SampleChainError as exc:
            _log.warning(
                "vcps_chain_failed",
                point=point.long_name,
                vdps_record=desc.record_num,
                first_vcps=desc.first_vcps,
                error=str(exc),
            )
            continue
        # Full spectrum = low band (vdps tail) + vcps chain, truncated to
        # n_lines. Calibrate velocity (-> mm/s) and acceleration (G's, kept
        # in G's) by their respective scale; leave unknown units raw with a
        # warning — see FORMAT §5.6.
        amplitude = assemble_spectrum(low_band, chain, desc.n_lines)
        if desc.units in VELOCITY_UNITS_RAW:
            amplitude = (amplitude * VELOCITY_SCALE_MM_S).astype(np.float32)
            units = VELOCITY_UNITS_CALIBRATED
        elif desc.units in ACCEL_UNITS_RAW:
            amplitude = (amplitude * ACCEL_SCALE_G).astype(np.float32)
            units = desc.units
        else:
            units = desc.units
            _log.warning(
                "spectrum_units_uncalibrated",
                point=point.long_name,
                vdps_record=desc.record_num,
                units=desc.units,
            )
        yield Spectrum(
            record_num=desc.record_num,
            point_record_num=point.record_num,
            timestamp_utc=desc.timestamp_utc,
            fmax_hz=desc.fmax_hz,
            n_lines=desc.n_lines,
            units=units,
            rpm=desc.rpm,
            carga_pct=desc.carga_pct,
            amplitude=amplitude,
        )


def walk_waveforms(reader: RbmReader, point: Point) -> Iterator[Waveform]:
    """Yield every time-domain waveform recorded for ``point``, oldest first.

    Walks ``vdpm.0x10 → pdcd → 0x5C → vdfw → (chain via 0x14)`` and, for
    each ``vdfw``, reads its full ``vcfw`` data chain into a numpy array.
    Per-waveform failures are logged and the walk continues; a missing
    pdcd or first-vdfw yields zero waveforms.
    """
    links = _resolve_pdcd_links(reader, point)
    if links is None:
        return

    if links.waveform_first_vdfw is None:
        _log.info(
            "point_has_no_waveform_chain",
            point=point.long_name,
            pdcd_record=links.record_num,
        )
        return

    try:
        descriptors = list(walk_vdfw_chain(reader, links.waveform_first_vdfw))
    except WaveformChainError as exc:
        _log.warning(
            "vdfw_chain_failed",
            point=point.long_name,
            first_vdfw=links.waveform_first_vdfw,
            error=str(exc),
        )
        return

    for desc in descriptors:
        if desc.first_vcfw is None:
            _log.warning(
                "vdfw_missing_vcfw_chain",
                point=point.long_name,
                vdfw_record=desc.record_num,
            )
            continue
        try:
            raw = read_vcfw_samples(reader, desc.first_vcfw)
        except WaveformChainError as exc:
            _log.warning(
                "vcfw_chain_failed",
                point=point.long_name,
                vdfw_record=desc.record_num,
                first_vcfw=desc.first_vcfw,
                error=str(exc),
            )
            continue
        # Calibrate raw int16 counts to display units via vdfw.0x28. Velocity
        # waveforms come out in inches/sec; convert to mm/s (x25.4) so they
        # match the velocity FFT/trend units instead of leaking plg/segs.
        samples = raw * desc.scale_factor
        units = desc.units
        if desc.units in VELOCITY_UNITS_RAW:
            samples = samples * WAVEFORM_VELOCITY_SCALE_MM_S
            units = VELOCITY_UNITS_CALIBRATED
        yield Waveform(
            record_num=desc.record_num,
            point_record_num=point.record_num,
            timestamp_utc=desc.timestamp_utc,
            n_samples=desc.n_samples,
            sample_rate_hz=desc.sample_rate_hz,
            rpm=desc.rpm,
            units=units,
            carga_pct=desc.carga_pct,
            samples=samples.astype(np.float32),
        )


@dataclass(frozen=True, slots=True)
class TypeSummary:
    """Count and first/last timestamps for one sample type at a point.

    ``first`` / ``last`` are ``None`` when ``count`` is zero. Timestamps are
    the descriptor (sample) timestamps, oldest and newest, so ``rbm report``
    can show the date span of each measurement type without reading payloads.
    """

    count: int
    first: datetime | None
    last: datetime | None

    @classmethod
    def empty(cls) -> TypeSummary:
        return cls(count=0, first=None, last=None)

    @classmethod
    def of(cls, timestamps: list[datetime]) -> TypeSummary:
        if not timestamps:
            return cls.empty()
        return cls(count=len(timestamps), first=min(timestamps), last=max(timestamps))


@dataclass(frozen=True, slots=True)
class SampleRef:
    """A lightweight handle to one sample: its descriptor record and time.

    Lets the on-demand viewer list a point's samples without reading any
    amplitude/sample payloads; the chosen one is rendered later by matching
    ``record_num`` against :func:`walk_spectra` / :func:`walk_waveforms`.
    """

    record_num: int
    timestamp_utc: datetime


@dataclass(frozen=True, slots=True)
class PointSampleSummary:
    """Per-type counts and date ranges for one point.

    Mirrors what :func:`walk_spectra` / :func:`walk_waveforms` /
    :func:`walk_trends` would emit, computed from the descriptor chains
    without materializing any amplitude/sample arrays.
    """

    spectra: TypeSummary
    waveforms: TypeSummary
    trend: TypeSummary


def _summarize_spectra(reader: RbmReader, first_vdps: int | None) -> TypeSummary:
    """Summarize FFT spectra for a point without reading their vcps payloads."""
    if first_vdps is None:
        return TypeSummary.empty()
    try:
        timestamps = [
            d.timestamp_utc
            for d in walk_vdps_chain(reader, first_vdps)
            if d.first_vcps is not None
        ]
    except SampleChainError:
        return TypeSummary.empty()
    return TypeSummary.of(timestamps)


def _summarize_waveforms(reader: RbmReader, first_vdfw: int | None) -> TypeSummary:
    """Summarize waveforms for a point without reading their vcfw payloads."""
    if first_vdfw is None:
        return TypeSummary.empty()
    try:
        timestamps = [
            d.timestamp_utc
            for d in walk_vdfw_chain(reader, first_vdfw)
            if d.first_vcfw is not None
        ]
    except WaveformChainError:
        return TypeSummary.empty()
    return TypeSummary.of(timestamps)


def _summarize_trend(reader: RbmReader, links: PdcdLinks) -> TypeSummary:
    """Summarize emitted (velocity) trend readings for a point."""
    if links.trend_first_vddt is None:
        return TypeSummary.empty()
    if _point_spectrum_units(reader, links) not in VELOCITY_UNITS_RAW:
        return TypeSummary.empty()
    try:
        records = list(walk_vddt_chain(reader, links.trend_first_vddt))
    except TrendChainError:
        return TypeSummary.empty()
    timestamps: list[datetime] = []
    for record_num in records:
        try:
            timestamps.extend(
                r.timestamp_utc for r in parse_vddt_record(reader, record_num)
            )
        except (TrendLayoutError, TrendChainError):
            continue
    return TypeSummary.of(timestamps)


def point_sample_summary(reader: RbmReader, point: Point) -> PointSampleSummary:
    """Return per-type counts and date ranges for ``point``.

    Mirrors what :func:`walk_spectra` / :func:`walk_waveforms` /
    :func:`walk_trends` would emit, but only via the descriptor chains
    (no amplitude/sample payloads) so the whole database can be tallied
    quickly. Backs both :func:`count_point_samples` (``rbm stats``) and the
    inventory report (``rbm report``).
    """
    links = _resolve_pdcd_links(reader, point)
    if links is None:
        empty = TypeSummary.empty()
        return PointSampleSummary(spectra=empty, waveforms=empty, trend=empty)
    return PointSampleSummary(
        spectra=_summarize_spectra(reader, links.fft_first_vdps),
        waveforms=_summarize_waveforms(reader, links.waveform_first_vdfw),
        trend=_summarize_trend(reader, links),
    )


def point_sample_refs(reader: RbmReader, point: Point, kind: str) -> list[SampleRef]:
    """Return descriptor refs (record_num + timestamp) for one sample kind.

    ``kind`` is ``"fft"`` or ``"waveform"``. Reads only the descriptor chains
    (no payloads), so the on-demand viewer can list a point's samples cheaply
    and render the chosen one by matching ``record_num`` against
    :func:`walk_spectra` / :func:`walk_waveforms`. Trends are a single
    per-point series and are not enumerated here.

    Raises:
        ValueError: If ``kind`` is neither ``"fft"`` nor ``"waveform"``.
    """
    if kind not in ("fft", "waveform"):
        raise ValueError(f"unknown sample kind {kind!r}; expected 'fft' or 'waveform'")
    links = _resolve_pdcd_links(reader, point)
    if links is None:
        return []
    if kind == "fft":
        if links.fft_first_vdps is None:
            return []
        try:
            return [
                SampleRef(d.record_num, d.timestamp_utc)
                for d in walk_vdps_chain(reader, links.fft_first_vdps)
                if d.first_vcps is not None
            ]
        except SampleChainError:
            return []
    if links.waveform_first_vdfw is None:
        return []
    try:
        return [
            SampleRef(d.record_num, d.timestamp_utc)
            for d in walk_vdfw_chain(reader, links.waveform_first_vdfw)
            if d.first_vcfw is not None
        ]
    except WaveformChainError:
        return []


def count_point_samples(reader: RbmReader, point: Point) -> tuple[int, int, int]:
    """Return ``(n_spectra, n_waveforms, n_trend_readings)`` for ``point``.

    Thin wrapper over :func:`point_sample_summary` that drops the date
    ranges — kept for ``rbm stats`` and existing callers.
    """
    summary = point_sample_summary(reader, point)
    return (
        summary.spectra.count,
        summary.waveforms.count,
        summary.trend.count,
    )


def _point_spectrum_units(reader: RbmReader, links: PdcdLinks) -> str | None:
    """Return the units string of the point's first FFT spectrum, or ``None``.

    A ``vddt`` carries no unit string, so the trend's native unit is read
    from the point's primary FFT measurement (velocity → ``plg/segs`` etc.,
    acceleration → ``G's``). Returns ``None`` if the point has no FFT chain
    or it cannot be parsed.
    """
    if links.fft_first_vdps is None:
        return None
    try:
        return next(walk_vdps_chain(reader, links.fft_first_vdps)).units
    except (SampleChainError, StopIteration):
        return None


@dataclass(frozen=True, slots=True)
class _BandColumn:
    """Label/calibration of one velocity-template vddt band column."""

    name: str
    scale: float
    units: str


# Band columns of the velocity template (band_count = 7), in slot order —
# FORMAT §5.7, each column validated 62/62 against the AMS per-band PLOTDATA
# gold for M1H AG-100. Mixed units: "Mp Wave" is a raw acceleration peak in
# G's, the rest are velocities (x 25.4 -> mm/s). Column 6 ("1-20 KHz") is
# NOT emitted: its unit/scale is unconfirmed (the gold table is empty).
VDDT_VELOCITY_BANDS: tuple[_BandColumn, ...] = (
    _BandColumn("Mp Wave", 1.0, "G's"),
    _BandColumn("SUBSINCRONO", TREND_VELOCITY_SCALE_MM_S, "mm/s"),
    _BandColumn("DESEQUILIBRIO", TREND_VELOCITY_SCALE_MM_S, "mm/s"),
    _BandColumn("DESALINEACION", TREND_VELOCITY_SCALE_MM_S, "mm/s"),
    _BandColumn("HOLGURAS", TREND_VELOCITY_SCALE_MM_S, "mm/s"),
    _BandColumn("11-40 X RPM", TREND_VELOCITY_SCALE_MM_S, "mm/s"),
)

# Slot band count that identifies the velocity template above. Records with
# other counts (reconfigured epochs) decode the overall but their band
# columns are unlabeled, so those readings contribute no band values.
_VELOCITY_TEMPLATE_BAND_COUNT = 7


def walk_trends(reader: RbmReader, point: Point) -> Iterator[Trend]:
    """Yield the "Valores Globales" trend series for ``point`` (usually one).

    Walks ``vdpm.0x10 → pdcd → 0x3C → vddt → (chain via 0x10)``, decodes
    each ``vddt`` record's sample slots, and flattens the whole chain into a
    single :class:`~ams_extract.models.Trend` with the overall calibrated to
    mm/s (FORMAT §5.7).

    Only **velocity** points are emitted (overall ``x 25.4`` → mm/s), the
    case validated 47/47 against the AMS gold. Acceleration points (PeakVue /
    high-frequency, units ``G's``) decode structurally too, but the overall
    scale is not yet gold-confirmed, so they are skipped with a log rather
    than emitting unverified values (PLAN §7.4). A missing pdcd / first-vddt,
    an undetermined unit, or an all-skipped chain yields no trend.

    Readings stored with the velocity band template (``band_count = 7``)
    also contribute the named band series (:data:`VDDT_VELOCITY_BANDS`) to
    ``Trend.bands``; readings from other band-count epochs only contribute
    the overall.
    """
    links = _resolve_pdcd_links(reader, point)
    if links is None:
        return

    if links.trend_first_vddt is None:
        _log.info(
            "point_has_no_trend_chain",
            point=point.long_name,
            pdcd_record=links.record_num,
        )
        return

    units_raw = _point_spectrum_units(reader, links)
    if units_raw not in VELOCITY_UNITS_RAW:
        _log.info(
            "trend_skipped_non_velocity",
            point=point.long_name,
            spectrum_units=units_raw,
        )
        return

    try:
        records = list(walk_vddt_chain(reader, links.trend_first_vddt))
    except TrendChainError as exc:
        _log.warning(
            "vddt_chain_failed",
            point=point.long_name,
            first_vddt=links.trend_first_vddt,
            error=str(exc),
        )
        return

    timestamps: list[datetime] = []
    overall: list[float] = []
    band_timestamps: list[datetime] = []
    band_rows: list[tuple[float, ...]] = []
    for record_num in records:
        try:
            readings = parse_vddt_record(reader, record_num)
        except TrendLayoutError as exc:
            _log.info(
                "vddt_layout_unsupported",
                point=point.long_name,
                vddt_record=record_num,
                error=str(exc),
            )
            continue
        except TrendChainError as exc:
            _log.warning(
                "vddt_record_failed",
                point=point.long_name,
                vddt_record=record_num,
                error=str(exc),
            )
            continue
        for reading in readings:
            timestamps.append(reading.timestamp_utc)
            overall.append(reading.overall_raw * TREND_VELOCITY_SCALE_MM_S)
            if len(reading.bands_raw) == _VELOCITY_TEMPLATE_BAND_COUNT:
                band_timestamps.append(reading.timestamp_utc)
                band_rows.append(reading.bands_raw)

    if not timestamps:
        return

    bands: tuple[TrendBand, ...] = ()
    if band_timestamps:
        bands = tuple(
            TrendBand(
                name=column.name,
                units=column.units,
                timestamps_utc=tuple(band_timestamps),
                values=np.asarray([row[i] * column.scale for row in band_rows], dtype=np.float32),
            )
            for i, column in enumerate(VDDT_VELOCITY_BANDS)
        )

    yield Trend(
        record_num=links.trend_first_vddt,
        point_record_num=point.record_num,
        units="mm/s",
        timestamps_utc=tuple(timestamps),
        overall=np.asarray(overall, dtype=np.float32),
        bands=bands,
    )
