"""Top-down walker over the .rbm hierarchy.

Phase 2 scope: areas only. The walker reads the primary and secondary
area-chain pointers from the header and combines their slots into a list
of :class:`Area`. Equipment and Point are not yet walked; the equipment
chain pointer format is still under investigation (see ``docs/PLAN.md``
§5 Fase 2 and ``docs/DECISIONS.md`` ADR-0002).
"""

from __future__ import annotations

import structlog

from ams_extract.models import Area
from ams_extract.naming import NameSanitizer
from ams_extract.reader import RbmReader
from ams_extract.records.area import AreaSlot, parse_area_record
from ams_extract.records.header import (
    AREA_CHAIN_SECONDARY_POINTER_OFFSET,
    parse_header,
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
