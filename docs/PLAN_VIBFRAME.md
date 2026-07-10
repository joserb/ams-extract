# Plan: alinear `rbm export` con VibFrame v0.1 y cerrar los huecos del export

**Fecha**: 2026-07-10 · **Estado**: pendiente · Para ejecutar por un agente
desde este repo, sin más contexto que este documento y las referencias.

## Contexto

El formato de intercambio se llama **VibFrame** (decisión 2026-07-10; antes
"VibDataset", nombre provisional). La especificación pública y normativa:

- Spec: `../../vibsynth/vibsynth-contracts/docs/VIBFRAME.md` (relativo a este
  repo; monorepo vibsynth, github.com:twave-io/vibsynth, commit `4f9c3c1`+).
- Contratos Pydantic normativos: `vibsynth_contracts/dataset/` en ese repo.
- Diseño y decisiones: `~/wslprojects/RESONINS/tmp/docs/ESTUDIO-FORMATO-ESTANDAR.md`.

`rbm export` ya escribe el layout VibDataset desde el commit `cf4b240`
(2026-07-09, ver `docs/VIBDATASET_EXPORT_PLAN.md`, ya histórico): carpeta
`machine=<short_code>/` con `machine.json` + 4 parquet, contrato local mínimo
copiado en `src/ams_extract/export/vibdataset_contract.py` (sin dependencia
runtime del monorepo vibsynth — decisión que se mantiene).

Productores hermanos ya operativos con este formato: `t8-extract`
(github.com:joserb/t8-extract) — útil como referencia de descriptores bien
rellenados y de las métricas reservadas de contexto.

## Trabajo

### 1. Renombrado y sincronización del contrato local

- Renombrar VibDataset → **VibFrame** en docs, docstrings y nombres de módulo
  del repo (`vibdataset_contract.py` → `vibframe_contract.py` o similar).
- Re-sincronizar el contrato local con `vibsynth_contracts/dataset/tables.py`
  actual y anotar fecha/commit de la copia.

### 2. Auditoría de conformidad con la spec (corregir lo que falle)

Checklist contra `VIBFRAME.md`:

- [ ] Timestamps `t`/`snap_t` int64 **epoch µs UTC** en las 4 tablas.
- [ ] Unidades canónicas: aceleración **`g`** (hoy el repo exporta `"G's"`,
      etiqueta legacy de AMS — cambiar etiqueta; el valor numérico es el mismo).
- [ ] `detector` explícito en cada métrica y `spectrum_detector` por espectro
      (nunca implícito en unidad o nombre); si AMS no lo conserva → null.
- [ ] `config_id`: AMS tiene una sola generación → columna constante `""` en
      `trends`/`metrics` y sin `config_generations` en machine.json.
- [ ] Identidad de serie `(metric_id, config_id)` y join limpio
      trends ↔ metrics.
- [ ] `machine.json` valida contra `MachineDoc` (probarlo en un test con
      vibsynth-contracts como dev-dependency opcional, skip si no está).
- [ ] Contexto de operación como métricas reservadas `speed`/`load`/`state`
      si el `.rbm` lo trae (canónicas de contexto, regla `RESERVED` — ver
      spec §"Reserved context metrics").

### 3. Emitir lo decodificado que hoy se descarta

Del estudio (gaps conocidos, en orden de valor):

1. **Bandas `vddt` con nombre** (Mp Wave, SUBSINCRONO, DESEQUILIBRIO…): hoy
   se decodifican y no se emiten. Emitirlas como métricas propias con
   descriptor: `statistic="spectrum_rms"` (verificar), `band_type="single"`,
   `band_low/high_hz` si el `.rbm` da los límites, `name` = nombre original.
2. **RPM en FFT** → `speed_hz` en `spectra.parquet` cuando exista fuente
   fiable (hoy solo waveform lo lleva).
3. **Ventana / promedios / detector / sensor** donde el `.rbm` lo permita →
   `AcquisitionModeDoc` (casi todo es opcional; null donde no haya dato).
4. Tendencias de aceleración y por banda que hoy no se exporten.

### 4. Etiquetado canónico

`canonical_metric`/`proxy_quality`/`mapping_rule` se dejan **null**: los
rellenará el adaptador VibFrame→firma de `t8-metrics-mapper` (trabajo aparte
en ese repo). No implementar mapeo de nombres aquí — en VibFrame el nombre
nunca decide semántica; lo que importa es rellenar bien los descriptores
estructurales del §3.

## Validación

- `uv sync && pytest` (usa `RBM_TEST_FILE` para integración), `ruff`,
  `pyright src/` — todo limpio como hasta ahora.
- Export de `DEPURADORA` con los valores gold existentes (M1H: 5 FFT,
  5 waveform, 62 tendencias) sigue pasando.
- Dataset resultante legible con duckdb/polars según los ejemplos de la spec;
  spot-check de un join trends↔metrics.
- Actualizar `docs/PLAN.md`, `README.md` y `docs/DECISIONS.md` (ADR del
  renombrado y de las bandas vddt).
