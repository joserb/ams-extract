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

import structlog

from ams_extract.models import Area, Equipment, Point, Spectrum
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
    SampleChainError,
    read_vcps_amplitudes,
    walk_vdps_chain,
)
from ams_extract.records.sample_index import (
    SampleIndexError,
    parse_pdcd_links,
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


def walk_spectra(reader: RbmReader, point: Point) -> Iterator[Spectrum]:
    """Yield every FFT spectrum recorded for ``point``, oldest first.

    Walks ``vdpm.0x10 → pdcd → 0x44 → vdps → (chain via 0x14)`` and, for
    each ``vdps``, reads its full ``vcps`` data chain into a numpy array.
    Per-spectrum failures are logged and the walk continues; a missing
    pdcd or first-vdps yields zero spectra.
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
        return
    if pdcd_record is None:
        _log.info(
            "point_has_no_sample_index",
            point=point.long_name,
            vdpm_record=point.record_num,
        )
        return

    try:
        links = parse_pdcd_links(reader, pdcd_record)
    except SampleIndexError as exc:
        _log.warning(
            "pdcd_parse_failed",
            point=point.long_name,
            pdcd_record=pdcd_record,
            error=str(exc),
        )
        return

    if links.fft_first_vdps is None:
        _log.info(
            "point_has_no_fft_chain",
            point=point.long_name,
            pdcd_record=pdcd_record,
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
            amplitude = read_vcps_amplitudes(reader, desc.first_vcps)
        except SampleChainError as exc:
            _log.warning(
                "vcps_chain_failed",
                point=point.long_name,
                vdps_record=desc.record_num,
                first_vcps=desc.first_vcps,
                error=str(exc),
            )
            continue
        yield Spectrum(
            record_num=desc.record_num,
            point_record_num=point.record_num,
            timestamp_utc=desc.timestamp_utc,
            fmax_hz=desc.fmax_hz,
            n_lines=desc.n_lines,
            units=desc.units,
            carga_pct=desc.carga_pct,
            amplitude=amplitude,
        )
