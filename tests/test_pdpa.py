"""Unit tests for the shared analysis-parameter / alarm-limit set parsers.

Synthetic records mirror the layout solved in FORMAT §5.8 against BUNGE
(``pdpa`` band templates, ``pdla`` threshold sets, and the ``gipa``/``gila``
directory sections near the header).
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from ams_extract.reader import RECORD_SIZE, RbmReader
from ams_extract.records.pdpa import (
    ALARM_SET_LABEL,
    ANALYSIS_SET_LABEL,
    BAND_TYPE_FIXED_HZ,
    BAND_TYPE_HF_FIXED_HZ,
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
    TAG_OFFSET,
    THRESHOLD_UNIT_ACCELERATION,
    THRESHOLD_UNIT_VELOCITY,
    ParamSetError,
    ParamSetIndex,
    alarm_level,
    find_set_directory,
    parse_pdla_record,
    parse_pdpa_record,
    read_set_directory,
)

# The Estandar 1500 rpm (S) template of BUNGE, as decoded from record 153.
_SLOTS = (
    ("Mp Wave", BAND_TYPE_WAVEFORM_PEAK, 0.0, 0.0),
    ("SUBSINCRONO", BAND_TYPE_ORDERS, 0.0, 0.7),
    ("DESEQUILIBRIO", BAND_TYPE_ORDERS, 0.7, 1.5),
    ("FALLO ELECTRIC", BAND_TYPE_FIXED_HZ, 99.8, 100.2),
    ("1 - 20 KHz", BAND_TYPE_HF_FIXED_HZ, 1000.0, 20000.0),
)


def _empty_record() -> bytearray:
    return bytearray(RECORD_SIZE)


def _make_header() -> bytes:
    record = _empty_record()
    record[0x1C : 0x1C + 6] = b"MT4.00"
    return bytes(record)


def _pack_padded(buf: bytearray, offset: int, text: bytes, width: int) -> None:
    field = bytearray(b" " * width)
    field[: len(text)] = text
    buf[offset : offset + width] = field


def _make_pdpa(
    *,
    index: int = 1,
    name: bytes = b"Estandar 1500 rpm (S)",
    slots=_SLOTS,
    active: int | None = None,
    trailing_junk: int = 0,
) -> bytes:
    """Build a pdpa record; ``trailing_junk`` adds named-but-inactive slots."""
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = PDPA_TAG
    _pack_padded(record, SET_NAME_OFFSET, name, 32)
    n_active = len(slots) if active is None else active
    struct.pack_into("<HH", record, SET_INDEX_OFFSET, index, n_active)
    for i in range(12):
        name_off = PDPA_SLOT_NAMES_OFFSET + i * PDPA_SLOT_NAME_LENGTH
        if i < len(slots):
            slot_name, band_type, low, high = slots[i]
            _pack_padded(record, name_off, slot_name.encode("cp1252"), 14)
            record[PDPA_SLOT_TYPES_OFFSET + i] = band_type
            struct.pack_into("<f", record, PDPA_SLOT_LOW_OFFSET + i * 4, low)
            struct.pack_into("<f", record, PDPA_SLOT_HIGH_OFFSET + i * 4, high)
        elif i < len(slots) + trailing_junk:
            # Stale leftovers from template edits: named but inactive.
            _pack_padded(record, name_off, b"1 - 20 KHz", 14)
            record[PDPA_SLOT_TYPES_OFFSET + i] = BAND_TYPE_HF_FIXED_HZ
            struct.pack_into("<f", record, PDPA_SLOT_LOW_OFFSET + i * 4, 1000.0)
            struct.pack_into("<f", record, PDPA_SLOT_HIGH_OFFSET + i * 4, 20000.0)
        else:
            _pack_padded(record, name_off, b"INDEFINID", 14)
            record[PDPA_SLOT_TYPES_OFFSET + i] = BAND_TYPE_ORDERS
    return bytes(record)


def _make_pdla(
    *,
    index: int = 5,
    name: bytes = b"Motor Horizontal P<300 kW (S)",
    alert=(),
    danger=(),
    unit_codes=(),
) -> bytes:
    record = _empty_record()
    record[TAG_OFFSET : TAG_OFFSET + 4] = PDLA_TAG
    _pack_padded(record, SET_NAME_OFFSET, name, 32)
    struct.pack_into("<H", record, SET_INDEX_OFFSET, index)
    for i in range(PDLA_ARRAY_LENGTH):
        struct.pack_into(
            "<f", record, PDLA_ALERT_OFFSET + i * 4, alert[i] if i < len(alert) else 0.0
        )
        struct.pack_into(
            "<f",
            record,
            PDLA_DANGER_OFFSET + i * 4,
            danger[i] if i < len(danger) else 0.0,
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
    record = _empty_record()
    record[DIRECTORY_LABEL_OFFSET : DIRECTORY_LABEL_OFFSET + len(label)] = label
    return bytes(record)


@pytest.fixture
def reader_factory(tmp_path: Path):
    def make(records: list[bytes]) -> RbmReader:
        rbm = tmp_path / "fixture.rbm"
        rbm.write_bytes(b"".join(records))
        return RbmReader(rbm)

    return make


class TestParsePdpaRecord:
    def test_decodes_active_slots(self, reader_factory) -> None:
        with reader_factory([_make_header(), _make_pdpa()]) as reader:
            template = parse_pdpa_record(reader, 1)
        assert template.index == 1
        assert template.name == "Estandar 1500 rpm (S)"
        assert [b.name for b in template.bands] == [
            "Mp Wave",
            "SUBSINCRONO",
            "DESEQUILIBRIO",
            "FALLO ELECTRIC",
            "1 - 20 KHz",
        ]
        sub = template.bands[1]
        assert sub.band_type == BAND_TYPE_ORDERS
        assert sub.low == pytest.approx(0.0)
        assert sub.high == pytest.approx(0.7)
        fallo = template.bands[3]
        assert fallo.band_type == BAND_TYPE_FIXED_HZ
        assert fallo.low == pytest.approx(99.8)
        assert fallo.high == pytest.approx(100.2)

    def test_drops_trailing_inactive_slots(self, reader_factory) -> None:
        # BUNGE's HR template names 7 slots but only 6 are active; the
        # trailing named slot is a stale leftover and must not be returned.
        pdpa = _make_pdpa(active=len(_SLOTS), trailing_junk=2)
        with reader_factory([_make_header(), pdpa]) as reader:
            template = parse_pdpa_record(reader, 1)
        assert len(template.bands) == len(_SLOTS)

    def test_rejects_wrong_tag(self, reader_factory) -> None:
        with (
            reader_factory([_make_header(), _make_pdla()]) as reader,
            pytest.raises(ParamSetError),
        ):
            parse_pdpa_record(reader, 1)


class TestParsePdlaRecord:
    def test_decodes_thresholds_and_unit_codes(self, reader_factory) -> None:
        # Raw in/s values of alarm set 5: overall 0.11024/0.17717,
        # Mp Wave (slot 0, G's) 8/12, SUBSINCRONO (slot 1) 0.055118/0.086614.
        pdla = _make_pdla(
            alert=(0.11024, 8.0, 0.055118),
            danger=(0.17717, 12.0, 0.086614),
            unit_codes=(
                THRESHOLD_UNIT_VELOCITY,
                THRESHOLD_UNIT_ACCELERATION,
                THRESHOLD_UNIT_VELOCITY,
            ),
        )
        with reader_factory([_make_header(), pdla]) as reader:
            limits = parse_pdla_record(reader, 1)
        assert limits.index == 5
        assert limits.name == "Motor Horizontal P<300 kW (S)"
        assert limits.alert_for(0) == pytest.approx(0.11024)
        assert limits.danger_for(0) == pytest.approx(0.17717)
        assert limits.alert_for(2) == pytest.approx(0.055118)
        assert limits.danger_for(2) == pytest.approx(0.086614)
        assert limits.unit_codes[1] == THRESHOLD_UNIT_ACCELERATION

    def test_zero_threshold_means_not_configured(self, reader_factory) -> None:
        pdla = _make_pdla(alert=(0.11024,), danger=(0.17717,))
        with reader_factory([_make_header(), pdla]) as reader:
            limits = parse_pdla_record(reader, 1)
        assert limits.alert_for(3) is None
        assert limits.danger_for(3) is None

    def test_rejects_wrong_tag(self, reader_factory) -> None:
        with (
            reader_factory([_make_header(), _make_pdpa()]) as reader,
            pytest.raises(ParamSetError),
        ):
            parse_pdla_record(reader, 1)


class TestDirectories:
    def _records(self) -> list[bytes]:
        # Layout: header, pdpa at 1, pdla at 2, then the two directory
        # sections (span of 4 records + label record each).
        records = [_make_header(), _make_pdpa(index=7), _make_pdla(index=200)]
        records += _make_directory_span({7: 1})
        records.append(_make_label(ANALYSIS_SET_LABEL))
        records += _make_directory_span({200: 2})
        records.append(_make_label(ALARM_SET_LABEL))
        return records

    def test_find_and_read_directory(self, reader_factory) -> None:
        with reader_factory(self._records()) as reader:
            analysis_first = find_set_directory(reader, ANALYSIS_SET_LABEL)
            alarm_first = find_set_directory(reader, ALARM_SET_LABEL)
            assert analysis_first == 3
            assert alarm_first == 8
            assert read_set_directory(reader, analysis_first) == {7: 1}
            # Index 200 lands past the first record of the span: the flat
            # array continues through the following records' full payload.
            assert read_set_directory(reader, alarm_first) == {200: 2}

    def test_param_set_index_resolves_sets(self, reader_factory) -> None:
        with reader_factory(self._records()) as reader:
            index = ParamSetIndex.load(reader)
            template = index.analysis_set(7)
            assert template is not None
            assert template.name == "Estandar 1500 rpm (S)"
            limits = index.alarm_set(200)
            assert limits is not None
            assert limits.index == 200
            assert index.analysis_set(99) is None
            assert index.alarm_set(99) is None

    def test_missing_directories_resolve_to_none(self, reader_factory) -> None:
        with reader_factory([_make_header(), _make_pdpa()]) as reader:
            index = ParamSetIndex.load(reader)
            assert index.analysis_set(1) is None
            assert index.alarm_set(5) is None


class TestAlarmLevel:
    def test_levels_follow_vibframe_scale(self) -> None:
        # 0 normal, 2 alert (AMS C), 3 danger (AMS D); level 1 unused.
        assert alarm_level(0.05, 0.055118, 0.086614) == 0
        assert alarm_level(0.056, 0.055118, 0.086614) == 2
        assert alarm_level(0.09, 0.055118, 0.086614) == 3

    def test_none_when_no_thresholds(self) -> None:
        assert alarm_level(1.0, None, None) is None

    def test_partial_thresholds(self) -> None:
        assert alarm_level(1.0, None, 2.0) == 0
        assert alarm_level(3.0, None, 2.0) == 3
        assert alarm_level(3.0, 2.0, None) == 2


@pytest.mark.integration
class TestRealDatabase:
    """Integration checks against BUNGE (gold anchors of FORMAT §5.8)."""

    def test_estandar_1500_template(self, real_rbm: Path) -> None:
        with RbmReader(real_rbm) as reader:
            index = ParamSetIndex.load(reader)
            template = index.analysis_set(1)
        assert template is not None
        assert template.name == "Estandar 1500 rpm (S)"
        names = [b.name for b in template.bands]
        assert names == [
            "Mp Wave",
            "SUBSINCRONO",
            "DESEQUILIBRIO",
            "DESALINEACION",
            "HOLGURAS",
            "11-40 X RPM",
            "1 - 20 KHz",
        ]
        # Contiguous order-scaled bands; "11-40 X RPM" ends at 40.5 x RPM.
        sub = template.bands[1]
        assert sub.band_type == BAND_TYPE_ORDERS
        assert (sub.low, sub.high) == (pytest.approx(0.0), pytest.approx(0.7))
        eleven40 = template.bands[5]
        assert (eleven40.low, eleven40.high) == (
            pytest.approx(10.5),
            pytest.approx(40.5),
        )
        # "1 - 20 KHz" is a fixed 1000-20000 Hz HF band.
        hf = template.bands[6]
        assert hf.band_type == BAND_TYPE_HF_FIXED_HZ
        assert (hf.low, hf.high) == (pytest.approx(1000.0), pytest.approx(20000.0))

    def test_m1h_point_links_and_thresholds(self, real_rbm: Path) -> None:
        # M1H (MOTOR LOA HORIZONTAL of AG-100): vdpm 336982 -> pdcd with
        # (analysis, alarm) = (1, 5). Alarm set 5 is "Motor Horizontal
        # P<300 kW (S)" whose SUBSINCRONO thresholds x25.4 are the gold
        # C/D transition levels (~1.4 / ~2.2 mm/s).
        from ams_extract.records.sample_index import parse_pdcd_links

        with RbmReader(real_rbm) as reader:
            links = parse_pdcd_links(reader, 336986)
            assert links.analysis_set_index == 1
            assert links.alarm_set_index == 5
            index = ParamSetIndex.load(reader)
            limits = index.alarm_set(5)
        assert limits is not None
        assert limits.name == "Motor Horizontal P<300 kW (S)"
        # Array index 2 = band slot 1 (SUBSINCRONO), raw inches/s.
        assert limits.alert_for(2) is not None
        assert limits.alert_for(2) * 25.4 == pytest.approx(1.4, abs=0.01)
        assert limits.danger_for(2) is not None
        assert limits.danger_for(2) * 25.4 == pytest.approx(2.2, abs=0.01)
        assert limits.unit_codes[2] == THRESHOLD_UNIT_VELOCITY
        # Slot 0 (Mp Wave) thresholds are in G's.
        assert limits.unit_codes[1] == THRESHOLD_UNIT_ACCELERATION
        assert limits.alert_for(1) == pytest.approx(8.0)
        assert limits.danger_for(1) == pytest.approx(12.0)

    def test_directories_cover_all_referenced_sets(self, real_rbm: Path) -> None:
        with RbmReader(real_rbm) as reader:
            analysis_first = find_set_directory(reader, ANALYSIS_SET_LABEL)
            alarm_first = find_set_directory(reader, ALARM_SET_LABEL)
            assert analysis_first is not None
            assert alarm_first is not None
            analysis_dir = read_set_directory(reader, analysis_first)
            alarm_dir = read_set_directory(reader, alarm_first)
            # BUNGE holds 41 pdpa templates and 92 pdla sets.
            assert len(analysis_dir) == 41
            assert len(alarm_dir) == 92
            for record_num in analysis_dir.values():
                assert reader.read_record(record_num)[8:12] == PDPA_TAG
            for record_num in alarm_dir.values():
                assert reader.read_record(record_num)[8:12] == PDLA_TAG
