"""Vocabularios DiagGT y mapeo de la prosa del analista a findings canónicos.

Capa sin dependencias fuera de stdlib **a propósito**: es la que cambia cuando
cambia el vocabulario del analista y la que los tests de regresión ejercitan
sin necesidad de los PDFs (workplan 09).

El mapeo replica el patrón del mapper de métricas —``canonical_metric`` /
``proxy_quality`` / ``mapping_rule``—: cada etiqueta lleva su
``label_quality`` y la regla ``GTxxx`` que la produjo, el texto original nunca
se pierde y lo que ninguna regla reconoce se declara ``unmapped`` en vez de
callarse (spec ``docs/GROUND_TRUTH.md`` §2.5, §3.3).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

SCHEMA_VERSION = "0.1.5"
"""Versión del esquema DiagGT que declara el documento emitido.

0.1.5 añade ``weight`` al finding. Hasta la adopción en el paquete el script
decía ``"0.1.0"`` mientras emitía 0.1.4: el desalineado era un bug de la
constante, no del contenido.
"""

WEIGHT_DECIMALS = 6
"""Decimales del ``weight`` emitido.

Un reparto entre cláusulas da fracciones periódicas (1/3, 1/6): se cuantizan a
10⁻⁶ para que el JSON sea estable y la suma no se pase de 1 por redondeo.
"""

WEIGHT_UNITS = 10**WEIGHT_DECIMALS

# ---------------------------------------------------------------------------
# Estado canónico
# ---------------------------------------------------------------------------

STATUS_MAP: dict[str, tuple[str, int | None]] = {
    "bueno": ("OK", 0),
    "seguimiento": ("WATCH", 1),
    "vigilar": ("WATCH", 1),
    "alerta": ("ALERT", 2),
    "peligro": ("DANGER", 3),
    "parada": ("STOPPED", None),
    "no medida": ("NOT_MEASURED", None),
    "fuera de servicio": ("OUT_OF_SERVICE", None),
}
"""Etiqueta del informe → ``(status, alarm)``.

``alarm`` replica la escala int8 de ``trends.parquet`` de VibFrame (0 normal,
1 vigilancia, 2 alerta, 3 peligro).
"""

MODALITY_MAP: dict[str, str] = {
    "Vibraciones": "vibration",
    "Inspección visual": "visual_inspection",
    "Inspeccion visual": "visual_inspection",
    "Termografía": "thermography",
    "Ultrasonidos": "ultrasound",
}

# ---------------------------------------------------------------------------
# Reglas de mapeo GTxxx (spec §3.3)
# ---------------------------------------------------------------------------

FINDING_RULES: tuple[tuple[str, str, str | None, str, str], ...] = (
    ("GT001v2", r"desequilibri|desbalance", "IMBALANCE", "IMBALANCE", "direct"),
    ("GT002", r"desalineac", None, "MISALIGNMENT", "group"),
    ("GT003", r"holguras? rotacional", "LOOSENESS", "LOOSENESS", "direct"),
    ("GT004v2", r"holgura|huelgo", "LOOSENESS", "LOOSENESS", "approximate"),
    ("GT005", r"debilidad estructural|debilidad en", "LOOSENESS", "STRUCTURE", "approximate"),
    ("GT006", r"resonancia", "RESONANCE", "STRUCTURE", "direct"),
    ("GT007", r"pista externa|bpfo", "BEARING_OUTER", "BEARING", "direct"),
    ("GT008", r"pista interna|bpfi", "BEARING_INNER", "BEARING", "direct"),
    ("GT009", r"elementos? rodantes?|bsf", "BEARING_BALL", "BEARING", "direct"),
    ("GT010", r"jaula|ftf", "BEARING_CAGE", "BEARING", "direct"),
    ("GT011v2", r"lubricaci", "BEARING_LUBRICATION", "LUBRICATION", "direct"),
    (
        "GT012",
        r"deterioro .*rodamiento|rodamiento.*deterior|fallo .*rodamiento|"
        r"da[ñn]o .*rodamiento|desgaste .*rodamiento",
        None,
        "BEARING",
        "group",
    ),
    ("GT013", r"el[eé]ctric", "ELECTRICAL_ROTOR", "ELECTRICAL", "approximate"),
    ("GT014", r"engran|gmf", "GEAR_WEAR", "GEAR", "approximate"),
    ("GT015", r"cavitaci", "CAVITATION", "FLOW", "direct"),
    ("GT016", r"correa", "BELT_FAULT", "BELT", "direct"),
    ("GT017", r"[aá]labe|rodete|paso de paleta|vpf|impulsor", "BROKEN_BLADE", "FLOW", "weak"),
    ("GT018", r"rozamiento", None, "OTHER", "group"),
    ("GT019", r"anclaje|bancada|perno", "LOOSENESS", "STRUCTURE", "approximate"),
    # v0.2.0 (auditoría 2026-07-28 §3.8): familias recurrentes que salían
    # UNMAPPED. Ver GROUND_TRUTH.md §3.3.
    (
        "GT020",
        r"distorsi[oó]n arm[oó]nica|variador de frecuencia|calidad de la energ[ií]a",
        None,
        "ELECTRICAL",
        "group",
    ),
    ("GT021v2", r"excentricidad", "ELECTRICAL_ROTOR", "ELECTRICAL", "approximate"),
    (
        "GT022",
        r"excitaci[oó]n as[ií]ncrona|arm[oó]nicos as[ií]ncronos|"
        r"traza as[ií]ncrona|excitaci[oó]n .{0,30}as[ií]ncrona",
        None,
        "BEARING",
        "group",
    ),
    (
        "GT023",
        r"falta de rigidez|holgura estructural|pata coja",
        "LOOSENESS",
        "STRUCTURE",
        "approximate",
    ),
    (
        "GT024",
        r"ruidos? mec[aá]nic|ruido de origen el[eé]ctric|cabece[ao]|"
        r"fuga de|ruido ultras[oó]nic",
        None,
        "OTHER",
        "group",
    ),
    # v0.4.0 (workplan 11): la excentricidad de una polea es de la transmisión,
    # no del rotor eléctrico. El grupo BELT sólo tiene BELT_FAULT en el
    # catálogo `FaultMode` y el fallo no es la correa, así que se declara el
    # grupo y no se fuerza el modo (§2.5).
    (
        "GT025",
        r"excentricidad\s+(?:en|de|del)\s+(?:la\s+)?polea|polea\s+exc[eé]ntrica",
        None,
        "BELT",
        "group",
    ),
    (
        "GT026",
        r"(?:suciedad|desgaste|deterioro).{0,35}v[aá]lvula|"
        r"v[aá]lvula.{0,35}(?:sucia|suciedad|desgaste|deterioro)",
        None,
        "OTHER",
        "group",
    ),
    (
        "GT027",
        r"deterioro\s+(?:en|del?)\s+(?:el\s+)?acoplamiento",
        None,
        "OTHER",
        "group",
    ),
    (
        "GT028",
        r"bandas? laterales?.{0,80}barras?.{0,20}(?:rotas?|sueltas?)|"
        r"barras?.{0,20}(?:rotas?|sueltas?)",
        "ELECTRICAL_ROTOR",
        "ELECTRICAL",
        "direct",
    ),
    (
        "GT029",
        r"ruido\s+(?:en|del?)\s+(?:el\s+)?acople",
        None,
        "OTHER",
        "group",
    ),
)
"""``(rule_id, patrón, fault_mode|None, fault_group, label_quality)``.

``fault_group`` es el vocabulario propio de DiagGT (superconjunto agrupado de
``FaultMode``) para diagnósticos que el informe no concreta. Invariante del
modelo normativo: ``label_quality="group"`` exige ``fault_mode`` nulo; las
demás calidades lo exigen no nulo.

El sufijo ``vN`` del id versiona la **lectura** de una regla, como los
``IRxxx`` del t8-mapper: cambiarle la lógica obliga a versionar el id para que
un finding ya emitido siga diciendo qué regla lo produjo. En 0.4.0 (workplan
11) se versionaron las tres que el corpus desmentía: ``GT001v2`` (añade el
sinónimo «desbalanceo»), ``GT011v2`` y ``GT021v2`` (ganan veto, ver
:data:`RULE_VETOES`). En 0.5.0 ``GT004v2`` incorpora el sinónimo observado
«huelgo»; ``GT026`` a ``GT029`` son familias nuevas sustentadas por el censo
0.4.0 (válvula, acoplamiento, barras del rotor y ruido en el acople).
"""

RULE_VETOES: dict[str, re.Pattern[str]] = {
    "GT011v2": re.compile(
        r"\bbuen(?:a|as|os)?\s+(?:estado\s+de\s+)?lubricaci"
        # \b delante: «Ineficiente/Deficiente lubricación» son fallos, y sin él
        # el veto los leía como su contrario.
        r"|\b(?:correcta|adecuada|eficiente|[oó]ptima)s?\s+lubricaci"
        r"|lubricaci\w*\s+(?:\S+\s+){0,3}?"
        r"(?:en\s+buen\s+estado|\bcorrecta\b|\badecuada\b|\beficiente\b|\b[oó]ptima\b)"
        r"|(?:sin|no\s+se\s+aprecian?)\s+(?:\S+\s+){0,4}?"
        r"(?:problemas?|indicios?|s[ií]ntomas?|deficiencias?)\s+(?:\S+\s+){0,2}?lubricaci",
    ),
    "GT021v2": re.compile(
        r"excentricidad\s+(?:en|de|del)\s+(?:la\s+)?polea|polea\s+exc[eé]ntrica",
    ),
}
"""Contextos en los que una regla **no** dispara, por ``rule_id``.

Un patrón de regla es una palabra suelta y el analista escribe frases: hay
cláusulas donde la palabra aparece afirmando justo lo contrario de lo que la
regla lee. El veto es la forma honesta de decirlo — la regla se calla y la
cláusula pasa a lo que no cubre ninguna regla, en vez de emitir un fallo que
el texto niega.

- **GT011v2**: «Se aprecia **buen estado de lubricación** de los rodamientos
  del conjunto» no es un fallo de lubricación. El veto cubre además las
  fórmulas afirmativas y negadas del mismo juicio («correcta lubricación»,
  «sin problemas de lubricación»); «*mejorable*» y «*mejor* estado de
  lubricación» quedan fuera a propósito: la primera es un fallo y la segunda,
  una nota de evolución que el reparto de pesos ya matiza.
- **GT021v2**: «excentricidad **en polea**» es mecánica, de la transmisión, y
  la recoge :data:`GT025 <FINDING_RULES>`; llevarla a ``ELECTRICAL_ROTOR``
  era leer «excentricidad» sin mirar de qué.

Los vetos son **por cláusula**, la misma unidad en la que se aplican las
reglas: una cláusula que niega la lubricación y otra que la afirma son dos
cláusulas, y cada una se lee sola.
"""

UNMAPPED_GROUP = "UNMAPPED"
UNMAPPED_QUALITY = "unmapped"

FAULT_GROUPS: frozenset[str] = frozenset(
    {
        "IMBALANCE",
        "MISALIGNMENT",
        "LOOSENESS",
        "BEARING",
        "LUBRICATION",
        "GEAR",
        "ELECTRICAL",
        "FLOW",
        "BELT",
        "STRUCTURE",
        "OTHER",
        UNMAPPED_GROUP,
    }
)
"""Vocabulario ``FaultGroup`` de DiagGT, replicado del contrato (ADR-0009).

Las :data:`FINDING_RULES` sólo usan los grupos que el corpus necesita; esta
constante existe para validar grupos que no salen de una regla — hoy, los
re-mapeos por juicio de ``informes.overlay``.
"""

# ---------------------------------------------------------------------------
# Textos de estado (spec §3.3): producen findings=[]
# ---------------------------------------------------------------------------

HEALTHY_RE = re.compile(
    r"(m[aá]quina|equipo|conjunto|rodamientos?|motor|reductor)\s+"
    r"(?:\S+\s+){0,3}?en buen estado"
    # «Se aprecia buen estado de lubricación de los rodamientos del conjunto»
    # declara una parte sana; sin esto la cláusula era masa de juicio y GT011
    # la leía como fallo de lubricación (workplan 11).
    r"|\bbuen(?:a|as|os)?\s+(?:estado\s+de\s+)?lubricaci"
    r"|\bse establece (?:su|el) buen estado\b"
    r"|\bno se aprecian? (?:\S+\s+){0,2}?trazas? de fallo\b"
    r"|\bniveles? aptos? (?:de|para) operaci[oó]n\b",
    re.I,
)
STABLE_RE = re.compile(
    r"^estable\b|\bsin evoluci[oó]n(?: negativa)?\b",
    re.I,
)
STOPPED_RE = re.compile(r"m[aá]quina parada|l[ií]nea .{0,40} parada\b", re.I)
NOT_MEASURED_RE = re.compile(r"m[aá]quina no medida|no se ha medido", re.I)
OUT_OF_SERVICE_RE = re.compile(r"fuera de servicio", re.I)

STATUS_CLAUSES: tuple[tuple[re.Pattern[str], tuple[str, int | None]], ...] = (
    (STOPPED_RE, ("STOPPED", None)),
    (NOT_MEASURED_RE, ("NOT_MEASURED", None)),
    (OUT_OF_SERVICE_RE, ("OUT_OF_SERVICE", None)),
    (HEALTHY_RE, ("OK", 0)),
    (STABLE_RE, ("OK", 0)),
)
"""Prioridad al agregar el estado de un texto de varias cláusulas."""

CLAUSE_SPLIT_RE = re.compile(r"[.;\n]+|\s+-\s+|(?<=[\wáéíóúñ)])\s*-(?=[A-ZÁÉÍÓÚÑ])")
"""El analista redacta el diagnóstico como una lista de cláusulas.

Separadas por punto o por guion de viñeta («-Falta de rigidez. -Rodamientos en
buen estado.»). El corte importa: mirar el texto entero con ``search`` hacía
que bastara una cláusula sana para tirar los fallos de las demás.
"""

_GLOBAL_STATUS_LABELS = (
    r"M[AÁ]QUINA NO MEDIDA|M[AÁ]QUINA PARADA|FUERA DE SERVICIO|"
    r"EN MANTENIMIENTO|SEGUIMIENTO|PELIGRO|ALERTA|BUENO|VIGILAR"
)

GLOBAL_STATUS_RE = re.compile(rf"^({_GLOBAL_STATUS_LABELS})\b")
"""Vocabulario cerrado de la etiqueta global de máquina (auditoría §3.9.2).

La banda geométrica de la cabecera recogía también la línea de RPM y el
título; sólo se acepta lo que empieza por una de estas etiquetas.
"""

MARKER_RE = re.compile(rf"^({_GLOBAL_STATUS_LABELS})$", re.I)
"""Cláusula que es **sólo** la etiqueta global, repetida dentro del texto.

El analista escribe «-Desequilibrio del ventilador. ALERTA. -Debilidad
estructural»: «ALERTA» es la severidad de la ficha, no un hallazgo, y no
participa en el reparto de la masa de juicio.
"""


def norm_tag(tag: str) -> str:
    """Normaliza un TAG de planta para el crosswalk: ``AG.100`` → ``AG100``."""
    text = unicodedata.normalize("NFKD", tag.upper())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]", "", text)


def map_status(label: str) -> tuple[str, int | None]:
    """Etiqueta de estado del informe → ``(status, alarm)`` canónicos."""
    key = label.strip().lower()
    for candidate, mapped in STATUS_MAP.items():
        if candidate in key:
            return mapped
    return ("UNKNOWN", None)


def clauses(text: str) -> list[str]:
    """Cláusulas de un texto de diagnóstico (ver :data:`CLAUSE_SPLIT_RE`)."""
    stripped = " -–·\t/"  # noqa: RUF001 — el guion largo es viñeta del informe
    return [
        clause
        for clause in (part.strip(stripped) for part in CLAUSE_SPLIT_RE.split(text or ""))
        if clause
    ]


def status_from_text(text: str) -> tuple[str, int | None] | None:
    """Estado declarado por un diagnóstico que no nombra ningún fallo.

    Devuelve estado sólo si **todas** las cláusulas son de estado: un «-Falta
    de rigidez / Resonancia… -Rodamientos en buen estado.» declara un fallo y
    una parte sana, y lo que manda es el fallo.
    """
    parts = clauses(text)
    if not parts:
        return None
    ranks: list[int] = []
    for clause in parts:
        rank = next(
            (i for i, (pattern, _) in enumerate(STATUS_CLAUSES) if pattern.search(clause)),
            None,
        )
        if rank is None:
            return None  # una cláusula que no es de estado: hay fallo
        ranks.append(rank)
    return STATUS_CLAUSES[min(ranks)][1]


@dataclass(slots=True)
class _Merged:
    """Un finding en construcción: su regla, su cita y la masa acumulada."""

    index: int
    matched_text: str
    mass: Fraction


def clause_findings(clause: str) -> list[tuple[int, str]]:
    """``(índice de regla, fragmento que casó)`` de **una** cláusula.

    Deduplicado por ``(fault_group, fault_mode)``: dos reglas que llegan a la
    misma etiqueta desde la misma cláusula son una lectura, no dos (gana la de
    menor índice, que es la prioridad de :data:`FINDING_RULES`).

    Una regla con veto en :data:`RULE_VETOES` no dispara si la cláusula casa su
    contexto de veto, aunque su patrón esté ahí: la palabra aparece afirmando
    lo contrario de lo que la regla lee.
    """
    low = clause.lower()
    matched: list[tuple[int, str]] = []
    seen: set[str] = set()
    for index, (rule_id, pattern, fault_mode, group, _quality) in enumerate(FINDING_RULES):
        match = re.search(pattern, low)
        if not match:
            continue
        veto = RULE_VETOES.get(rule_id)
        if veto is not None and veto.search(low):
            continue  # la cláusula dice lo contrario de lo que la regla lee
        key = f"{group}:{fault_mode}"
        if key in seen:
            continue
        seen.add(key)
        matched.append((index, match.group(0)))
    return matched


def is_status_clause(clause: str) -> bool:
    """La cláusula declara un estado (sano, parada, no medida, fuera de servicio)."""
    return any(pattern.search(clause) for pattern, _ in STATUS_CLAUSES)


def is_marker_clause(clause: str) -> bool:
    """La cláusula es sólo la etiqueta global de la ficha repetida en el texto.

    «-Desequilibrio del ventilador. ALERTA. -Debilidad estructural.» tiene tres
    cláusulas pero dos juicios: «ALERTA» es la severidad de la máquina, no un
    hallazgo, y sin esta regla se llevaría un tercio de la masa a `unmapped`.
    El vocabulario es el mismo cerrado que valida la cabecera de la ficha.
    """
    return MARKER_RE.match(clause) is not None


def quantize_weights(masses: list[Fraction]) -> list[float]:
    """Redondea un reparto exacto a :data:`WEIGHT_DECIMALS` sin pasarse de 1.

    Método del **resto mayor**: se reparte en unidades de 10⁻⁶ y el sobrante va
    a las mayores partes fraccionarias, de modo que la suma en enteros sea
    exactamente la del reparto original. El contrato exige suma ≤ 1 y no
    perdona el redondeo hacia arriba.
    """
    scaled = [mass * WEIGHT_UNITS for mass in masses]
    units = [int(value) for value in scaled]
    spare = int(sum(masses) * WEIGHT_UNITS) - sum(units)
    order = sorted(range(len(masses)), key=lambda i: (units[i] - scaled[i], i))
    for index in order[:spare]:
        units[index] += 1
    weights = [value / WEIGHT_UNITS for value in units]
    excess = sum(weights) - 1.0
    if excess > 0:  # último seguro contra el error de coma flotante
        largest = max(range(len(weights)), key=lambda i: weights[i])
        weights[largest] -= excess
    return weights


def map_findings(text: str) -> list[dict[str, Any]]:
    """Findings de un diagnóstico, con su reparto de la masa de juicio.

    Las :data:`FINDING_RULES` se aplican **por cláusula**, no sobre el texto
    entero: cada una de las ``n`` cláusulas de juicio recibe ``1/n`` y la
    reparte a partes iguales entre los findings que produce; una cláusula que
    ninguna regla reconoce cede su parte al finding ``unmapped``. Los findings
    de la misma etiqueta se funden sumando masa y quedándose con la regla de
    menor índice. Las cláusulas de estado y los marcadores de severidad no
    reciben masa; si no queda ninguna cláusula de juicio, el diagnóstico no
    afirma ningún fallo y la lista sale vacía.
    """
    if not text:
        return []
    verbatim = text.strip()
    judged: list[list[tuple[int, str]]] = []
    for clause in clauses(text):
        matches = clause_findings(clause)
        if not matches and (is_status_clause(clause) or is_marker_clause(clause)):
            continue  # estado o severidad: no es un juicio de fallo
        judged.append(matches)
    if not judged:
        return []

    share = Fraction(1, len(judged))
    merged: dict[str, _Merged] = {}
    uncovered = Fraction(0)
    for matches in judged:
        if not matches:
            uncovered += share
            continue
        each = share / len(matches)
        for index, matched_text in matches:
            _rule_id, _pattern, fault_mode, group, _quality = FINDING_RULES[index]
            key = f"{group}:{fault_mode}"
            current = merged.get(key)
            if current is None:
                merged[key] = _Merged(index=index, matched_text=matched_text, mass=each)
                continue
            current.mass += each
            if index < current.index:
                current.index = index
                current.matched_text = matched_text

    found = sorted(merged.values(), key=lambda entry: entry.index)
    masses = [entry.mass for entry in found]
    if uncovered > 0:
        masses.append(uncovered)
    weights = quantize_weights(masses)

    findings: list[dict[str, Any]] = []
    for entry, weight in zip(found, weights, strict=False):
        rule_id, _pattern, fault_mode, group, quality = FINDING_RULES[entry.index]
        findings.append(
            {
                "source_text": verbatim,
                "matched_text": entry.matched_text,
                "fault_mode": fault_mode,
                "fault_group": group,
                "label_quality": quality,
                "mapping_rule": rule_id,
                "weight": weight,
            }
        )
    if uncovered > 0:
        findings.append(
            {
                "source_text": verbatim,
                # ninguna regla disparó: no hay fragmento que citar (§2.5)
                "matched_text": None,
                "fault_mode": None,
                "fault_group": UNMAPPED_GROUP,
                "label_quality": UNMAPPED_QUALITY,
                "mapping_rule": None,
                "weight": weights[-1],
            }
        )
    return findings
