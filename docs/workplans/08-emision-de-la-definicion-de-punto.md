---
status: completed
created: 2026-08-04
updated: 2026-08-04
---

# Plan: emitir al dataset lo que AMS declara del eje del punto

**Fecha**: 2026-08-04 · **Estado**: **COMPLETADO**. `rbm export` emite ya
`PointDoc.bearing_designations` y `PointDoc.nominal_speed_rpm` en cada
`machine.json`, verbatim del `.rbm`. Sin `definition_provenance`: este repo
no escribe definición.

Remate de la **fase C** del marco *Marco de definiciones de máquina en
VibFrame para ML*
(`/mnt/c/Users/joser/work/vibsynth/docs/work-plans/08-marco-definiciones-maquina-ml.md`).

## Contexto

El workplan 07 dejó `vdpm.0x07E` (designaciones de rodamiento) y
`vdpm.0x164` (RPM nominal del eje del punto) decodificados, verificados
contra BUNGE y documentados en FORMAT §3.2 — pero **sin emitir**: el
contrato VibFrame no tenía dónde ponerlos, y emitir órdenes derivadas de una
designación habría exigido un catálogo de rodamientos en este repo y habría
violado la regla de la casa («no emitir lo no validado»).

El hueco llegó con el workplan 04 de `vibsynth-contracts`
(`/mnt/c/Users/joser/work/vibsynth/vibsynth-contracts/docs/workplans/04-procedencia-de-la-definicion-de-maquina.md`):

- `PointDoc.bearing_designations: list[str]` — verbatim del origen, sin
  normalizar, lista porque un punto puede vigilar más de un rodamiento.
- `PointDoc.nominal_speed_rpm: float | None` — por punto, porque el origen
  ya propaga la velocidad por la reductora; desconocida es `None`, nunca `0`.
- `MachineInfo.definition_provenance` — quién escribió el conocimiento
  cinemático y desde qué evidencia.

`vibsynth-contracts` es vecino (`../../vibsynth/vibsynth-contracts`, editable
en `[tool.uv.sources]`), así que el checkout local con los campos nuevos es
justo lo que valida el test de conformidad; no hubo que tocar el contrato
vendorizado (`export/vibframe_contract.py`), que sólo cubre las columnas
parquet.

## Hecho

### 1. El walker carga la configuración del punto

`models.Point` gana `bearing_designations: tuple[str, ...] = ()` y
`nominal_speed_rpm: float | None = None`; `tree._walk_points_for_equipment()`
los rellena con `parse_vdpm_bearings()` / `parse_vdpm_nominal_rpm()` sobre el
mismo `vdpm` que ya estaba leyendo. Un fallo de decode del punto sigue
saltándose el punto con log, como antes.

Ponerlo en el modelo y no en el exportador es lo que mantiene
`_build_machine_doc()` sin `RbmReader`: el machine doc se construye desde el
árbol, y el árbol es lo que cruza el `ProcessPoolExecutor` del export
paralelo.

### 2. El export lo escribe verbatim

`export/dataset._build_point_doc()` añade los dos campos:

- `bearing_designations`: los slots decodificados **en su orden**, tal cual
  los tecleó el analista (`6204`, `SKF 6308`, `22218 EKC3`, y el `RED` que ni
  siquiera es designación). Un punto que no declara ninguno emite `[]`, no
  `null`. Normalizar contra catálogo y proyectar a `BPFO`/`BPFI` es del
  enriquecedor (fase B), que además debe poder rehacerlo cuando el catálogo
  crezca: por eso el crudo es lo único que se emite aquí.
- `nominal_speed_rpm`: el float32 de `0x164` en RPM, como está almacenado;
  `null` si no hay velocidad utilizable — nunca `0`, que se leería como eje
  parado.

**Sin `definition_provenance`.** Este repo no escribe definición: declara lo
que el origen guarda, que es el `declared` implícito que el contrato asume
para todo documento sin el campo. Firmar la procedencia corresponde a quien
resuelve la designación en frecuencias (fase B), no a quien la copia.

`location`/`direction` siguen saliendo del nombre del punto (workplan 07) y
tampoco se firman aún: cuando el enriquecedor escriba `definition_provenance`
serán `approximate` por construcción, como anotaba el 07.

### 3. Tests

- `tests/test_export_dataset.py`: los dos campos en el `machine.json` desde
  `Point`s sintéticos — orden de slots, texto libre intacto, `[]` para el
  punto sin rodamiento, `null` (no `0`) sin velocidad, y ausencia de
  `definition_provenance`. La prueba contra el contrato opcional valida ahora
  un doc **con** los campos y comprueba que `MachineDoc` los conserva.
- `tests/conftest.py`: el punto de la fixture de dataset declara `6204`/`6208`
  y 1 455 RPM, así que todo lo que se construye con
  `build_vibframe_dataset()` —incluida la conformidad con
  `vibframe-validate`— pasa por los campos nuevos.
- `tests/test_integration_tree.py`: golds del walker sobre BUNGE — AG-100
  `MOTOR LOA HORIZONTAL` → `("6204", "6208")` y `MOTOR LA VERTICAL` →
  `("6205", "6208")` (por punto, no por máquina), sus puntos de reductora sin
  designación, PM-9101-A `MOTOR LOA HORIZONTAL` a 2 900 RPM sin designación,
  y la cobertura global (1 520 de 5 203 puntos con rodamiento, todos con
  velocidad).
- `tests/test_integration_export.py`: los mismos golds **sobre el
  `machine.json` emitido** por `rbm export --areas DEPURADORA`, con los tipos
  JSON que se escriben en disco.

## Verificación

- `uv run pytest`: **312 passed, 48 skipped** (antes 311/46).
- `RBM_TEST_FILE="…/BUNGE CARTAGENA marzo 2.0.rbm" uv run pytest`:
  **360 passed** (antes 357), incluidas las dos de conformidad VibFrame
  contra el checkout local de `vibsynth-contracts` con los campos nuevos.
- `uv run ruff check src tests` limpio. `uv run pyright src`: los 3 errores
  preexistentes de `cli.py` (import de `vibframe_viewer` no resuelto porque
  el venv de esta máquina vive fuera de `.venv`), ninguno nuevo.

## Flecos

- ~~**Re-export de `bunge_cartagena_ams`**~~ — **hecho 2026-08-04** (ver
  «Re-export y enriquecimiento del dataset real» más abajo).
- El contrato con los campos nuevos está **en local, sin push**, en el
  checkout de `vibsynth-contracts`. Hasta que aterrice allí, la conformidad
  de este repo sólo es verde contra ese checkout.
- `definition_provenance` sigue sin escribirse desde aquí, por diseño. Si
  algún día este repo declarase también `location`/`direction` como evidencia
  firmada, tendría que hacerlo el enriquecedor, no el extractor.

## Re-export y enriquecimiento del dataset real (2026-08-04)

Operación sobre `~/wslprojects/RESONINS/datasets/bunge_cartagena_ams`, en
este orden:

```bash
rbm export "…/AMS databases/BUNGE CARTAGENA marzo 2.0.rbm" \
    --out ~/wslprojects/RESONINS/datasets/bunge_cartagena_ams \
    --types fft,waveform,trend --parallel 4          # 34 s, 0 fallos
t8-mapper vibframe <dataset> --write                 # etiquetado canónico
vibsynth-machines enrich <dataset> --write           # frecuencias de fallo
vibframe-validate <dataset> --strict                 # PASS
```

347 máquinas (311 con muestras), 137 270 FFT + 137 208 waveform + 1 571 433
trend. El export ahora emite los campos del punto: **1 520** puntos con
`bearing_designations` y **5 203** con `nominal_speed_rpm` (todos), más
`location` en 5 108 (98,2 %) y `direction` en 4 220 (81,1 %). Los golds del
workplan se confirman sobre el dataset real: AG-100 `MOTOR LOA HORIZONTAL` →
`["6204", "6208"]` a 1 455 RPM.

`vibsynth-machines enrich` (workplan 10 del monorepo `vibsynth`) resolvió por
catálogo **2 784 entradas** `fault_frequencies_order` en **696 puntos de 73
máquinas**, todas firmadas `source="enriched"`, `quality="direct"`. La segunda
pasada no cambió un byte de los 347 `machine.json`: idempotente. Quedan **56
designaciones sin resolver** (las más frecuentes: `23248`, `6316`, `6317`,
`23120`, `6314`, `6312`, `6411`, `6216`, `6213`, `6319`), material para
ampliar catálogo o entrar por `--input`.

Dos cosas que el re-export se llevó por delante y hubo que rehacer:

- **El etiquetado canónico**, como manda ADR-0011: `t8-mapper vibframe
  --write` devolvió la cobertura exacta de antes (23 590 de 24 684 métricas,
  95,6 %). Es post-proceso, no paso del export: re-exportar siempre lo exige.
- **`dataset.json:path`** (`["Bunge Cartagena"]`, el nivel de agrupación por
  encima del dataset). `rbm export` nunca ha escrito ese campo —lo puso a
  mano quien curó el dataset— así que el re-export lo perdió y se restauró a
  mano. Si se quiere que sobreviva solo, tiene que emitirlo el export.

Y un **bug de conformidad corregido en el camino** (`f1d7b91`): `rbm export`
limpiaba `--out` con un `rmtree` a secas, y VIBFRAME.md prohíbe borrar
`ground-truth/` y `analysis/` al re-exportar sobre un dataset existente —
habría destruido los siete documentos DiagGT y la capa `diaggt-contrast` de
BUNGE. Ahora la limpieza va entrada a entrada y respeta los dos sidecars;
`test_export_keeps_curated_sidecars` lo fija. Verificado sobre el dataset
real: `diff -r` contra la copia de seguridad, idénticos byte a byte.
