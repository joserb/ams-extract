"""Parsers for the per-point alarm note (``gdsc`` status header + ``gdnl`` text).

AMS keeps, for every point, the verdict of its last "exception analysis":
the literal report a user reads in the software as *"SUBSINCRONO - 1.986
mm/Seg - C Alarm"*. It lives in two records (FORMAT §5.9, solved
2026-07-27)::

    vdpm (point)
      └── 0x1E4 → gdsc (status header: when, how bad, who)
                    └── 0x38 → gdnl (the note text itself)

``gdsc`` is the **status descriptor** of the point. It carries the
timestamp of the measurement the verdict was computed on (``0x1C``, gold:
equals the point's newest sample date in 4648/4648 points of BUNGE), a
0-100 severity index (``0x1A``: 0 = not in alarm, 1-40 = C/alert zone,
41-100 = D/danger zone) and the AMS user that ran the analysis. Equipment
records have a ``gdsc`` too (``gscm.0xD4``) but never a note attached
(``0x38 = 0`` in all 347 equipment of BUNGE): the note is per point.

``gdnl`` is a plain text blob, cp1252, space-padded, CRLF-separated. Two
lines in every one of BUNGE's 5 783 records: a header naming the analysis
and one alarm line — or the "not in alarm" literal::

    Stored Parameter Analysis
    SUBSINCRONO - 1.986 mm/Seg -  C Alarm

The note is a *snapshot*, not a history: AMS overwrites it on every
exception analysis, so a point has exactly one, dated by ``gdsc.0x1C``.

The header language follows the AMS version that wrote the record
(``gdsc.0x18`` mirrors the version marker at ``0x06``): code 13 writes the
Spanish "Medición de Análisis por Excepción / NO en Alarma", codes 20 and
51 the English "Stored Parameter Analysis / Not in Alarm". All 145 v13
notes of BUNGE are "not in alarm", so no Spanish alarm line was ever
observed.

The band named by an alarm line is a slot of the point's ``pdpa``
template and its value is compared against the ``pdla`` thresholds of the
same slot (FORMAT §5.8) — that cross-check is the validation of this
decode and lives in :func:`ams_extract.tree.walk_alarm_note`.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from datetime import UTC, datetime

from ams_extract.encoding import decode_string
from ams_extract.reader import RECORD_SIZE, RbmReader, decode_inner_pointer

GDSC_TAG = b"gdsc"
GDNL_TAG = b"gdnl"
TAG_OFFSET = 0x08

VDPM_STATUS_OFFSET = 0x1E4
"""``vdpm`` offset holding the +1-encoded pointer to the point's ``gdsc``."""

GDSC_FORMAT_CODE_OFFSET = 0x18
GDSC_SEVERITY_OFFSET = 0x1A
GDSC_MEASURED_AT_OFFSET = 0x1C
GDSC_REVIEW_AT_OFFSET = 0x24
GDSC_USER_OFFSET = 0x28
GDSC_USER_LENGTH = 16
GDSC_NOTE_OFFSET = 0x38

GDNL_TEXT_OFFSET = 0x18
"""Start of the note text. ``0x18``-``0x37`` is blank in every BUNGE record;
the text proper starts at ``0x38``, so decoding from here and stripping the
padding is equivalent and tolerant to a used title field."""

SEVERITY_NONE = 0
"""``gdsc.0x1A`` value of a point that is not in alarm."""

SEVERITY_ALERT_MAX = 40
"""Last severity of the C (alert) zone; 41+ is the D (danger) zone."""

ALARM_LEVEL_ALERT = "C"
ALARM_LEVEL_DANGER = "D"

VELOCITY_UNITS_NOTE = "mm/Seg"
ACCELERATION_UNITS_NOTE = "G-s"

NOTE_UNITS_DISPLAY = {
    VELOCITY_UNITS_NOTE: "mm/s",
    ACCELERATION_UNITS_NOTE: "G's",
}
"""Units as spelled by the note → the display units used across the repo."""

OVERALL_BAND_NAMES = frozenset({"OVERALL VALUE"})
"""Band names that mean "the overall", i.e. index 0 of the ``pdla`` arrays."""

_ALARM_LINE = re.compile(
    r"^(?P<band>.+?)\s*-\s*(?P<value>[0-9]+(?:\.[0-9]+)?)\s+"
    r"(?P<units>mm/Seg|G-s)\s*-\s*(?P<level>[CD])\s+Alarm\s*$"
)
"""One alarm line. The lazy band group plus the closed unit vocabulary is
what lets band names that contain the separator parse right
(``"1 - 20 KHz - 11.278 G-s -  D Alarm"`` → band ``"1 - 20 KHz"``)."""


class AlarmNoteError(ValueError):
    """Raised when a ``gdsc``/``gdnl`` record has an unexpected tag."""


@dataclass(frozen=True, slots=True)
class AlarmLine:
    """The parsed alarm line of a note: which band, how much, how bad."""

    band: str
    value: float
    units_note: str
    level: str

    @property
    def units(self) -> str:
        """Display units (``mm/s`` / ``G's``) of :attr:`value`."""
        return NOTE_UNITS_DISPLAY.get(self.units_note, self.units_note)

    @property
    def is_overall(self) -> bool:
        """Whether the line reports the overall instead of a named band."""
        return self.band.upper() in OVERALL_BAND_NAMES


@dataclass(frozen=True, slots=True)
class NoteStatus:
    """The ``gdsc`` status header of a point."""

    record_num: int
    format_code: int
    severity: int
    measured_at_utc: datetime | None
    review_at_utc: datetime | None
    user: str
    note_record: int | None

    @property
    def in_alarm(self) -> bool:
        """Whether AMS flagged the point (severity 0 means "not in alarm")."""
        return self.severity > SEVERITY_NONE

    @property
    def severity_level(self) -> str | None:
        """``"C"``/``"D"`` implied by :attr:`severity`, or ``None`` if calm."""
        if self.severity <= SEVERITY_NONE:
            return None
        if self.severity <= SEVERITY_ALERT_MAX:
            return ALARM_LEVEL_ALERT
        return ALARM_LEVEL_DANGER


def _check_tag(record: bytes, expected: bytes, record_num: int) -> None:
    tag = bytes(record[TAG_OFFSET : TAG_OFFSET + 4])
    if tag != expected:
        raise AlarmNoteError(f"record {record_num}: expected tag {expected!r}, got {tag!r}")


def _timestamp(raw: int) -> datetime | None:
    """Unix seconds → aware UTC datetime; ``None`` for 0 / out of range."""
    if raw <= 0:
        return None
    try:
        return datetime.fromtimestamp(raw, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def point_status_record(reader: RbmReader, vdpm_record: int) -> int | None:
    """Return the ``gdsc`` record of the point at ``vdpm_record``, if any."""
    record = reader.read_record(vdpm_record)
    (stored,) = struct.unpack_from("<I", record, VDPM_STATUS_OFFSET)
    return decode_inner_pointer(stored)


def parse_gdsc_status(reader: RbmReader, record_num: int) -> NoteStatus:
    """Decode the ``gdsc`` status header at ``record_num``.

    Raises:
        AlarmNoteError: If the record's tag is not ``gdsc``.
    """
    record = reader.read_record(record_num)
    _check_tag(record, GDSC_TAG, record_num)
    format_code, severity = struct.unpack_from("<HH", record, GDSC_FORMAT_CODE_OFFSET)
    (measured_raw,) = struct.unpack_from("<I", record, GDSC_MEASURED_AT_OFFSET)
    (review_raw,) = struct.unpack_from("<I", record, GDSC_REVIEW_AT_OFFSET)
    (note_stored,) = struct.unpack_from("<I", record, GDSC_NOTE_OFFSET)
    return NoteStatus(
        record_num=record_num,
        format_code=format_code,
        severity=severity,
        measured_at_utc=_timestamp(measured_raw),
        review_at_utc=_timestamp(review_raw),
        user=decode_string(record[GDSC_USER_OFFSET : GDSC_USER_OFFSET + GDSC_USER_LENGTH]),
        note_record=decode_inner_pointer(note_stored),
    )


def read_gdnl_text(reader: RbmReader, record_num: int) -> str:
    """Return the note text of the ``gdnl`` at ``record_num``, newline-joined.

    CRLF line breaks are normalized to ``\\n`` and trailing padding is
    stripped from every line, so the result is the text as AMS shows it.

    Raises:
        AlarmNoteError: If the record's tag is not ``gdnl``.
    """
    record = reader.read_record(record_num)
    _check_tag(record, GDNL_TAG, record_num)
    raw = decode_string(record[GDNL_TEXT_OFFSET:RECORD_SIZE])
    lines = [line.strip() for line in raw.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


def parse_alarm_line(text: str) -> AlarmLine | None:
    """Return the alarm reported by a note text, or ``None`` if calm.

    Scans every line of ``text`` (the header line never matches) and
    returns the first alarm line. A note with no alarm line is a
    "Not in Alarm" / "NO en Alarma" note.
    """
    for line in text.split("\n"):
        match = _ALARM_LINE.match(line.strip())
        if match is not None:
            return AlarmLine(
                band=match["band"].strip(),
                value=float(match["value"]),
                units_note=match["units"],
                level=match["level"],
            )
    return None
