"""Serialize the area / equipment / point hierarchy to JSON.

Phase 2b emits the schema below with the full Áreas → Equipos → Puntos
hierarchy. Consumers can detect schema generation via
``meta.schema_version`` and ``meta.phase``.

Schema (informal)::

    {
      "meta": {
        "schema_version": 2,
        "phase": "phase-2b-complete",
        "source": "<path of the input .rbm>",
        "signature": "MT4.00",
        "description": "Preditec",
        "area_count": 15,
        "equipment_count": ...,
        "point_count": ...
      },
      "areas": [
        {
          "record_num": 69,
          "slot_index": 0,
          "long_name": "CONTRA INCENDIOS",
          "short_code": "CONTRA_INCENDIOS",
          "equipment": [
            {
              "record_num": 300,
              "long_name": "Bomba Centrifuga PM-0CI/1",
              "short_code": "Bomba_Centrifuga_PM_0CI_1",
              "points": [
                {"record_num": 301,
                 "long_name": "MOTOR LOA HORIZONTAL",
                 "short_code": "MOTOR_LOA_HORIZONTAL"},
                ...
              ]
            },
            ...
          ]
        },
        ...
      ]
    }
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ams_extract.models import Area, Equipment, Point
from ams_extract.reader import RbmReader
from ams_extract.records.header import parse_header

SCHEMA_VERSION = 2
PHASE_LABEL = "phase-2b-complete"


def _point_to_dict(point: Point) -> dict[str, Any]:
    return {
        "record_num": point.record_num,
        "long_name": point.long_name,
        "short_code": point.short_code,
    }


def _equipment_to_dict(equipment: Equipment) -> dict[str, Any]:
    return {
        "record_num": equipment.record_num,
        "long_name": equipment.long_name,
        "short_code": equipment.short_code,
        "points": [_point_to_dict(p) for p in equipment.points],
    }


def _area_to_dict(area: Area) -> dict[str, Any]:
    return {
        "record_num": area.record_num,
        "slot_index": area.slot_index,
        "long_name": area.long_name,
        "short_code": area.short_code,
        "equipment": [_equipment_to_dict(e) for e in area.equipment],
    }


def build_tree_document(
    reader: RbmReader,
    areas: Iterable[Area],
    *,
    source_path: Path | str | None = None,
) -> dict[str, Any]:
    """Build the JSON-ready dict for the hierarchy of ``areas``."""
    area_list = list(areas)
    header = parse_header(reader)
    equipment_count = sum(len(a.equipment) for a in area_list)
    point_count = sum(len(e.points) for a in area_list for e in a.equipment)
    return {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "phase": PHASE_LABEL,
            "source": str(source_path) if source_path is not None else None,
            "signature": header.signature,
            "description": header.description,
            "area_count": len(area_list),
            "equipment_count": equipment_count,
            "point_count": point_count,
        },
        "areas": [_area_to_dict(a) for a in area_list],
    }


def write_tree_json(document: dict[str, Any], output_path: Path) -> None:
    """Pretty-print ``document`` as UTF-8 JSON to ``output_path``."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
