"""Placement (``location`` / ``direction``) read off an AMS point name.

AMS stores no structured placement for a point: the ``vdpm`` record keeps a
single 32-byte ``long_name`` (FORMAT §3.1) and that name is where the analyst
wrote everything — component, bearing side and measurement direction::

    MOTOR LOA HORIZONTAL          -> location NDE, direction H
    BOMBA LA VERTICAL PEAKVUE     -> location DE,  direction V
    Reductor Lado Libre Peakvue   -> location NDE, direction None
    Eje Entrada Vertical          -> location None, direction V

This module turns that convention into the two optional VibFrame ``PointDoc``
fields. The component is deliberately *not* extracted: the contract has no
field for it (it belongs to the kinematic ``definition``, still absent for
AMS) and the full name is emitted anyway.

Rules are conservative by construction: a token has to appear literally for
its code to be produced, contradictory evidence yields ``None``, and a name
that simply does not declare a side or a direction stays ``None`` instead of
being guessed. On the Bunge Cartagena database (5 203 points, 232 distinct
names) they resolve `location` for 98.2 % and `direction` for 81.1 %; what is
left out is names that carry no such information at all (``Campana Peakvue``,
``1º Eje Rodam Sup Peakv 1000Hz``).

Vocabulary observed in that database (Spanish, mixed case, freely abbreviated
because the name is capped at 32 bytes):

- ``LA`` = *lado acople* (coupled side) -> ``DE``;
  ``LOA`` = *lado opuesto acople* and ``LCA`` = *lado contrario acople*
  -> ``NDE``. ``LCA`` and ``LOA`` name the same bearing: machines using both
  (``CENTRIFUGA LOA VERTICAL`` + ``CENTRIFUGA LCA VERTICAL (HF)``,
  ``Reductor LOA Horiz`` + ``Reductor LCA Horiz (P)``) pair a velocity point
  with the acceleration variant of the very same location.
- ``Lado Acople`` / ``Lado Motor`` -> ``DE`` (the end the drive comes in
  through); ``Lado Libre`` / ``Lado Op(uesto) Motor`` / ``Lado Contrario``
  -> ``NDE``.
- ``HORIZONTAL`` / ``VERTICAL`` / ``AXIAL`` -> ``H`` / ``V`` / ``A``, matched
  by prefix so the truncations the 32-byte field forces (``Horiz``, ``Vert``,
  ``Horizont``, ``Verti``) resolve too.

Suffixes naming the acquisition rather than the placement (``PEAKVUE``,
``(P)``, ``(HF)``, ``[HF]``, ``ALTA FRECUENCIA``, ``(HR)``) carry no
direction and are simply not matched.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

LOCATION_DE = "DE"
"""Drive end — the coupled side (``LA``, ``Lado Acople``, ``Lado Motor``)."""

LOCATION_NDE = "NDE"
"""Non-drive end (``LOA``, ``LCA``, ``Lado Libre``, ``Lado Op Motor``)."""

DIRECTION_H = "H"
DIRECTION_V = "V"
DIRECTION_A = "A"

_TOKEN_SPLIT = re.compile(r"[^0-9A-Za-z]+")

_SIDE_TOKENS = {
    "la": LOCATION_DE,
    "loa": LOCATION_NDE,
    "lca": LOCATION_NDE,
}
"""Standalone abbreviations of the bearing side."""

_SIDE_NDE_PHRASE = re.compile(r"\blad[o]?\s+(?:op\w*|contrari\w*|libre)\b")
"""``Lado Libre``, ``Lado Op Motor``, ``Lad Op Mot``, ``Lado Contrario``."""

_SIDE_DE_PHRASE = re.compile(r"\blad[o]?\s+(?:acopl\w*|motor?)\b")
"""``Lado Acople``, ``Lado Motor``, ``Lad Mot`` (checked after the NDE one)."""

_DIRECTION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("horiz", DIRECTION_H),
    ("vert", DIRECTION_V),
    ("axial", DIRECTION_A),
)
"""Prefixes of the direction word, longest form first in each family."""


@dataclass(frozen=True, slots=True)
class PointPlacement:
    """Where a point measures, as far as its name declares it.

    Both fields are ``None`` when the name carries no (or contradictory)
    evidence; they map one-to-one onto ``PointDoc.location`` and
    ``PointDoc.direction``.
    """

    location: str | None = None
    direction: str | None = None


def _normalize(name: str) -> str:
    """Return ``name`` lowercased and stripped of diacritics."""
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _tokens(normalized: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT.split(normalized) if t]


def point_location(name: str) -> str | None:
    """Return ``"DE"``/``"NDE"`` for ``name``, or ``None`` if undeclared.

    Evidence from the standalone abbreviations and from the ``Lado …``
    phrases is pooled; disagreement (a name claiming both sides) resolves to
    ``None`` rather than to an arbitrary winner.
    """
    normalized = _normalize(name)
    codes = {_SIDE_TOKENS[t] for t in _tokens(normalized) if t in _SIDE_TOKENS}
    if _SIDE_NDE_PHRASE.search(normalized):
        codes.add(LOCATION_NDE)
    elif _SIDE_DE_PHRASE.search(normalized):
        codes.add(LOCATION_DE)
    if len(codes) != 1:
        return None
    return codes.pop()


def point_direction(name: str) -> str | None:
    """Return ``"H"``/``"V"``/``"A"`` for ``name``, or ``None`` if undeclared.

    Two different directions in one name (never seen in Bunge, but cheap to
    guard) resolve to ``None``.
    """
    normalized = _normalize(name)
    codes = {
        code
        for token in _tokens(normalized)
        for prefix, code in _DIRECTION_PREFIXES
        if token.startswith(prefix)
    }
    if len(codes) != 1:
        return None
    return codes.pop()


def parse_point_name(name: str) -> PointPlacement:
    """Return the :class:`PointPlacement` declared by an AMS point name."""
    return PointPlacement(
        location=point_location(name),
        direction=point_direction(name),
    )
