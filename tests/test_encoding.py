"""Tests for ``ams_extract.encoding``."""

from __future__ import annotations

from ams_extract.encoding import decode_string, strip_padding


class TestStripPadding:
    def test_removes_trailing_spaces(self) -> None:
        assert strip_padding(b"Preditec        ") == b"Preditec"

    def test_removes_trailing_nuls(self) -> None:
        assert strip_padding(b"AREA\x00\x00\x00\x00") == b"AREA"

    def test_removes_mixed_trailing_padding(self) -> None:
        assert strip_padding(b"EQUIPO \x00\x00 \x00") == b"EQUIPO"

    def test_leaves_internal_spaces_alone(self) -> None:
        assert strip_padding(b"PARQUE TANQUES   ") == b"PARQUE TANQUES"

    def test_empty_input(self) -> None:
        assert strip_padding(b"") == b""

    def test_all_padding(self) -> None:
        assert strip_padding(b"\x00 \x00 ") == b""


class TestDecodeString:
    def test_plain_ascii(self) -> None:
        assert decode_string(b"Preditec        ") == "Preditec"

    def test_cp1252_accented_chars(self) -> None:
        # 0xC1 = 'Á' in cp1252; 0xD3 = 'Ó' in cp1252.
        assert decode_string(b"EST\xc1NDAR\x00\x00") == "ESTÁNDAR"
        assert decode_string(b"OPERACI\xd3N") == "OPERACIÓN"

    def test_empty_field(self) -> None:
        assert decode_string(b"\x00" * 32) == ""

    def test_padding_stripped_before_decode(self) -> None:
        assert decode_string(b"AREA       \x00\x00") == "AREA"

    def test_invalid_bytes_dont_raise(self) -> None:
        # 0x81, 0x8D, 0x8F, 0x90, 0x9D are unmapped in cp1252; cp850 also has
        # gaps but the final latin-1 fallback guarantees no exception.
        result = decode_string(b"\x81\x8d\x8f\x90\x9d")
        assert isinstance(result, str)
        assert len(result) == 5
