"""Segunda generación del GT de informes: pesos contextuales de un LLM.

El workplan 09 dejó una **línea base determinista**: la masa de juicio de cada
observación repartida ``1/n`` entre las cláusulas del diagnóstico
(:func:`ams_extract.informes.rules.map_findings`). Es reproducible y explicable
en una frase, pero es ciega a lo que el analista enfatiza: «predominancia del
1xRPM […] indicativo de debilidad estructural» y una nota de lubricación de
pasada salen del reparto valiendo lo mismo.

Este módulo aplica un **overlay de juicio** —un fichero versionable, escrito
por un LLM que leyó ``diagnosis_text`` + ``analysis_text`` +
``recommendation_text`` de todo el corpus— sobre los ``*.diaggt.json`` ya
emitidos, y produce la segunda generación: mismos documentos, mismo
``provenance`` (incluido el ``source_sha256`` del PDF), mismos findings, otro
reparto de ``weight`` (workplan 10).

Tres invariantes, todas comprobadas al cargar y al aplicar:

- **El overlay no crea ni borra findings.** Sus claves han de casar exactamente
  con las del documento; si no casan, el overlay está desfasado y no se aplica.
- **Guarda puntuaciones, no pesos.** La aritmética —normalizar y cuantizar a
  10⁻⁶ por el resto mayor— la hace este módulo con la misma función que la
  generación determinista, así que la suma es exactamente 1 por construcción y
  no por confiar en unos decimales escritos a mano.
- **Un peso LLM nunca sube la calidad de un mapeo.** Un re-mapeo (sólo desde
  ``unmapped``, cuando el texto sí identifica el fallo) se emite con
  ``mapping_rule`` nulo —no hay regla GTxxx detrás, es juicio— y
  ``label_quality`` como mucho ``approximate``; nunca ``direct``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

from ams_extract.informes.rules import (
    FAULT_GROUPS,
    UNMAPPED_GROUP,
    UNMAPPED_QUALITY,
    quantize_weights,
)

OVERLAY_KIND = "diaggt_weight_overlay"
"""Literal del campo ``kind`` de un fichero de overlay."""

OVERLAY_SERIES = "0.1."
"""Serie de versiones de overlay que este módulo sabe leer."""

LLM_EXTRACTOR = "informes-gt-weights-llm 0.1.0"
"""Lo que se anota en ``provenance.extractor`` de la generación LLM."""

LLM_EXTRACTION_METHOD = "llm"
"""``extraction_method`` del vocabulario DiagGT que describe esta pasada."""

LLM_LABEL_QUALITIES = frozenset({"approximate", "weak", "group"})
"""Calidades que un re-mapeo por juicio puede declarar.

``direct`` queda fuera a propósito: significa «el origen nombra el modo
canónico», y si lo nombrara habría casado una regla GTxxx. ``unmapped``
también, porque un re-mapeo que deja el finding sin mapear no es un re-mapeo.
"""


class OverlayError(ValueError):
    """El overlay está mal formado o no casa con los documentos."""


def finding_key(finding: dict[str, Any]) -> str:
    """Clave estable de un finding dentro de su observación.

    ``"{fault_group}:{fault_mode}"`` con ``-`` para el modo nulo: la misma
    identidad con la que ``rules.map_findings`` funde findings de la misma
    etiqueta, y legible en el overlay sin descifrar índices posicionales.
    """
    return f"{finding['fault_group']}:{finding['fault_mode'] or '-'}"


@dataclass(frozen=True, slots=True)
class Remap:
    """Re-mapeo de un finding ``unmapped`` que el contexto sí identifica."""

    source: str
    fault_group: str
    fault_mode: str | None
    label_quality: str
    matched_text: str | None
    why: str


@dataclass(frozen=True, slots=True)
class Judgement:
    """El juicio sobre un texto de diagnóstico: puntuaciones y re-mapeos."""

    diagnosis_text: str
    rationale: str
    observations: int
    scores: tuple[tuple[str, Fraction], ...]
    remaps: tuple[Remap, ...] = ()

    @property
    def keys(self) -> list[str]:
        return [key for key, _ in self.scores]

    def weights(self) -> list[float]:
        """Puntuaciones → pesos que suman exactamente 1."""
        total = sum(score for _, score in self.scores)
        return quantize_weights([score / total for _, score in self.scores])


@dataclass(frozen=True, slots=True)
class Overlay:
    """Fichero de overlay cargado y validado."""

    version: str
    extractor: str
    extraction_method: str
    judgements: dict[str, Judgement]


@dataclass(slots=True)
class ApplyReport:
    """Lo que la pasada tocó, para que el CLI lo cuente."""

    documents: int = 0
    observations: int = 0
    with_findings: int = 0
    judged: int = 0
    reweighted: int = 0
    remapped: int = 0
    single_finding: int = 0
    used: set[str] = field(default_factory=set[str])

    def unused(self, overlay: Overlay) -> list[str]:
        """Juicios del overlay que ningún documento reclamó (overlay desfasado)."""
        return sorted(set(overlay.judgements) - self.used)


def _remap(raw: dict[str, Any], text: str) -> Remap:
    source: str = str(raw.get("from"))
    target: dict[str, Any] = raw.get("to") or {}
    if source != f"{UNMAPPED_GROUP}:-":
        raise OverlayError(
            f"overlay {text[:60]!r}: un re-mapeo sale de un finding "
            f"{UNMAPPED_QUALITY!r}, no de {source!r}. Los findings mapeados los "
            "produjo una regla GTxxx y el juicio no los reescribe."
        )
    group: str | None = target.get("fault_group")
    mode: str | None = target.get("fault_mode")
    quality: str | None = target.get("label_quality")
    matched: str | None = target.get("matched_text")
    if group not in FAULT_GROUPS or group == UNMAPPED_GROUP:
        raise OverlayError(
            f"overlay {text[:60]!r}: fault_group {group!r} no es un grupo "
            "concreto del vocabulario DiagGT."
        )
    if quality not in LLM_LABEL_QUALITIES:
        raise OverlayError(
            f"overlay {text[:60]!r}: label_quality {quality!r} fuera de "
            f"{sorted(LLM_LABEL_QUALITIES)}. Un peso LLM no sube la calidad de "
            "un mapeo: si el origen nombrara el modo, habría casado una regla."
        )
    if (quality == "group") != (mode is None):
        raise OverlayError(
            f"overlay {text[:60]!r}: label_quality={quality!r} y "
            f"fault_mode={mode!r} se contradicen (group exige modo nulo, el "
            "resto lo exige presente)."
        )
    return Remap(
        source=source,
        fault_group=group,
        fault_mode=mode,
        label_quality=quality,
        matched_text=matched,
        why=str(raw.get("why", "")),
    )


def load_overlay(path: Path) -> Overlay:
    """Lee y valida un overlay de pesos."""
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("kind") != OVERLAY_KIND:
        raise OverlayError(f"{path}: kind {raw.get('kind')!r} != {OVERLAY_KIND!r}")
    version = str(raw.get("$overlay_version", ""))
    if not version.startswith(OVERLAY_SERIES):
        raise OverlayError(
            f"{path}: versión de overlay {version!r} fuera de la serie {OVERLAY_SERIES}x"
        )
    judgements: dict[str, Judgement] = {}
    entries: list[dict[str, Any]] = raw.get("judgements") or []
    for entry in entries:
        text: str = entry["diagnosis_text"]
        if text in judgements:
            raise OverlayError(f"{path}: dos juicios para el mismo texto {text[:60]!r}")
        scores: list[tuple[str, Fraction]] = []
        items: list[dict[str, Any]] = entry["findings"]
        for item in items:
            score = Fraction(str(item["score"]))
            if score <= 0:
                raise OverlayError(
                    f"overlay {text[:60]!r}: puntuación {item['score']!r} para "
                    f"{item['finding']!r}. Un finding sin masa no se emite con "
                    "peso cero, se deja fuera del reparto."
                )
            scores.append((item["finding"], score))
        raw_remaps: list[dict[str, Any]] = entry.get("remap") or []
        remaps = tuple(_remap(item, text) for item in raw_remaps)
        known = {key for key, _ in scores}
        for remap in remaps:
            if remap.source not in known:
                raise OverlayError(
                    f"overlay {text[:60]!r}: re-mapeo desde {remap.source!r}, "
                    "que no está entre los findings puntuados."
                )
        judgements[text] = Judgement(
            diagnosis_text=text,
            rationale=entry.get("rationale", ""),
            observations=int(entry.get("observations", 0)),
            scores=tuple(scores),
            remaps=remaps,
        )
    return Overlay(
        version=version,
        extractor=str(raw.get("extractor") or LLM_EXTRACTOR),
        extraction_method=str(raw.get("extraction_method") or LLM_EXTRACTION_METHOD),
        judgements=judgements,
    )


def _apply_observation(observation: dict[str, Any], judgement: Judgement) -> int:
    """Reescribe los findings de una observación. Devuelve los re-mapeados."""
    findings = observation["findings"]
    keys = [finding_key(finding) for finding in findings]
    if keys != judgement.keys:
        raise OverlayError(
            f"observación {observation['observation_id']!r}: el documento trae "
            f"{keys} y el overlay puntúa {judgement.keys}. El overlay está "
            "desfasado respecto al extractor que emitió estos documentos."
        )
    weights = judgement.weights()
    remaps = {remap.source: remap for remap in judgement.remaps}
    remapped = 0
    for finding, key, weight in zip(findings, keys, weights, strict=True):
        finding["weight"] = weight
        remap = remaps.get(key)
        if remap is None:
            continue
        finding["fault_group"] = remap.fault_group
        finding["fault_mode"] = remap.fault_mode
        finding["label_quality"] = remap.label_quality
        finding["mapping_rule"] = None  # juicio, no regla GTxxx
        finding["matched_text"] = remap.matched_text
        remapped += 1
    return remapped


def apply_overlay(
    document: dict[str, Any], overlay: Overlay, report: ApplyReport
) -> dict[str, Any]:
    """Aplica el overlay a un documento DiagGT y devuelve la generación LLM.

    El documento se copia en profundidad: la generación determinista de entrada
    no se toca. Fuera de ``findings[*].weight`` (y de los re-mapeos declarados)
    lo único que cambia es ``provenance.extractor``, ``extracted_at`` y
    ``extraction_method`` — el ``source_sha256`` del PDF sigue siendo el mismo y
    sigue siendo verificable.
    """
    result = json.loads(json.dumps(document))
    report.documents += 1
    for observation in result["observations"]:
        report.observations += 1
        findings = observation["findings"]
        if not findings:
            continue
        report.with_findings += 1
        judgement = overlay.judgements.get(observation["diagnosis_text"] or "")
        if judgement is None:
            if len(findings) > 1:
                raise OverlayError(
                    f"observación {observation['observation_id']!r}: "
                    f"{len(findings)} findings y ningún juicio en el overlay. El "
                    "reparto de una observación se juzga entero o no se toca."
                )
            report.single_finding += 1
            findings[0]["weight"] = 1.0
            continue
        report.used.add(judgement.diagnosis_text)
        report.judged += 1
        report.reweighted += len(findings)
        report.remapped += _apply_observation(observation, judgement)
    provenance = result["provenance"]
    provenance["extractor"] = overlay.extractor
    provenance["extraction_method"] = overlay.extraction_method
    provenance["extracted_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    return result
