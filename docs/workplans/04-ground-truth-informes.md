---
status: in-progress
created: 2026-07-27
updated: 2026-07-27
---

# Plan: ground truth de diagnóstico externo (DiagGT) desde los informes Preditec

**Fecha**: 2026-07-27 · **Estado**: formato v0.1 definido y extracción de los
6 informes BUNGE 2026 completada y verificada; pendiente el crosswalk contra
`bunge_cartagena_ams` y la revisión de `t8-extract` (repo en WSL, fuera del
alcance de la sesión Windows).

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

## Limitaciones conocidas (v0.1)

- Los pies de figura («Tendencia de…», «Espectros…») quedan al final de
  `analysis_text` (la maquetación no los distingue tipográficamente).
- La matriz coloreada "Resumen Estado de Máquinas" (≈12 meses de estado por
  color de celda, sin texto) no se extrae; daría cadencia mensual completa
  por máquina. Requiere leer color de rects del PDF.
- Sin severidad numérica: los informes dan categorías; el mapeo a [0,1] se
  deja como política del consumidor (ver spec §6).

## Pendiente

1. **Crosswalk** `normalized_tag` → `machine_id` del dataset
   `bunge_cartagena_ams` (rellenar `dataset_machine_id`; tabla explícita para
   ambigüedades). Con eso, `observations.parquet` se une directamente a las
   features del VibFrame para evaluar diagnostics con GT real.
2. **Revisar `t8-extract`** (repo en `~/wslprojects`, inaccesible desde la
   sesión Windows): contrastar que DiagGT no choca con nada de su lado y
   valorar si el visor puede superponer las observaciones.
3. **Decidir el hogar definitivo del contrato**: si DiagGT se consolida,
   mover los modelos a `vibsynth-contracts` (p. ej.
   `vibsynth_contracts/diagnosis/external.py`) y dejar aquí solo la
   referencia, como se hizo con VibFrame (ADR-0009).
4. Posible extracción de los récords `gdnl` del `.rbm` (informes de alarma en
   texto literal, FORMAT §4): serían observaciones DiagGT con
   `origin="ams-rbm"` — GT de alarma nativo del sistema, complementario al
   del analista.
