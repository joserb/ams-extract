"""Parser for trend records (``vddt``) — the AMS "Valores Globales" series.

A point's ``pdcd`` indexes a chain of ``vddt`` records (``pdcd.0x3C`` =
first/oldest, ``pdcd.0x40`` = last/newest) that hold the time series AMS
plots as "Gráf. tendencia de Valores Globales": the overall RMS velocity
sampled over years, plus named bands. The layout was solved on 2026-05-30
against the AMS PLOTDATA gold for M1H of AG-100 (47/47 readings match);
see FORMAT §5.7 and ADR-0006.

Record layout (velocity trend, the validated case)::

    vddt
      ├── 0x10 → next vddt (+1-encoded, 0 = end of chain)
      ├── 0x14 → back-ref to pdcd
      ├── 0x18 → u32 Unix ts of the FIRST reading in this record (d0)
      ├── 0x1C → u32 Unix ts of the LAST reading in this record
      ├── 0x24 → u32 column count (7 for the velocity template; see below)
      └── 0x2F.. → sequence of 41-byte sample SLOTS:

    slot (41 bytes, stride 0x29, first at offset 0x2F):
      +0x00  marker  d3 fa ff 00
      +0x04  float32 overall (Valores Globales), inches/sec
      +0x08  7 x float32  named bands (raw; identity/scale unconfirmed)
      +0x24  u32  Unix ts of the NEXT reading (see the date rule below)

The off-by-one **date rule** is the crux of the decode: the timestamp
stored in a slot is the date of the *next* reading, not its own. So::

    date[0] = vddt.0x18 (d0)                 # first reading of the record
    date[k] = slot[k-1].next_ts  (k >= 1)

The last slot's ``next_ts`` is 0; the next record's first reading takes its
date from that record's own ``d0``.

Only the velocity template (column count 7, marker ``d3 fa ff 00``) is
supported here. PeakVue / acceleration points use a *different* trend
layout (column count 1, no such marker) that is not yet reverse-engineered;
:func:`parse_vddt_record` raises :class:`TrendLayoutError` for those so the
walker can skip them rather than emit garbage (PLAN §7.4).

Calibration: the overall is stored in inches/sec; AMS displays mm/s, so the
single conversion is ``mm/s = raw * 25.4`` (:data:`TREND_VELOCITY_SCALE_MM_S`,
a pure inch→mm factor — note this differs from the FFT velocity scale 48.5,
which carries an extra window/normalization term). Applied by
:func:`ams_extract.tree.walk_trends`; this module returns raw values.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from ams_extract.reader import RbmReader, decode_inner_pointer

VDDT_TAG = b"vddt"
TAG_OFFSET = 0x08

# vddt header offsets
VDDT_NEXT_OFFSET = 0x10
VDDT_PDCD_BACKREF_OFFSET = 0x14
VDDT_FIRST_TS_OFFSET = 0x18
VDDT_LAST_TS_OFFSET = 0x1C
VDDT_COLUMN_COUNT_OFFSET = 0x24

# Sample slots
VDDT_FIRST_SLOT_OFFSET = 0x2F
VDDT_SLOT_STRIDE = 0x29  # 41 bytes
VDDT_SLOT_MARKER = b"\xd3\xfa\xff\x00"
VDDT_SLOT_OVERALL_OFFSET = 0x04
VDDT_SLOT_BANDS_OFFSET = 0x08
VDDT_SLOT_NEXT_TS_OFFSET = 0x24
VDDT_BAND_COUNT = 7

# The velocity-trend template carries 7 named bands; this is the only layout
# whose per-sample stride/marker has been verified. Other templates (e.g.
# PeakVue, column count 1) are skipped — see the module docstring.
VDDT_VELOCITY_COLUMN_COUNT = 7

# Pure inch->mm conversion: the overall is stored in in/s, AMS shows mm/s.
TREND_VELOCITY_SCALE_MM_S = 25.4

# Plausibility guard for an overall reading (raw in/s) — rejects garbage
# floats from a misaligned or unsupported layout.
_OVERALL_MIN_RAW = 0.0
_OVERALL_MAX_RAW = 200.0  # 200 in/s ~ 5000 mm/s, well above any real reading

# Safety cap to bound traversal of a malformed chain.
VDDT_CHAIN_MAX_LENGTH = 4096


class TrendChainError(ValueError):
    """Raised when a record in a vddt chain has an unexpected tag or loops."""


class TrendLayoutError(ValueError):
    """Raised when a vddt record uses an unsupported (non-velocity) layout."""


@dataclass(frozen=True, slots=True)
class TrendReading:
    """One trend reading: a timestamp plus the overall and raw band values.

    ``overall_raw`` and ``bands_raw`` are the on-disk float32 values in
    inches/sec; the walker scales the overall to mm/s. The bands are kept
    raw and unlabeled — their identity (SUBSINCRONO, etc.) and scale are
    not yet confirmed (FORMAT §5.7).
    """

    timestamp_utc: datetime
    overall_raw: float
    bands_raw: tuple[float, ...]


def _check_tag(record: bytes, record_num: int) -> None:
    tag = bytes(record[TAG_OFFSET : TAG_OFFSET + 4])
    if tag != VDDT_TAG:
        raise TrendChainError(
            f"record {record_num}: expected tag {VDDT_TAG!r}, got {tag!r}"
        )


def _is_supported_layout(record: bytes) -> bool:
    """True if this vddt uses the verified velocity template."""
    (columns,) = struct.unpack_from("<I", record, VDDT_COLUMN_COUNT_OFFSET)
    if columns != VDDT_VELOCITY_COLUMN_COUNT:
        return False
    marker = record[
        VDDT_FIRST_SLOT_OFFSET : VDDT_FIRST_SLOT_OFFSET + len(VDDT_SLOT_MARKER)
    ]
    return marker == VDDT_SLOT_MARKER


def parse_vddt_record(reader: RbmReader, vddt_record: int) -> list[TrendReading]:
    """Decode all readings stored in one ``vddt`` record, oldest first.

    Applies the off-by-one date rule (first reading dated from ``0x18``,
    each subsequent reading from the previous slot's ``next_ts``). Returns
    raw values; the caller scales the overall to display units.

    Raises:
        TrendChainError: If the record's tag is not ``vddt``.
        TrendLayoutError: If the record uses an unsupported layout (e.g. a
            PeakVue trend) whose slot structure has not been verified.
    """
    record = reader.read_record(vddt_record)
    _check_tag(record, vddt_record)
    if not _is_supported_layout(record):
        (columns,) = struct.unpack_from("<I", record, VDDT_COLUMN_COUNT_OFFSET)
        raise TrendLayoutError(
            f"record {vddt_record}: unsupported vddt layout (column count "
            f"{columns}, expected {VDDT_VELOCITY_COLUMN_COUNT})"
        )

    (first_ts,) = struct.unpack_from("<I", record, VDDT_FIRST_TS_OFFSET)
    readings: list[TrendReading] = []
    next_date_raw = first_ts
    offset = VDDT_FIRST_SLOT_OFFSET
    while offset + VDDT_SLOT_STRIDE <= len(record):
        marker = record[offset : offset + len(VDDT_SLOT_MARKER)]
        if marker != VDDT_SLOT_MARKER:
            break
        (overall,) = struct.unpack_from("<f", record, offset + VDDT_SLOT_OVERALL_OFFSET)
        if not (_OVERALL_MIN_RAW <= overall <= _OVERALL_MAX_RAW):
            break
        bands = struct.unpack_from(
            f"<{VDDT_BAND_COUNT}f", record, offset + VDDT_SLOT_BANDS_OFFSET
        )
        (slot_next_ts,) = struct.unpack_from(
            "<I", record, offset + VDDT_SLOT_NEXT_TS_OFFSET
        )
        readings.append(
            TrendReading(
                timestamp_utc=datetime.fromtimestamp(next_date_raw, UTC),
                overall_raw=float(overall),
                bands_raw=tuple(float(b) for b in bands),
            )
        )
        next_date_raw = slot_next_ts
        offset += VDDT_SLOT_STRIDE
    return readings


def walk_vddt_chain(reader: RbmReader, first_vddt: int) -> Iterator[int]:
    """Yield each ``vddt`` record number in the chain from ``first_vddt``.

    Chain follows ``vddt.0x10`` (+1-encoded), 0 = end. Detects cycles and
    bounds the walk at :data:`VDDT_CHAIN_MAX_LENGTH`.

    Raises:
        TrendChainError: If any record has the wrong tag, or the chain
            loops or exceeds the safety bound.
    """
    visited: set[int] = set()
    current: int | None = first_vddt
    for _ in range(VDDT_CHAIN_MAX_LENGTH):
        if current is None:
            return
        if current in visited:
            raise TrendChainError(f"vddt chain cycle detected at record {current}")
        visited.add(current)
        record = reader.read_record(current)
        _check_tag(record, current)
        yield current
        (next_stored,) = struct.unpack_from("<I", record, VDDT_NEXT_OFFSET)
        current = decode_inner_pointer(next_stored)
    raise TrendChainError(
        f"vddt chain exceeds {VDDT_CHAIN_MAX_LENGTH} records starting at {first_vddt}"
    )
