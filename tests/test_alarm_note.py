"""Unit tests for the per-point alarm note (``gdsc`` + ``gdnl``).

Synthetic records mirror the layout solved in FORMAT §5.9 against BUNGE.
The gold case is M1H of AG-100 and its ``pdla`` set 5 (alert 1.4 mm/s,
danger 2.2 mm/s): the note ``"SUBSINCRONO - 1.986 mm/Seg -  C Alarm"``
must land inside ``[1.4, 2.2)``.
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ams_extract.models import Point
from ams_extract.reader import RECORD_SIZE, RbmReader
from ams_extract.records.alarm_note import (
    GDNL_TAG,
    GDNL_TEXT_OFFSET,
    GDSC_FORMAT_CODE_OFFSET,
    GDSC_MEASURED_AT_OFFSET,
    GDSC_NOTE_OFFSET,
    GDSC_REVIEW_AT_OFFSET,
    GDSC_TAG,
    GDSC_USER_OFFSET,
    TAG_OFFSET,
    VDPM_STATUS_OFFSET,
    AlarmNoteError,
    parse_alarm_line,
    parse_gdsc_status,
    point_status_record,
    read_gdnl_text,
)
from ams_extract.records.pdpa import (
    ALARM_SET_LABEL,
    ANALYSIS_SET_LABEL,
    BAND_TYPE_ORDERS,
    BAND_TYPE_WAVEFORM_PEAK,
    DIRECTORY_ENTRIES_OFFSET,
    DIRECTORY_LABEL_OFFSET,
    DIRECTORY_SPAN_RECORDS,
    PDLA_ALERT_OFFSET,
    PDLA_ARRAY_LENGTH,
    PDLA_DANGER_OFFSET,
    PDLA_TAG,
    PDLA_UNIT_CODES_OFFSET,
    PDPA_SLOT_HIGH_OFFSET,
    PDPA_SLOT_LOW_OFFSET,
    PDPA_SLOT_NAME_LENGTH,
    PDPA_SLOT_NAMES_OFFSET,
    PDPA_SLOT_TYPES_OFFSET,
    PDPA_TAG,
    SET_INDEX_OFFSET,
    SET_NAME_OFFSET,
    THRESHOLD_UNIT_ACCELERATION,
    THRESHOLD_UNIT_VELOCITY,
    ParamSetIndex,
)
from ams_extract.records.sample_index import (
    PDCD_ALARM_SET_INDEX_OFFSET,
    PDCD_ANALYSIS_SET_INDEX_OFFSET,
    PDCD_TAG,
)
from ams_extract.tree import walk_alarm_note

MEASURED_AT = 1_582_097_034  # 2020-02-19 07:23:54 UTC, the M1H gold date
ENGLISH_HEADER = "Stored Parameter Analysis"
GOLD_LINE = "SUBSINCRONO - 1.986 mm/Seg -  C Alarm"

# The M1H template/limits of BUNGE, trimmed to the slots the tests need.
_SLOTS = (
    ("Mp Wave", BAND_TYPE_WAVEFORM_PEAK, 0.0, 0.0),
    ("SUBSINCRONO", BAND_TYPE_ORDERS, 0.0, 0.7),
)
_ALERT_RAW = (0.0, 8.0, 0.055118)  # overall, Mp Wave (G's), SUBSINCRONO (in/s)
_DANGER_RAW = (0.0, 12.0, 0.086614)
_UNIT_CODES = (
    THRESHOLD_UNIT_VELOCITY,
    THRESHOLD_UNIT_ACCELERATION,
    THRESHOLD_UNIT_VELOCITY,
)


def _empty() -> bytearray:
    return bytearray(RECORD_SIZE)


def _pack_padded(buf: bytearray, offset: int, text: bytes, width: int) -> None:
    field = bytearray(b" " * width)
    field[: len(text)] = text
    buf[offset : offset + width] = field


def _make_header() -> bytes:
    record = _empty()
    record[0x1C : 0x1C + 6] = b"MT4.00"
    return bytes(record)


def _make_gdnl(lines: tuple[str, ...]) -> bytes:
    record = _empty()
    record[TAG_OFFSET : TAG_OFFSET + 4] = GDNL_TAG
    text = "\r\n".join(lines).encode("cp1252")
    _pack_padded(record, 0x38, text, RECORD_SIZE - 0x38)
    _pack_padded(record, GDNL_TEXT_OFFSET, b"", 0x38 - GDNL_TEXT_OFFSET)
    return bytes(record)


def _make_gdsc(
    *,
    severity: int,
    note_record: int | None,
    measured_at: int = MEASURED_AT,
    format_code: int = 51,
) -> bytes:
    record = _empty()
    record[TAG_OFFSET : TAG_OFFSET + 4] = GDSC_TAG
    struct.pack_into("<HH", record, GDSC_FORMAT_CODE_OFFSET, format_code, severity)
    struct.pack_into("<I", record, GDSC_MEASURED_AT_OFFSET, measured_at)
    struct.pack_into("<I", record, GDSC_REVIEW_AT_OFFSET, measured_at + 30 * 86_400)
    _pack_padded(record, GDSC_USER_OFFSET, b"Administrator", 16)
    struct.pack_into(
        "<I", record, GDSC_NOTE_OFFSET, 0 if note_record is None else note_record + 1
    )
    return bytes(record)


def _make_vdpm(*, pdcd_record: int, gdsc_record: int | None) -> bytes:
    record = _empty()
    record[TAG_OFFSET : TAG_OFFSET + 4] = b"vdpm"
    struct.pack_into("<I", record, 0x10, pdcd_record + 1)
    struct.pack_into(
        "<I", record, VDPM_STATUS_OFFSET, 0 if gdsc_record is None else gdsc_record + 1
    )
    return bytes(record)


def _make_pdcd(*, analysis_index: int, alarm_index: int) -> bytes:
    record = _empty()
    record[TAG_OFFSET : TAG_OFFSET + 4] = PDCD_TAG
    struct.pack_into("<H", record, PDCD_ANALYSIS_SET_INDEX_OFFSET, analysis_index)
    struct.pack_into("<H", record, PDCD_ALARM_SET_INDEX_OFFSET, alarm_index)
    return bytes(record)


def _make_pdpa(index: int = 1) -> bytes:
    record = _empty()
    record[TAG_OFFSET : TAG_OFFSET + 4] = PDPA_TAG
    _pack_padded(record, SET_NAME_OFFSET, b"Estandar 1500 rpm (S)", 32)
    struct.pack_into("<HH", record, SET_INDEX_OFFSET, index, len(_SLOTS))
    for i, (name, band_type, low, high) in enumerate(_SLOTS):
        _pack_padded(
            record,
            PDPA_SLOT_NAMES_OFFSET + i * PDPA_SLOT_NAME_LENGTH,
            name.encode("cp1252"),
            PDPA_SLOT_NAME_LENGTH,
        )
        record[PDPA_SLOT_TYPES_OFFSET + i] = band_type
        struct.pack_into("<f", record, PDPA_SLOT_LOW_OFFSET + i * 4, low)
        struct.pack_into("<f", record, PDPA_SLOT_HIGH_OFFSET + i * 4, high)
    return bytes(record)


def _make_pdla(index: int = 5, unit_codes: tuple[int, ...] = _UNIT_CODES) -> bytes:
    record = _empty()
    record[TAG_OFFSET : TAG_OFFSET + 4] = PDLA_TAG
    _pack_padded(record, SET_NAME_OFFSET, b"Motor Horizontal P<300 kW (S)", 32)
    struct.pack_into("<H", record, SET_INDEX_OFFSET, index)
    for i in range(PDLA_ARRAY_LENGTH):
        struct.pack_into(
            "<f",
            record,
            PDLA_ALERT_OFFSET + i * 4,
            _ALERT_RAW[i] if i < len(_ALERT_RAW) else 0.0,
        )
        struct.pack_into(
            "<f",
            record,
            PDLA_DANGER_OFFSET + i * 4,
            _DANGER_RAW[i] if i < len(_DANGER_RAW) else 0.0,
        )
        struct.pack_into(
            "<H",
            record,
            PDLA_UNIT_CODES_OFFSET + i * 2,
            unit_codes[i] if i < len(unit_codes) else THRESHOLD_UNIT_VELOCITY,
        )
    return bytes(record)


def _make_directory_span(entries: dict[int, int]) -> list[bytes]:
    """Directory span: flat +1-encoded u32 array over 4 records (FORMAT §5.8)."""
    flat = bytearray((RECORD_SIZE * DIRECTORY_SPAN_RECORDS) - DIRECTORY_ENTRIES_OFFSET)
    for set_index, record_num in entries.items():
        struct.pack_into("<I", flat, (set_index - 1) * 4, record_num + 1)
    data = bytes(DIRECTORY_ENTRIES_OFFSET) + bytes(flat)
    return [data[i * RECORD_SIZE : (i + 1) * RECORD_SIZE] for i in range(DIRECTORY_SPAN_RECORDS)]


def _make_label(label: bytes) -> bytes:
    record = _empty()
    record[DIRECTORY_LABEL_OFFSET : DIRECTORY_LABEL_OFFSET + len(label)] = label
    return bytes(record)


@pytest.fixture
def reader_factory(tmp_path: Path):
    def make(records: list[bytes]) -> RbmReader:
        rbm = tmp_path / "fixture.rbm"
        rbm.write_bytes(b"".join(records))
        return RbmReader(rbm)

    return make


def _point_file(
    *, line: str | None, severity: int, unit_codes: tuple[int, ...] = _UNIT_CODES
) -> list[bytes]:
    """A one-point database: header, vdpm, pdcd, gdsc, gdnl, pdpa, pdla."""
    lines = (ENGLISH_HEADER, line) if line else (ENGLISH_HEADER, "Not in Alarm")
    return [
        _make_header(),  # 0
        _make_vdpm(pdcd_record=2, gdsc_record=3),  # 1
        _make_pdcd(analysis_index=1, alarm_index=5),  # 2
        _make_gdsc(severity=severity, note_record=4),  # 3
        _make_gdnl(lines),  # 4
        _make_pdpa(),  # 5
        _make_pdla(unit_codes=unit_codes),  # 6
        *_make_directory_span({1: 5}),  # 7-10: pdpa directory
        _make_label(ANALYSIS_SET_LABEL),  # 11
        *_make_directory_span({5: 6}),  # 12-15: pdla directory
        _make_label(ALARM_SET_LABEL),  # 16
    ]


class TestParseAlarmLine:
    def test_parses_the_gold_line(self) -> None:
        line = parse_alarm_line(f"{ENGLISH_HEADER}\n{GOLD_LINE}")
        assert line is not None
        assert line.band == "SUBSINCRONO"
        assert line.value == pytest.approx(1.986)
        assert line.units == "mm/s"
        assert line.level == "C"
        assert not line.is_overall

    def test_band_name_may_contain_the_separator(self) -> None:
        line = parse_alarm_line("1 - 20 KHz - 11.278 G-s      -  D Alarm")
        assert line is not None
        assert line.band == "1 - 20 KHz"
        assert line.value == pytest.approx(11.278)
        assert line.units == "G's"
        assert line.level == "D"

    def test_recognises_the_overall(self) -> None:
        line = parse_alarm_line("OVERALL VALUE - 4.079 mm/Seg -  C Alarm")
        assert line is not None
        assert line.is_overall

    @pytest.mark.parametrize(
        "text",
        [
            "Stored Parameter Analysis\nNot in Alarm",
            "Medición de Análisis por Excepción:\nNO en Alarma",
            "",
        ],
    )
    def test_calm_notes_have_no_line(self, text: str) -> None:
        assert parse_alarm_line(text) is None


class TestParseRecords:
    def test_reads_status_pointer_and_header(self, reader_factory) -> None:
        with reader_factory(_point_file(line=GOLD_LINE, severity=15)) as reader:
            assert point_status_record(reader, 1) == 3
            status = parse_gdsc_status(reader, 3)
        assert status.severity == 15
        assert status.severity_level == "C"
        assert status.in_alarm
        assert status.user == "Administrator"
        assert status.note_record == 4
        assert status.measured_at_utc == datetime(2020, 2, 19, 7, 23, 54, tzinfo=UTC)
        assert status.review_at_utc is not None

    def test_severity_zero_is_calm(self, reader_factory) -> None:
        with reader_factory(_point_file(line=None, severity=0)) as reader:
            status = parse_gdsc_status(reader, 3)
        assert not status.in_alarm
        assert status.severity_level is None

    def test_missing_note_pointer_is_none(self, reader_factory) -> None:
        records = _point_file(line=None, severity=0)
        records[3] = _make_gdsc(severity=0, note_record=None)
        with reader_factory(records) as reader:
            assert parse_gdsc_status(reader, 3).note_record is None

    def test_reads_note_text_without_padding(self, reader_factory) -> None:
        with reader_factory(_point_file(line=GOLD_LINE, severity=15)) as reader:
            text = read_gdnl_text(reader, 4)
        assert text == f"{ENGLISH_HEADER}\n{GOLD_LINE}"

    def test_rejects_wrong_tags(self, reader_factory) -> None:
        with reader_factory(_point_file(line=GOLD_LINE, severity=15)) as reader:
            with pytest.raises(AlarmNoteError):
                parse_gdsc_status(reader, 4)
            with pytest.raises(AlarmNoteError):
                read_gdnl_text(reader, 3)


class TestWalkAlarmNote:
    def _walk(self, reader: RbmReader):
        point = Point(record_num=1, long_name="MOTOR LOA HORIZONTAL", short_code="M1H")
        return walk_alarm_note(reader, point, ParamSetIndex.load(reader))

    def test_gold_alarm_falls_between_its_thresholds(self, reader_factory) -> None:
        with reader_factory(_point_file(line=GOLD_LINE, severity=15)) as reader:
            note = self._walk(reader)
        assert note is not None
        assert note.in_alarm
        assert note.band == "SUBSINCRONO"
        assert note.units == "mm/s"
        # pdla set 5: alert 0.055118 in/s = 1.4 mm/s, danger 0.086614 = 2.2 mm/s.
        assert note.alert == pytest.approx(1.4, abs=1e-3)
        assert note.danger == pytest.approx(2.2, abs=1e-3)
        assert note.alert <= note.value < note.danger
        assert note.coherent is True
        assert note.unit_consistent
        assert note.emittable
        assert note.alarm == 2
        assert note.limit_set == "Motor Horizontal P<300 kW (S)"

    def test_danger_alarm_maps_to_level_three(self, reader_factory) -> None:
        records = _point_file(line="SUBSINCRONO - 3.500 mm/Seg -  D Alarm", severity=55)
        with reader_factory(records) as reader:
            note = self._walk(reader)
        assert note is not None
        assert note.level == "D"
        assert note.alarm == 3
        assert note.coherent is True
        assert note.emittable

    def test_value_outside_its_interval_is_not_emittable(self, reader_factory) -> None:
        # A "C Alarm" above the danger threshold contradicts the pdla set.
        records = _point_file(line="SUBSINCRONO - 3.500 mm/Seg -  C Alarm", severity=15)
        with reader_factory(records) as reader:
            note = self._walk(reader)
        assert note is not None
        assert note.coherent is False
        assert not note.emittable

    def test_unit_mismatch_is_flagged_and_not_emittable(self, reader_factory) -> None:
        # The note reports G's but the pdla slot declares a velocity limit:
        # the number "fits" but the units do not, so it is not ground truth.
        codes = (THRESHOLD_UNIT_VELOCITY,) * 3
        records = _point_file(
            line="Mp Wave - 20.000 G-s      -  D Alarm", severity=60, unit_codes=codes
        )
        with reader_factory(records) as reader:
            note = self._walk(reader)
        assert note is not None
        assert note.unit_consistent is False
        assert not note.emittable

    def test_severity_zone_must_agree_with_the_text(self, reader_factory) -> None:
        # Severity 60 is the D zone but the line says C: one of the two
        # decodes would be wrong, so the note is not published.
        records = _point_file(line=GOLD_LINE, severity=60)
        with reader_factory(records) as reader:
            note = self._walk(reader)
        assert note is not None
        assert note.severity_level == "D"
        assert note.level == "C"
        assert not note.emittable

    def test_calm_point_yields_a_note_without_alarm(self, reader_factory) -> None:
        with reader_factory(_point_file(line=None, severity=0)) as reader:
            note = self._walk(reader)
        assert note is not None
        assert not note.in_alarm
        assert note.alarm == 0
        assert not note.emittable

    def test_point_without_status_record_yields_none(self, reader_factory) -> None:
        records = _point_file(line=None, severity=0)
        records[1] = _make_vdpm(pdcd_record=2, gdsc_record=None)
        with reader_factory(records) as reader:
            assert self._walk(reader) is None
