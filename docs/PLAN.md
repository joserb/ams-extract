# ams-extract — estado y arquitectura

> Herramienta CLI en Python para extraer datos de bases RBMware / AMS Machinery
> Manager (`.rbm`) a formatos modernos (Parquet + JSON), sin depender de la VM
> Windows XP ni del software AMS original.

Última actualización: 2026-05-31 · Repo: `git@github.com:joserb/ams-extract.git`
(privado) · Branch de trabajo: `master`.

> **Nota histórica**: este documento fue originalmente un plan por fases (0–7)
> con un esquema de ejecución agéntica por worktrees. El proyecto ya está
> completo en lo esencial, así que se ha reducido a su **estado y arquitectura
> vigentes**. El formato binario reverse-engineered vive en
> [`FORMAT.md`](FORMAT.md); las decisiones en [`DECISIONS.md`](DECISIONS.md);
> el protocolo y registro de verificación en [`VERIFICATION.md`](VERIFICATION.md).

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
| Waveforms → G's / mm/s | ✅ escala `vdfw.0x28`; velocidad ×25.4 → mm/s |
| Tendencias "Valores Globales" → mm/s | ✅ `vddt`, off-by-one de fechas (validado 47/47) |
| Export masivo (`rbm export`) | ✅ BUNGE entero (1,8 GiB) en **~19 s** `--parallel 4`; **274.478** muestras FFT+wv = conteo exacto AMS; 0 fallos; ~1,3 GB Parquet; ahora emite `report.html` |
| Estadísticas (`rbm stats`) | ✅ summary / machines / points (sp/wv/tn) |
| Inventario HTML (`rbm report`) | ✅ árbol localizaciones → máquinas con conteos + fechas (primera/última) por tipo, archivo único con filtro; leído del `.rbm` |
| Viewer on-demand (`rbm serve`) | ✅ sirve un `.rbm` directo (arranque solo jerarquía; puntos/muestras lazy; render desde el `.rbm`) o un dataset Parquet exportado; FFT/onda/tendencia bajo demanda (sin pregenerar PNG) |

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
o un **dataset exportado** (lee `manifest.parquet`). En ambos casos las gráficas
se renderizan **bajo demanda** y nunca se pregenera PNG.

`sp` = espectros FFT, `wv` = waveforms, `tn` = lecturas de tendencia.

## 4. Salida de `rbm export` (contrato de datos)

Decisión: **un Parquet por equipo y por tipo de muestra**, particionado tipo
Hive por área.

```
dataset/
├── hierarchy.json                       # árbol completo (Área → Equipo → Punto)
├── report.html                          # inventario HTML (= rbm report); base de rbm serve
├── manifest.parquet                     # índice global, una fila por muestra, sin arrays
└── samples/
    └── area=<AREA>/
        ├── equipment=<EQUIPO>__fft.parquet
        ├── equipment=<EQUIPO>__waveform.parquet
        └── equipment=<EQUIPO>__trend.parquet
```

**Esquema por tipo** (una fila por muestra; el eje de frecuencia/tiempo se
deriva de `fmax_hz`/`n_lines` o `sample_rate_hz`):

- **FFT**: `sample_id, point_record_num, point_long_name, point_short_code,
  spectrum_record_num, timestamp_utc, sample_type="FFT", fmax_hz, n_lines,
  units, carga_pct, amplitude: list<float32>`.
- **Waveform**: `… waveform_record_num, timestamp_utc, sample_type="WAVEFORM",
  sample_rate_hz, n_samples, rpm, units, carga_pct, samples: list<float32>`.
- **Trend**: una fila **por lectura** — `… trend_record_num, timestamp_utc,
  sample_type="TREND", units, overall: float32`.

**`manifest.parquet`**: una fila por muestra sin arrays, con columnas
type-específicas nullables (`fmax_hz`/`n_lines` para FFT; `sample_rate_hz`/
`rpm`/`n_samples` para waveform; `overall` para trend) + `parquet_path`.

`sample_id` = SHA-1 determinista de `point:sample_record:type[:idx]`.
Sanitización de nombres en `naming.py`; el mapeo original ↔ sanitizado se
persiste en `hierarchy.json`.

## 5. Modelo de datos

`models.py` (frozen + slots): `Area` → `Equipment` → `Point`; y las muestras
`Spectrum` (amplitude calibrada), `Waveform` (samples calibradas), `Trend`
(serie `timestamps_utc` + `overall` en mm/s). Sin Pydantic en el parser; solo
en los modelos de export.

## 6. Decisiones técnicas clave

Python 3.13 + `uv`; layout `src/`; acceso por **`mmap`** (no se cargan 1,8 GB
en RAM) con lectura lazy de muestras; `structlog` JSON desde el día uno;
política **saltar-con-log** (no abortar) salvo `--strict`; export paralelo con
`ProcessPoolExecutor` (un equipo por proceso). Encoding cp1252 → cp850 →
latin-1. Detalle y justificación en [`DECISIONS.md`](DECISIONS.md) (ADR-0001…0006).

## 7. Trabajo restante / opcional

- **Formato destino TWist**: confirmar qué campos/estructura espera su
  API/loader; puede requerir un adaptador de salida sobre los Parquet.
- **Bandas `vddt`**: emitir las bandas con nombre (unidades mixtas: Mp Wave en
  G's, resto en mm/s) además del overall; y tendencias de **aceleración**
  (layout decodifica, escala del overall sin gold).
- **`pdpa`** (config de análisis): mapear offsets exactos por banda
  (rango de frecuencia + umbrales de alarma); ver memoria del proyecto.
- Field notes, short codes nativos, plantillas no enlazadas.

## 8. Testing

Tres capas: (1) **unit** con fixtures sintéticos (`tests/fixtures/`); (2)
**integración** contra el `.rbm` real, marcadas `@pytest.mark.integration`,
saltadas si no hay `RBM_TEST_FILE`; (3) **verificación visual humana** contra
capturas de AMS, documentada en [`VERIFICATION.md`](VERIFICATION.md). El `.rbm`
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
df = pl.scan_parquet("dataset/samples/", hive_partitioning=True)        # area como columna
recent = (pl.scan_parquet("dataset/manifest.parquet")
            .filter(pl.col("area") == "EXTRACCION")
            .filter(pl.col("timestamp_utc") > "2024-01-01").collect())
```

```sql
-- DuckDB
SELECT area, equipment, COUNT(*) AS samples
FROM read_parquet('dataset/samples/**/*.parquet', hive_partitioning=true)
GROUP BY area, equipment ORDER BY samples DESC;
```
