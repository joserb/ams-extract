# DiagGT — Formato de intercambio de ground truth de diagnóstico externo

**Versión de esquema: 0.1.5** · Estado: propuesta · Ámbito: ecosistema VibFrame
(vibsynth-contracts, vibsynth-diagnostics, vibsynth-metrics, ams-extract,
t8-extract, t8-mapper)

> **Hogar del contrato**: los **modelos normativos** de DiagGT viven en
> `vibsynth-contracts` (`vibsynth_contracts.diagnosis.external`, Pydantic v2),
> igual que el layout VibFrame (ADR-0009: el formato lo define contracts, este
> repo lo produce sin depender de él en runtime). Este documento es la **spec de
> referencia**: describe el porqué, los vocabularios y las reglas de mapeo, y es
> el texto citado por `docs/VIBFRAME.md` de contracts. Ante una discrepancia
> entre este documento y los modelos, gana el modelo — y la discrepancia es un
> bug de esta spec.
>
> **Materialización VibFrame 0.2** (2026-08-09): el esquema documental
> DiagGT permanece en `0.1.5`; lo que cambia de forma incompatible es su
> proyección dentro de un dataset VibFrame 0.2. Los `*.diaggt.json` siguen
> siendo la fuente. `observations.parquet` pasa a ser la proyección completa,
> `observations_consolidated.parquet` la selección deduplicada,
> `findings.parquet` conserva cada finding y su orden, y
> `materialization.json` ancla inputs y outputs con SHA-256. Los CSV y la
> proyección separada `observations_system.parquet` son legado y no se emiten.
>
> **Cambios en 0.1.5** (2026-08-04, retrocompatible con toda la serie 0.1.x —
> el campo nuevo es **opcional**, ninguna semántica anterior cambia; los
> documentos que declaran cualquier `"0.1.x"` anterior siguen siendo válidos y
> nadie tiene que reemitir):
> - §2.5: **`weight`**, la *masa de juicio* que un finding se lleva dentro de su
>   observación. Es la primera revisión de la serie que toca el modelo
>   normativo: `DiagGTFinding.weight: float | None` en [0, 1], con las dos
>   reglas de observación —todos o ninguno, suma ≤ 1— en `DiagGTObservation`.
> - §5: **`findings.parquet`**, el consolidado a nivel de finding, modelado
>   por columnas en el contrato (`FINDINGS_COLUMNS`). El aplanado con «+» de
>   `observations.parquet` se queda como está.
> - §3.3: el reparto por cláusulas del extractor de informes —la línea base
>   determinista de pesos— y el **marcador de severidad** («ALERTA», «PELIGRO»)
>   como cláusula que no es juicio.
> - Primer productor con pesos: el extractor de informes
>   (`ams_extract.informes`, adoptado en el paquete en el mismo workplan 09).
>
> **Nota (2026-08-05)**: la revisión 0.1.5 se amplía con la edición del
> 2026-08-05 (commit `9d615aa`, workplan 11) **sin subir versión**, porque
> tampoco toca el esquema — son reglas y vocabulario del extractor, como
> GT050 en 0.1.1, GT900 en 0.1.3 y GT020–GT024 en 0.1.4:
> - §3.3: **GT025**, la excentricidad de polea leída como fallo de la
>   transmisión (grupo `BELT` con `fault_mode` nulo, porque el catálogo no
>   tiene modo para la polea).
> - §3.3.1: **Vetos**, sección nueva — el contexto, por cláusula, en el que una
>   regla **no** dispara porque la frase afirma lo contrario de lo que su patrón
>   lee. Lo estrenan `GT011v2` y `GT021v2`; con `GT001v2` son las tres lecturas
>   versionadas en `informes-gt-extract` 0.4.0.
> - §3.3, textos de estado: «buen estado de lubricación» entra en el
>   vocabulario de «sano», que es la otra mitad del veto de `GT011v2`.

> **Cambios en 0.1.4** (2026-07-28, retrocompatible con toda la serie 0.1.x —
> ningún campo nuevo, ningún campo nuevo obligatorio, ninguna semántica
> cambiada; sólo reglas del extractor, como en 0.1.1 con GT050 y en 0.1.3 con
> GT900):
> - §3.3: **GT020–GT024**, las familias de vocabulario que la auditoría de
>   lectura completa de los informes Bunge encontró recurrentes y sin regla
>   (distorsión armónica del variador, excentricidad, excitación asíncrona en
>   alta frecuencia, falta de rigidez / holgura estructural y el vocabulario
>   de inspección visual). Bajan el `unmapped` del extractor de informes del
>   10,4 % al 2,3 %.
> - §3.3: se fija además qué es un **texto de estado** y no de fallo (la
>   familia «… en buen estado», «fuera de servicio») y que la comprobación es
>   **por cláusula**, no sobre el texto entero: un «-Falta de rigidez.
>   -Rodamientos en buen estado.» nombra un fallo.
> - §6: se corrige la asunción sobre la **matriz de estados coloreada** — las
>   celdas no son `rects` con color de relleno sino **imágenes**; y entra una
>   decisión abierta nueva, el **índice de figuras** por observación.
> - Ninguno de los dos toca el esquema: las reglas GTxxx viven en el extractor
>   y `mapping_rule` es una cadena libre del namespace GT. Los documentos que
>   declaran cualquier `"0.1.x"` anterior siguen siendo válidos.
> - Los modelos de `vibsynth-contracts` **no cambian** con esta revisión; la
>   constante `DIAGGT_SCHEMA_VERSION` y la cita de la spec en el docstring del
>   módulo se actualizaron allí (edición de documentación, no de contrato).
>   **Cumplido** (nota 2026-08-05): hoy
>   `vibsynth_contracts.diagnosis.external` declara
>   `DIAGGT_SCHEMA_VERSION = "0.1.5"`, subida ya por la revisión siguiente.
>
> **Cambios en 0.1.3** (2026-07-28, retrocompatible con 0.1.2, 0.1.1 y 0.1.0 —
> ningún campo nuevo, ningún campo nuevo obligatorio, ninguna semántica
> cambiada):
> - §2.2: el vocabulario de `origin` añade **`synthetic-truth`** — el juicio
>   derivado de la *verdad de construcción* de un dataset sintético. Es el
>   único origen no falible del vocabulario, y §2.2 documenta el matiz
>   epistemológico y lo que implica en los demás campos.
> - §3.5: familia de reglas **GT900–GT919**, el namespace del extractor
>   sintético; hoy la ocupa una sola regla, GT900, la identidad.
> - §4: dónde consolida `synthetic-truth` (en `observations.parquet`, porque
>   nunca convive con informes de analista) y §6 recoge las dos políticas que
>   su primer productor —`vibsynth_metrics.diag_gt_export`— ha tenido que
>   declarar: cadencia de observación y severidad→`status`.
> - Los documentos que declaran `"0.1.2"`, `"0.1.1"` o `"0.1.0"` siguen siendo
>   válidos: añadir un valor de vocabulario no obliga a nadie a reemitir.
>
> **Cambios en 0.1.2** (2026-07-28, retrocompatible con 0.1.1 y 0.1.0 —
> ningún campo nuevo, ningún campo nuevo obligatorio, ninguna semántica
> cambiada):
> - §2.2: el vocabulario de `extraction_method` añade **`structured_read`**
>   (lectura determinista de una fuente estructurada: decode de récords
>   binarios, consulta de una tabla SQLite). Los dos productores
>   `system-alarm` —las notas `gdnl` de AMS y `alarms.db` del T8— lo declaran
>   en vez de `null`, y §6 retira la decisión abierta correspondiente.
> - §6: dos decisiones abiertas nuevas, ambas planteadas por el productor T8
>   — el **GT de calidad de dato** (los fallos del equipo de medida) y la
>   **precisión temporal** de `observed_at`.
> - Los documentos que declaran `"0.1.1"` o `"0.1.0"` siguen siendo válidos:
>   añadir un valor de vocabulario no obliga a nadie a reemitir.
>
> **Cambios en 0.1.1** (2026-07-27, retrocompatible con 0.1.0 — ningún campo
> nuevo obligatorio, ningún cambio de semántica):
> - §2.4: la regla de crosswalk «subcadena» se sustituye por los niveles
>   versionados CW001–CW004 (era demasiado laxa: falsos positivos en TAGs
>   numéricos que son prefijo de otros), y se fija dónde vive el mapeo.
> - §4: `crosswalk.csv` y `crosswalk_ambiguities.md` entran en la lista de
>   ficheros del directorio `ground-truth/`; se resuelve la ambigüedad
>   «junto al dataset» vs `<informes>/ground-truth/`.
> - §5: `dataset_machine_id` se lista entre las columnas del consolidado
>   (§2.4 ya lo exigía).
> - §3.4 (misma fecha, con el primer productor `system-alarm`): familia de
>   reglas **GT050-GT053** para bandas de alarma. La primera materialización
>   usó un `observations_system.parquet` propio; VibFrame 0.2 lo integra en la
>   proyección completa y conserva `origin` para separar las familias.
>   Ninguna de las dos decisiones toca el esquema documental:
>   las reglas GTxxx viven en el extractor (§3.3) y `mapping_rule` es una
>   cadena libre del namespace GT.

## 1. Motivación

El ecosistema ya tiene tres representaciones de ground truth, y ninguna sirve
para capturar un diagnóstico obtenido *externamente* (informe de analista,
etiqueta de campo, histórico de mantenimiento):

- `FailureModeCase` (vibsynth-contracts/benchmark) describe *inyección
  sintética*: sus campos obligatorios (`seed`, `profile`,
  `operating_conditions.rpm_factor`) no tienen sentido para un informe real.
  Es además el único hueco de GT en VibFrame (`MachineDoc.ground_truth`) y es
  por caso/máquina, no por instante. (Desde 0.1.3 hay un puente en la otra
  dirección: el origen `synthetic-truth` de §2.2 publica el *contenido* de esa
  inyección como observaciones DiagGT fechadas —sin sustituir el campo, que
  sigue siendo el que hace reproducible la generación.)
- `ground_truth.csv` de fleet_demo es un esquema ad hoc por dataset (una
  columna `severity_<modo>` por modo activo), sin versionado ni procedencia.
  Desde 0.1.3 es, además, la *fuente* del origen `synthetic-truth`: sigue
  existiendo tal cual para el análisis en pandas, y DiagGT es su proyección
  versionada y con procedencia.
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
| `$schema_version` | string | semver del esquema DiagGT (`"0.1.5"`; los documentos que declaran cualquier `"0.1.x"` anterior siguen siendo válidos — ninguna revisión de la serie añade obligaciones) |
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
| `origin` | string | tipo de fuente: `"inspection-report"`, `"analyst-annotation"`, `"system-alarm"` (alarma del propio sistema: `gdnl` de AMS, `alarms.db` del T8 — juicio automático por umbral, no de analista), `"synthetic-truth"` (verdad de construcción de un dataset sintético, ver abajo); otros futuros: `"cmms"`, `"work-order"` |
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
| `extraction_method` | string | `"pdf_text_parse"` \| `"manual"` \| `"llm"` \| `"structured_read"`; `null` cuando ninguno aplica |

`extraction_method` describe **cómo se llegó del documento fuente al DiagGT**,
no la calidad del juicio (esa la califica `label_quality` por finding).
`structured_read` (desde 0.1.2) es la lectura **determinista de una fuente
estructurada** —el decode de un récord binario, la consulta de una tabla— sin
interpretación de texto libre: releer la misma fuente da el mismo documento.
Lo declaran los dos productores `origin="system-alarm"` —las notas `gdnl` de
AMS (`ams_extract.export.diag_gt`) y `alarms.db` del T8
(`t8_extract.ground_truth`)— y también el productor `synthetic-truth`
(`vibsynth_metrics.diag_gt_export`), que lee la tabla de verdad
(`ground_truth.csv`) del dataset sintético y ancla su hash en
`source_sha256`.

#### `synthetic-truth` — el único origen no falible (desde 0.1.3)

Un dataset generado sintéticamente conoce su verdad **por construcción**: sabe
qué modos de fallo inyectó y con qué severidad, captura a captura. Publicar esa
verdad como DiagGT permite que un dataset sintético lleve el mismo sidecar
`ground-truth/` que uno de planta real y que el mismo consumidor —el visor, un
evaluador de diagnóstico— los lea por la misma puerta. El productor actúa como
un **«analista perfecto y omnisciente»**: no infiere el diagnóstico de la
medida, lo deriva del plan de inyección, así que ni falla un fallo ni se
inventa ninguno.

Ese matiz no es decorativo — se lee en los campos del contrato:

- `label_quality` es siempre `direct`. El modo canónico no se deduce de un
  texto: se copia del `FaultMode` que se inyectó (regla GT900, §3.5). Nunca
  aparecen `approximate`, `weak`, `group` ni `unmapped`.
- El `status` no lleva incertidumbre: sale de la severidad [0,1] de la
  inyección por una política de umbrales que el productor **declara** (§6).
- `analysts` queda **vacío**, y a propósito: nadie firmó este juicio, se
  derivó. La autoría entera está en `extractor`.

Consecuencia práctica: un DiagGT `synthetic-truth` es la **referencia superior**
contra la que evaluar un diagnóstico automático —el techo de acierto
alcanzable—, no una opinión más que promediar con las otras. Un consumidor que
pondere orígenes debería tratarlo aparte.

Este origen **cruza a propósito** la frontera que §1 traza entre
`MachineDoc.ground_truth` (verdad por construcción, por máquina, del dataset
sintético) y DiagGT (juicio, por instante): toma el contenido de la primera y
lo republica con la granularidad y la procedencia del segundo. Lo que no hace
es sustituirla: `machine.json` sigue siendo el sitio del `FailureModeCase` con
su `seed` y su `profile` —lo que hace reproducible la inyección—, los dos
pueden convivir sin decirse nada, y la tabla de `docs/VIBFRAME.md` que los
distingue sigue vigente para todo lo demás.

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

#### Reglas de crosswalk CWxxx

El crosswalk es un **post-proceso** (análogo al etiquetado del t8-mapper), no
un paso del extractor, y sus reglas se versionan como las GTxxx de §3.3:
cambiar la lógica de una regla obliga a nuevo id o sufijo de versión. Se
comparan `normalized_tag` (TAG del informe, mayúsculas y sin separadores) y
`norm(machine_id)` del dataset (mayúsculas, separadores `_`/`-`/espacio como
límites de token).

| Regla | Nivel | Condición |
|---|---|---|
| CW001 | `exact_suffix` | el tag es exactamente la concatenación de los **últimos** tokens del `machine_id` (`"AG100"` ↔ `MECLADOR_AGITADOR_AG_100`) |
| CW002 | `delimited` | el tag es una secuencia **completa de tokens** del `machine_id`, no final (`"MA9306"` ↔ `MECLADOR_AGITADOR_MA_9306_B`) |
| CW003 | `substring` | el tag aparece como subcadena de `norm(machine_id)` — la regla base, la más laxa |
| CW004 | unicidad inversa | un `machine_id` no puede colgar de dos tags: si dos tags lo reclaman, se queda con el del nivel más fuerte y el otro queda sin match |

Resolución: **gana el nivel más fuerte** con candidatos (CW001 > CW002 >
CW003) y **sólo se rellena `dataset_machine_id` si ese nivel deja un único
candidato**; si quedan varios, el tag se declara ambiguo y no se fuerza
ninguno. La regla base sola no basta: los TAGs numéricos que son prefijo de
otros (`PM.700` ⊂ `PM_7001`, `PM_7002`, `PM_7006A/B`…) generan falsos
positivos, y los niveles CW001/CW002 son los que los desempatan.

#### Dónde vive el mapeo

El mapeo resuelto vive en una **tabla explícita `crosswalk.csv`** (§4), una
fila por `normalized_tag` con el `dataset_machine_id`, la regla y el nivel que
lo decidieron y los candidatos evaluados. Esa tabla es la **fuente** del
mapeo: admite entradas manuales para lo que el algoritmo no resuelve, y es
donde se audita cada decisión. El consolidado (§5) es su **proyección**: lleva
`dataset_machine_id` como columna para poder unir con VibFrame sin releer los
JSON.

Los `*.diaggt.json` **no se tocan** en el crosswalk: son salida pura del
extractor (con su `extracted_at` y el hash del PDF), y `dataset_machine_id`
queda `null` en ellos salvo que el propio productor ya conozca el
`machine_id`. El campo se rellena, nunca sobrescribe el TAG original, y un
crosswalk se puede rehacer entero contra otro dataset sin regenerar nada.

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
| `weight` | float\|null | (0.1.5) masa de juicio en [0, 1] dentro de la observación; ver abajo |

`"group"` significa "el origen dice el grupo pero no el modo concreto"
(p. ej. «deterioro en rodamientos» → grupo `BEARING`, `fault_mode=null`: el
informe no distingue pista externa/interna). Un diagnóstico sano, de parada o
de no-medida produce `findings=[]`. Un texto de fallo que ninguna regla
reconoce produce exactamente un finding `unmapped` con `fault_group="UNMAPPED"`
— nunca se descarta en silencio (regla "no emitir lo no validado" de
ams-extract, aplicada al revés: no callar lo no mapeado).

#### `weight` — la masa de juicio (desde 0.1.5)

Sin peso, un finding no dice **cuánto** del juicio se lleva. «Desalineación
severa en el acoplamiento» y «desalineación severa en el acoplamiento; se
observa además lubricación mejorable en el rodamiento del motor» producen
etiquetas indistinguibles, y quien evalúe un diagnóstico automático contra el
GT tiene que tratar las dos etiquetas de la segunda como si cada una fuese la
afirmación central. El analista no dijo eso: repartió su juicio.

`weight` es ese reparto. Reglas, todas dentro de la observación:

- **Rango**: `[0, 1]`. Es una fracción del juicio de esa observación, no una
  severidad ni una probabilidad — un `weight` alto no dice que el fallo sea
  grave, dice que el origen dedicó a él la mayor parte de lo que afirmó.
  La severidad sigue siendo `status`/`alarm` (§3.1), y §6 sigue sin inventar
  una severidad numérica.
- **Suma ≤ 1** (con tolerancia de redondeo; el contrato la fija en 1e-6).
- **Todos o ninguno**: o cada finding de la observación lleva peso, o no lo
  lleva ninguno. Un finding sin peso al lado de otros con peso describiría una
  distribución a medias — el consumidor no sabría si vale cero, si vale el
  resto o si el extractor se dejó uno.
- **Opcional para siempre**: un origen que no sabe repartir masa emite `null`
  en vez de inventarse un 1,0 uniforme. Es la misma honestidad de
  `label_quality`: lo que no se sabe se declara, no se rellena.
- **Duplicados de modo con peso son legales**: dos reglas GT distintas sobre el
  mismo texto son dos lecturas, cada una con su parte. El esquema no decide si
  eso es un hecho contado dos veces; la política es del consumidor.

**Agregación en el consumidor**: sumar. La masa de un modo de fallo en una
observación es la suma de los pesos de sus findings; la de un `fault_group`, la
suma de los de su grupo (y es el nivel al que buena parte del corpus real puede
puntuarse: quien dice «deterioro en rodamientos» no concreta la pista). Un
consumidor que no quiera pesos filtra por `label_quality` como hasta ahora y
los ignora — nada de lo anterior a 0.1.5 cambia.

**La masa que falta hasta 1 es «otros / no concluido» implícito**: lo que el
origen no diagnosticó. No hay que materializar un finding sumidero para ella —
ningún finding existe sin `source_text` y ahí no habría texto que citar. Ahora
bien, cuando el texto *sí* existe y es una parte del diagnóstico que ninguna
regla reconoce, el sitio de esa masa es el finding `unmapped` que esta spec ya
exige desde 0.1.0 (arriba): no es un sumidero inventado, es la cláusula que el
analista escribió y el extractor no supo leer. El extractor de informes lo hace
así (§3.3), y por eso sus observaciones suman exactamente 1: lo no cubierto
está nombrado, no implícito. Los dos comportamientos son legales; el implícito
es el de un productor que reserva masa sin texto que la respalde.

Efecto lateral útil: la masa `unmapped` agregada es una **medida de cobertura**
de las reglas GTxxx — qué fracción del juicio del analista sabe leer el
extractor —, y baja sola cuando entra una regla nueva.

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

### 3.3 Reglas de mapeo GTxxx (prosa de analista)

Las reglas viven en el extractor y se versionan como las IRxxx del t8-mapper:
cambiar la lógica de una regla obliga a nuevo id o sufijo de versión.

| Regla | Patrón (es) | fault_mode | grupo | calidad |
|---|---|---|---|---|
| GT001v2 | desequilibri- / desbalance- | IMBALANCE | IMBALANCE | direct |
| GT002 | desalineac- | — | MISALIGNMENT | group |
| GT003 | holguras rotacionales | LOOSENESS | LOOSENESS | direct |
| GT004 | holgura (genérica) | LOOSENESS | LOOSENESS | approximate |
| GT005 | debilidad estructural | LOOSENESS | STRUCTURE | approximate |
| GT006 | resonancia | RESONANCE | STRUCTURE | direct |
| GT007–GT010 | pista externa/interna, elementos rodantes, jaula (o BPFO/BPFI/BSF/FTF) | BEARING_* | BEARING | direct |
| GT011v2 | lubricaci- (con veto, §3.3.1) | BEARING_LUBRICATION | LUBRICATION | direct |
| GT012 | deterioro/fallo/desgaste de rodamiento sin concretar | — | BEARING | group |
| GT013 | eléctric- | ELECTRICAL_ROTOR | ELECTRICAL | approximate |
| GT014 | engran-/GMF | GEAR_WEAR | GEAR | approximate |
| GT015 | cavitaci- | CAVITATION | FLOW | direct |
| GT016 | correa | BELT_FAULT | BELT | direct |
| GT017 | álabe/rodete/VPF/impulsor | BROKEN_BLADE | FLOW | weak |
| GT018 | rozamiento | — | OTHER | group |
| GT019 | anclaje/bancada/pernos | LOOSENESS | STRUCTURE | approximate |

**GT020–GT024** (desde 0.1.4) cubren las familias que la auditoría de lectura
completa de los informes Bunge (2026-07-28 §3.8) encontró **repetidas** en el
`unmapped` — no casos raros, sino vocabulario habitual del analista sin regla:

| Regla | Patrón (es) | fault_mode | grupo | calidad |
|---|---|---|---|---|
| GT020 | distorsión armónica / variador de frecuencia / calidad de la energía | — | ELECTRICAL | group |
| GT021v2 | excentricidad (con veto, §3.3.1) | ELECTRICAL_ROTOR | ELECTRICAL | approximate |
| GT022 | excitación asíncrona / armónicos asíncronos / traza asíncrona | — | BEARING | group |
| GT023 | falta de rigidez / holgura estructural / pata coja | LOOSENESS | STRUCTURE | approximate |
| GT024 | ruido mecánico / ruido de origen eléctrico / ruido ultrasónico / cabeceo / fuga de… | — | OTHER | group |

GT022 se emite como `group` y no como `weak`: el origen no nombra ningún
`FaultMode` concreto —una excitación asíncrona en alta frecuencia es un
*precursor* de rodamiento o engrane, no el fallo— y el modelo normativo exige
`fault_mode` a toda calidad que no sea `group`/`unmapped` (§2.5). GT023 cruza
la agrupación a propósito, como GT005 y GT019.

**GT025** (desde `informes-gt-extract` 0.4.0) recoge lo que GT021 leía mal:

| Regla | Patrón (es) | fault_mode | grupo | calidad |
|---|---|---|---|---|
| GT025 | excentricidad en/de polea, polea excéntrica | — | BELT | group |

Es un fallo de la **transmisión**, no del rotor eléctrico. Se declara el grupo
y no el modo porque el único `FaultMode` de `BELT` es `BELT_FAULT` y el fallo
no es la correa sino la polea: el catálogo no tiene modo para eso y el
contrato prefiere `group` con `fault_mode` nulo a un modo cercano (§2.5).

#### 3.3.1 Vetos: la cláusula que afirma lo contrario

El patrón de una regla es una palabra y el analista escribe frases. Desde
0.4.0 una regla puede llevar un **veto**: un contexto en el que, aunque su
patrón esté en la cláusula, la regla **no dispara** porque la frase afirma lo
contrario de lo que la regla lee. El veto es por cláusula, la misma unidad en
la que se aplican las reglas.

| Regla | No dispara ante |
|---|---|
| GT011v2 | «buen estado de lubricación», «correcta/adecuada/eficiente lubricación», «sin problemas de lubricación» |
| GT021v2 | «excentricidad en polea» (la recoge GT025) |

«Mejorable» y «mejor estado de lubricación» quedan **fuera** del veto: la
primera es un fallo y la segunda es una nota de evolución favorable que el
reparto de pesos ya matiza, no una afirmación de buen estado. Y el veto de
GT011v2 lee palabras enteras: «Deficiente/Ineficiente lubricación» llevan
«eficiente» dentro y son fallos.

Las tres reglas versionadas en 0.4.0 (`GT001v2`, `GT011v2`, `GT021v2`) son las
lecturas que la lectura completa del corpus desmintió y que el reparto
contextual de pesos sólo pudo paliar (workplan 11). El sufijo `vN` versiona la
**lectura**: un finding ya emitido sigue diciendo qué regla lo produjo.

#### Textos de estado, no de fallo

Un diagnóstico sano, de parada, de no-medida o de fuera de servicio produce
`findings=[]` (§2.5). El vocabulario de «sano» de los informes no es sólo
«máquina en buen estado»: el analista escribe también «equipo», «conjunto»,
«motor», «reductor» o «rodamientos … en buen estado», y v0.1 emitía por ellos
un `unmapped` espurio. Desde 0.4.0 entra en ese vocabulario «buen estado de
lubricación», que además lleva el veto de GT011v2 (§3.3.1): sin las dos cosas
la cláusula era masa de juicio *y* fallo de lubricación.

La comprobación es **por cláusula** —el analista redacta el diagnóstico como
una lista separada por punto o por guion de viñeta—, no sobre el texto entero:
sólo si *todas* las cláusulas son de estado el diagnóstico es de estado. Un
«-Falta de rigidez / Resonancia… -Rodamientos en buen estado.» nombra un fallo
y una parte sana, y lo que manda es el fallo. Buscar la frase sana en el texto
completo (v0.1) tiraba los findings de las demás cláusulas.

Hay un tercer tipo de cláusula, que no es ni fallo ni estado: el **marcador de
severidad**. El analista repite dentro del texto la etiqueta global de la ficha
(«-Desequilibrio del ventilador. ALERTA. -Debilidad estructural.») y esa
palabra suelta no diagnostica nada. Se reconoce por el mismo vocabulario
cerrado que valida la cabecera (BUENO, SEGUIMIENTO, VIGILAR, ALERTA, PELIGRO,
MÁQUINA PARADA, MÁQUINA NO MEDIDA, FUERA DE SERVICIO, EN MANTENIMIENTO) cuando
ocupa la cláusula **entera**, y no participa en el reparto de la masa (§2.5).
En el corpus BUNGE son 44 de las 124 cláusulas que ninguna regla cubre.

#### Reparto de la masa por cláusulas (desde 0.1.5)

La cláusula es también la unidad del `weight` (§2.5), y por eso las reglas
GTxxx se aplican **por cláusula** y no sobre el texto entero:

1. Cada una de las `n` cláusulas de juicio —ni de estado ni marcador— recibe
   `1/n`, y la reparte a partes iguales entre los findings que produce.
2. Una cláusula de juicio que ninguna regla reconoce cede su `1/n` al finding
   `unmapped`.
3. Los findings de la misma etiqueta `(fault_group, fault_mode)` se funden
   sumando masa y quedándose con la regla de menor número.

El reparto es **uniforme a propósito**: es una línea base determinista,
reproducible y explicable en una frase, sin ningún parámetro que ajustar.
Ponderar por longitud de la cláusula, por su severidad o por el orden de
mención sería una hipótesis sobre cómo escribe el analista, y habría que
validarla contra él y no contra el texto.

Leer por cláusula tiene además un efecto colateral que no es de pesos: una
regla ya no puede casar **cruzando** cláusulas. La alternativa
`rodamiento.*deterior` de GT012 casaba «rodamientos del conjunto. Posible
deterioro» —dos frases distintas— y ahora cita el fragmento que de verdad
nombra el fallo.

Implementación de referencia: `ams_extract.informes` (workplan 09 de
ams-extract), el extractor de los informes Preditec de Bunge Cartagena.

### 3.4 Reglas de banda de alarma GT050-GT059 (origen `system-alarm`)

Una alarma de sistema no nombra un fallo: nombra una **banda del análisis**
que cruzó su umbral (`"DESEQUILIBRIO - 4.512 mm/Seg - D Alarm"`). La banda
la bautizó el analista al configurar la plantilla, así que su nombre es una
pista fuerte pero no una afirmación diagnóstica — de ahí una familia de
reglas propia, un escalón por debajo de la de prosa (§3.3) para el mismo
texto:

| Regla | Banda | fault_mode | grupo | calidad |
|---|---|---|---|---|
| GT050 | DESEQUILIBRIO | IMBALANCE | IMBALANCE | weak |
| GT051 | DESALINEACION | — | MISALIGNMENT | group |
| GT052 | HOLGURAS | LOOSENESS | LOOSENESS | weak |
| GT053 | FALLO ELECTRIC | ELECTRICAL_ROTOR | ELECTRICAL | weak |

Las bandas sin semántica de fallo (SUBSINCRONO, OVERALL VALUE, Mp Wave,
`11-40 X RPM`, `1 - 20 KHz`…) producen el finding `unmapped` obligatorio con
`fault_group="UNMAPPED"`: se declara, no se calla ni se fuerza.

Implementación de referencia: `ams_extract.export.diag_gt` (ADR-0018 de
ams-extract), que emite las alarmas `gdnl` de una base AMS.

### 3.5 Reglas del extractor sintético GT900-GT919 (origen `synthetic-truth`)

Bloque reservado para el extractor de verdad sintética, disjunto de las reglas
de prosa (§3.3) y de las de banda (§3.4). Hoy lo ocupa **una sola regla**,
porque hay una sola operación de mapeo y es la identidad: el origen no dice
«desequilibrio» en castellano, dice `IMBALANCE` — ya *es* el vocabulario
canónico.

| Regla | Patrón | fault_mode | grupo | calidad |
|---|---|---|---|---|
| GT900 | `FaultMode` inyectado | el mismo modo | el suyo (§3.2) | direct |

No hay regla de «sano»: una máquina sin fallo inyectado produce
`findings=[]`, como cualquier diagnóstico sano (§2.5). La diferencia con los
demás orígenes es que aquí ese vacío **afirma** la salud en vez de sólo no
afirmar nada, porque el productor es omnisciente: si no hay finding es que no
se inyectó nada, no que el analista no lo viera.

Tampoco hay `unmapped`: si la tabla de verdad nombrara un modo fuera del
catálogo canónico, el extractor **falla** en vez de emitir. Es el mismo
criterio de «no emitir lo no validado» aplicado a un origen que, por
construcción, no puede tener texto ambiguo — un modo desconocido ahí es un bug
del generador, no una imprecisión del origen.

Implementación de referencia: `vibsynth_metrics.diag_gt_export`, que emite la
verdad de construcción de los datasets demo de vibsynth.

## 4. Convenciones de fichero

```
<informes>/
├── <documento>.pdf                      # fuente (no se modifica)
└── ground-truth/
    ├── <documento>.diaggt.json          # un DiagGT por documento fuente
    ├── observations.parquet             # proyección completa (§5)
    ├── observations_consolidated.parquet # selección deduplicada (§5.1)
    ├── findings.parquet                 # findings completos y ordenados (§5.2)
    ├── materialization.json             # política, herramienta, inputs y hashes
    ├── crosswalk.csv                    # tabla explícita TAG ↔ machine_id (§2.4)
    ├── crosswalk_ambiguities.md         # no-matches y ambigüedades, con evidencia
    └── FORMATO_GROUND_TRUTH.md          # esta especificación
```

Los documentos de distinto `origin` conviven en el mismo directorio (los
`*.diaggt.json` del analista, del sistema y sintéticos) y **todos** entran en
la misma proyección completa. No se confunden: `origin` forma parte de la
clave de deduplicación, por lo que dos juicios de distinta naturaleza nunca
compiten. `observations_system.parquet` era una tercera vista con semántica
implícita y queda retirado en VibFrame 0.2.

`ground-truth/` es **un único directorio**, no dos: §2.4 dice que la tabla de
crosswalk se mantiene junto al dataset y este §4 la sitúa bajo
`<informes>/ground-truth/`, y no hay contradicción porque **`ground-truth/` es
precisamente el directorio copiable a la raíz del dataset VibFrame**. Se
produce junto a los informes (donde está el PDF fuente) y se copia entero al
dataset cuando se quiere el GT al lado del dato; `crosswalk.csv` viaja con él
porque el mapeo es específico de ese par (informes, dataset).

Integración con VibFrame: `ground-truth/` es un directorio raíz opcional y
reconocido por el contrato (`docs/VIBFRAME.md` de vibsynth-contracts), que los
productores no borran al re-exportar. No se tocan las particiones `machine=`
ni `machine.json`; la unión se hace por `dataset_machine_id` tras el crosswalk.

## 5. Proyecciones tabulares VibFrame 0.2

Los `*.diaggt.json` son la fuente documental. Las tablas son materializaciones
normativas, regenerables y verificables mediante `materialization.json`; no
son una segunda fuente de verdad. Todas usan esquemas PyArrow explícitos:
incluso una columna completamente nula conserva su tipo declarado.

### 5.1 Proyección completa (`observations.parquet`)

Una fila por observación de cada documento, **sin deduplicar**. La clave es
`(document_id, observation_id)`. Conserva `origin`, `record_kind`, la
identidad externa y el `dataset_machine_id` proyectado por el crosswalk, las
fechas documentales, estado, textos, contexto, `source_page` y `n_findings`.
No contiene `fault_modes` ni `fault_groups`: ambos se resuelven mediante el
join con `findings.parquet`, sin strings unidos por `+`.

`observed_at` e `inspection_date` son fechas ISO `YYYY-MM-DD`, no instantes.
Una fecha nombra el intervalo semiabierto de ese día en UTC; ningún writer
inventa hora ni zona para aumentar una precisión que el documento no declara.

### 5.2 Selección consolidada (`observations_consolidated.parquet`)

Cada fila es una fila elegida de la proyección completa, nunca una agregación.
La política `dedup-primary-latest/1.0` usa la clave
`(origin, normalized_tag, observed_at, modality)`: gana `primary`; entre
retrospectivos, el documento con `inspection_date` más reciente. La columna
`valid_to` contiene la fecha exclusiva de la siguiente observación de la
misma serie `(origin, normalized_tag, modality)`; `null` significa vigencia
abierta.

### 5.3 Proyección de findings (`findings.parquet`)

Una fila por finding de la **proyección completa**, alineada mediante
`(document_id, observation_id)`. `finding_index` es la posición 0-based en el
documento, contigua, y conserva orden y multiplicidad. Viajan además
`fault_mode`, `fault_group`, `label_quality`, `mapping_rule`, `weight`,
`source_text` y `matched_text`. Un consumidor de la vista deduplicada filtra
estos findings mediante join con `observations_consolidated.parquet`.

### 5.4 Procedencia (`materialization.json`)

Declara `$schema_version="0.2.0"`, `kind="gt_materialization"`, herramienta,
instante RFC 3339 UTC, política, cada input `*.diaggt.json` con SHA-256 y
número de observaciones, y los tres outputs con SHA-256 y filas. Se escribe
en la misma operación que las tablas para que el validador detecte una
proyección desfasada o mezclada.

No se emiten `observations.csv`, `findings.csv`,
`observations_system.csv` ni `observations_system.parquet` en VibFrame 0.2.

## 6. Qué NO cubre v0.1 (decisiones abiertas)

- **Severidad numérica**: los informes dan categorías, no severidad [0,1].
  Se decidió NO inventar un mapeo `status→severity`; si diagnostics lo
  necesita, que lo declare como política propia (p. ej. WATCH=0.3, ALERT=0.6,
  DANGER=0.9) y lo documente en su evaluación. Desde 0.1.3 hay un productor
  que recorre el camino **inverso** —`synthetic-truth` parte de la severidad
  de la inyección y tiene que llegar al `status`— y la spec le exige lo mismo:
  declarar la política, no esconderla. La primera declarada, por
  `vibsynth_metrics.diag_gt_export`, toma como cotas superiores las
  severidades representativas que sugiere el párrafo anterior:
  `0 → OK`, `≤ 0,30 → WATCH`, `≤ 0,60 → ALERT`, `> 0,60 → DANGER`, **sin
  banda muerta** (cualquier severidad inyectada distinta de cero es al menos
  WATCH, porque el fallo se conoce, no se mide). Sigue siendo política de
  productor, no del esquema: otro emisor sintético puede declarar otra, y por
  eso viaja escrita en `analysis_text` de cada observación.
- **Cadencia de observación**: DiagGT no dice cada cuánto se observa —el
  informe de analista lo hereda de su ruta— pero un productor que fabrica las
  fechas sí tiene que decidirlo. `synthetic-truth` declara una **ruta
  simulada**: la verdad se colapsa a día (`observed_at` es una fecha, §2.3)
  quedándose con el peor estado del día, y se observa el primer día, el
  último, todo día en que cambia el `status`, todo día en que cambia el
  **conjunto de modos inyectados** (aunque el `status` no se mueva: un fallo
  nuevo es noticia) y un suelo de N días entre observaciones. Los dos
  disparadores de cambio son los que hacen que las bandas caigan exactamente
  sobre las transiciones de la verdad; el suelo es lo que impide que una
  máquina sana quede muda en vez de afirmada sana.
- **Localización de componente**: «rodamientos de la bomba» localiza el
  fallo mejor que `machine_id` pero peor que un `point_id`. v0.1 lo deja en
  el texto; un futuro `component_ref` podría enlazar con nodos de
  `MachineDefinition`.
- **Matriz de estados coloreada**: la sección "Resumen Estado de Máquinas"
  del informe (17 páginas) codifica 12 inspecciones de estado por color de
  celda, sin texto. Extraerla daría **cadencia mensual completa de toda la
  planta**: son ~343 filas de máquina por informe contra las 138 que tienen
  ficha, es decir **209 máquinas que el DiagGT no conoce en absoluto**, y para
  ellas es la única fuente. Para las que sí tienen ficha es redundante con los
  diagnósticos previos (§3.3 del extractor de informes).
  **Corrección de 0.1.4**: hasta 0.1.3 esta spec decía que extraerla era leer
  el «color de rects del PDF». **No lo es**: las celdas se emiten como
  **imágenes** (`page.images`, ~2.000 por informe); los únicos `rects` con
  color de relleno son el gris del zebrado de fila. Sigue siendo una
  extracción determinista, pero la operación es leer el píxel de cada imagen y
  casar el color con el vocabulario `status` de §3.1, no inspeccionar
  atributos de relleno vectoriales. Antes de emitirla hay que decidir si el
  consolidado admite filas **sin texto** (`diagnosis_text=null`,
  `findings=[]`) y resolver el crosswalk de los ~209 TAGs nuevos.
- **Índice de figuras**: cada ficha de máquina lleva sus gráficos con pie
  («Tendencia de los valores globales…», «Espectros PeakVue…»), que el
  maquetador intercala con la prosa y que v0.1 dejaba pegados dentro de
  `analysis_text`. Separarlos es determinista (catálogo cerrado de arranques)
  y da además una **lista de la evidencia gráfica por máquina**, útil para
  saber qué miró el analista. El extractor de informes ya la emite como
  `figures: list[str]` en la observación primaria: es un campo **fuera del
  esquema**, que los lectores DiagGT ignoran por la regla de §7, y por eso no
  está en §2.3 ni en los modelos de `vibsynth-contracts`. Formalizarlo —o
  decidir que la evidencia gráfica no es asunto de DiagGT— es una decisión de
  una versión futura, porque añadir un campo al modelo normativo sí es un
  cambio de esquema.
- **Política de evaluación**: cómo puntuar un `DiagnosisResult` contra DiagGT
  (¿ventana de acierto?, ¿multi-etiqueta parcial?) es análogo a
  `EvaluationPolicy` de BenchmarkCase y queda para cuando exista el primer
  consumidor.
- **GT de calidad de dato**: `alarms.db` del T8 trae 15.114 eventos que no son
  juicios sobre la máquina sino sobre el **equipo de medida** (sensor fuera de
  rango o de límites, tensión de bias, error de cálculo de un parámetro,
  adquisición sin tacómetro). Son excelente ground truth de *cuándo un canal
  no es fiable* —una ventana de dato sospechoso— pero DiagGT v0.1.x modela el
  estado de la **máquina**, no el del instrumento: no hay `status`, ni
  `modality`, ni `fault_group` que les corresponda, y meterlos forzaría a
  mentir en los tres. Quedan sin emitir a propósito (`t8_extract.ground_truth`
  los cuenta y los declara en el resumen). Si algún día hacen falta, el
  candidato es un **formato hermano** con su propio `kind` —misma procedencia,
  otro sujeto— antes que un `origin` más dentro de DiagGT.
- **Precisión temporal**: `observed_at` es una **fecha** y una alarma es un
  **instante**. Hoy el instante completo no se pierde —viaja en el
  `observation_id` (`…:2026-04-20T07:31:12Z:L2`) y en el verbatim de
  `analysis_text`— pero un consumidor que agrupe por `observed_at` pierde la
  resolución y no puede ordenar dos eventos del mismo día. Subir la precisión
  del campo (cambiar el tipo, o añadir un `observed_at_us` opcional al lado)
  es un cambio de esquema y por tanto decisión de una versión futura: los
  informes de analista, que son el otro productor, sí son genuinamente
  diarios y no ganan nada con ello.
- **Eventos de mantenimiento**: las intervenciones se infieren del texto
  («tras su intervención…»). Un `record_kind="intervention"` sería la
  extensión natural cuando haya fuente estructurada (CMMS).

## 7. Compatibilidad

- **Implementación de referencia**: los modelos Pydantic de
  `vibsynth_contracts.diagnosis.external` (`DiagGTDocument`, `DiagGTProvenance`,
  `DiagGTObservation`, `DiagGTMachineRef`, `DiagGTFinding` + vocabularios) son
  la versión normativa del esquema; el CLI `vibframe-validate` de
  vibsynth-contracts los aplica a los `*.diaggt.json` que encuentre en
  `<dataset>/ground-truth/`.
- **Productores conocidos**: `ams_extract.export.diag_gt` (`system-alarm`,
  alarmas `gdnl` de AMS), `ams_extract.informes` (`inspection-report`, los
  informes PDF de Preditec para Bunge; el único que emite `weight` hoy),
  `t8_extract.ground_truth` (`system-alarm`, `alarms.db` del T8) y
  `vibsynth_metrics.diag_gt_export` (`synthetic-truth`, verdad de construcción
  de los datasets sintéticos).
- Lectores DiagGT deben ignorar campos desconocidos (regla VibFrame).
- Añadir campo opcional o valor de vocabulario ⇒ sube versión menor;
  cambiar semántica de campo existente ⇒ versión mayor.
- El texto verbatim (`diagnosis_text`, `analysis_text`,
  `recommendation_text`) es el contrato de último recurso: cualquier
  re-mapeo futuro (mejores reglas GTxxx, LLM, revisión humana) debe poder
  regenerar `findings` sin volver al PDF.

**Nota (2026-08-05)**: la regla de arriba dice que añadir un campo opcional
sube versión **menor**, pero la práctica de toda la serie 0.1.x ha movido el
**tercer** dígito para todo — incluido `weight`, el campo opcional nuevo de
0.1.5. La discrepancia se anota, no se resuelve aquí: reconciliarla (cambiar la
regla o renumerar la serie) es decisión normativa del autor.
