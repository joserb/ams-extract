---
status: completed
created: 2026-07-29
updated: 2026-08-12
---

# Plan: conformidad VibFrame en CI y nulabilidad alineada de los parquet

**Fecha**: 2026-07-29 · **Estado**: **COMPLETADO**. `tests/test_vibframe_conformance.py`
pone lo que escribe `rbm export` bajo `vibframe-validate` (API y CLI) y hace
round-trip de los goldens de los tres orígenes. En la foto 0.1 de este plan,
las columnas requeridas de las cuatro tablas parquet pasaron a declararse
**non-nullable**. VibFrame 0.2 sustituyó la tabla de métricas por
`metric_catalog.json`, por lo que hoy son tres Parquet más un catálogo JSON
null-free (workplan 12).

Cierra dos pendientes del workplan 03 de t8-extract
(`~/wslprojects/t8-extract/docs/workplans/03-unificacion-repos-extraccion.md`,
sección «Estado 2026-07-29 y pendientes»): «CI de conformidad en ams-extract» —
punto 3 de su Parte 2 — y «alinear ams-extract: escribe todas las columnas
requeridas de sus parquet como `nullable`».

## Contexto

La Parte 2 del workplan 03 dejó en `vibsynth-contracts` el CLI
`vibframe-validate` (layout, documentos contra los modelos Pydantic, columnas,
tipos, reglas de fila, `columns.null-in-required`) y un golden por origen en
`vibsynth_contracts/goldens/`, `ams-rbm` incluido —recortado de un export real
de este repo, con ground-truth—. t8-extract ya tenía su test de conformidad
(`tests/test_vibframe_conformance.py`); aquí la conformidad seguía siendo *de
facto*: validada a mano y por el round-trip del mapper.

El patrón oficial del ecosistema es el de este repo: **contrato vendorizado**
(`src/ams_extract/export/vibframe_contract.py`, importado de contracts el
2026-07-10 con el commit de origen anotado) para el runtime, y validación
contra `vibsynth-contracts` **solo en tests/CI**. Ya estaba en
`[dependency-groups] dev`, así que no hubo que tocar dependencias.

## Hecho

### 1. Nulabilidad alineada

`vibframe_contract.schema()` construye el esquema con
`pa.field(..., nullable=not col.required)` en vez de dejar el `nullable=True`
por defecto de `pa.schema([(name, type)])`. Las cuatro tablas quedan como las
escriben t8-extract y vibsynth.

El dato ya era correcto —ninguna columna requerida salía nula, el contrato
nunca se violó—; lo que cambia es que ahora **un requerido vacío falla al
escribir**, aquí, en lugar de aparecer después como error
`columns.null-in-required` del validador. Ninguna columna se queda `nullable`
por excepción: no hay ningún caso en el `.rbm` en que una columna requerida
pueda venir nula.

- Requeridas por tabla: `trends` t/metric_id/value/config_id; `spectra`
  t/point_id/proc_mode_id/fmin_hz/fmax_hz/lines/unit/signal_family/config_id/data;
  `waves` t/point_id/proc_mode_id/sample_rate_hz/n_samples/unit/signal_family/
  config_id/data; `metrics` metric_id/config_id/statistic/signal_family/unit/
  band_type. Todas las construyen los row builders con valor propio o literal
  (`CONFIG_ID`, `_canonical_unit`, `_signal_family`, `band_type`), nunca desde
  un campo opcional del `.rbm`.
- Un `float('nan')` de una lectura de tendencia no es un nulo: sigue pasando.
- El golden `ams-rbm` de contracts es anterior al cambio y sigue todo
  `nullable`. No se re-corta desde aquí (vive en otro repo y el contrato habla
  del valor, no de cómo se declare el campo); el test lo documenta y comprueba
  nombres y tipos, no nulabilidad. Ninguna de sus columnas requeridas contiene
  un nulo — si lo contuviera, el round-trip por nuestro escritor fallaría.

### 2. Test de conformidad

`tests/test_vibframe_conformance.py`, con el patrón de t8-extract:

- **Nuestro export pasa el validador**, por API (`validate_dataset`) y por el
  **CLI instalado** (`vibframe-validate --strict --json` en subproceso) — la
  vía que usan los productores no-Python (DataWaver).
- **Invariante de nulabilidad**: toda columna requerida se declara
  non-nullable (y ninguna opcional lo hace).
- **Goldens**: existe el de nuestro origen; los tres validan sin errores ni
  avisos; **round-trip** por nuestro escritor conservando nombres, tipos y
  valores (los tres orígenes a propósito: el esquema derivado de `*_COLUMNS`
  tiene que servir a cualquier productor); sus `dataset.json`/`machine.json`
  reentran en `DatasetInfo`/`MachineDoc` sin pérdida.
- **Base real** (marker `integration`, `RBM_TEST_FILE`): `rbm export` de un
  área completa por CLI → validador limpio y cero nulos en columnas
  requeridas.

El dataset bajo prueba pasa a `conftest.build_vibframe_dataset` (fixtures
`vibframe_dataset` y `make_dataset`), compuesto con **los mismos row builders,
machine doc y escritor parquet de `rbm export`** — solo falta el lector del
`.rbm`, porque la fixture sintética commiteada tiene áreas pero ningún
equipo y la base real es opt-in. `tests/test_viewer_delegation.py` deja de
escribir sus propias filas a mano y comparte la fixture.

## Verificación

- `uv run pytest`: 247 passed, 42 skipped (antes 233/40). Con
  `RBM_TEST_FILE="…/BUNGE CARTAGENA marzo 2.0.rbm"`: **289 passed**, 0 skipped,
  incluidas las dos de conformidad sobre la base real.
- `uv run ruff check src tests` y `uv run pyright src` (strict) limpios.
- Validador sobre un export fresco del área DEPURADORA (fft+waveform+trend,
  `rbm export` por CLI): `report.errors == []` y `report.warnings == []`, con
  `parquet_checked` — es decir, `--strict` limpio.

## Flecos

- El workflow de GitHub (`.github/workflows/ci.yml`) hace `uv sync --frozen`,
  pero `vibsynth-contracts` y `vibframe-viewer` entran por path editable a
  checkouts locales que el runner no tiene: la conformidad se ejecuta hoy en
  local (`uv run pytest`), no en GitHub. Si algún día se quiere verde en
  GitHub, hay que publicar contracts/visor en un índice o clonar los repos
  vecinos en el workflow — decisión del ecosistema, no de este repo.
- El golden `ams-rbm` de `vibsynth-contracts` se re-cortará con el esquema
  nuevo cuando toque tocar ese repo; hasta entonces la diferencia es solo de
  declaración.
- Sigue pendiente la Parte 3 del workplan 03 (empaquetado `.vibframe.zip`,
  `rbm export --zip`): fuera de alcance aquí a propósito.

### Actualización 2026-08-12

- El golden AMS, `snap_t` y la nulabilidad 0.2 están sincronizados; la suite
  compara además los Common Codes del contrato vendorizado con los de
  `vibsynth-contracts`.
- El empaquetado `.vibframe.zip` sigue siendo responsabilidad del contrato/
  tooling común; `rbm export` escribe directorios y no ofrece `--zip`.
- El workflow aislado de GitHub continúa necesitando una estrategia de
  publicación o checkout coordinado para las dependencias por path; la matriz
  local Linux/WSL es la verificación reproducible de este checkout.
