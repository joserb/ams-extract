"""String decoding helpers for the .rbm binary format.

RBMware databases were authored on Windows (cp1252) and, on older CSI/DOS
installations, in cp850. We decode optimistically with cp1252, fall back to
cp850 when cp1252 raises, and finally fall back to latin-1 with replacement
so we never raise from string decoding.

Fields in the file are typically padded with ASCII spaces (``0x20``) and/or
NULs (``0x00``) to a fixed width; ``strip_padding`` removes both.
"""

from __future__ import annotations

PRIMARY_ENCODING = "cp1252"
DOS_FALLBACK_ENCODING = "cp850"


def strip_padding(raw: bytes) -> bytes:
    """Strip trailing NUL and space padding from a fixed-width byte field.

    Args:
        raw: Raw bytes from a fixed-width field.

    Returns:
        ``raw`` with trailing ``0x00`` and ``0x20`` bytes removed.
    """
    return raw.rstrip(b"\x00 ")


def decode_string(raw: bytes) -> str:
    """Decode a fixed-width string field, stripping padding.

    Tries cp1252 first, then cp850, then latin-1 with replacement. Padding
    (NULs and trailing spaces) is removed before decoding.

    Args:
        raw: Raw bytes from a fixed-width string field.

    Returns:
        The decoded, padding-stripped string.
    """
    stripped = strip_padding(raw)
    if not stripped:
        return ""
    try:
        return stripped.decode(PRIMARY_ENCODING)
    except UnicodeDecodeError:
        pass
    try:
        return stripped.decode(DOS_FALLBACK_ENCODING)
    except UnicodeDecodeError:
        return stripped.decode("latin-1", errors="replace")
