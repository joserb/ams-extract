# Plan: alinear `rbm export` con VibFrame v0.1 y cerrar los huecos del export

**Fecha**: 2026-07-10 (actualizado 2026-07-19) · **Estado**: en curso —
conformidad base cerrada (`f17bb9c`), bandas vddt + `path=[área]` emitidas
(`2c5e1fe`, ADR-0010), etiquetado canónico vía mapper operativo (§4,
ADR-0011) y decode de `pdpa`/`pdla` con límites de banda + columna `alarm`
derivada (ADR-0012, FORMAT §5.8); quedan los trends de aceleración, la
columna "1-20 KHz" y el contexto de operación.
Para ejecutar por un agente desde este repo, sin más contexto que este
documento y las referencias.

## Contexto

El formato de intercambio se llama **VibFrame** (decisión 2026-07-10; antes
"VibDataset", nombre provisional). La especificación pública y normativa:

- Spec: `../../vibsynth/vibsynth-contracts/docs/VIBFRAME.md` (relativo a este
  repo; monorepo vibsynth, github.com:twave-io/vibsynth, commit `4f9c3c1`+).
- Contratos Pydantic normativos: `vibsynth_contracts/dataset/` en ese repo.
- Diseño y decisiones: `~/wslprojects/RESONINS/t8-extract/docs/ESTUDIO-FORMATO-ESTANDAR.md` (repo github.com:joserb/t8-extract).

`rbm export` ya escribe el layout VibDataset desde el commit `cf4b240`
(2026-07-09, ver `docs/workplans/02-vibdataset-export.md`, ya histórico): carpeta
`machine=<short_code>/` con `machine.json` + 4 parquet, contrato local mínimo
copiado en `src/ams_extract/export/vibframe_contract.py` (sin dependencia
runtime del monorepo vibsynth — decisión que se mantiene).

Productores hermanos ya operativos con este formato: `t8-extract`
(github.com:joserb/t8-extract) — útil como referencia de descriptores bien
rellenados y de las métricas reservadas de contexto.

## Trabajo

### 1. Renombrado y sincronización del contrato local — completado

- Renombrar VibDataset → **VibFrame** en docs, docstrings y nombres de módulo
  del repo (`vibdataset_contract.py` → `vibframe_contract.py` o similar).
- Re-sincronizar el contrato local con `vibsynth_contracts/dataset/tables.py`
  actual y anotar fecha/commit de la copia.

### 2. Auditoría de conformidad con la spec (corregir lo que falle)

Checklist contra `VIBFRAME.md`:

- [x] Timestamps `t`/`snap_t` int64 **epoch µs UTC** en las 4 tablas.
- [x] Unidades canónicas: aceleración **`g`** (hoy el repo exporta `"G's"`,
      etiqueta legacy de AMS — cambiar etiqueta; el valor numérico es el mismo).
- [x] `detector` explícito en cada métrica y `spectrum_detector` por espectro
      (nunca implícito en unidad o nombre); si AMS no lo conserva → null.
- [x] `config_id`: AMS tiene una sola generación → columna constante `""` en
      `trends`/`metrics` y sin `config_generations` en machine.json.
- [x] Identidad de serie `(metric_id, config_id)` y join limpio
      trends ↔ metrics.
- [ ] `machine.json` valida contra `MachineDoc` (probarlo en un test con
      vibsynth-contracts como dev-dependency opcional, skip si no está).
- [ ] Contexto de operación como métricas reservadas `speed`/`load`/`state`
      si el `.rbm` lo trae (canónicas de contexto, regla `RESERVED` — ver
      spec §"Reserved context metrics").

### 3. Emitir lo decodificado que hoy se descarta

Del estudio (gaps conocidos, en orden de valor):

1. **Bandas `vddt` con nombre** — completado 2026-07-18 (ADR-0010) y
   cerrado 2026-07-19 (ADR-0012): se emiten como métricas propias
   (`band_<slug>__<punto>`) etiquetadas desde la plantilla `pdpa` del punto,
   con límites reales (`band_low/high_order` para bandas en órdenes,
   `band_low/high_hz` para bandas fijas) y la columna `alarm` de
   `trends.parquet` derivada de los umbrales `pdla` (0/2/3). La columna
   "1-20 KHz" sigue sin emitirse (escala en G's sin gold). En el mismo
   cambio ADR-0010: `machine.path = [área]` — solo niveles de ubicación,
   alineado con la jerarquía location→machine del `vibframe_viewer` de
   t8-extract.
2. **RPM en FFT** → `speed_hz` en `spectra.parquet` desde `vdps.0x28`
   (completado; AMS lo almacena como RPM × 2).
3. **Ventana / promedios / detector / sensor** donde el `.rbm` lo permita →
   `AcquisitionModeDoc` (casi todo es opcional; null donde no haya dato).
4. Tendencias de aceleración y por banda que hoy no se exporten.

### 4. Etiquetado canónico

`canonical_metric`/`proxy_quality`/`mapping_rule` se dejan **null**: los
rellenará el adaptador VibFrame→firma de `t8-metrics-mapper` (trabajo aparte
en ese repo). No implementar mapeo de nombres aquí — en VibFrame el nombre
nunca decide semántica; lo que importa es rellenar bien los descriptores
estructurales del §3.

**HECHO (2026-07-19, ADR-0011): el etiquetado es un post-proceso con el
front-end VibFrame de `t8-metrics-mapper`** (repo
`~/wslprojects/t8-metrics-mapper`), no un paso de `rbm export` — cero
dependencias nuevas aquí y un único punto de verdad de las reglas para los
tres orígenes (T8/AMS/vibsynth). Tras cada export:

```bash
# en el repo t8-metrics-mapper
uv run t8-mapper vibframe /ruta/al/dataset --write   # escribe las etiquetas
uv run t8-mapper vibframe /ruta/al/dataset --diff    # valida el round-trip
```

`--write` rellena `canonical_metric`/`proxy_quality` cuando resuelven y
`mapping_rule` siempre (en los null la regla registra la causa); es
idempotente. La velocidad de referencia sale de la mediana de
`spectra.speed_hz` (global y por punto) porque este export aún no emite la
métrica reservada `speed`.

Resultado sobre BUNGE CARTAGENA completo (347 máquinas, 15 612 métricas,
`datasets/bunge_cartagena_ams` en RESONINS): **45.0 % etiquetado** —
4 882 direct (overall → `vel_overall_rms`, Mp Wave → `waveform_peak`),
2 146 approximate (11-40 X RPM → `band_sync_high_rms`), 8 584 null (las 4
bandas vddt con nombre sin límites: SUBSINCRONO, DESEQUILIBRIO,
DESALINEACION, HOLGURAS — el nombre nunca decide semántica). Nota:
vibsynth-contracts acepta desde 2026-07-19 `band_type="single"` sin límites,
así que la desviación asumida en ADR-0010 §3 ya es conforme a la spec.

- HECHO (2026-07-19, ADR-0012): `pdpa` decodificado y límites emitidos
  (en órdenes para las bandas ×RPM, en Hz para las fijas) + columna `alarm`
  derivada de los umbrales `pdla`. Dataset regenerado y re-etiquetado:
  **100.0 % de cobertura** (16 462 métricas: 5 457 direct, 8 801
  approximate, 2 204 weak; `--diff` 16 462 match / 0 differ). Las bandas
  antes null resuelven por estructura: SUBSINCRONO → `band_subsync_rms`,
  DESEQUILIBRIO → `band_1X_rms`, DESALINEACION → `band_2X_rms`, HOLGURAS →
  `band_harmonics_high/low_rms` (weak), FALLO ELECTRIC → `band_2xLine_rms`,
  COMBUSTION → `band_3X_rms`; además los puntos HF suman bandas nuevas
  (10 Hz-2 kHz, 2-4 kHz, 4-6 kHz).

### 5. Cierres del 2026-07-19 (capturas AMS del usuario)

- [x] **Banda "1 - 20 KHz" emitida** (ADR-0013): escala validada contra la
  captura de PM-9101-A M1H (crudo = G's, valor a valor); descriptor
  `spectrum_rms`/`g`/`single` 1000–20000 Hz + alarma pdla en G's.
- [x] **`spectra.speed_hz` corregido** (ADR-0013): `vdps.0x28` es la RPM
  del análisis que fija AMS (captura: 2900 = crudo), no "RPM × 2"; fuera
  el `/2` del decode. Re-etiquetar datasets tras re-exportar.
- [ ] Nivel "Advertencia" de las gráficas AMS (~0,95 G's) ≠ C/D del pdla:
  sin localizar en el binario.

## Validación

- `uv sync && pytest` (usa `RBM_TEST_FILE` para integración), `ruff`,
  `pyright src/` — todo limpio como hasta ahora.
- Export de `DEPURADORA` con los valores gold existentes (M1H: 5 FFT,
  5 waveform, 62 tendencias) sigue pasando.
- Dataset resultante legible con duckdb/polars según los ejemplos de la spec;
  spot-check de un join trends↔metrics.
- Actualizar `docs/workplans/01-plan-general.md`, `README.md` y `docs/DECISIONS.md` (ADR del
  renombrado y de las bandas vddt).
