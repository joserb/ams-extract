---
status: completed
created: 2026-07-27
updated: 2026-07-28
---

# Plan: ground truth de diagnóstico externo (DiagGT) desde los informes Preditec

**Fecha**: 2026-07-28 · **Estado**: **COMPLETADO**. Formato DiagGT
especificado (v0.1.4) con modelos normativos en `vibsynth-contracts`
(ADR-0016) y validador `vibframe-validate` con goldens por origen; los 6
informes BUNGE 2026 extraídos y verificados (**6.669 observaciones del
analista** tras el fix de geometría de columnas de la auditoría, Hecho §10-§12);
crosswalk contra `bunge_cartagena_ams` resuelto (273/283 tags, 95,9 % de
observaciones; 10 restantes descartados por decisión); overlay DiagGT en el
visor `vibframe-viewer`; y las dos fuentes `system-alarm` emitidas: `gdnl` de
AMS (973 obs, ADR-0018, validación 991/991 contra `pdla`) y `alarms.db` del T8
(91 obs en 3 datasets, workplan 05 de t8-extract). `bunge_cartagena_ams`
re-exportado con ADR-0017 y en PASS permanente de `vibframe-validate` (347
máquinas, 7 documentos DiagGT, **7.642 observaciones**, 0 errores). Flecos
supervivientes al final del documento.

## Contexto

Los informes mensuales de inspección de Preditec para BUNGE Cartagena
(`../Informes Bunge Cartagena 2026/*.pdf`, 6 documentos, ene–jun 2026,
~145–190 págs cada uno) contienen el diagnóstico del analista por máquina:
estado (Bueno/Seguimiento/Alerta/Peligro/Parada/No medida), diagnóstico,
análisis y recomendación por modalidad (vibraciones, inspección visual,
ultrasonidos), más los diagnósticos previos fechados. Es exactamente el
*ground truth* externo que falta en el ecosistema VibFrame para evaluar
diagnostics sobre datos reales (el dataset `bunge_cartagena_ams` exportado por
este repo cubre las mismas máquinas, 2013–2026).

Revisión previa de los proyectos hermanos (vibsynth-contracts,
vibsynth-diagnostics, vibsynth-metrics-mapper, este repo): existen tres GT
(`FailureModeCase` sintético embebido en `machine.json`, `ground_truth.csv`
de fleet_demo, `BenchmarkCase` v3 del peak-finder) y ninguno representa un
diagnóstico externo: faltan procedencia del juicio (analista, documento,
hash), fecha de observación por inspección y vocabulario para diagnósticos
que no concretan `FaultMode`. De ahí el formato nuevo.

## Hecho

1. **Formato DiagGT v0.1.0** — especificado en
   [`../GROUND_TRUTH.md`](../GROUND_TRUTH.md) (copia de referencia también en
   `../Informes Bunge Cartagena 2026/ground-truth/FORMATO_GROUND_TRUTH.md`).
   Ideas clave: un JSON por documento fuente con `provenance` del juicio
   (proveedor, analistas, sha256 del PDF, periodo de medida); observación =
   (máquina, fecha, modalidad) con `record_kind` primary/retrospective; texto
   verbatim como contrato de último recurso; findings con
   `fault_mode`/`fault_group` + `label_quality`
   (direct/approximate/weak/group/unmapped) + `mapping_rule` GTxxx — el
   patrón `canonical_metric`/`proxy_quality`/`mapping_rule` del t8-mapper
   aplicado a diagnósticos; `status` canónico proyectado a la escala `alarm`
   int8 de `trends.parquet` (OK=0, WATCH=1, ALERT=2, DANGER=3, coherente con
   ADR-0012); crosswalk no destructivo TAG de planta ↔ `machine_id` VibFrame
   (`normalized_tag` ⊂ `norm(machine_id)`).

2. **Extractor** —
   `../Informes Bunge Cartagena 2026/ground-truth/extract_informes_gt.py`
   (pdfplumber + pandas, sin dependencias de vibsynth). Parsea las fichas de
   máquina a dos columnas por coordenadas (corte en x=297), la portada,
   alcance/rutas, analistas y listados de paradas/no medidas.

3. **Extracción y verificación** — salidas en
   `../Informes Bunge Cartagena 2026/ground-truth/`: 6 `*.diaggt.json` +
   consolidado `observations.parquet`/`.csv` (una fila por máquina × fecha ×
   modalidad, dedupe primary > retrospective más reciente). Cifras: 1.679
   observaciones primarias + 651 retrospectivas → 1.881 filas, 283 máquinas,
   2025-04-22 → 2026-06-25; estados: 1.054 OK / 90 WATCH / 76 ALERT / 28
   DANGER / 512 STOPPED / 43 NOT_MEASURED / 2 OUT_OF_SERVICE / 76 UNKNOWN
   (retrospectivos sin estado declarado, semántica documentada).
   Verificación: 100 % de fichas parseadas en los 6 informes (recuento de
   páginas con `DIAGNÓSTICO:`), fidelidad 240/240 muestras aleatorias contra
   el texto crudo de página, y contraste visual página↔JSON (PM.9121A mayo).

4. **Revisión de `t8-extract`** (2026-07-27, repo en
   `~/wslprojects/RESONINS/t8-extract`, HEAD `869abc6`) — **DiagGT es
   compatible**; hallazgos:
   - t8-extract no tiene ninguna representación propia de GT/diagnóstico; su
     única señal de estado es la columna `alarm` int8 0–3 nullable de
     `trends.parquet`, passthrough del protobuf T8 (la alarma de máquina
     cuelga de la métrica reservada `speed`). La escala coincide con la
     proyección DiagGT §3.1.
   - El visor `vibframe_viewer` descubre datasets por `dataset.json` y
     particiones por `glob("machine=*")`: un `ground-truth/` extra en la raíz
     del dataset **se ignora limpiamente** y sobrevive a re-extracciones
     (el extractor no limpia el directorio de salida). No sirve ficheros del
     dataset: el overlay de observaciones exigiría un endpoint nuevo
     (`server.py`) + bandas en `timeline.js` (`setBands()`; hoy ni
     `layout.shapes` ni `annotations` de Plotly se usan — terreno libre).
   - Crosswalk aplicable también a T8: `machine_id = sanitize(tag)` = nombre
     de partición, ya normalizado. Avisos: el nombre legible va en
     `machine.name` (≠ id), y la unicidad global requiere
     `(dataset, machine_id)` — el visor ya usa esa clave.
   - Fricciones de spec detectadas (no de código): `MachineDoc.ground_truth`
     ya significa `FailureModeCase` sintético (misma palabra, otro concepto);
     `mapping_rule` existe en `metrics.parquet` con namespace Rxxx/IRxxx (el
     prefijo GTxxx desambigua, dejarlo explícito); `STOPPED`/`NOT_MEASURED`
     no caben en 0–3 (no escribir jamás en `trends.parquet`, mantener la
     proyección en `observations.parquet`); el futuro CLI `vibframe-validate`
     (workplan 03 de t8-extract, Parte 2) podría rechazar directorios no
     declarados, y el visor se muda a repo propio (Parte 1) — timing crítico
     para registrar `ground-truth/` en `VIBFRAME.md`.
   - El backup T8 trae fuentes «casi-GT» aún sin extraer (`data/alarms.db`,
     `annotations/*.json`, FORMATO-BACKUP-T8 §): candidatas naturales a
     emitirse como DiagGT con `origin` propio, simétrico al punto gdnl de
     AMS.

5. **Crosswalk `normalized_tag` → `machine_id`** (2026-07-27) — script
   reproducible
   `../Informes Bunge Cartagena 2026/ground-truth/crosswalk_gt.py`
   (pandas + stdlib; se ejecuta *después* de `extract_informes_gt.py`, que
   regenera el consolidado sin la columna). Contra el dataset
   `~/wslprojects/RESONINS/datasets/bunge_cartagena_ams` (347 particiones
   `machine=`):
   - **Cobertura**: 283 `normalized_tag` únicos → **273 con
     `dataset_machine_id` (96,5 %)**, 1 colisión inversa, 9 sin match; **1.801
     de 1.881 filas de `observations.parquet` (95,7 %)**; **273 de 347
     máquinas del dataset (78,7 %) con ≥1 observación DiagGT** (240 de ellas
     con `trends.parquet` que alcanza la ventana del GT). Aviso de añada: el
     `.rbm` exportado llega a 2026-03-26 y el GT a 2026-06-25, así que sólo
     383 de las 1.801 filas mapeadas caen dentro de la cobertura temporal de
     su máquina; para evaluar contra los diagnósticos de abr–jun 2026 hace
     falta re-exportar un `.rbm` más reciente (limitación del dato, no del
     crosswalk).
   - **Reglas CWxxx** (versionadas como las GTxxx): la regla base de la spec
     (`normalized_tag` ⊂ `norm(machine_id)`) dejaba **8 tags con varios
     candidatos** (p. ej. `PM.700` casaba con `PM_700`, `PM_7001`, `PM_7002`,
     `PM_7006A/B`), así que se refina por nivel de match: CW001 `exact_suffix`
     (el tag es la concatenación de los últimos tokens del `machine_id`) >
     CW002 `delimited` (secuencia completa de tokens, no final) > CW003
     `substring` (regla base); gana el nivel más fuerte y sólo se rellena si
     deja un único candidato. Las 8 ambigüedades se resuelven así sin
     intervención manual (todas por CW001). CW004 añade unicidad inversa: un
     `machine_id` no puede colgar de dos tags (`MA.9306` cede ante `MA.9306B`,
     que es su match exacto, y queda sin match).
   - **Validación**: el área del informe (`area_name`) coincide con
     `machine.path` del dataset en **273/273** matches (0 discrepancias), y
     todas las particiones referenciadas existen. Los 9 sin match son reales
     (equipos que el dataset no exporta o que AMS nombra sin TAG); no se
     fuerza ninguno.
   - **Salidas**: `crosswalk.csv` (tabla explícita, 283 filas con regla,
     nivel y candidatos), `crosswalk_ambiguities.md` (los 10 sin resolver con
     candidatos y resolución propuesta, las 8 ambigüedades resueltas con la
     cobertura temporal de cada candidato como evidencia, y las 74 máquinas
     del dataset sin GT) y `observations.parquet`/`.csv` regenerados con la
     columna `dataset_machine_id` insertada tras `normalized_tag` (el resto de
     columnas idéntico, verificado con `DataFrame.equals`).
   - **Decisión de no-destructividad**: la spec es ambigua (§2.4 declara
     `dataset_machine_id` en el `machine` del JSON, pero manda mantener el
     crosswalk en «una tabla explícita»). Se opta por **tabla aparte +
     consolidado**: los `*.diaggt.json` no se tocan (siguen siendo salida pura
     del extractor, con su `extracted_at` y su hash de PDF), `crosswalk.csv`
     es la fuente del mapeo y el consolidado su proyección para el join.
   - **Casos abiertos documentados** (no aplicados): `PM.OSMOSIS1/2` ↔
     `Bomba_Centrifuga_PM_1001/1002` (misma área OSMOSIS, mismo tipo, mismo
     cardinal, ninguna reclamada por otro tag) y los 3 agitadores `AG.80xx` de
     PARQUE DE TANQUES, que existen en el dataset pero AMS nombra sin TAG
     (`AGITADOR`, `AGITADOR_1..3`, `MEZCLADOR`). Ambos exigen la lista de
     equipos de planta; la vía es una entrada manual en `crosswalk.csv`.
   - **Fricciones de spec detectadas** (para v0.1.1 de `GROUND_TRUTH.md`):
     (a) la regla de crosswalk de §2.4 (subcadena) es demasiado laxa — genera
     falsos positivos en TAGs numéricos que son prefijo de otros; conviene
     elevar CW001/CW002/CW004 a la spec; (b) §5 no lista
     `dataset_machine_id` entre las columnas del consolidado aunque §2.4 lo
     exige; (c) §2.4 dice que la tabla de crosswalk se mantiene «junto al
     dataset» y §4 sitúa las salidas en `<informes>/ground-truth/` — se
     resuelve manteniéndola en `ground-truth/`, que es justamente el
     directorio que §4 declara copiable a la raíz del dataset.

6. **`ground-truth/` registrado en `VIBFRAME.md`** (2026-07-27,
   vibsynth-contracts) — directorio raíz **opcional** en el layout, con regla
   general nueva: la raíz del dataset es abierta y las herramientas deben
   tolerar entradas top-level no reconocidas (los validadores pueden avisar,
   no rechazar — blindaje frente al futuro `vibframe-validate`). Sección
   dedicada con referencia normativa a la spec de este repo
   (`docs/GROUND_TRUTH.md`, citada, no copiada), el join por
   `dataset_machine_id`, la proyección de `status` a la escala `alarm` 0–3,
   el namespace GTxxx disjunto del Rxxx/IRxxx y la prohibición de escribir
   `STOPPED`/`NOT_MEASURED` en `trends.parquet`. Tabla comparativa
   `MachineDoc.ground_truth` (FailureModeCase sintético) vs DiagGT.
   Decisión: el empaquetado `.vibframe.zip` **sí** incluye `ground-truth/`
   (una frase-restricción; la sección de empaquetado es la Parte 3 del
   workplan 03 de t8-extract). Sin subir versión del contrato (0.1.0): cambio
   aditivo que no altera columnas ni campos, justificado en la sección de
   versioning.

7. **Spec DiagGT v0.1.1** (2026-07-27) — [`../GROUND_TRUTH.md`](../GROUND_TRUTH.md),
   cambios acotados con las fricciones de Hecho §5, sin reestructurar:
   - §2.4: la regla «subcadena» se sustituye por las **reglas versionadas
     CW001 `exact_suffix` > CW002 `delimited` > CW003 `substring` + CW004
     unicidad inversa** (gana el nivel más fuerte; sólo se rellena
     `dataset_machine_id` si ese nivel deja un candidato único), y se fija
     dónde vive el mapeo: `crosswalk.csv` es la **fuente**, el consolidado su
     **proyección**, y los `*.diaggt.json` no se tocan (salida pura del
     extractor).
   - §4: `crosswalk.csv` y `crosswalk_ambiguities.md` entran en la lista de
     ficheros, y se resuelve la aparente contradicción «junto al dataset» vs
     `<informes>/ground-truth/`: es el mismo directorio, porque
     `ground-truth/` es justamente el copiable a la raíz del dataset.
   - §5: `dataset_machine_id` se lista entre las columnas del consolidado.
   - Cabecera: versión 0.1.1 con nota de cambios y declaración de que el
     **hogar del contrato pasa a `vibsynth-contracts`** (modelos normativos),
     quedando este documento como spec de referencia — patrón ADR-0009,
     registrado en **ADR-0016**.
   - Los documentos que declaran `$schema_version: "0.1.0"` siguen siendo
     válidos: 0.1.1 no añade obligaciones.

8. **Contrato DiagGT en `vibsynth-contracts`** (2026-07-27, Parte 2 del
   workplan 03 de t8-extract, ejecutada allí; detalle y pendientes en
   `vibsynth-contracts/docs/workplans/01-conformidad-vibframe.md`):
   - **Modelos** `vibsynth_contracts/diagnosis/external.py`: `DiagGTDocument`,
     `DiagGTProvenance`, `DiagGTObservation`, `DiagGTMachineRef`,
     `DiagGTFinding`, `DiagGTOperatingContext` + vocabularios y las tablas
     `STATUS_ALARM` / `FAULT_GROUP_MODES`. Reglas que el modelo sí impone:
     `alarm` coherente con la proyección de `status`, `label_quality` ⟺
     presencia de `fault_mode`, `unmapped` ⟺ `fault_group=UNMAPPED`,
     `mapping_rule` en el namespace GTxxx, `observation_id` único.
     **Los 6 informes reales validan sin cambios** (2.321 observaciones).
     Deliberadamente NO se valida que `fault_mode` pertenezca a su
     `fault_group`: GT005/GT019 cruzan la agrupación a propósito.
   - **CLI `vibframe-validate`** (layout, JSON contra los modelos, columnas y
     tipos de los parquet, métricas reservadas, join trends↔metrics, escala de
     `alarm`, longitud de arrays y los DiagGT de `ground-truth/`), con las dos
     reglas duras de `VIBFRAME.md`: las entradas top-level desconocidas son
     informativas y el GT inválido es aviso (error sólo con `--strict`).
   - **Goldens** por origen (`t8-backup`, `ams-rbm`, `vibsynth`), recortados de
     datasets reales; el de `ams-rbm` sale de `bunge_cartagena_ams` y lleva un
     `ground-truth/` mínimo (DiagGT de 3 observaciones + `crosswalk.csv`).
   - **Hallazgo de conformidad de este repo**: `rbm export` escribe
     `waves.n_samples` con el valor **nominal** del modo (512, 4096, 256)
     mientras el array almacenado tiene otra longitud (488, 4148, 244) — 311
     de las 347 máquinas de `bunge_cartagena_ams`. Es el único incumplimiento
     del dataset: columnas, tipos, join trends↔metrics y escala de `alarm`
     pasan limpios en las 347. **Arreglado el mismo día** en el export
     (ADR-0017, Pendiente §3); el dataset publicado necesita re-export.
   - Sin subir `SCHEMA_VERSION` de VibFrame (sigue 0.1.0): añadir el origen
     `t8-api` al literal `Origin` es aditivo y no cambia la forma de ningún
     campo ni columna; además la constante está vendorizada aquí y en
     t8-extract, así que un bump obligaría a una edición coordinada a cambio
     de nada.

9. **Alarmas nativas de AMS (`gdnl`) → DiagGT `origin="system-alarm"`**
   (2026-07-27, ADR-0018; era el Pendiente §4 de este plan):
   - **Ingeniería inversa** (FORMAT §5.9): el informe de alarma que AMS
     enseña por punto vive en `vdpm.0x1E4 → gdsc → 0x38 → gdnl`. El `gdsc`
     aporta la **fecha de la medida analizada** (`0x1C`), un **índice de
     severidad 0-100** (`0x1A`: 1-40 zona C, 41-100 zona D), el usuario y
     una fecha de revisión derivada (`0x24` = `0x1C` + 30 días). El `gdnl`
     es texto cp1252 de dos líneas: encabezado (español o inglés según el
     código de formato `gdsc.0x18` = 13 / 20 / 51) y `"<banda> - <valor>
     <mm/Seg|G-s> -  <C|D> Alarm"`. **Es una foto, no un histórico**: AMS
     la sobrescribe en cada análisis por excepción. En BUNGE: 5.783 `gdnl`,
     4.970 colgando de puntos vivos, **991 en alarma** (462 C + 529 D).
   - **Validación** (VERIFICATION §«Alarmas almacenadas»): `gdsc.0x1C`
     coincide con el timestamp de una muestra del punto en **4.648/4.648**
     (100 %, y en 4.627 con la más reciente); el valor del texto cae en el
     intervalo de su nivel contra los umbrales `pdla` del punto (§5.8) en
     **991/991 (100 %)** sin tolerancia — test de nulidad barajando sets:
     53,8 % en las alarmas C; y la zona de severidad concuerda con el nivel
     del texto en **991/991**. La severidad C se ajusta además a
     `1 + 40·(v − C)/(D − C)` en 461/462 (±1).
   - **No emitido**: 18 alarmas (1,8 %) con el código de unidad del `pdla`
     en desacuerdo con la unidad del texto (15 `1 - 20 KHz` de PM-0CI/1-3,
     3 `Mp Wave` en sets HF) — plantillas mal configuradas en AMS; se
     cuentan y quedan documentadas, no se publican.
   - **Código**: `records/alarm_note.py`, `tree.walk_alarm_note`,
     `models.AlarmNote`, `export/diag_gt.py` y el comando **`rbm alarms`**
     (JSON siempre; `--consolidate` añade `observations_system.parquet`
     /`.csv`, fichero propio que no toca el consolidado del analista).
     39 tests nuevos (18 unitarios de récord, 17 de export, 4 de
     integración que fijan las cifras de BUNGE).
   - **Emitido**: `bunge_cartagena_ams/ground-truth/BUNGE CARTAGENA marzo
     2.0.diaggt.json` — **973 observaciones** (461 ALERT + 512 DANGER),
     **235 máquinas**, 2013-08-14 → 2026-03-26, con `dataset_machine_id`
     resuelto en el 100 % (el productor conoce el `machine_id`: no hace
     falta crosswalk) y `normalized_tag` compatible con el del analista
     (`AG-100` y `AG.100` → `AG100`). `vibframe-validate`: PASS.
   - **Spec**: `GROUND_TRUTH.md` §3.4 añade la familia de reglas
     **GT050-GT053** (banda en alarma = evidencia, no diagnóstico: calidad
     `weak`/`group`, un escalón por debajo de las reglas de prosa) y §4 el
     consolidado propio. `extraction_method` queda `null`: el vocabulario
     no contempla un decode binario (propuesto `"binary_decode"`).

10. **Auditoría de cobertura por lectura completa** (2026-07-28) —
    `../Informes Bunge Cartagena 2026/ground-truth/audit-lectura-completa-mayo-2026.md`.
    Lectura íntegra de las 167 páginas del informe de Mayo (el mayor y el de
    más anomalías estructurales), con los contadores calculados sobre los 6.
    Veredicto: el extractor determinista **no** tenía un problema de
    comprensión de texto libre sino de **geometría de columnas**. La sospecha
    de partida (texto ad-hoc valioso fuera del formato de ficha) se confirma
    sólo en parte —hay **un único** estudio especial en 921 páginas, el bloque
    «ACTUALIZACIÓN» de `TC.1523A2` en Abril pp. 134-136—, y la pérdida grande
    resultó estar *dentro* de las fichas: **el 87 % de los diagnósticos
    retrospectivos** (4.348 de 4.999). Lo bueno queda confirmado: detección de
    fichas 826/826, `provenance` completo, paradas/no-medidas correctas y
    reparto por modalidad correcto.

11. **Extractor v0.2.0 — el fix determinista de la auditoría** (2026-07-28,
    prioridad 1 de §5.1 de la auditoría; sigue siendo
    `extraction_method="pdf_text_parse"`, sin pasada LLM):
    - **(a) Previos de las cuatro fuentes.** `parse_machine_page` sólo miraba
      `right["DIAGNÓSTICOS PREVIOS:"]`, pero el maquetador coloca el bloque en
      la **izquierda** siempre que la ficha es simple (la derecha queda para
      los gráficos), que es el caso del ~80 % de las máquinas. Ahora se unen
      izquierda/derecha × sección/`_pre` y se deduplica por (fecha,
      modalidad), ganando el texto más largo ante un reflujo partido.
    - **(b) Páginas de continuación.** Si una página no es ficha pero casa
      `PREV_DIAG_RE`, sus entradas se arrastran a la **última ficha vista**:
      6 páginas en el corpus (Enero p73, Marzo p64, Abril p72 y p136, Mayo p88
      y p94), 39 entradas, atribución inequívoca. La auditoría dice «5
      páginas» en el texto de §3.3 pero enumera 6 en la misma frase; son 6.
      Abril p136 es a la vez continuación de `TC.1523A2` **y** cola del
      estudio ad-hoc, con la p135 (que no lleva anclas) en medio.
    - **(c) Pie de página en `column_text`.** La columna derecha no tenía cota
      inferior, así que el número de página caía dentro de la última sección y
      se pegaba al último diagnóstico previo: **57 textos** saneados
      (`"Máquina parada 77"`, `"Cabeceo de la máquina. 74"`). Se pasa la misma
      banda `45 < top < height − 40` que ya usaba la detección de título, en
      las dos columnas. El recorte `y_min=100` de la derecha baja a 45: el
      bloque de previos arranca a veces por encima de 100 y su cabecera se
      perdía (§3.2, 46 fichas / 242 entradas).
    - **(d) `global_status_label` con vocabulario cerrado** y banda **anclada
      al `Área:`** en vez de al `top` absoluto. La ventana fija recogía la
      línea de RPM o el título; y en la primera ficha de cada área, que baja
      ~45 pt por el epígrafe «2 Análisis», se perdía además el estado por
      modalidad (`TC.1523A2` de Abril pasaba de DANGER a UNKNOWN en inspección
      visual). De **20 valores distintos a 7**: 276 observaciones con la
      etiqueta arreglada y 127 `status_source_label` corregidos.
    - **(e) Pies de figura fuera del texto.** Catálogo cerrado de arranques
      (`Tendencia…`, `Espectros?…`, `Evolución…`, `Firmas…`, `Formas de
      onda…`, `Comparación…`) más la regla de continuación «la línea siguiente
      arranca en minúscula» —los pies parten a mitad de sintagma y la prosa
      reabre con mayúscula—. 346 pies separados de `analysis_text`, que además
      queda **continuo** cuando el análisis seguía después del pie. Se emiten
      como `figures: list[str]`, campo **fuera del esquema** que los lectores
      DiagGT ignoran (spec §7): formalizarlo exigiría tocar los modelos de
      contracts y queda anotado en la spec §6, no hecho.
    - **(f) Reglas GT020–GT024 y vocabulario de «sano».** `unmapped` del
      **10,4 % al 2,3 %** (73 → 29 findings). GT022 se emite `group` y no
      `weak` como proponía la auditoría: el modelo normativo exige
      `fault_mode` a toda calidad que no sea `group`/`unmapped`, y una
      excitación asíncrona no nombra ningún modo concreto. Además el
      cortocircuito de «texto sano» pasa a evaluarse **por cláusula**: con
      `search` sobre el texto entero, ampliar `HEALTHY_RE` a «equipo /
      rodamientos en buen estado» tiraba los fallos de un
      «-Falta de rigidez / Resonancia… -Rodamientos en buen estado.» (24
      observaciones detectadas en la comparación antes/después).
    - **Invariante de anclas** dentro del extractor: por ficha, las anclas
      `-DD/MM/AAAA: (Modalidad)` del cuerpo de la página tienen que ser
      exactamente las que suman las cuatro fuentes. **826/826 fichas, 4.960 =
      4.960**; el extractor aborta si alguna no cuadra. Es el test que fija la
      geometría: si una futura maquetación vuelve a esconder texto, salta.
    - **Desempate del consolidado**: el dedupe de retrospectivos ordenaba por
      `document_id`, que lleva la fecha en DDMMAA y **no ordena
      cronológicamente** (`…-250526` < `…-260226`). Pasa a `inspection_date`
      ISO, que es lo que la spec §5 pide («gana el del documento más
      reciente»).

12. **Cifras de la re-extracción** (2026-07-28) — antes → después:
    - `*.diaggt.json`: 2.321 → **6.669 observaciones** (1.670 primarias
      inalteradas + 651 → **4.999 retrospectivas**, el 100 % de las anclas del
      PDF).
    - Consolidado: 1.881 → **3.379 filas** (+1.498 únicas, **+80 %**), **0
      filas perdidas**, 283 `normalized_tag` (los mismos).
    - De las 1.498 nuevas, **112 con texto de fallo real** (el resto son
      etiquetas negativas: 901 sanas, 479 paradas, 6 no medidas), de las que
      **102 mapean a grupo** — STRUCTURE 45, LOOSENESS 20, BEARING 19,
      LUBRICATION 15, ELECTRICAL 14, IMBALANCE 13, OTHER 12, MISALIGNMENT 6,
      FLOW 2 — y 10 quedan `unmapped`.
    - `findings`: 702 → 1.286; `unmapped` 73 (10,4 %) → **29 (2,3 %)**.
    - Rango temporal **2025-04-22 → 2026-06-25, sin cambio**: la profundidad
      es lo que crece (2025-04-22 pasa de 12 a 114 filas; 2025-07-25 de 14 a
      221). La auditoría anuncia «8 fechas nuevas, histórico hasta
      2025-04-22», pero eso es cierto **contra las observaciones primarias**
      (que arrancan en 2026-01-26), no contra el consolidado de v0.1, que ya
      llegaba a 2025-04-22 con los 651 retrospectivos que sí leía. **No hay
      fechas nuevas**: son las mismas 14.
    - Verificación: **fidelidad muestral 150/150** (25 retrospectivos
      aleatorios por informe, semilla fija) contra el texto de la columna
      extraído por `page.crop().extract_text()` —el motor de layout propio de
      pdfplumber, vía independiente de `words_to_lines`—, con el script
      reproducible `ground-truth/verify_previous.py`.
    - Crosswalk re-ejecutado: 283 tags → 273 resueltos (96,5 %), **3.239 de
      3.379 filas (95,9 %)**, 273 de 347 máquinas del dataset, **0
      discrepancias de área**. Contrato de columnas del consolidado
      **idéntico** (mismos nombres, mismo orden, mismos dtypes) — el visor lo
      lee sin cambios.
    - `vibframe-validate --strict` sobre `bunge_cartagena_ams`: **PASS**, 347
      máquinas, 7 documentos DiagGT, 7.642 observaciones, 0 errores, 0 avisos.

13. **Spec DiagGT v0.1.4** (2026-07-28) — [`../GROUND_TRUTH.md`](../GROUND_TRUTH.md),
    retrocompatible, sin tocar el esquema (mismo patrón que GT050 en 0.1.1 y
    GT900 en 0.1.3: las reglas GTxxx viven en el extractor y `mapping_rule` es
    una cadena libre del namespace GT):
    - §3.3: tabla **GT020–GT024**, la nota de por qué GT022 es `group` y no
      `weak`, y un apartado nuevo sobre **textos de estado y no de fallo** con
      la regla de comprobación por cláusula.
    - §6: se corrige la asunción errónea sobre la **matriz coloreada** —las
      celdas son **imágenes** (`page.images`, ~2.000 por informe), no `rects`
      con color de relleno; los únicos `rects` coloreados son el zebrado gris
      de fila— y se dimensiona lo que aporta (209 máquinas sin ficha). Entra
      la decisión abierta del **índice de figuras**.
    - Pendiente en `vibsynth-contracts` (fuera del alcance de esta sesión):
      subir `DIAGGT_SCHEMA_VERSION` a `"0.1.4"` y la cita de la spec en el
      docstring de `diagnosis/external.py`. Es documentación, no contrato: los
      modelos no cambian y los documentos siguen declarando `"0.1.0"`.

## Limitaciones conocidas (v0.2)

- **La matriz coloreada "Resumen Estado de Máquinas"** sigue sin extraerse.
  Es el fleco grande: 17 páginas por informe, ~343 filas de máquina contra
  las 138 con ficha, es decir **209 máquinas de planta que el DiagGT no
  conoce**, y ~2.000 celdas pintadas por informe. Para las 138 con ficha es
  redundante con los previos ya recuperados; **el valor está en las otras
  209**. Corregida en la spec la asunción de v0.1: las celdas son
  **imágenes**, no `rects` con color de relleno, así que la extracción es
  leer el píxel de cada `page.images` y casarlo por coordenada (fila, columna
  de fecha). Antes hay que decidir si el consolidado admite filas sin texto y
  resolver el crosswalk de 209 TAGs nuevos. Paso separado y posterior, como
  recomienda la auditoría §5.1(g).
- **`ANÁLISIS` desbordado a la columna derecha** (auditoría §3.5): cuando la
  cola del análisis no cabe, salta al hueco de la derecha y cae en
  `right["_pre"]`, donde hoy sólo se minan anclas de previos. Son ~7 párrafos
  en los 6 informes, siempre en las mismas 2 máquinas de layout más denso
  (`CF.9110S1` y `TC.1523A2`), pero de alto valor unitario: en Enero/Febrero/
  Marzo el `ANÁLISIS` de Ultrasonidos de `TC.1523A2` se pierde entero
  (`analysis_text = null`) y es el precursor, cuatro meses antes, del fallo
  que desencadena el estudio ad-hoc de Abril.
- **Estudio ad-hoc «ACTUALIZACIÓN»** (Abril pp. 134-136): 1 caso en 921
  páginas, sin encabezado predecible y con el texto duplicado entre columnas
  por el reflujo. La ficha de la p134 sí se extrae y su diagnóstico ya
  dispara GT014; lo que se pierde es la **evidencia cuantitativa** (la
  cinemática del reductor, los tres GMF y la frecuencia observada de 13 Hz).
  Vía LLM o manual, no regla.
- **Evidencia e intervenciones que sólo viven en `ANÁLISIS`/`RECOMENDACIÓN`**
  (auditoría §3.7): `map_findings` se aplica sólo a `diagnosis_text`. Sobre
  las 224 observaciones con análisis hay 69 intervenciones fechadas, 66
  medidas numéricas (mm/s, Hz) y 45 peticiones/contexto de cliente que no
  aparecen en el diagnóstico. Es el caso donde un LLM aporta de verdad
  (prioridad 2 de la auditoría, §5.2), y exige decidir antes el esquema
  (`record_kind="intervention"` ya está apuntado en la spec §6; la evidencia
  numérica no tiene hueco todavía).
- **`unmapped` residual**: 29 findings (2,3 %). Casi todos son honestos —
  peticiones de información coladas como diagnóstico («Informar a Preditec si
  se ha intervenido», 12) y estados de planta («Linea 1 de refinería
  parada», 5)—. El único candidato claro a regla nueva es «bandas laterales
  … fallo de barras sueltas» (4), que es `ELECTRICAL_ROTOR` de libro y pide
  un GT025; se deja fuera por no salirse del alcance GT020–GT024 del encargo.
- `figures` es un campo **fuera del esquema** (spec §7 manda ignorarlo).
  Formalizarlo exige tocar los modelos de `vibsynth-contracts`.
- Sin severidad numérica: los informes dan categorías; el mapeo a [0,1] se
  deja como política del consumidor (ver spec §6).

## Pendiente

1. ~~Cerrar los 10 tags sin `dataset_machine_id`~~ — **descartado 2026-07-27**:
   no hay lista de equipos de planta y sin pistas claras no se fuerzan
   matches (decisión de Jose). Las propuestas quedan documentadas en
   `crosswalk_ambiguities.md` §2 por si algún día llega la lista; la vía
   sigue siendo una entrada manual en `crosswalk.csv`. Descartada también,
   de momento, la evaluación contra abr–jun 2026: no hay `.rbm` más
   reciente que 2026-03-26 ni informes nuevos previstos.
2. ~~Overlay en el visor~~ — **hecho 2026-07-27** en el repo
   `vibframe-viewer` (workplan 02 de ese repo): endpoint `/api/diaggt/<key>`,
   bandas de estado en el timeline (banda hasta la siguiente observación;
   la última, 30 días y marcada abierta) y badge de status con el mismo
   criterio de dominancia que las bandas. 57/57 tests con dataset real.
3. ~~Regenerar la copia de cortesía~~ — hecho (hoy sincronizada a v0.1.2).
   ~~Arreglar `waves.n_samples`~~ — **hecho 2026-07-27** (ADR-0017);
   incógnita del padding cerrada (FORMAT §5.5:
   `stored = 244 · ceil((nominal − 150) / 244)`).
   ~~Re-exportar `bunge_cartagena_ams`~~ — **hecho 2026-07-27**: export con
   el fix + `t8-mapper --write` + `ground-truth/`; `vibframe-validate` PASS
   (347 máquinas, 7 docs DiagGT, 0 errores).
4. ~~Extracción de los récords `gdnl`~~ — **hecho 2026-07-27** (Hecho §9,
   ADR-0018): 973 observaciones `origin="system-alarm"`, validadas 991/991
   contra los umbrales `pdla`. ~~Lado T8~~ — **hecho 2026-07-27** (workplan
   05 de t8-extract): 91 observaciones `system-alarm` desde `alarms.db` en 3
   datasets; las 195 `annotations/*.json` del workspace están vacías (0
   anotaciones). Spec consolidada en **v0.1.2** (2026-07-28):
   `extraction_method="structured_read"` adoptado por ambos productores y
   documentos regenerados.
5. ~~Auditar la cobertura del extractor por lectura completa de un informe~~ —
   **hecho 2026-07-28** (Hecho §10) y **fix determinista ejecutado**
   (Hecho §11-§13, extractor v0.2.0, spec v0.1.4). Pendiente derivado: subir
   `DIAGGT_SCHEMA_VERSION` a `"0.1.4"` en `vibsynth-contracts` (documentación,
   no contrato). La **matriz de estados coloreada** queda como paso aparte y
   posterior, con la asunción de la spec ya corregida (celdas = imágenes).

## Flecos que sobreviven al plan (fuera de su alcance)

- Matriz coloreada «Resumen Estado de Máquinas»: ~209 máquinas de planta sin
  ficha y ~2.000 celdas por informe, legibles por el píxel de `page.images`
  (ver «Limitaciones conocidas (v0.2)»).
- Pasada LLM quirúrgica de la auditoría §5.2: el bloque ad-hoc de Abril, la
  evidencia numérica e intervenciones de `analysis_text` y el re-mapeo de los
  29 `unmapped` residuales.
- `ANÁLISIS` desbordado a la columna derecha (~7 párrafos, 2 máquinas).

- Ley de la severidad `gdsc.0x1A` en zona D y las 18 alarmas con unidad
  inconsistente (FORMAT §5.9).
- Recorte de la cola de ceros de la waveform al payload real — decisión
  aparte con gold propio (ADR-0017).
- Re-extraer los 28 datasets T8 multi-generación (workplan 04 de t8-extract)
  y el colapso por `(metric_id, config_id)` en el visor.
- CI de productores y procedimiento de cambio de formato (workplan 01 de
  contracts).
