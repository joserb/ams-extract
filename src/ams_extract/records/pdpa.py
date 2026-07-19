"""Parsers for the shared analysis-parameter and alarm-limit sets.

An AMS point does not carry its band definitions inline: it references two
small pools of shared templates (FORMAT §5.8, layout solved 2026-07-19):

- ``pdpa`` — *analysis parameter set*: the named bands of a point (the
  columns of its ``vddt`` trend), each with a frequency range in shaft
  orders or fixed Hz.
- ``pdla`` — *alarm limit set*: the alert (C) / danger (D) thresholds for
  the overall and for each band slot, in the slot's native unit.

Record layout (both are single 512-byte records)::

    pdpa                                  pdla
      ├── 0x10  name (32 B)                 ├── 0x10  name (32 B)
      ├── 0x30  u16 set index (1-based)     ├── 0x30  u16 set index (1-based)
      ├── 0x32  u16 active slot count      ├── 0x38  f32[13] danger (D)
      ├── 0x34  12 x 14 B slot names       ├── 0xA0  f32[13] alert  (C)
      ├── 0xDC  12 x u8 slot band type     └── 0x108 u16[13] unit codes
      ├── 0xE8  f32[12] low edge per slot
      └── 0x118 f32[12] high edge per slot

Only the first ``active slot count`` slots are the point's real bands;
trailing named slots are stale leftovers from template edits (observed in
BUNGE: the HR template names 7 slots but only 6 are active). The ``pdla``
arrays are indexed ``[overall, slot 0, slot 1, …, slot 11]``; a stored 0
means "no limit configured".

Band type codes (``0xDC`` array):

- ``0x02`` — band edges in **shaft orders** (x RPM), e.g. SUBSINCRONO 0-0.7.
- ``0x01`` — band edges in **fixed Hz**, e.g. FALLO ELECTRIC 99.8-100.2 Hz.
- ``0x04`` — fixed Hz too, but the slot's *value* is an HF energy in G's
  ("1 - 20 KHz"); its trend scale is not gold-validated, so callers skip it.
- ``0x0B`` — waveform peak ("Mp Wave"), no frequency range.

Threshold unit codes (``pdla.0x108``): 1 = velocity (stored inches/s),
3 = acceleration (G's).

**Directories**: the pools are indexed by two directory tables near the
header — a ``gipa`` record labelled ``pdpa`` and a ``gila`` record labelled
``pdla``. Each directory is a flat u32 little-endian array of +1-encoded
record numbers indexed by ``set index - 1``. The array starts at offset
0x10 of the directory record and continues through the *whole* 512 bytes of
the next :data:`DIRECTORY_SPAN_RECORDS - 1` records; the record after the
span is a label record (zero tag, 4-char type name at 0x10) naming the
record type the directory indexes.

**Point → sets link**: ``pdcd.0xAC`` (u16) is the point's analysis-set
index and ``pdcd.0xAE`` (u16) its alarm-set index (0 = unset). See
:mod:`ams_extract.records.sample_index`.

Everything above was validated numerically against BUNGE: the vddt band
value is exactly the root-sum-square of the raw spectrum bins inside
``[low, high)`` (median error < 0.1% over 7 templates), and the M1H gold
alarm transitions (C at 1.44 mm/s, D at 2.24 mm/s) match the decoded
thresholds 1.4 / 2.2 mm/s of alarm set 5.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ams_extract.encoding import decode_string
from ams_extract.reader import RbmReader

PDPA_TAG = b"pdpa"
PDLA_TAG = b"pdla"
TAG_OFFSET = 0x08

# Shared name/index header of both record types.
SET_NAME_OFFSET = 0x10
SET_NAME_LENGTH = 32
SET_INDEX_OFFSET = 0x30

# pdpa (analysis parameter set) offsets.
PDPA_ACTIVE_COUNT_OFFSET = 0x32
PDPA_SLOT_NAMES_OFFSET = 0x34
PDPA_SLOT_NAME_LENGTH = 14
PDPA_SLOT_TYPES_OFFSET = 0xDC
PDPA_SLOT_LOW_OFFSET = 0xE8
PDPA_SLOT_HIGH_OFFSET = 0x118
MAX_BAND_SLOTS = 12

# Band type codes (pdpa slot types).
BAND_TYPE_FIXED_HZ = 0x01
BAND_TYPE_ORDERS = 0x02
BAND_TYPE_HF_FIXED_HZ = 0x04
BAND_TYPE_WAVEFORM_PEAK = 0x0B

# pdla (alarm limit set) offsets. Arrays are [overall, slot 0 .. slot 11].
PDLA_DANGER_OFFSET = 0x38
PDLA_ALERT_OFFSET = 0xA0
PDLA_UNIT_CODES_OFFSET = 0x108
PDLA_ARRAY_LENGTH = 13

# Threshold unit codes (pdla.0x108).
THRESHOLD_UNIT_VELOCITY = 1
THRESHOLD_UNIT_ACCELERATION = 3

# Directory sections near the header: [directory span][label record].
DIRECTORY_SPAN_RECORDS = 4
DIRECTORY_ENTRIES_OFFSET = 0x10
DIRECTORY_LABEL_OFFSET = 0x10
DIRECTORY_SEARCH_LIMIT = 256

ANALYSIS_SET_LABEL = b"pdpa"
ALARM_SET_LABEL = b"pdla"


class ParamSetError(ValueError):
    """Raised when a pdpa/pdla record has an unexpected tag."""


@dataclass(frozen=True, slots=True)
class AnalysisBand:
    """One active band slot of an analysis parameter set.

    ``low``/``high`` are in shaft orders for :data:`BAND_TYPE_ORDERS` and
    in Hz for :data:`BAND_TYPE_FIXED_HZ` / :data:`BAND_TYPE_HF_FIXED_HZ`;
    they are meaningless (0) for :data:`BAND_TYPE_WAVEFORM_PEAK`.
    """

    name: str
    band_type: int
    low: float
    high: float


@dataclass(frozen=True, slots=True)
class AnalysisParameterSet:
    """A decoded ``pdpa`` record: the band template shared by many points."""

    record_num: int
    index: int
    name: str
    bands: tuple[AnalysisBand, ...]


@dataclass(frozen=True, slots=True)
class AlarmLimitSet:
    """A decoded ``pdla`` record: alert/danger thresholds per band slot.

    Arrays are indexed ``0 = overall``, ``k + 1 = band slot k``, in the
    slot's native stored unit (inches/s for velocity, G's for
    acceleration, per ``unit_codes``). A stored 0 means "no limit" and is
    surfaced as ``None`` by the accessors.
    """

    record_num: int
    index: int
    name: str
    alert: tuple[float, ...]
    danger: tuple[float, ...]
    unit_codes: tuple[int, ...]

    def alert_for(self, array_index: int) -> float | None:
        """Alert (C) threshold at ``array_index`` (0 = overall), or ``None``."""
        value = self.alert[array_index]
        return value if value > 0 else None

    def danger_for(self, array_index: int) -> float | None:
        """Danger (D) threshold at ``array_index`` (0 = overall), or ``None``."""
        value = self.danger[array_index]
        return value if value > 0 else None


def _check_tag(record: bytes, expected: bytes, record_num: int) -> None:
    tag = bytes(record[TAG_OFFSET : TAG_OFFSET + 4])
    if tag != expected:
        raise ParamSetError(
            f"record {record_num}: expected tag {expected!r}, got {tag!r}"
        )


def parse_pdpa_record(reader: RbmReader, record_num: int) -> AnalysisParameterSet:
    """Decode the ``pdpa`` analysis parameter set at ``record_num``.

    Only the active slots (count at ``0x32``) are returned; trailing named
    slots are stale template leftovers and are dropped.

    Raises:
        ParamSetError: If the record's tag is not ``pdpa``.
    """
    record = reader.read_record(record_num)
    _check_tag(record, PDPA_TAG, record_num)
    index, active = struct.unpack_from("<HH", record, SET_INDEX_OFFSET)
    active = min(active, MAX_BAND_SLOTS)
    bands: list[AnalysisBand] = []
    for i in range(active):
        name_start = PDPA_SLOT_NAMES_OFFSET + i * PDPA_SLOT_NAME_LENGTH
        (low,) = struct.unpack_from("<f", record, PDPA_SLOT_LOW_OFFSET + i * 4)
        (high,) = struct.unpack_from("<f", record, PDPA_SLOT_HIGH_OFFSET + i * 4)
        bands.append(
            AnalysisBand(
                name=decode_string(record[name_start : name_start + PDPA_SLOT_NAME_LENGTH]),
                band_type=record[PDPA_SLOT_TYPES_OFFSET + i],
                low=float(low),
                high=float(high),
            )
        )
    return AnalysisParameterSet(
        record_num=record_num,
        index=index,
        name=decode_string(record[SET_NAME_OFFSET : SET_NAME_OFFSET + SET_NAME_LENGTH]),
        bands=tuple(bands),
    )


def parse_pdla_record(reader: RbmReader, record_num: int) -> AlarmLimitSet:
    """Decode the ``pdla`` alarm limit set at ``record_num``.

    Raises:
        ParamSetError: If the record's tag is not ``pdla``.
    """
    record = reader.read_record(record_num)
    _check_tag(record, PDLA_TAG, record_num)
    (index,) = struct.unpack_from("<H", record, SET_INDEX_OFFSET)
    danger = struct.unpack_from(f"<{PDLA_ARRAY_LENGTH}f", record, PDLA_DANGER_OFFSET)
    alert = struct.unpack_from(f"<{PDLA_ARRAY_LENGTH}f", record, PDLA_ALERT_OFFSET)
    codes = struct.unpack_from(f"<{PDLA_ARRAY_LENGTH}H", record, PDLA_UNIT_CODES_OFFSET)
    return AlarmLimitSet(
        record_num=record_num,
        index=index,
        name=decode_string(record[SET_NAME_OFFSET : SET_NAME_OFFSET + SET_NAME_LENGTH]),
        alert=tuple(float(v) for v in alert),
        danger=tuple(float(v) for v in danger),
        unit_codes=tuple(int(c) for c in codes),
    )


def find_set_directory(
    reader: RbmReader,
    label: bytes,
    *,
    search_limit: int = DIRECTORY_SEARCH_LIMIT,
) -> int | None:
    """Return the first record of the directory span labelled ``label``.

    Scans the low records for a label record (zero tag, ``label`` at
    ``0x10``); the directory span is the :data:`DIRECTORY_SPAN_RECORDS`
    records immediately before it. Returns ``None`` if not found.
    """
    limit = min(search_limit, reader.record_count)
    for n in range(DIRECTORY_SPAN_RECORDS, limit):
        record = reader.read_record(n)
        if record[TAG_OFFSET : TAG_OFFSET + 4] != b"\x00\x00\x00\x00":
            continue
        if record[DIRECTORY_LABEL_OFFSET : DIRECTORY_LABEL_OFFSET + len(label)] == label:
            # The 4 bytes after the label must be NUL (bare type name).
            tail = record[
                DIRECTORY_LABEL_OFFSET + len(label) : DIRECTORY_LABEL_OFFSET + len(label) + 4
            ]
            if tail == b"\x00\x00\x00\x00":
                return n - DIRECTORY_SPAN_RECORDS
    return None


def read_set_directory(reader: RbmReader, first_record: int) -> dict[int, int]:
    """Return ``{set index: record number}`` for the directory at ``first_record``.

    The directory is a flat u32 LE array of +1-encoded record numbers
    starting at ``first_record + 0x10`` and continuing through the whole
    payload of the next :data:`DIRECTORY_SPAN_RECORDS - 1` records. Index
    ``i + 1`` maps to entry ``i``; zero entries (unused indexes) are
    omitted.
    """
    data = reader.read_record(first_record)[DIRECTORY_ENTRIES_OFFSET:]
    for i in range(1, DIRECTORY_SPAN_RECORDS):
        data += reader.read_record(first_record + i)
    count = len(data) // 4
    entries = struct.unpack(f"<{count}I", data[: count * 4])
    return {i + 1: stored - 1 for i, stored in enumerate(entries) if stored}


class ParamSetIndex:
    """Cached resolver of set index → parsed ``pdpa``/``pdla`` record.

    Build once per reader with :meth:`load` and reuse across points: the
    directories are read eagerly (a handful of records) and the referenced
    set records are parsed lazily and memoized. On files without the
    directories (e.g. synthetic fixtures) both lookups return ``None``.
    """

    def __init__(
        self,
        reader: RbmReader,
        analysis_dir: dict[int, int],
        alarm_dir: dict[int, int],
    ) -> None:
        self._reader = reader
        self._analysis_dir = analysis_dir
        self._alarm_dir = alarm_dir
        self._analysis_cache: dict[int, AnalysisParameterSet | None] = {}
        self._alarm_cache: dict[int, AlarmLimitSet | None] = {}

    @classmethod
    def load(cls, reader: RbmReader) -> ParamSetIndex:
        """Locate and read both set directories of ``reader``'s file."""
        analysis_dir: dict[int, int] = {}
        alarm_dir: dict[int, int] = {}
        analysis_first = find_set_directory(reader, ANALYSIS_SET_LABEL)
        if analysis_first is not None:
            analysis_dir = read_set_directory(reader, analysis_first)
        alarm_first = find_set_directory(reader, ALARM_SET_LABEL)
        if alarm_first is not None:
            alarm_dir = read_set_directory(reader, alarm_first)
        return cls(reader, analysis_dir, alarm_dir)

    def analysis_set(self, index: int) -> AnalysisParameterSet | None:
        """Parsed analysis parameter set for ``index``, or ``None``."""
        if index not in self._analysis_cache:
            record_num = self._analysis_dir.get(index)
            parsed: AnalysisParameterSet | None = None
            if record_num is not None and 0 <= record_num < self._reader.record_count:
                try:
                    parsed = parse_pdpa_record(self._reader, record_num)
                except ParamSetError:
                    parsed = None
            self._analysis_cache[index] = parsed
        return self._analysis_cache[index]

    def alarm_set(self, index: int) -> AlarmLimitSet | None:
        """Parsed alarm limit set for ``index``, or ``None``."""
        if index not in self._alarm_cache:
            record_num = self._alarm_dir.get(index)
            parsed: AlarmLimitSet | None = None
            if record_num is not None and 0 <= record_num < self._reader.record_count:
                try:
                    parsed = parse_pdla_record(self._reader, record_num)
                except ParamSetError:
                    parsed = None
            self._alarm_cache[index] = parsed
        return self._alarm_cache[index]


def alarm_level(
    value_raw: float, alert: float | None, danger: float | None
) -> int | None:
    """Derive the VibFrame ``alarm`` level of a reading from its thresholds.

    Compares the raw stored value against the raw thresholds of the same
    slot (both in the slot's native unit): ``0`` normal, ``2`` alert (AMS
    "C Alarm"), ``3`` danger (AMS "D Alarm"). Level 1 is unused — AMS has
    no tier between normal and alert. Returns ``None`` when no threshold
    is configured (the level is then unknown, not "normal").
    """
    if alert is None and danger is None:
        return None
    if danger is not None and value_raw >= danger:
        return 3
    if alert is not None and value_raw >= alert:
        return 2
    return 0
