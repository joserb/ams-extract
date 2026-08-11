---
status: completed
created: 2026-08-10
updated: 2026-08-10
---

# Plan: migración a VibFrame 0.2

Plan escrito **a posteriori**: la migración de código entró sin él, contra la
convención del repo, y este documento la deja registrada junto con la ola
documental que la cierra. Se abre y se cierra en la misma sesión.

## Contexto

VibFrame saltó de **0.1 a 0.2** con un cambio incompatible, coordinado a la vez
en los seis repos del ecosistema (`vibsynth`, `vibsynth-contracts`,
`vibsynth-metrics-mapper`, `t8-extract`, `vibframe-viewer` y éste). No es una
extensión: 0.2 prohíbe piezas que 0.1 exigía y no hay alias ni fallback. El
plan coordinador vive en el monorepo vibsynth
(`docs/work-plans/16-actualizacion-docs-vibframe-0.2.md`, «Fase 4 —
ams-extract»); aquí queda la parte de este repo.

## Lo hecho

### 1. Código — commit `5781773` «Export VibFrame 0.2 datasets»

- Contrato vendorizado (`src/ams_extract/export/vibframe_contract.py`)
  re-vendorizado a **0.2**: `SCHEMA_VERSION = "0.2.0"`, con el estado de origen
  congelado anotado en el docstring (`ea50b0f3e567`, la coordinada 0.2 de
  `vibsynth-contracts` del 2026-08-09). El pin es la unidad de actualización:
  cuando contracts se mueva, se re-vendoriza y se cambia el sello.
- **`metric_catalog.json` sustituye a `metrics.parquet`**: los descriptores de
  métrica de cada partición son un documento JSON
  (`{"schema_version", "metrics": [...]}`), no una tabla. `metrics.parquet` no
  se escribe ni se lee.
- **JSON null-free**: `prune_nulls` recursivo sobre `machine.json` y
  `metric_catalog.json`. Lo que no se sabe no se escribe; «ausente» deja de
  competir con «declarado nulo».
- **`mode_definitions` + `mode_bindings`** sustituyen a `proc_modes`; las filas
  de `spectra`/`waves` llevan `mode_definition_id` y las notas de procedencia
  cuelgan del *binding*. La antigua nota de divergencia del bloque nominal de
  AMS quedó retirada por ADR-0020: la waveform completa sí tiene esa longitud.
- **`machine.frequencies`** es el catálogo único; `fault_frequencies_order`
  queda prohibido. Este repo lo emite vacío: sigue declarando designaciones de
  rodamiento y RPM nominal sin resolverlas (workplans 07 y 08).
- **Sidecar `ground-truth/`: cuatro proyecciones normativas 0.2** —
  `observations.parquet` (completa, todas las familias, separadas por
  `origin`), `observations_consolidated.parquet` (selección deduplicada bajo
  `dedup-primary-latest/1.0`, con `valid_to`), `findings.parquet` y
  `materialization.json`. Los `*.diaggt.json` siguen siendo la fuente
  documental y su esquema sigue en la serie **0.1.x**.
- **Retirada de los CSV y de `observations_system.parquet`**:
  `_remove_legacy_projections` los borra al rematerializar, con tests que lo
  exigen (`tests/test_diag_gt.py`, `tests/test_informes.py`).

### 2. Decisión de formato — el crosswalk sale del formato

`crosswalk.csv` y `crosswalk_ambiguities.md` se reclasifican como **artefactos
de herramienta**: los emite `scripts/crosswalk_gt.py` para dejar auditable el
mapeo TAG ↔ `machine_id` (regla CWxxx que ganó, candidatos, ambigüedades). Se
quedan físicamente dentro de `ground-truth/` —que tolera entradas no
reconocidas— pero **el formato no los define**, ningún consumidor debe
requerirlos y un sidecar sin ellos es igual de conforme. La fuente normativa
del vínculo es la columna `dataset_machine_id` de las proyecciones, avalada
por `materialization.json`.

### 3. Documentación — esta ola (2026-08-10)

- **ADR-0019** (`docs/DECISIONS.md`): la decisión completa, con los ocho
  puntos y sus consecuencias. Marca *superseded by ADR-0019 (parcial)* en
  ADR-0009, ADR-0010, ADR-0011, ADR-0015 y ADR-0016, sin reescribir sus
  cuerpos.
- **ADR-0018 §6**: corrección fechada dentro del propio ADR. El texto original
  («`--consolidate` escribe `observations_system.parquet`/`.csv`… nunca se
  toca `observations.parquet`») describía lo contrario de lo que hace el
  código desde 0.2; se conserva como registro y se corrige encima.
- `README.md`: declara VibFrame 0.2 explícitamente, la salida real de
  `rbm export` (con `metric_catalog.json`) y de `rbm informes` (las cuatro
  proyecciones, cero CSV); el quick start de Polars avisa de que el catálogo
  es JSON, no parquet.
- `AGENTS.md`: bloque de conformidad reescrito (pinning del contrato
  vendorizado, `prune_nulls`, prohibición de `metrics.parquet`, tres parquet +
  catálogo JSON); el «rojo conocido» de `snap_t` se retira, verificado en
  verde.
- `docs/GROUND_TRUTH.md` §2.4 y §4: reclasificación del crosswalk. El resto de
  §4/§5 ya era 0.2 y no se toca; la serie documental 0.1.x y los changelogs,
  intactos.
- `docs/workplans/01-plan-general.md` §4: único bloque de un plan `completed`
  que se reescribe en vez de anotarse, porque el README lo enlaza como
  referencia viva del contrato de salida. La razón queda escrita en el propio
  bloque.
- `docs/VERIFICATION.md`: entrada nueva fechada, sin tocar filas históricas —
  lo validado end-to-end era 0.1, la re-validación 0.2 está pendiente de
  regenerar los artefactos externos.
- `docs/FORMAT.md` §5.5: las notas del bloque nominal viajan en el *mode
  binding*, no en un `proc_mode`.
- Docstrings de `scripts/crosswalk_gt.py` y `src/ams_extract/informes/
  consolidate.py` alineados con la decisión del crosswalk (sólo prosa: ni la
  lógica ni el destino de escritura cambian).
- Nota de cabecera de una línea en los planes históricos con vocabulario 0.1
  (02, 03, 04, 07, 08, 09, 11).

## Verificación

`uv run pytest` en verde salvo lo que estuviera en curso en
`export/dataset.py` / `tests/test_export_dataset.py`.
`tests/test_vibframe_conformance.py` valida con `vibframe-validate` (API y
CLI) lo que escribe `rbm export` y hace round-trip de los tres goldens 0.2;
`test_the_goldens_round_trip_through_our_writer[vibsynth]` —el rojo de
`snap_t` del 2026-08-05— pasa.

## Pendiente (fuera de este repo)

Los **artefactos desplegados** siguen siendo emisiones 0.1 y quedan por
regenerar con el extractor 0.2:

- `…/bunge_dataset/bunge_cartagena_ams/` (dataset y su `ground-truth/`).
- `…/Informes Bunge Cartagena 2026/ground-truth/` (incluido el snapshot de
  cortesía `FORMATO_GROUND_TRUTH.md`, v0.1.0).

De esa regeneración salen los números de la re-validación end-to-end 0.2 que
`docs/VERIFICATION.md` deja anotada como pendiente.
