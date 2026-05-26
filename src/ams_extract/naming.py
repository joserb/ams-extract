"""Sanitization of RBM names to filesystem-safe identifiers.

Names in the .rbm file may contain accented characters, spaces, slashes,
parentheses and other characters that don't play nicely with file paths or
Hive-partition values. We map them deterministically to ASCII identifiers
made of ``[A-Za-z0-9_]``, truncated to 64 chars.

Collisions after sanitization are resolved with a numeric suffix
``_1``, ``_2``, … assigned in the order ``sanitize`` is called. This makes
the mapping deterministic for a given input order; for fully deterministic
output across runs, callers should iterate names in a canonical order
(e.g. record-number then slot-index).
"""

from __future__ import annotations

import re
import unicodedata

MAX_LENGTH = 64
"""Maximum length of a sanitized name."""

_NON_WORD = re.compile(r"[^A-Za-z0-9]+")
_REPEATED_UNDERSCORE = re.compile(r"_+")


def _basic_sanitize(name: str) -> str:
    """Return ``name`` mapped to an ASCII identifier, without collision handling."""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = decomposed.encode("ascii", errors="ignore").decode("ascii")
    replaced = _NON_WORD.sub("_", ascii_only)
    collapsed = _REPEATED_UNDERSCORE.sub("_", replaced).strip("_")
    truncated = collapsed[:MAX_LENGTH]
    return truncated or "unnamed"


class NameSanitizer:
    """Stateful sanitizer that guarantees output uniqueness via numeric suffix.

    Example:
        >>> s = NameSanitizer()
        >>> s.sanitize("CONTRA INCENDIOS")
        'CONTRA_INCENDIOS'
        >>> s.sanitize("CONTRA INCENDIOS")
        'CONTRA_INCENDIOS_1'
        >>> s.sanitize("EXTRACCIÓN")
        'EXTRACCION'
    """

    def __init__(self) -> None:
        self._used: set[str] = set()

    def sanitize(self, name: str) -> str:
        """Return a sanitized version of ``name`` unique within this sanitizer."""
        base = _basic_sanitize(name)
        candidate = base
        suffix = 1
        while candidate in self._used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        self._used.add(candidate)
        return candidate


def sanitize(name: str) -> str:
    """Sanitize ``name`` without collision tracking. See :class:`NameSanitizer`."""
    return _basic_sanitize(name)
