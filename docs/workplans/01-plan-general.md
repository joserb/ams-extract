---
status: completed
created: 2026-05-27
updated: 2026-08-12
---

# ams-extract — estado y arquitectura

> Herramienta CLI en Python para extraer datos de bases RBMware / AMS Machinery
> Manager (`.rbm`) a formatos modernos (Parquet + JSON), sin depender de la VM
> Windows XP ni del software AMS original.

Estado consolidado el 2026-08-12 (movido a `docs/workplans/` el 2026-07-19;
la evolución posterior vive en los workplans 02–15) · Repo:
`git@github.com:joserb/ams-extract.git`
(privado) · Branch de trabajo: `master`.

> **Nota histórica**: este documento fue originalmente un plan por fases (0–7)
> con un esquema de ejecución agéntica por worktrees. El proyecto ya está
> completo en lo esencial, así que se ha reducido a su **estado y arquitectura
> vigentes**. El formato binario reverse-engineered vive en
> [`FORMAT.md`](../FORMAT.md); las decisiones en
> [`DECISIONS.md`](../DECISIONS.md); el protocolo y registro de verificación en
> [`VERIFICATION.md`](../VERIFICATION.md).
>
> **Nota (2026-08-12)**: la referencia viva de la CLI es `README.md`; este
> documento conserva la arquitectura y las decisiones del plan original. Las
> notas fechadas explican las sustituciones posteriores (visor portable,
> VibFrame 0.2, waveforms completas y Common Codes). El historial completo
> continúa en los workplans 02–15 y ADR-0009–ADR-0021.

## 1. Objetivo y caso de uso

Abrir ficheros `.rbm` legacy de instrumentos CSI/Emerson (recogidos con AMS
Machinery Manager 5.x) directamente desde Linux/WSL/macOS y producir:

1. La jerarquía completa (Áreas → Equipos → Puntos) en JSON.
2. Un índice de muestras (qué, cuándo, dónde, con qué config) en Parquet.
3. Los espectros FFT, las waveforms y las tendencias, calibrados, en Parquet
   particionado por área y por equipo.

**Caso de uso primario**: migración offline hacia **TWist** (TWave). Es un ETL
de **solo lectura** que corre fuera del backend de TWist; este ingiere los
Parquet por su API/loader. No es librería embebida ni escribe `.rbm`.

## 2. Estado actual (todo verde)

| Capacidad | Estado |
|---|---|
| Jerarquía (`rbm tree`) | ✅ 15 áreas, 347 equipos, 5203 puntos (verificado vs AMS) |
| FFT velocidad → mm/s | ✅ banda baja `vdps` + cadena `vcps`, ×48.5 (3 máquinas, ±5–10%) |
| FFT aceleración (PeakVue + HF) → G's | ✅ ×1.30 (validado PeakVue y HF fmax 6000, ±10%) |
| Waveforms → G's / mm/s | ✅ 150 muestras inline de `vdfw` + continuación `vcfw`, escala `vdfw.0x28`; velocidad ×25.4 → mm/s |
| Tendencias "Valores Globales" → mm/s | ✅ `vddt`, off-by-one de fechas (validado 47/47) |
| Export masivo (`rbm export`) | ✅ BUNGE entero (1,8 GiB) en **~19 s** `--parallel 4`; **274.478** capturas FFT+wv = conteo exacto AMS; con trends: 1.571.433 filas; 0 fallos; VibFrame 0.2 + `report.html` |
| Estadísticas (`rbm stats`) | ✅ summary / machines / points (sp/wv/tn) |
| Inventario HTML (`rbm report`) | ✅ árbol localizaciones → máquinas con conteos + fechas (primera/última) por tipo, archivo único con filtro; leído del `.rbm` |
| Viewer on-demand (`rbm serve`) | ✅ sirve un `.rbm` directo (arranque solo jerarquía; puntos/muestras lazy; render desde el `.rbm`) o un dataset Parquet exportado; FFT/onda/tendencia bajo demanda (sin pregenerar PNG) |

**Nota (2026-08-05)**: la fila del viewer describe los **dos visores propios**
de entonces. El de datasets (`export/viewer.py`) se retiró el 2026-07-29
(workplan 05): hoy `rbm serve <dataset>` **delega** en `vibframe-viewer`, el
visor portable del ecosistema (Plotly en cliente, timeline y matriz de
parámetros), y sólo `rbm serve FILE.rbm` sigue siendo backend propio
(`export/live_viewer.py`), herramienta de depuración de este repo. Lo mismo
vale para los párrafos de §3 y para la frase de §4 sobre los IDs de muestra
del viewer.

Calidad: `pytest` (unit + integración con `RBM_TEST_FILE`), `ruff` y
`pyright src/` limpios. CI matrix Linux/macOS/Windows × Python 3.13.

## 3. Comandos

```bash
rbm info   FILE                                   # firma, descripción, conteos
rbm tree   FILE [--out tree.json]                 # jerarquía Áreas/Equipos/Puntos
rbm report FILE [--out report.html] [--area SUBSTR]   # inventario HTML interactivo
rbm stats  summary  FILE [--area SUBSTR]          # máquinas + totales sp/wv/tn
rbm stats  machines FILE [--area SUBSTR] [--sort total|sp|wv|tn|name] [--limit N]
rbm stats  points   FILE --equipment SUBSTR [--area SUBSTR]
rbm extract FILE --point NAME [--equipment SUBSTR] \
                 --type fft|waveform|trend|both --limit N --out DIR   # Parquet + PNG
rbm export FILE --out dataset/ [--types fft,waveform,trend] \
                [--areas …] [--parallel N]            # + report.html en el dataset
rbm serve  FILE.rbm | dataset/ [--host H] [--port N] [--no-browser]  # viewer on-demand
# dev: rbm-dev scan --tags | dump-record --rec N | follow-chain --from N
```

`rbm report` lee el `.rbm` directamente (sin extraer) y escribe un HTML
autocontenido: árbol colapsable localizaciones → máquinas con nº de archivos por
tipo y fechas primera/última, más un filtro de máquinas. `rbm serve` abre un
viewer on-demand y elige backend según el argumento: un **`.rbm`** (renderiza
directo de la BD; arranque solo con la jerarquía, puntos/muestras cargados lazy)
o un **dataset exportado** (lee tablas VibFrame). En ambos casos las gráficas
se renderizan **bajo demanda** y nunca se pregenera PNG.

`sp` = espectros FFT, `wv` = waveforms, `tn` = lecturas de tendencia.

**Nota (2026-08-12)**: este inventario de comandos está incompleto — faltan
`rbm alarms` (workplan 04), `rbm informes` e `rbm informes-weights`
(workplans 09 y 10) y la opción `rbm export --dataset-path` (workplan 11). La
referencia viva es el bloque «Commands» del `README.md`; aquí no se duplica.

## 4. Salida de `rbm export` (contrato VibFrame)

> **Actualizado el 2026-08-10 (VibFrame 0.2, ADR-0019).** Este bloque es la
> única parte de un plan `completed` que se reescribe en vez de anotarse: el
> README enlaza este documento como referencia viva del contrato de salida, y
> dejarlo describiendo `metrics.parquet` y `proc_modes` —ambos **prohibidos**
> en 0.2— sería publicar un contrato que el código ya no cumple. El resto del
> plan se conserva como registro histórico.

Decisión vigente: `rbm export` escribe **VibFrame 0.2**, un formato
parquet+JSON importado conceptualmente de `vibsynth-contracts.dataset` pero
copiado localmente para no depender del monorepo `vibsynth` en runtime.

```
dataset/
├── dataset.json                         # metadata del dataset
├── report.html                          # inventario HTML extra; base de rbm serve
└── machine=<ASSET_ID>/                  # un directorio por asset AMS
    ├── machine.json                     # metadata del asset, puntos,
    │                                    #   mode_definitions + mode_bindings
    │                                    #   y el catálogo machine.frequencies
    ├── metric_catalog.json              # descriptores de métricas escalares
    │                                    #   (JSON null-free, no una tabla)
    ├── spectra.parquet                  # FFT: eje derivado de fmin/fmax/lines
    ├── waves.parquet                    # waveforms: eje derivado de sample_rate_hz
    └── trends.parquet                   # tendencias escalares
```

**Esquema por tipo** (columnas requeridas; las opcionales, en el contrato
vendorizado `export/vibframe_contract.py`):

`unit` es siempre el Common Code de UN/CEFACT Recommendation 20, no una label:
`C16` (mm/s), `K40` (gravedad estándar), `HTZ` (Hz), `P1` (%).

- **FFT** (`spectra.parquet`): `t`, `point_id`, `proc_mode_id`, `fmin_hz`,
  `fmax_hz`, `lines`, `unit`, `signal_family`, `config_id`,
  `data: list<float32>`; más `mode_definition_id`, que resuelve la firma de
  adquisición contra `machine.json:mode_definitions`.
- **Waveform** (`waves.parquet`): `t`, `point_id`, `proc_mode_id`,
  `sample_rate_hz`, `n_samples`, `unit`, `signal_family`, `speed_hz`,
  `config_id`, `data: list<float32>`; más `mode_definition_id`.
- **Trend** (`trends.parquet`): una fila por lectura — `t`, `metric_id`,
  `value`, `alarm`, `config_id`; el `metric_id` se resuelve contra
  `metric_catalog.json` y se emite único por punto
  (`overall_velocity_rms__<point_id>`).

Las notas de adquisición que no caben en un campo tipado viajan como prosa en
el **mode binding** del punto, no en un modo global: `proc_modes` desapareció
en 0.2 y lo sustituyen la pareja
`mode_definitions` (la firma) + `mode_bindings` (su aplicación a un punto).
Desde ADR-0020 la waveform reconstruida coincide con el bloque nominal, por
lo que esa longitud ya no necesita una nota de divergencia.

El formato anterior (`manifest.parquet` + `samples/`) queda obsoleto. Los IDs
de muestra del viewer se generan en memoria al cargar el VibFrame.

## 5. Modelo de datos

`models.py` (frozen + slots): `Area` → `Equipment` → `Point`; y las muestras
`Spectrum` (amplitude calibrada), `Waveform` (samples calibradas), `Trend`
(serie `timestamps_utc` + `overall` en mm/s o G's y bandas). Sin Pydantic en
el parser; los modelos normativos de `vibsynth-contracts` sólo entran en
tests/CI, no en runtime.

## 6. Decisiones técnicas clave

Python 3.13 + `uv`; layout `src/`; acceso por **`mmap`** (no se cargan 1,8 GB
en RAM) con lectura lazy de muestras; `structlog` JSON desde el día uno;
política **saltar-con-log** (no abortar) salvo `--strict`; export paralelo con
`ProcessPoolExecutor` (un equipo por proceso). Encoding cp1252 → cp850 →
latin-1. Detalle y justificación en [`DECISIONS.md`](../DECISIONS.md)
(ADR-0001…ADR-0021).

## 7. Trabajo restante / opcional

- **Formato destino TWist**: confirmar qué campos/estructura espera su
  API/loader; puede requerir un adaptador de salida sobre los Parquet.
- ~~**Bandas `vddt`**: emitir las bandas con nombre (unidades mixtas: Mp Wave
  en G's, resto en mm/s) además del overall; y tendencias de **aceleración**
  (layout decodifica, escala del overall sin gold).~~
- ~~**`pdpa`** (config de análisis): mapear offsets exactos por banda
  (rango de frecuencia + umbrales de alarma); ver memoria del proyecto.~~
- Field notes, short codes nativos, plantillas no enlazadas.

**Nota (2026-08-05)**: los dos puntos **tachados** están hechos; se tachan en
vez de reescribir la lista:

- **Bandas `vddt`** — emitidas como métricas VibFrame propias (ADR-0010,
  2026-07-18: `band_<slug>__<punto>` en `trends.parquet` con su descriptor en
  `metrics.parquet` — desde 2026-08-10, en `metric_catalog.json`
  (ADR-0019) —, Mp Wave en g como `true_peak`), y las **tendencias de
  aceleración** (PeakVue/HF) emitidas con el overall crudo en G's tras el gold
  de DT-0070 M1P, 147/147 (ADR-0014, 2026-07-20).
- **`pdpa`** — layout resuelto el 2026-07-19 (FORMAT §5.8, ADR-0012,
  `records/pdpa.py`): plantillas de banda con sus rangos, sets `pdla` con los
  umbrales C/D, y la columna `alarm` de `trends.parquet` derivada de ellos. Lo
  que sigue abierto no son los offsets sino los **otros tipos de alarma** de
  AMS («Advertencia», «Bs», «Vl»), sin localizar en el binario (ADR-0013 y
  ADR-0014).
- El **formato destino TWist** y la última línea (field notes, short codes,
  plantillas no enlazadas) siguen vivos.

## 8. Testing

Tres capas: (1) **unit** con fixtures sintéticos (`tests/fixtures/`); (2)
**integración** contra el `.rbm` real, marcadas `@pytest.mark.integration`,
saltadas si no hay `RBM_TEST_FILE`; (3) **verificación visual humana** contra
capturas de AMS, documentada en [`VERIFICATION.md`](../VERIFICATION.md). El `.rbm`
real (datos de cliente) **no** se commitea (`.gitignore`).

## 9. Glosario

- **AMS / RBMware / MT4.00**: software y formato de Emerson/CSI (Master Trend 4).
- **FFT / waveform / overall**: espectro en frecuencia / serie temporal / valor
  global RMS o pico.
- **PeakVue**: técnica de Emerson para fallos de baja energía (demodulación HF).
- **Valores Globales**: tendencia temporal del overall + bandas que pinta AMS.
- **TWist / TWave**: software destino de la migración.
- **Hive partitioning**: convención `key=value/` en rutas, entendida por
  pandas/polars/duckdb/pyarrow.

## 10. Referencias

- Eka Siswanto, *RBMware (\*.RBM) File Format*, 2018.
- Emerson, *AMS Machinery Manager User Guide v5.61*, 2014.
- TWave T8 Explorer (ecosistema destino).

## Apéndice — carga del dataset

```python
import polars as pl
spectra = pl.scan_parquet("dataset/machine=*/spectra.parquet")
waves = pl.scan_parquet("dataset/machine=*/waves.parquet")
trends = pl.scan_parquet("dataset/machine=*/trends.parquet")
```

```sql
-- DuckDB
SELECT regexp_extract(filename, 'machine=([^/]+)', 1) AS asset, COUNT(*) AS samples
FROM read_parquet('dataset/machine=*/spectra.parquet', filename=true)
GROUP BY asset ORDER BY samples DESC;
```
