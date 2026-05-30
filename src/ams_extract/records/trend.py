"""Parser for trend records (``vddt``) — the AMS "Valores Globales" series.

A point's ``pdcd`` indexes a chain of ``vddt`` records (``pdcd.0x3C`` =
first/oldest, ``pdcd.0x40`` = last/newest) holding the time series AMS plots
as "Gráf. tendencia de Valores Globales": the overall value sampled over
years, plus a configurable set of named bands. The layout was solved on
2026-05-30 against the AMS PLOTDATA gold for M1H of AG-100 (47/47 readings
match) and generalized across column counts the next iteration; see
FORMAT §5.7 and ADR-0006.

Record layout::

    vddt
      ├── 0x10 → next vddt (+1-encoded, 0 = end of chain)
      ├── 0x14 → back-ref to pdcd
      ├── 0x18 → u32 Unix ts of the FIRST reading in this record (d0)
      ├── 0x1C → u32 Unix ts of the LAST reading in this record
      ├── 0x24 → u32 band count (columns per slot besides the overall)
      └── 0x2F.. → sequence of fixed-size sample SLOTS

    slot (size = 13 + band_count * 4, first at offset 0x2F):
      +0x00          4 bytes  per-slot flags (alarm/status; not decoded)
      +0x04          float32  overall value (Valores Globales), native unit
      +0x08          band_count x float32  named bands (raw; unlabeled)
      +0x08+bands*4  u32       Unix ts of the NEXT reading (date rule below)

The band count (``0x24``) varies *within* a point's chain — the analyst
reconfigured the band set over time — so it is NOT a measurement-type
discriminator; it only fixes the slot stride. M1H AG-100 happens to be all
``band_count = 7`` (stride 41); other points mix 7/4/1.

The off-by-one **date rule** is the crux of the decode: the timestamp
stored in a slot is the date of the *next* reading, not its own. So::

    date[0] = vddt.0x18 (d0)                 # first reading of the record
    date[k] = slot[k-1].next_ts  (k >= 1)

The last slot's ``next_ts`` is 0; the next record's first reading takes its
date from that record's own ``d0``.

This module returns the raw on-disk floats; the **unit/scale** is the
caller's job because ``vddt`` carries no unit string. The native unit
matches the point's primary measurement: velocity points store inches/sec
(AMS shows mm/s, so ``mm/s = raw * 25.4``, :data:`TREND_VELOCITY_SCALE_MM_S`
— validated 47/47); acceleration points store G's. See
:func:`ams_extract.tree.walk_trends`.
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
VDDT_BAND_COUNT_OFFSET = 0x24

# Sample slots. Each slot is [4 flag bytes][overall f32][bands f32...][ts u32].
VDDT_FIRST_SLOT_OFFSET = 0x2F
VDDT_SLOT_OVERALL_OFFSET = 0x04
VDDT_SLOT_BANDS_OFFSET = 0x08

# Pure inch->mm conversion: a velocity overall is stored in in/s, AMS shows
# mm/s. (Distinct from the FFT velocity scale 48.5, which folds in a window
# /normalization term; the trend overall is a plain stored RMS scalar.)
TREND_VELOCITY_SCALE_MM_S = 25.4

# Sanity bounds.
_BAND_COUNT_MAX = 32  # a slot must fit in a 512-byte record
_OVERALL_MAX_RAW = 200.0  # 200 in/s ~ 5000 mm/s; well above any real reading
# A reading's date must be plausible (2000-01-01 .. 2038-01-01); guards
# against running past the live slots into trailing garbage.
_TS_MIN = 946_684_800
_TS_MAX = 2_145_916_800

# Safety cap to bound traversal of a malformed chain.
VDDT_CHAIN_MAX_LENGTH = 4096


class TrendChainError(ValueError):
    """Raised when a record in a vddt chain has an unexpected tag or loops."""


class TrendLayoutError(ValueError):
    """Raised when a vddt record has an implausible band count / slot size."""


@dataclass(frozen=True, slots=True)
class TrendReading:
    """One trend reading: a timestamp plus the overall and raw band values.

    ``overall_raw`` and ``bands_raw`` are the on-disk float32 values in the
    point's native unit; the caller scales the overall to display units.
    The bands are kept raw and unlabeled — their identity (SUBSINCRONO,
    etc.) and scale are not yet confirmed (FORMAT §5.7).
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


def parse_vddt_record(reader: RbmReader, vddt_record: int) -> list[TrendReading]:
    """Decode all readings stored in one ``vddt`` record, oldest first.

    The slot stride is derived from the band count at ``0x24``
    (``13 + band_count * 4``). Applies the off-by-one date rule (first
    reading dated from ``0x18``, each subsequent reading from the previous
    slot's ``next_ts``) and stops at the first empty/garbage slot. Returns
    raw values; the caller scales the overall to display units.

    Raises:
        TrendChainError: If the record's tag is not ``vddt``.
        TrendLayoutError: If the band count is implausible (``< 1`` or so
            large the slot can't fit in a record).
    """
    record = reader.read_record(vddt_record)
    _check_tag(record, vddt_record)

    (band_count,) = struct.unpack_from("<I", record, VDDT_BAND_COUNT_OFFSET)
    if not (1 <= band_count <= _BAND_COUNT_MAX):
        raise TrendLayoutError(
            f"record {vddt_record}: implausible band count {band_count}"
        )

    ts_offset = VDDT_SLOT_BANDS_OFFSET + band_count * 4
    stride = ts_offset + 4 + 1  # + next_ts (u32) + 1 pad byte

    (first_ts,) = struct.unpack_from("<I", record, VDDT_FIRST_TS_OFFSET)
    readings: list[TrendReading] = []
    next_date_raw = first_ts
    offset = VDDT_FIRST_SLOT_OFFSET
    while offset + stride <= len(record):
        if not (_TS_MIN <= next_date_raw <= _TS_MAX):
            break
        (overall,) = struct.unpack_from("<f", record, offset + VDDT_SLOT_OVERALL_OFFSET)
        if not (0.0 < overall <= _OVERALL_MAX_RAW):
            break
        bands = struct.unpack_from(
            f"<{band_count}f", record, offset + VDDT_SLOT_BANDS_OFFSET
        )
        (slot_next_ts,) = struct.unpack_from("<I", record, offset + ts_offset)
        readings.append(
            TrendReading(
                timestamp_utc=datetime.fromtimestamp(next_date_raw, UTC),
                overall_raw=float(overall),
                bands_raw=tuple(float(b) for b in bands),
            )
        )
        if slot_next_ts == 0:  # last reading of this record
            break
        next_date_raw = slot_next_ts
        offset += stride
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
