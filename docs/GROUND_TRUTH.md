# DiagGT — Formato de intercambio de ground truth de diagnóstico externo

**Versión de esquema: 0.1.0** · Estado: propuesta · Ámbito: ecosistema VibFrame
(vibsynth-contracts, vibsynth-diagnostics, ams-extract, t8-extract, t8-mapper)

## 1. Motivación

El ecosistema ya tiene tres representaciones de ground truth, y ninguna sirve
para capturar un diagnóstico obtenido *externamente* (informe de analista,
etiqueta de campo, histórico de mantenimiento):

- `FailureModeCase` (vibsynth-contracts/benchmark) describe *inyección
  sintética*: sus campos obligatorios (`seed`, `profile`,
  `operating_conditions.rpm_factor`) no tienen sentido para un informe real.
  Es además el único hueco de GT en VibFrame (`MachineDoc.ground_truth`) y es
  por caso/máquina, no por instante.
- `ground_truth.csv` de fleet_demo es un esquema ad hoc por dataset (una
  columna `severity_<modo>` por modo activo), sin versionado ni procedencia.
- `BenchmarkCase` (peak-finder v3) etiqueta *picos espectrales*, no estados de
  máquina.

DiagGT cubre el hueco: representa **la interpretación de un experto u otro
sistema externo sobre el estado de una máquina en un instante**, con
procedencia completa del juicio (quién, cuándo, desde qué documento) y con
mapeo trazable al vocabulario canónico (`FaultMode`), siguiendo el patrón de
honestidad del t8-mapper (`canonical_metric` + `proxy_quality` +
`mapping_rule`): el texto original nunca se pierde, la etiqueta canónica es
un añadido calificado, y lo no mapeable se declara como tal en vez de
forzarse.

## 2. Modelo de datos

Un fichero DiagGT es un documento JSON (UTF-8) con tres bloques: `provenance`
(procedencia del documento fuente y de la extracción), listas de contexto
(`machines_stopped`, `machines_not_measured`) y `observations` (la carga
útil). La unidad de intercambio es el **documento fuente** — un fichero DiagGT
por informe — para que la procedencia sea única y verificable (hash del PDF).

### 2.1 Raíz

| Campo | Tipo | Descripción |
|---|---|---|
| `$schema_version` | string | semver del esquema DiagGT (`"0.1.0"`) |
| `kind` | string | literal `"diagnosis_ground_truth"` |
| `provenance` | object | ver §2.2 |
| `machines_stopped` | list[string] | máquinas declaradas paradas en el documento |
| `machines_not_measured` | list[string] | máquinas declaradas no medidas |
| `observations` | list[object] | ver §2.3 |

### 2.2 `provenance` — procedencia del juicio

Extiende el espíritu de `SourceInfo` (vibsynth-contracts/dataset/provenance),
que solo cubre la procedencia del *dato*, con la procedencia de la
*interpretación*:

| Campo | Tipo | Descripción |
|---|---|---|
| `origin` | string | tipo de fuente: `"inspection-report"` (otros futuros: `"cmms"`, `"work-order"`, `"analyst-annotation"`) |
| `provider` | string | organización autora (p. ej. `"Preditec"`) |
| `document_id` | string | referencia del documento (`"P25/81115-260126"`) |
| `document_title` | string | título legible |
| `source_ref` | string | nombre/ruta del fichero fuente |
| `source_sha256` | string | hash del fichero fuente — ancla de verificación |
| `client`, `plant` | string | cliente y planta |
| `inspection_date` | date ISO | fecha nominal de la inspección |
| `measurement_period` | {from, to} | ventana real de medida |
| `routes` | list[string] | rutas cubiertas, tal como las nombra el documento |
| `analysts`, `reviewers` | list[string] | autoría del análisis |
| `extractor` | string | herramienta y versión (patrón `SourceInfo.extractor`) |
| `extracted_at` | datetime ISO | momento de la extracción |
| `extraction_method` | string | `"pdf_text_parse"` \| `"manual"` \| `"llm"` |

### 2.3 `observation` — una interpretación

Una observación = **(máquina, fecha, modalidad)**. Cada ficha de máquina de un
informe produce una observación por modalidad presente (vibración, inspección
visual, ultrasonidos…), más observaciones *retrospectivas* por cada entrada de
"diagnósticos previos".

| Campo | Tipo | Descripción |
|---|---|---|
| `observation_id` | string | `{doc}:{tag}:{modalidad}[:{fecha}]` — único en el documento |
| `record_kind` | string | `"primary"` (ficha del propio informe) \| `"retrospective"` (mención a un diagnóstico anterior) |
| `machine` | object | referencia de máquina, ver §2.4 |
| `modality` | string | `"vibration"` \| `"visual_inspection"` \| `"thermography"` \| `"ultrasound"` \| otros |
| `observed_at` | date ISO | fecha del diagnóstico (≠ fecha del documento en retrospectivos) |
| `status` | string | estado canónico, ver §3.1 |
| `status_source_label` | string\|null | etiqueta literal del origen (`"Seguimiento"`) |
| `alarm` | int\|null | proyección a la escala `alarm` int8 de `trends.parquet` VibFrame (0–3) |
| `global_status_label` | string\|null | estado global de máquina del origen (`"ALERTA"`) |
| `diagnosis_text` | string\|null | diagnóstico **verbatim** — campo de referencia |
| `analysis_text` | string\|null | análisis/evidencia verbatim |
| `recommendation_text` | string\|null | recomendación verbatim |
| `findings` | list[object] | mapeo canónico del diagnóstico, ver §2.5 |
| `operating_context` | object\|null | `{rpm1, rpm2, power_kw}` declarados por el origen |
| `source_page` | int | página del documento fuente — trazabilidad y auditoría |

Semántica temporal: `observed_at` es un instante (la fecha de ruta). La
vigencia del diagnóstico se extiende implícitamente hasta la siguiente
observación de la misma máquina y modalidad; DiagGT no materializa
`valid_to` porque el consolidado (§5) lo deriva.

### 2.4 `machine` — referencia y crosswalk

El informe nombra las máquinas por su TAG de planta; el dataset VibFrame las
nombra por el `machine_id` del extractor (slug del nombre AMS). DiagGT guarda
ambas identidades y nunca las confunde:

| Campo | Tipo | Descripción |
|---|---|---|
| `external_tag` | string\|null | TAG tal como aparece (`"PM.1250A"`, `"AG.100"`) |
| `external_name` | string | nombre legible (`"Bomba Centrifuga"`) |
| `normalized_tag` | string | TAG normalizado para joins: mayúsculas, sin separadores (`"PM1250A"`, `"AG100"`) |
| `area_code`, `area_name` | string | jerarquía del origen (equivale a `MachineInfo.path`) |
| `dataset_machine_id` | string\|null | `machine_id` VibFrame tras el crosswalk; `null` hasta resolverse |

Regla de crosswalk propuesta (post-proceso, análoga al etiquetado del
t8-mapper): `normalized_tag` debe aparecer como subcadena de
`norm(machine_id)` del dataset (`"AG100"` ⊂ `"MECLADOR_AGITADOR_AG_100"` →
match). Ambigüedades o no-matches se resuelven con una tabla de crosswalk
explícita mantenida junto al dataset; el campo se rellena, no se sobrescribe
el TAG original.

### 2.5 `finding` — mapeo canónico calificado

Cada finding traduce (parte de) `diagnosis_text` al vocabulario canónico. El
patrón replica `canonical_metric`/`proxy_quality`/`mapping_rule` del
t8-mapper:

| Campo | Tipo | Descripción |
|---|---|---|
| `source_text` | string | texto de diagnóstico origen (verbatim) |
| `matched_text` | string\|null | fragmento que disparó la regla |
| `fault_mode` | string\|null | `FaultMode` canónico si es determinable |
| `fault_group` | string | grupo de fallo, ver §3.2 — siempre presente |
| `label_quality` | string | `"direct"` \| `"approximate"` \| `"weak"` \| `"group"` \| `"unmapped"` |
| `mapping_rule` | string\|null | id de la regla (GTxxx) — trazabilidad y versionado |

`"group"` significa "el origen dice el grupo pero no el modo concreto"
(p. ej. «deterioro en rodamientos» → grupo `BEARING`, `fault_mode=null`: el
informe no distingue pista externa/interna). Un diagnóstico sano, de parada o
de no-medida produce `findings=[]`. Un texto de fallo que ninguna regla
reconoce produce exactamente un finding `unmapped` con `fault_group="UNMAPPED"`
— nunca se descarta en silencio (regla "no emitir lo no validado" de
ams-extract, aplicada al revés: no callar lo no mapeado).

## 3. Vocabularios

### 3.1 `status` canónico

| status | alarm | Etiquetas de origen observadas |
|---|---|---|
| `OK` | 0 | Bueno |
| `WATCH` | 1 | Seguimiento, Vigilar |
| `ALERT` | 2 | Alerta |
| `DANGER` | 3 | Peligro |
| `STOPPED` | null | Parada |
| `NOT_MEASURED` | null | No medida |
| `OUT_OF_SERVICE` | null | Fuera de servicio |
| `UNKNOWN` | null | (retrospectivos: el origen no declara estado pasado) |

`alarm` proyecta a la escala int8 de VibFrame `trends.parquet` (ADR-0012 de
ams-extract usa 0/2/3; DiagGT añade 1 para "Seguimiento", coherente con la
semántica "0 normal … 3 danger" del contrato).

### 3.2 `fault_group`

Superconjunto agrupado de `FaultMode`, para diagnósticos que el origen no
concreta: `IMBALANCE`, `MISALIGNMENT`, `LOOSENESS`, `BEARING`, `LUBRICATION`,
`GEAR`, `ELECTRICAL`, `FLOW`, `BELT`, `STRUCTURE`, `OTHER`, `UNMAPPED`.

Correspondencia con `FaultMode` (16 modos de vibsynth-contracts):
`MISALIGNMENT` ⊃ {MISALIGNMENT_PARALLEL, MISALIGNMENT_ANGULAR};
`BEARING` ⊃ {BEARING_OUTER, BEARING_INNER, BEARING_BALL, BEARING_CAGE};
`LUBRICATION` = {BEARING_LUBRICATION}; `GEAR` ⊃ {GEAR_WEAR, GEAR_TOOTH};
`ELECTRICAL` = {ELECTRICAL_ROTOR}; `FLOW` ⊃ {CAVITATION, BROKEN_BLADE};
`BELT` = {BELT_FAULT}; `STRUCTURE` ⊃ {RESONANCE} (+ debilidad estructural
mapeada a LOOSENESS approximate).

### 3.3 Reglas de mapeo GTxxx (v0.1)

Las reglas viven en el extractor y se versionan como las IRxxx del t8-mapper:
cambiar la lógica de una regla obliga a nuevo id o sufijo de versión.

| Regla | Patrón (es) | fault_mode | grupo | calidad |
|---|---|---|---|---|
| GT001 | desequilibri- | IMBALANCE | IMBALANCE | direct |
| GT002 | desalineac- | — | MISALIGNMENT | group |
| GT003 | holguras rotacionales | LOOSENESS | LOOSENESS | direct |
| GT004 | holgura (genérica) | LOOSENESS | LOOSENESS | approximate |
| GT005 | debilidad estructural | LOOSENESS | STRUCTURE | approximate |
| GT006 | resonancia | RESONANCE | STRUCTURE | direct |
| GT007–GT010 | pista externa/interna, elementos rodantes, jaula (o BPFO/BPFI/BSF/FTF) | BEARING_* | BEARING | direct |
| GT011 | lubricaci- | BEARING_LUBRICATION | LUBRICATION | direct |
| GT012 | deterioro/fallo/desgaste de rodamiento sin concretar | — | BEARING | group |
| GT013 | eléctric- | ELECTRICAL_ROTOR | ELECTRICAL | approximate |
| GT014 | engran-/GMF | GEAR_WEAR | GEAR | approximate |
| GT015 | cavitaci- | CAVITATION | FLOW | direct |
| GT016 | correa | BELT_FAULT | BELT | direct |
| GT017 | álabe/rodete/VPF/impulsor | BROKEN_BLADE | FLOW | weak |
| GT018 | rozamiento | — | OTHER | group |
| GT019 | anclaje/bancada/pernos | LOOSENESS | STRUCTURE | approximate |

## 4. Convenciones de fichero

```
<informes>/
├── <documento>.pdf                      # fuente (no se modifica)
└── ground-truth/
    ├── <documento>.diaggt.json          # un DiagGT por documento fuente
    ├── observations.parquet             # consolidado plano (§5)
    ├── observations.csv                 # ídem, para inspección rápida
    └── FORMATO_GROUND_TRUTH.md          # esta especificación
```

Integración con VibFrame (no intrusiva, igual que `report.html` de
ams-extract queda fuera del contrato): los DiagGT pueden copiarse a un
directorio `ground-truth/` en la raíz del dataset VibFrame. No se tocan las
particiones `machine=` ni el `machine.json`; la unión se hace por
`dataset_machine_id` tras el crosswalk. Si en el futuro se quiere una tabla
dentro del contrato VibFrame, el consolidado §5 es directamente la candidata
(`diagnoses.parquet` a nivel de dataset), y ese paso requeriría subir la
versión menor del contrato en vibsynth-contracts.

## 5. Consolidado plano (`observations.parquet`)

Una fila por (máquina, `observed_at`, modalidad), pensado para join con
features de VibFrame (mismo espíritu que `ground_truth.csv` de fleet_demo pero
genérico y con procedencia). Columnas: `document_id`, `inspection_date`,
`observed_at`, `record_kind`, `external_tag`, `normalized_tag`,
`external_name`, `area_code`, `area_name`, `modality`, `status`,
`status_source_label`, `alarm`, `fault_modes` (multi-etiqueta unida por `+`,
como fleet_demo), `fault_groups`, `diagnosis_text`, `recommendation_text`,
`analysis_text`, `rpm1`, `power_kw`, `source_page`.

Reglas de deduplicación (los informes mensuales repiten los diagnósticos
previos): para cada (normalized_tag, observed_at, modality) gana el registro
`primary`; entre retrospectivos gana el del documento más reciente. Los
`diaggt.json` conservan todo sin deduplicar — el consolidado es una vista.

## 6. Qué NO cubre v0.1 (decisiones abiertas)

- **Severidad numérica**: los informes dan categorías, no severidad [0,1].
  Se decidió NO inventar un mapeo `status→severity`; si diagnostics lo
  necesita, que lo declare como política propia (p. ej. WATCH=0.3, ALERT=0.6,
  DANGER=0.9) y lo documente en su evaluación.
- **Localización de componente**: «rodamientos de la bomba» localiza el
  fallo mejor que `machine_id` pero peor que un `point_id`. v0.1 lo deja en
  el texto; un futuro `component_ref` podría enlazar con nodos de
  `MachineDefinition`.
- **Matriz de estados coloreada**: la sección "Resumen Estado de Máquinas"
  del informe codifica 12 meses de estado por color de celda (sin texto). Es
  redundante con los diagnósticos previos, pero extraerla (color de rects del
  PDF) daría cadencia mensual completa por máquina.
- **Política de evaluación**: cómo puntuar un `DiagnosisResult` contra DiagGT
  (¿ventana de acierto?, ¿multi-etiqueta parcial?) es análogo a
  `EvaluationPolicy` de BenchmarkCase y queda para cuando exista el primer
  consumidor.
- **Eventos de mantenimiento**: las intervenciones se infieren del texto
  («tras su intervención…»). Un `record_kind="intervention"` sería la
  extensión natural cuando haya fuente estructurada (CMMS).

## 7. Compatibilidad

- Lectores DiagGT deben ignorar campos desconocidos (regla VibFrame).
- Añadir campo opcional o valor de vocabulario ⇒ sube versión menor;
  cambiar semántica de campo existente ⇒ versión mayor.
- El texto verbatim (`diagnosis_text`, `analysis_text`,
  `recommendation_text`) es el contrato de último recurso: cualquier
  re-mapeo futuro (mejores reglas GTxxx, LLM, revisión humana) debe poder
  regenerar `findings` sin volver al PDF.
