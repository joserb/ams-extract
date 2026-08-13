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
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

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


EvidenceStatus = Literal["derived", "ambiguous", "absent"]


@dataclass(frozen=True, slots=True)
class EvidenceHit:
    """One literal name fragment recognized by a stable parser rule."""

    rule: str
    token: str
    value: str


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    """Result and trace for one field derived from a point name.

    ``value`` is intentionally absent when two different values matched.  A
    caller can therefore distinguish an undeclared field from contradictory
    text without choosing a winner by regex order.
    """

    value: str | None
    status: EvidenceStatus
    hits: tuple[EvidenceHit, ...] = ()


@dataclass(frozen=True, slots=True)
class PointNameEvidence:
    """All deterministic, non-emitted evidence extracted from a point name."""

    original_name: str
    normalized_name: str
    location: FieldEvidence
    direction: FieldEvidence
    component_hint: FieldEvidence
    acquisition_hint: FieldEvidence

    @property
    def placement(self) -> PointPlacement:
        """Compatibility projection used by today's VibFrame writer."""
        return PointPlacement(self.location.value, self.direction.value)


@dataclass(frozen=True, slots=True)
class DirectionProposal:
    """A non-emitted direction proposed from one unambiguous sibling."""

    point_name: str
    direction: str
    sibling_name: str
    rule: str = "sibling.same-acquisition-base-v1"


_COMPONENT_TOKENS: Mapping[str, str] = {
    "motor": "motor",
    "bomba": "pump",
    "reductor": "gearbox",
    "reductora": "gearbox",
    "ventilador": "fan",
    "centrifuga": "centrifuge",
    "campana": "bell",
}

_ACQUISITION_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\bpeakv\w*\b"), "acquisition.peakvue-v1", "peakvue"),
    (
        re.compile(r"\balta\s+frecuencia\b|(?:\(|\[)\s*hf\s*(?:\)|\])"),
        "acquisition.high-frequency-v1",
        "high_frequency",
    ),
    (
        re.compile(r"\balta\s+resolucion\b|(?:\(|\[)\s*hr\s*(?:\)|\])"),
        "acquisition.high-resolution-v1",
        "high_resolution",
    ),
    (
        re.compile(r"(?:\(|\[)\s*p\s*(?:\)|\])"),
        "acquisition.parenthesized-p-v1",
        "peakvue",
    ),
    (
        re.compile(r"\bconsumo\s+intensidad\b"),
        "acquisition.current-v1",
        "electrical_current",
    ),
)

_ACQUISITION_SUFFIX = re.compile(
    r"(?:\s+peakv\w*(?:\s+\d+\s*hz)?"
    r"|\s+alta\s+frecuencia(?:\s+\(\s*hf\s*\))?"
    r"|\s+alta\s+resolucion(?:\s+\(\s*hr\s*\))?"
    r"|\s*(?:\(|\[)\s*(?:p|hf|hr)\s*(?:\)|\])(?:\s+\d+\s*hz)?)\s*$"
)


def _normalize(name: str) -> str:
    """Return ``name`` lowercased and stripped of diacritics."""
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _tokens(normalized: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT.split(normalized) if t]


def normalize_point_name(name: str) -> str:
    """Canonical comparison form; the original name remains the authority."""
    return " ".join(_tokens(_normalize(name)))


def _field_evidence(hits: Iterable[EvidenceHit]) -> FieldEvidence:
    ordered = tuple(sorted(set(hits), key=lambda hit: (hit.rule, hit.token, hit.value)))
    values = {hit.value for hit in ordered}
    if not values:
        return FieldEvidence(None, "absent")
    if len(values) > 1:
        return FieldEvidence(None, "ambiguous", ordered)
    return FieldEvidence(next(iter(values)), "derived", ordered)


def _location_evidence(normalized: str) -> FieldEvidence:
    hits = [
        EvidenceHit(f"location.token-{token}-v1", token, _SIDE_TOKENS[token])
        for token in _tokens(normalized)
        if token in _SIDE_TOKENS
    ]
    for pattern, rule, value in (
        (_SIDE_NDE_PHRASE, "location.lado-nde-v1", LOCATION_NDE),
        (_SIDE_DE_PHRASE, "location.lado-de-v1", LOCATION_DE),
    ):
        hits.extend(
            EvidenceHit(rule, match.group(0), value) for match in pattern.finditer(normalized)
        )
    return _field_evidence(hits)


def _direction_evidence(normalized: str) -> FieldEvidence:
    hits: list[EvidenceHit] = []
    for token in _tokens(normalized):
        for prefix, code in _DIRECTION_PREFIXES:
            if token.startswith(prefix):
                hits.append(EvidenceHit(f"direction.{prefix}-v1", token, code))
    return _field_evidence(hits)


def _component_evidence(normalized: str) -> FieldEvidence:
    hits = [
        EvidenceHit(f"component.token-{token}-v1", token, _COMPONENT_TOKENS[token])
        for token in _tokens(normalized)
        if token in _COMPONENT_TOKENS
    ]
    return _field_evidence(hits)


def _acquisition_evidence(normalized: str) -> FieldEvidence:
    hits: list[EvidenceHit] = []
    for pattern, rule, value in _ACQUISITION_PATTERNS:
        hits.extend(
            EvidenceHit(rule, match.group(0), value) for match in pattern.finditer(normalized)
        )
    return _field_evidence(hits)


def point_name_evidence(name: str) -> PointNameEvidence:
    """Parse name evidence without promoting hints to the VibFrame contract."""
    normalized = _normalize(name)
    return PointNameEvidence(
        original_name=name,
        normalized_name=normalize_point_name(name),
        location=_location_evidence(normalized),
        direction=_direction_evidence(normalized),
        component_hint=_component_evidence(normalized),
        acquisition_hint=_acquisition_evidence(normalized),
    )


def point_location(name: str) -> str | None:
    """Return ``"DE"``/``"NDE"`` for ``name``, or ``None`` if undeclared.

    Evidence from the standalone abbreviations and from the ``Lado …``
    phrases is pooled; disagreement (a name claiming both sides) resolves to
    ``None`` rather than to an arbitrary winner.
    """
    return point_name_evidence(name).location.value


def point_direction(name: str) -> str | None:
    """Return ``"H"``/``"V"``/``"A"`` for ``name``, or ``None`` if undeclared.

    Two different directions in one name (never seen in Bunge, but cheap to
    guard) resolve to ``None``.
    """
    return point_name_evidence(name).direction.value


def parse_point_name(name: str) -> PointPlacement:
    """Return the :class:`PointPlacement` declared by an AMS point name."""
    return point_name_evidence(name).placement


def acquisition_base_name(name: str) -> str:
    """Remove only a closed acquisition suffix, for conservative matching."""
    normalized = _normalize(name).strip()
    previous = None
    while normalized != previous:
        previous = normalized
        normalized = _ACQUISITION_SUFFIX.sub("", normalized).strip()
    return normalize_point_name(normalized)


def _sibling_position_key(name: str) -> str:
    """Comparison key after separating placement and acquisition evidence."""
    normalized = _normalize(acquisition_base_name(name))
    normalized = _SIDE_NDE_PHRASE.sub(" ", normalized)
    normalized = _SIDE_DE_PHRASE.sub(" ", normalized)
    kept: list[str] = []
    for token in _tokens(normalized):
        if token in _SIDE_TOKENS:
            continue
        if any(token.startswith(prefix) for prefix, _ in _DIRECTION_PREFIXES):
            continue
        kept.append(token)
    return " ".join(kept)


def propose_sibling_directions(point_names: Sequence[str]) -> tuple[DirectionProposal, ...]:
    """Report uniquely supported sibling directions; never mutate/export them.

    Both names must declare the same side and one unambiguous component.  The
    remaining literal text must match after separating that placement
    evidence and removing a closed acquisition suffix.  A target with written
    direction or zero/multiple candidate directions is omitted.
    """
    parsed: list[tuple[str, PointNameEvidence]] = [
        (name, point_name_evidence(name)) for name in point_names
    ]
    proposals: list[DirectionProposal] = []
    for point_name, evidence in parsed:
        if evidence.direction.value is not None:
            continue
        if evidence.location.value is None or evidence.component_hint.value is None:
            continue
        base = _sibling_position_key(point_name)
        candidates = [
            (candidate_name, candidate.direction.value)
            for candidate_name, candidate in parsed
            if candidate_name != point_name
            and candidate.direction.value is not None
            and candidate.location.value == evidence.location.value
            and candidate.component_hint.value == evidence.component_hint.value
            and _sibling_position_key(candidate_name) == base
        ]
        directions = {direction for _, direction in candidates}
        if len(candidates) == 1 and len(directions) == 1:
            sibling_name, direction = candidates[0]
            assert direction is not None
            proposals.append(DirectionProposal(point_name, direction, sibling_name))
    return tuple(proposals)


def audit_name_corpus(entries: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Build a deterministic, aggregate audit from the distilled name corpus."""
    fields = ("location", "direction", "component_hint", "acquisition_hint")
    statuses: dict[str, Counter[str]] = {field: Counter() for field in fields}
    values: dict[str, Counter[str]] = {field: Counter() for field in fields}
    rules: Counter[str] = Counter()
    total_points = 0
    for entry in entries:
        name_value = entry["name"]
        points_value = entry["points"]
        if not isinstance(name_value, str) or not isinstance(points_value, int):
            raise TypeError("each corpus entry needs a string name and integer points")
        name = name_value
        points = points_value
        total_points += points
        evidence = point_name_evidence(name)
        evidence_fields: tuple[tuple[str, FieldEvidence], ...] = (
            ("location", evidence.location),
            ("direction", evidence.direction),
            ("component_hint", evidence.component_hint),
            ("acquisition_hint", evidence.acquisition_hint),
        )
        for field, result in evidence_fields:
            statuses[field][result.status] += points
            if result.value is not None:
                values[field][result.value] += points
            for hit in result.hits:
                rules[hit.rule] += points
    return {
        "schema_version": 1,
        "source": "tests/fixtures/bunge_point_names.json",
        "total_points": total_points,
        "distinct_names": len(entries),
        "fields": {
            field: {
                "status": dict(sorted(statuses[field].items())),
                "values": dict(sorted(values[field].items())),
            }
            for field in fields
        },
        "rule_hits_weighted_by_points": dict(sorted(rules.items())),
        "limitations": [
            "component_hint and acquisition_hint are internal report-only candidates",
            "sensor, speed_source and binary channel kind require AMS golds",
            "no inferred sibling direction is emitted to machine.json",
        ],
    }
