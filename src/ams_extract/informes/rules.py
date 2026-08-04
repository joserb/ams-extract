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
from typing import Any

SCHEMA_VERSION = "0.1.4"
"""Versión del esquema DiagGT que declara el documento emitido.

Hasta la adopción en el paquete el script decía ``"0.1.0"`` mientras emitía
0.1.4: el desalineado era un bug de la constante, no del contenido.
"""

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
    ("GT001", r"desequilibri", "IMBALANCE", "IMBALANCE", "direct"),
    ("GT002", r"desalineac", None, "MISALIGNMENT", "group"),
    ("GT003", r"holguras? rotacional", "LOOSENESS", "LOOSENESS", "direct"),
    ("GT004", r"holgura", "LOOSENESS", "LOOSENESS", "approximate"),
    ("GT005", r"debilidad estructural|debilidad en", "LOOSENESS", "STRUCTURE", "approximate"),
    ("GT006", r"resonancia", "RESONANCE", "STRUCTURE", "direct"),
    ("GT007", r"pista externa|bpfo", "BEARING_OUTER", "BEARING", "direct"),
    ("GT008", r"pista interna|bpfi", "BEARING_INNER", "BEARING", "direct"),
    ("GT009", r"elementos? rodantes?|bsf", "BEARING_BALL", "BEARING", "direct"),
    ("GT010", r"jaula|ftf", "BEARING_CAGE", "BEARING", "direct"),
    ("GT011", r"lubricaci", "BEARING_LUBRICATION", "LUBRICATION", "direct"),
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
    ("GT021", r"excentricidad", "ELECTRICAL_ROTOR", "ELECTRICAL", "approximate"),
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
)
"""``(rule_id, patrón, fault_mode|None, fault_group, label_quality)``.

``fault_group`` es el vocabulario propio de DiagGT (superconjunto agrupado de
``FaultMode``) para diagnósticos que el informe no concreta. Invariante del
modelo normativo: ``label_quality="group"`` exige ``fault_mode`` nulo; las
demás calidades lo exigen no nulo.
"""

UNMAPPED_GROUP = "UNMAPPED"
UNMAPPED_QUALITY = "unmapped"

# ---------------------------------------------------------------------------
# Textos de estado (spec §3.3): producen findings=[]
# ---------------------------------------------------------------------------

HEALTHY_RE = re.compile(
    r"(m[aá]quina|equipo|conjunto|rodamientos?|motor|reductor)\s+"
    r"(?:\S+\s+){0,3}?en buen estado",
    re.I,
)
STOPPED_RE = re.compile(r"m[aá]quina parada", re.I)
NOT_MEASURED_RE = re.compile(r"m[aá]quina no medida|no se ha medido", re.I)
OUT_OF_SERVICE_RE = re.compile(r"fuera de servicio", re.I)

STATUS_CLAUSES: tuple[tuple[re.Pattern[str], tuple[str, int | None]], ...] = (
    (STOPPED_RE, ("STOPPED", None)),
    (NOT_MEASURED_RE, ("NOT_MEASURED", None)),
    (OUT_OF_SERVICE_RE, ("OUT_OF_SERVICE", None)),
    (HEALTHY_RE, ("OK", 0)),
)
"""Prioridad al agregar el estado de un texto de varias cláusulas."""

CLAUSE_SPLIT_RE = re.compile(r"[.;\n]+|\s+-\s+|(?<=[\wáéíóúñ)])\s*-(?=[A-ZÁÉÍÓÚÑ])")
"""El analista redacta el diagnóstico como una lista de cláusulas.

Separadas por punto o por guion de viñeta («-Falta de rigidez. -Rodamientos en
buen estado.»). El corte importa: mirar el texto entero con ``search`` hacía
que bastara una cláusula sana para tirar los fallos de las demás.
"""

GLOBAL_STATUS_RE = re.compile(
    r"^(M[AÁ]QUINA NO MEDIDA|M[AÁ]QUINA PARADA|FUERA DE SERVICIO|"
    r"EN MANTENIMIENTO|SEGUIMIENTO|PELIGRO|ALERTA|BUENO|VIGILAR)\b"
)
"""Vocabulario cerrado de la etiqueta global de máquina (auditoría §3.9.2).

La banda geométrica de la cabecera recogía también la línea de RPM y el
título; sólo se acepta lo que empieza por una de estas etiquetas.
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


def map_findings(text: str) -> list[dict[str, Any]]:
    """Aplica :data:`FINDING_RULES` sobre el texto de diagnóstico."""
    if not text:
        return []
    low = text.lower()
    if status_from_text(low) is not None:
        return []
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule_id, pattern, fault_mode, group, quality in FINDING_RULES:
        match = re.search(pattern, low)
        if not match:
            continue
        key = f"{group}:{fault_mode}"
        if key in seen:
            continue
        seen.add(key)
        found.append(
            {
                "source_text": text.strip(),
                "matched_text": match.group(0),
                "fault_mode": fault_mode,
                "fault_group": group,
                "label_quality": quality,
                "mapping_rule": rule_id,
            }
        )
    if not found:
        found.append(
            {
                "source_text": text.strip(),
                "matched_text": None,
                "fault_mode": None,
                "fault_group": UNMAPPED_GROUP,
                "label_quality": UNMAPPED_QUALITY,
                "mapping_rule": None,
            }
        )
    return found
