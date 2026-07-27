---
status: in-progress
created: 2026-07-27
updated: 2026-07-27
---

# Plan: ground truth de diagnóstico externo (DiagGT) desde los informes Preditec

**Fecha**: 2026-07-27 · **Estado**: formato **v0.1.1** especificado (Hecho §7),
extracción de los 6 informes BUNGE 2026 completada y verificada, revisión de
`t8-extract` hecha (compatible, ver Hecho §4), **crosswalk contra
`bunge_cartagena_ams` resuelto** (Hecho §5: 273/283 tags, 95,7 % de las
observaciones), `ground-truth/` registrado en `VIBFRAME.md` (Hecho §6) y
**contrato DiagGT mudado a `vibsynth-contracts`** con validador y goldens
(Hecho §8, ADR-0016). Pendiente: cerrar los 10 tags sin match, overlay del
visor y fuentes casi-GT (`gdnl`, `alarms.db`).

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

## Limitaciones conocidas (v0.1)

- Los pies de figura («Tendencia de…», «Espectros…») quedan al final de
  `analysis_text` (la maquetación no los distingue tipográficamente).
- La matriz coloreada "Resumen Estado de Máquinas" (≈12 meses de estado por
  color de celda, sin texto) no se extrae; daría cadencia mensual completa
  por máquina. Requiere leer color de rects del PDF.
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
2. **Overlay en el visor** (opcional, tras la mudanza a repo
   `vibframe-viewer`): endpoint `/api/diaggt/<key>` + bandas de estado en el
   timeline (`setBands()`) y/o `layout.shapes` en las tendencias; badge de
   status DiagGT en el panel. Todo aditivo, sin colisiones detectadas.
3. ~~Regenerar la copia de cortesía~~ — hecho 2026-07-27 (sincronizada a
   v0.1.1). ~~**Arreglar `waves.n_samples`**~~ — **hecho 2026-07-27**
   (ADR-0017): `Waveform.n_samples` es ya la longitud del array emitido y el
   bloque nominal de AMS viaja en `nominal_n_samples` → notas del
   `proc_mode`. De paso queda cerrada la incógnita del padding (FORMAT §5.5:
   `stored = 244 · ceil((nominal − 150) / 244)`, verificado en las 137.208
   waveforms de BUNGE). Falta **re-exportar `bunge_cartagena_ams`** para que
   el dataset publicado valide (~19 s con `--parallel 4`); y queda como tema
   aparte, con gold propio, si el array emitido debe recortarse al payload
   real en vez de publicar la cola de ceros.
4. Posible extracción de los récords `gdnl` del `.rbm` (informes de alarma en
   texto literal, FORMAT §4): serían observaciones DiagGT con
   `origin="ams-rbm"` — GT de alarma nativo del sistema, complementario al
   del analista. Simétrico en el lado T8: `data/alarms.db` y
   `annotations/*.json` del backup (hoy sin extraer) podrían emitirse como
   DiagGT con su propio `origin`.
