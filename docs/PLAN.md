# Plan de proyecto: `ams-extract`

> Herramienta CLI en Python para extraer datos de bases RBMware / AMS Machinery Manager
> (ficheros `.rbm`) a formatos modernos (Parquet + JSON), sin depender de la VM Windows XP
> ni del software AMS original.

Versión del documento: 1.0 (post Fase 6 + **calibración FFT completa**:
`rbm export` produce el dataset completo —hierarchy.json + manifest.parquet
+ samples por equipo/tipo— con paralelización opcional; los espectros de
velocidad salen calibrados en mm/s y los de aceleración —PeakVue + alta
frecuencia— en G's, validados contra varias máquinas; las waveforms en G's.
No queda deuda de calibración funcional)
Última actualización: 2026-05-30

Repo: `git@github.com:joserb/ams-extract.git` (privado)

---

## Estado actual del proyecto

| Fase | Estado | Notas |
|---|---|---|
| 0 — Bootstrap | ✅ completada | uv + pyproject + structlog + stubs CLI, todo verde |
| 1 — Reader + header | ✅ completada | `rbm info` extrae firma/descripción/timestamp; ADR-0001 (base-0) |
| 2a — Áreas + CI | ✅ completada | 15 áreas verificadas; CI matrix listo; ADR-0002 |
| 2b — Equipos y Puntos | ✅ completada | 15 áreas, 347 equipos, 5203 puntos, 1198 PEAKVUE (tras el fix gicm 20-slot del 2026-05-28); `rbm-dev scan --tags`; ADR-0003 |
| 3 — Sample reader FFT | ✅ completada | Sub-3a + sub-3b: `rbm extract --point NAME --equipment SUBSTR --limit N` emite Parquet + PNG. **Calibración RESUELTA (2026-05-30)**: espectro completo = banda baja (`vdps[0xC8:0x200]`, 78 bins) + cadena `vcps`. Velocidad ×48.5 → mm/s; aceleración (PeakVue + alta frecuencia) ×1.30 → G's. Validado a ±5–10% en varias máquinas (§5.6). |
| 4 — Verificación visual | ✅ parcial | 7/15 áreas visualmente verificadas; FFT (amplitudes mm/s y G's, frecuencias) y waveform (Pc/Pk) dentro del ~5–10% del gold de AMS. La calibración FFT se resolvió leyendo la banda baja del `vdps` + escala ×48.5 (velocidad) / ×1.30 (aceleración) (§5.6). |
| 5 — Waveforms | ✅ completada | sub-5a (recon) + sub-5b (impl): `records/waveform.py`, `walk_waveforms`, `rbm extract --type fft\|waveform\|both`. **Calibración de amplitud RESUELTA** vía `vdfw.0x28` (Pc/Pk de M1H idénticos al gold de AMS). |
| 6 — Export masivo | ✅ completada | `rbm export FILE --out dataset/ [--types fft,waveform] [--areas …] [--parallel N]` emite hierarchy.json + manifest.parquet + samples/area=X/equipment=Y__{fft,waveform}.parquet. Decisión: **ficheros separados por tipo**. Serial + ProcessPoolExecutor por equipo. |
| 7 — Refinamientos | ⏳ pendiente | Plantillas, field notes, bandas de alarma, `vddt`, short codes nativos |

Todas las fases hasta la 6 están en `master`. Origin pendiente de push
manual. Trabajo continúa directo sobre master (no se abren `phase-NN-*`
branches salvo experimento arriesgado).

---

## 1. Contexto y objetivo

Existen bases de datos `.rbm` legacy de instrumentos CSI (2120, 2130, 2140…) recogidas con
AMS Machinery Manager 5.x, que contienen años de mediciones de vibración (espectros FFT,
waveforms, valores globales, configuración de máquinas y puntos). La extracción nativa
desde AMS es manual y poco práctica para volúmenes grandes, y requiere mantener una VM
Windows XP indefinidamente.

**Objetivo del proyecto**: una CLI multiplataforma (WSL/Linux/macOS) que abra ficheros
`.rbm` directamente y produzca:

1. La jerarquía completa de la base (Áreas → Equipos → Puntos) en JSON.
2. Un índice de muestras (qué se midió, cuándo, dónde, con qué configuración) en Parquet.
3. Los espectros FFT (y, en fases posteriores, waveforms) en Parquet, organizados por
   máquina y particionados por área.

**Caso de uso primario**: migración offline de datos hacia TWist. El extractor produce
ficheros que TWist ingiere por su API REST u otro loader externo. No es una librería
embebida; es un ETL ejecutado fuera del backend de TWist.

## 2. Alcance del MVP y no-objetivos

**Dentro del MVP**:

- Lectura de la cabecera y validación de firma `MT4.00`.
- Walker top-down de la jerarquía: Áreas, Equipos, Puntos.
- Extracción de espectros FFT con metadatos (timestamp, unidades, Fmax, líneas).
- Subcomandos `info`, `tree`, `extract`, `export`.
- Logging estructurado JSON desde el día uno.
- Tests unitarios con fixtures sintéticos y validación contra el `.rbm` real.

**Fuera del MVP** (puede venir en iteraciones posteriores):

- Waveforms (fase 5, tras el MVP).
- Notas de campo (`Field Notes` / `Notepad Observations`) — sabidamente complicadas,
  varios analistas en foros llevan años sin extraerlas limpiamente.
- Datos de oil analysis, termografía, balanceo dinámico, transients.
- Re-importación o escritura en `.rbm`. Solo lectura.
- Interfaz gráfica.
- Conector directo a la API de TWist (es otra herramienta sobre los Parquet).

## 3. Decisiones técnicas clave (consolidadas)

### 3.1 Identidad del proyecto

- **Repo / proyecto**: `ams-extract`.
- **Paquete Python (importable)**: `ams_extract`.
- **Binarios CLI** declarados en `[project.scripts]`:
  - `rbm` — herramienta principal de usuario.
  - `rbm-dev` — utilidades de desarrollo (scan de tags, dump de records, etc.).
- **Visibilidad**: GitHub privado (`joserb/ams-extract`).

Justificación del split entre nombre de proyecto y nombre de binario: el proyecto es
"ams-extract" porque su caso de uso es migrar bases AMS, pero el binario es `rbm` porque
es lo que el usuario teclea contra un fichero `.rbm` — coincide con la extensión, es
corto, es mnemónico.

### 3.2 Lenguaje, runtime y empaquetado

- **Python 3.13** (versión estable más reciente). uv la instala sin necesidad de tener
  Python global en el WSL.
- **uv** como gestor de paquetes y de venv. Lockfile `uv.lock` en el repo.
- **Layout `src/`**: el código vive en `src/ams_extract/`. Evita imports accidentales
  desde la raíz y juega bien con `uv build`.
- Backend de build: `hatchling` (estándar moderno, viene por defecto con `uv init --lib`).

### 3.3 Estructura del proyecto

```
ams-extract/
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSE                           # MIT (ya existente)
├── .gitignore                        # añadir *.rbm explícitamente
├── .python-version                   # 3.13
├── docs/
│   ├── PLAN.md                       # este documento
│   ├── FORMAT.md                     # spec viviente del .rbm conforme la descubrimos
│   ├── DECISIONS.md                  # ADRs cortos (architectural decision records)
│   └── VERIFICATION.md               # protocolo de comparación con AMS
├── src/ams_extract/
│   ├── __init__.py
│   ├── cli.py                        # entrypoint Typer (binario `rbm`)
│   ├── cli_dev.py                    # entrypoint Typer (binario `rbm-dev`)
│   ├── reader.py                     # acceso bajo nivel (mmap + read_record)
│   ├── encoding.py                   # cp1252/cp850 helpers, padding stripping
│   ├── records/
│   │   ├── __init__.py
│   │   ├── tags.py                   # constantes de tags 4-char observados
│   │   ├── header.py                 # parser del record 0
│   │   ├── area.py                   # áreas + cadena
│   │   ├── equipment.py              # gdts / equipos
│   │   ├── point.py                  # gipm / mpdo / puntos
│   │   ├── sample_index.py           # odcd / dcod
│   │   └── sample.py                 # oddt / tddo: FFT y waveform
│   ├── tree.py                       # walker top-down de la jerarquía
│   ├── scan.py                       # walker bottom-up (sanity check / tag stats)
│   ├── models.py                     # dataclasses inmutables del dominio
│   ├── export/
│   │   ├── __init__.py
│   │   ├── json_tree.py
│   │   ├── parquet_samples.py        # Parquet por equipo, partición Hive por área
│   │   └── manifest.py               # manifest.parquet global
│   ├── naming.py                     # sanitización de nombres → identificadores ficheros
│   └── logging_setup.py              # structlog en modo JSON desde el inicio
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── synthetic_minimal.rbm     # generado por script, 10-20 records
│   │   └── README.md
│   ├── test_reader.py
│   ├── test_header.py
│   ├── test_area.py
│   ├── test_tree.py
│   ├── test_sample_fft.py
│   ├── test_naming.py
│   └── test_export.py
├── scripts/
│   ├── make_synthetic_fixture.py
│   ├── compare_with_screenshot.py
│   └── benchmark.py
└── tools/
    └── hex_inspect.py                # helper para explorar bytes en un offset
```

### 3.4 CLI

Framework: **Typer** (sobre Click, con tipos). Salida con **Rich** para que sea legible.

Binario principal `rbm` (subcomandos del MVP):

```
rbm info FILE                         # firma, versión, tamaño, conteos rápidos
rbm tree FILE [--out tree.json]       # exporta jerarquía Áreas/Equipos/Puntos
rbm extract FILE --point NAME         # 2-3 muestras de un punto, Parquet + PNG
                 [--limit N]
                 [--out DIR]
rbm export FILE --out DATASET_DIR     # dump completo (ver §3.5 estructura)
                [--types fft,waveform]
                [--areas AREA1,AREA2]
                [--parallel N]
```

Binario auxiliar `rbm-dev` (no es producto final, es tooling de desarrollo):

```
rbm-dev scan FILE --tags              # frecuencia de cada tag 4-char en el fichero
rbm-dev dump-record FILE --rec N      # hex+ascii de un registro concreto
rbm-dev follow-chain FILE --from N    # sigue la lista enlazada desde el registro N
```

Flags globales (en ambos binarios):

```
--log-format {json,text}              # default: json
--log-level {debug,info,warning,error}
--strict                              # abortar al primer error en vez de saltar
```

### 3.5 Estructura del output de `rbm export`

Decisión: **un Parquet por equipo (máquina), particionado tipo Hive por área**. Esto
combina lo mejor de varias opciones:

```
dataset/
├── hierarchy.json                              # árbol completo (Área → Equipo → Punto)
├── manifest.parquet                            # índice global de muestras
└── samples/
    ├── area=CONTRA_INCENDIOS/
    │   ├── equipment=BOMBA_FC_01.parquet
    │   ├── equipment=BOMBA_FC_02.parquet
    │   └── ...
    ├── area=EXTRACCION/
    │   ├── equipment=MOTOR_EXT_01.parquet
    │   └── ...
    └── ...
```

**Por qué por equipo y no por punto**: un equipo típico tiene 4-12 puntos (LA H, LA V,
LA A, LOA H, LOA V, LOA A, motor LA, motor LOA…). Mantener todos los puntos de la misma
máquina en un fichero es la unidad lógica natural — el analista quiere ver "todo lo de
esta bomba" para correlacionar. Además genera del orden de cientos de ficheros y no miles.

**Por qué partición Hive por área**: estándar moderno entendido por pandas/polars/duckdb/
spark/pyarrow automáticamente. Permite:

```python
# todo lo de un área:
df = pl.scan_parquet("dataset/samples/area=EXTRACCION/")

# una máquina concreta:
df = pl.read_parquet("dataset/samples/area=EXTRACCION/equipment=MOTOR_EXT_01.parquet")

# todo el dataset, con area y equipment como columnas:
df = pl.scan_parquet("dataset/samples/", hive_partitioning=True)
```

**Esquema de un Parquet de equipo**: una fila por muestra (cada espectro o waveform).

| columna | tipo | nota |
|---|---|---|
| sample_id | string | UUID o hash determinista |
| point_id | string | referencia a hierarchy.json |
| point_name | string | denormalizado para legibilidad |
| point_short | string | código corto del punto |
| timestamp_utc | timestamp[ns] | hora de la medida |
| sample_type | string | fft \| waveform \| overall \| peakvue |
| units | string | mm/s, g, IPS, etc. |
| fmax_hz | float64 | nullable |
| n_lines | int32 | nullable, longitud del array |
| window | string | nullable |
| n_avgs | int32 | nullable |
| amplitude | list<float32> | el array de datos |
| frequency_hz | list<float32> | solo para FFT, derivable de fmax/n_lines |
| raw_metadata | map<string,string> | extras no estandarizados |

**Esquema del `manifest.parquet`**: una fila por muestra, sin los arrays — sirve de
índice maestro:

```
sample_id, area, equipment, point_id, point_name, timestamp_utc, sample_type,
units, fmax_hz, n_lines, parquet_path
```

Permite contestar a "¿qué medidas tengo entre fechas X e Y de la zona EXTRACCION?" sin
cargar ningún espectro.

**Sanitización de nombres** (`naming.py`): los nombres de áreas y equipos en el `.rbm`
pueden tener espacios, acentos, caracteres especiales. El mapeo a nombres de ficheros y
valores de partición se hace en `naming.py` con reglas:

- ASCII puro, caracteres especiales → `_`
- Espacios → `_`
- Truncar a 64 chars
- Si colisionan dos, sufijo numérico determinista

El mapeo original ↔ sanitizado se persiste en `hierarchy.json` para round-trip.

### 3.6 Modelo de datos (dataclasses)

```python
@dataclass(frozen=True, slots=True)
class Area:
    record_num: int
    long_name: str
    short_code: str
    equipment_chain_start: int

@dataclass(frozen=True, slots=True)
class Equipment:
    record_num: int
    long_name: str
    short_code: str
    area: Area
    point_chain_start: int

@dataclass(frozen=True, slots=True)
class Point:
    record_num: int
    long_name: str
    short_code: str
    equipment: Equipment
    sample_index_record: int
    template_name: str | None         # "REDUCTORA 50-150 rpm (S)"
    units: str | None
    fmax_hz: float | None
    n_lines: int | None

@dataclass(frozen=True, slots=True)
class Sample:
    record_num: int
    point: Point
    timestamp_utc: datetime
    sample_type: SampleType           # FFT | WAVEFORM | OVERALL | PEAKVUE
    description: str
    amplitude: np.ndarray             # lazy: cargado solo al accederlo
    metadata: dict[str, Any]
```

`frozen=True` y `slots=True` por inmutabilidad y eficiencia de memoria.

Decisión consciente: **no Pydantic en el núcleo del parser**. Pydantic se usa solo en
los modelos de export (donde sí valida el JSON de jerarquía).

### 3.7 Política de errores y logging

Confirmado: **saltar con log detallado**, nunca abortar a mitad de un export salvo error
fatal de I/O. Flag `--strict` opcional para CI y tests.

- **structlog** con renderer JSON por defecto, renderer texto coloreado opcional con
  `--log-format=text`.
- Tres severidades de dominio:
  - `INFO`: progreso normal, hitos.
  - `WARNING`: registro saltado pero esperado (tipo no soportado, fuera de rango, etc.).
  - `ERROR`: registro corrupto o no parseable; se loguea y se sigue.
- Resumen final del export: procesados, saltados, fallados, motivos agregados.
- Modo `--strict` aborta al primer ERROR.

### 3.8 Encoding y strings

- **`cp1252`** (Windows-1252) por defecto, fallback a **`cp850`** (CSI/DOS antiguo) si
  hay bytes inválidos en cp1252. Último fallback: `latin-1` con `errors=replace` para
  garantizar que nunca petamos.
- Confirmado en el dump: `EST\xc1NDAR` = "ESTÁNDAR" (cp1252). `OPERACI\xd3N` aparece
  también — confirma cp1252. Pero conviene tener cp850 a mano por si encontramos un
  `.rbm` más antiguo.
- Helper único `decode_string(raw: bytes) -> str` en `encoding.py`.
- Padding: nombres largos (32 bytes) y códigos cortos (4 bytes) vienen rellenos con
  espacios (`0x20`) y/o nulos (`0x00`). Función `strip_padding()` unificada.

### 3.9 Performance y memoria

- **`mmap`** sobre el fichero. NO cargar 1.8 GB en RAM. Acceso aleatorio rápido por
  offset.
- Lectura de muestras **lazy**: el walker devuelve `Sample` con `amplitude` cargada solo
  al accederlo.
- `export` masivo: procesado por equipo (todas las muestras de un equipo se acumulan, se
  escriben a su Parquet, se libera memoria, siguiente equipo). Footprint acotado.
- **Paralelización opcional** en `export` con `concurrent.futures.ProcessPoolExecutor`:
  un equipo por proceso, mmap reabierto en cada worker. Por defecto serial; activar con
  `--parallel N`.
- Progress bars con `rich.progress`.

### 3.10 Calidad: tests, lint, type-check

- **`pytest`** + `pytest-cov`. Objetivo >85% de cobertura en el parser.
- **`ruff`** para lint y format. Config en `pyproject.toml`.
- **`pyright`** en modo `strict` para type-checking. Razones sobre mypy: más rápido,
  mejor con `slots=True` y `TypedDict`.
- **Pre-commit hooks** opcionales (ruff format, ruff check, pyright en cambios).
- **CI con GitHub Actions** desde la **Fase 2**, no antes (decisión confirmada). Matrix
  Linux/macOS/Windows, Python 3.13.

## 4. Conocimiento actual del formato `.rbm`

Esta sección es **viviente**: se actualiza a medida que descubrimos detalles. La versión
canónica vivirá en `docs/FORMAT.md` una vez creado; este resumen sirve para arrancar.

> La spec viva está en `docs/FORMAT.md`. Las decisiones que justifican cada
> elección viven en `docs/DECISIONS.md` (ADR-0001 indexación, ADR-0002 áreas).
> Esta sección queda como puntos de partida y *gaps* aún abiertos.

### 4.1 Estructura general — VERIFICADO

- Fichero compuesto por **registros de 512 bytes exactos**. Tamaño total siempre múltiplo
  de 512 (verificado: 1 857 595 904 / 512 = 3 628 117 records sin resto).
- **Indexación base-0**: `offset = n × 512`, `n ∈ [0, record_count)`.
  Decidido y validado experimentalmente en Fase 1 — ver ADR-0001.
- El registro 0 contiene la cabecera global.

### 4.2 Cabecera (registro 0) — VERIFICADO en Fase 1

Layout confirmado contra `BUNGE CARTAGENA marzo 2.0.rbm` (extracto):

| Offset | Tamaño | Campo | Ejemplo en BUNGE |
|---|---|---|---|
| `0x00` | 4 | `header_marker` (¿checksum?) | `76 05 9f 3c` |
| `0x04` | 4 | `version_marker` | `01 00 0e 00` |
| `0x08` | 4 | tag ASCII `gddh` | `gddh` |
| `0x0C` | 16 | GUID / hash | `99304471db1ac447a20c3d117cc774cb` |
| `0x1C` | 6 | firma ASCII `MT4.00` | `MT4.00` |
| `0x2C` | 4 | u32 LE — timestamp candidato | `0x612f1c6b` = 2021-09-01 06:23:39 UTC |
| `0x58` | 40 | descripción (cp1252, space-padded) | `Preditec` |
| `0xDC` | 4 | u32 LE — puntero primario a record de áreas (layout "simple list") | `70` |
| `0xE4` | 4 | u32 LE — puntero secundario a record de áreas (layout "prefixed list") | `69` |

Notar: hay un **segundo puntero** a áreas en `0xE4`, sorpresa de Fase 2. El layout
"prefixed list" que vive en el record secundario contiene un preámbulo binario con
tag `gits` + tabla de u32 que probablemente apunta a las cadenas de equipos
(hipótesis para Fase 2b — §5 abajo).

### 4.3 Jerarquía — REVISADA tras Fase 2

```
Database (record 0 — gddh)
  ├── [0xDC] Area record "simple list"   (record 70 en BUNGE: 5 áreas)
  └── [0xE4] Area record "prefixed list" (record 69 en BUNGE: 10 áreas + prefijo binario)
       └── ¿punteros a equipos en la tabla u32 LE de 0x10-0x44?  ← Fase 2b
            └── Equipment records
                 └── ¿punteros a puntos?                          ← Fase 2b
                      └── Point records (incl. mezcla con templates)
                           └── dcod / odcd  (rango de samples)    ← Fase 3
                                └── tddo / oddt  (sample FFT)     ← Fase 3
```

NB: **no hay cadena enlazada entre records de área** (los records 71-77 en BUNGE
son `gdwn` vacíos, no continuación). La hipótesis de Eka "cadena con hasta 22
areas por record + chain pointer" no aplica a las versiones MT4.00 que tenemos.

Captura de AMS confirmada (15 áreas):
CONTRA INCENDIOS, EXTRACCION, DEPURADORA, IMPULSIÓN DE MAR, NAVES, PASILLO DE
BOMBAS, PELETIZACION, PREPARACION, REFINERIA, CALDERAS, FULL-FAT, PARQUE
TANQUES, OBSOLETOS, SERVICIOS, OSMOSIS.

Convención: los nombres de tag de 4 chars se leen **tal cual aparecen en disco**
(orden de bytes). `gddh`, `gits`, `gdwn`, `rdlg` ya observados; mapeo completo
en Fase 4.

### 4.4 Tags de 4 chars observados en el fichero real

Detectados en los dumps de Fases 1-2:

- `gddh` — cabecera (record 0, offset 0x08). _Confirmado en Fase 1._
- `gits` — record de áreas "prefixed list" (record 69 en BUNGE, offset 0x08).
  Encabeza la tabla de u32 que probablemente contiene los punteros a equipos.
  _Confirmado en Fase 2._
- `gdwn` — records vacíos contiguos al de áreas (71-77 en BUNGE). Función
  desconocida; podrían ser slots reservados / templates.
- `rdlg` — observado en record 78 con flotantes y banderas pequeñas. Posiblemente
  configuración de log/registro.
- `pdla`, `pdsh` — relacionados con puntos (`pdla` = "point data, long"?
  `pdsh` = "point data, short"?). _Observados en dumps tempranos, sin verificar._
- `vcfw`, `vcps`, `vcpsh` — relacionados con FFT/sample data
  (`vc` = "vibration channel"?). _Observados en dumps tempranos, sin verificar._

Mapearemos exhaustivamente en Fase 4 con `rbm-dev scan --tags`.

### 4.5 Sample record (oddt / tddo) — esperado

Según Eka:

- record_num del siguiente sample (lista enlazada),
- timestamp (Unix u otro),
- descripción del sample (string),
- array de float32 IEEE-754 little-endian.

A verificar para nuestros datos:

- ¿Hay flags que indiquen FFT vs waveform vs overall?
- ¿Dónde están las unidades, Fmax, líneas, ventana, n_avgs?
- ¿La longitud del array está en el header del record o se infiere?
- ¿Hay calibración/escala aplicada o son valores absolutos?

### 4.6 Incógnitas y zonas oscuras

Resueltas:

- ~~Indexación base-0 vs base-1~~. **Base-0** confirmado en Fase 1 (ADR-0001).
- ~~Encoding~~. **cp1252** confirmado en Fase 1-2; fallback cp850 → latin-1 implementado.
- ~~Estructura de la cabecera del header~~. Layout verificado en Fase 1.
- ~~Cómo se enlazan las áreas~~. **No hay cadena**: dos punteros en el header
  (0xDC y 0xE4). Documentado en ADR-0002.

Abiertas:

- **Cadena Área → Equipo**: hipótesis principal — la tabla de u32 LE en
  `0x10-0x44` del record "prefixed list" (record 69 en BUNGE) contiene
  punteros a records de equipos por área. 13 valores observados que crecen
  monótonamente: `298, 4853, 336467, 390654, 400612, 476104, 479522, 504709,
  819656, 967257, 1012745, 1025192, 1032888`. Hay que abrir cada uno con
  `rbm-dev dump-record` para verificar. **Trabajo de Fase 2b.**
- **Códigos cortos nativos** (CI, EXT, DEP, MAR…): viven en record 70 slots
  12-13 como concatenación de 4-char fixed-width. No emparejados aún con sus
  áreas. Phase 2 los deriva sanitizando el long_name. Fase 2b puede leerlos
  nativos si emerge la necesidad (p.ej. para coincidir con paths de export).
- **Plantillas vs equipos reales**: la UI de AMS muestra mezcla
  (DEP-M / DEP-M+T3 / IBL-REACC S1 al inicio de la lista de DEP). ¿Se
  distinguen por un flag en el record, por número de record, por tag, o por
  posición en la cadena? **Pregunta de Fase 2b.**
- **Estructura del record de Punto**: el árbol AMS muestra que un punto tiene
  sub-elementos: "Valores Globales", "Mp Wave", bandas con nombre
  (SUBSINCRONO, DESEQUILIBRIO, DESALINEACION, HOLGURAS, 11-40 X RPM, 1-20 KHz),
  lista de timestamps de FFT y waveform. Probablemente todo eso está en el
  record del punto + records hijos. **Fase 2b/3.**
- **Estructura interna del `oddt`** para distinguir tipos de muestra. _Fase 3._
- **Cómo se almacenan las bandas de alarma** ("FALLO ELECTRIC", "HOLGURAS"…).
  _Fase 3-7._
- **Field Notes / Notepad Observations** — sabidamente problemático. _Fase 7._

## 5. Hoja de ruta por fases

Cada fase es atómica: deja el proyecto en estado verde (tests pasando, `rbm --help`
funciona) y entrega valor incremental. Pensadas para ejecutarse como tareas agénticas
independientes desde la CLI.

### Fase 0 — Bootstrap (≈ 0.5 sesión) ✅ COMPLETADA

> Branch: `phase-00-bootstrap`. 6 commits, 1561 inserciones. Todo verde.

**Objetivo**: esqueleto del proyecto compilando y con tooling listo.

Entregables:

- `uv init --lib` (o equivalente manual), layout `src/`, `pyproject.toml` con metadatos.
- Python 3.13 fijado en `.python-version`.
- Dependencias mínimas: `typer`, `rich`, `numpy`, `pyarrow`, `structlog`, `pytest`,
  `ruff`, `pyright`.
- Binarios `rbm` y `rbm-dev` en `[project.scripts]` apuntando a stubs.
- Subcomandos vacíos pero presentes (`--help` muestra los 4 + los 3 de dev).
- Configuración de ruff y pyright en `pyproject.toml`.
- `logging_setup.py` con structlog en JSON.
- Un test smoke que pasa.
- `.gitignore` ampliado: `*.rbm`, `*.RBM`, `dataset/`, `samples/`, `.rbm-cache/`.
- `docs/FORMAT.md`, `docs/DECISIONS.md`, `docs/VERIFICATION.md` con plantilla vacía.

**Definition of done**: `uv run pytest` pasa; `uv run rbm --help` y `uv run rbm-dev --help`
muestran los subcomandos; `uv run ruff check .` y `uv run pyright src/` pasan limpios.

### Fase 1 — Reader y header (≈ 1 sesión) ✅ COMPLETADA

> Branch: `phase-01-reader-and-header`. 7 commits. ADR-0001 (base-0).
> `rbm info` extrae correctamente firma, descripción "Preditec", timestamp
> 2021-09-01 06:23:39 UTC y puntero a record 70.

**Objetivo**: leer registros y entender la cabecera.

Entregables:

- `RbmReader` con `mmap`, `read_record(n)`, validación de alineación 512.
- Decisión y documentación de la convención de indexación (base-0 o base-1) en
  `docs/DECISIONS.md`.
- Parser de record 0: firma `MT4.00`, descripción de BD, hash/GUID, timestamp, puntero
  inicial.
- Helper `decode_string` con cp1252 / cp850 fallback.
- Subcomando `rbm info FILE` operativo.
- Subcomandos `rbm-dev dump-record` y `rbm-dev follow-chain` operativos.
- Tests con fixture sintético + test de integración contra el fichero real.

**Definition of done**: `rbm info BUNGE_CARTAGENA_marzo_2.0.rbm` imprime correctamente
firma, versión y descripción ("Preditec"). El primer puntero del header apunta a un
registro cuyo contenido es plausiblemente la primera cadena de áreas.

### Fase 2a — Áreas + CI (≈ 1 sesión) ✅ COMPLETADA

> Branch: `phase-02-hierarchy-and-ci`. 9 commits. ADR-0002 (dos punteros de
> áreas + heurística de detección). CI matrix Linux/macOS/Windows configurado.
> `rbm tree` produce JSON con las 15 áreas verificadas contra captura de AMS.

**Objetivo**: extraer la lista de áreas y dejar la CI verde.

Entregables completados:

- Parser de Area (`records/area.py`) con soporte para los dos layouts observados:
  "simple list" (record 70) y "prefixed list" (record 69).
- Walker `walk_areas` (`tree.py`) que combina ambos punteros del header, dedupea
  records compartidos y devuelve la lista canónicamente ordenada.
- `models.py` con `Area`/`Equipment`/`Point` (los dos últimos como placeholders
  para Fase 2b).
- `naming.py` con `NameSanitizer` determinista + sufijos numéricos en colisión.
- Subcomando `rbm tree FILE [--out tree.json]` operativo.
- Export JSON con schema versionado (`schema_version=1`, `phase="phase-2-areas-only"`)
  para que consumidores detecten que equipos/puntos están vacíos.
- **GitHub Actions** con matrix Linux/macOS/Windows × Python 3.13: ruff + pyright + pytest.

**Definition of done cumplida**: `tree.json` se genera; el conteo de áreas
cuadra con la UI de AMS (15, no 14 como decía el plan original; documentado en
ADR-0002). CI estructurada para correr en push/PR a master.

### Fase 2b — Equipos y Puntos (≈ 1 sesión) ✅ COMPLETADA

> Branch: `phase-02b-equipment-points`. 8 commits. ADR-0003 (cadena
> `gdts → gicm → gdcm → gipm → vdpm` + convención "+1 encoded" para
> punteros internos). El recuento de PEAKVUE quedó en 869, dentro del
> ±5% del objetivo ~895 fijado en la DoD.

**Objetivo**: completar el walker top-down hasta el nivel de Point.

Hipótesis verificada primero con `rbm-dev dump-record`: la tabla de u32
LE en `0x10-0x4F` del record prefix-list (record 69) son los punteros a
records de equipos por área — **una entrada por área en orden walker**,
no 13 sino **15**, todas válidas y todas con tag `gdts`. La numeración
recordada en la sesión previa (`298, 4853, 336467, …`) estaba
ligeramente desviada; los valores correctos quedaron en ADR-0003.

Entregables completados:

- Parser de Equipment (`records/equipment.py`) — gdts → gicm → gdcm,
  con seguimiento de la lista enlazada `gicm.0x0C` y detección de
  ciclos para áreas con > 12 equipos.
- Parser de Point (`records/point.py`) — gipm → vdpm, con tabla de
  punteros en `gipm.0x1C0` (16 slots, terminada por 0) y long_name en
  `vdpm.0x18` (32 bytes cp1252 padded).
- `models.py` con `Equipment` y `Point` completamente poblados
  (record_num, long_name, short_code derivado).
- `walk_hierarchy()` recursivo con logging WARN-no-abort por record
  problemático y cycle-detection en la cadena de gicm.
- `rbm tree --out tree.json` emite jerarquía completa con
  `schema_version=2`, `phase="phase-2b-complete"`.
- `rbm-dev scan --tags` cuenta frecuencias de los 4-char tags;
  resultado de BUNGE ya inventariado en `docs/FORMAT.md` §4.
- Tests: unit (`tests/test_equipment.py`, `tests/test_point.py`,
  ampliaciones de `test_area.py`, `test_cli.py`) + 5 nuevos
  integration tests (`test_integration_tree.py`).

**Definition of done cumplida**: `tree.json` se genera con 15 áreas,
252 equipos, 3795 puntos. PEAKVUE-named points = 869, dentro del ±5%
del objetivo. El schema reporta `phase="phase-2b-complete"`. CI sigue
verde.

**Aplazado a otra iteración** (no bloqueante):

- Distinguir plantillas (DEP-M, IBL-REACC S1, …) de equipos reales. Como
  las plantillas no están enlazadas desde la jerarquía de áreas, el
  walker ya las omite por construcción. Si en algún momento se quieren
  exportar, habría que escanear records `vdpm` no alcanzados (Fase 7).
- Significado de los i32 signed deltas en `gicm.0x60+` y `vdpm.0x10+`.
  Pendiente cuando estorbe.

### Fase 2 — Sanity checks finales (post-2b)

Una vez completada 2b, validar contra AMS (capturas del usuario):

- Cada área tiene la lista correcta de equipos.
- DEP tiene exactamente la lista vista en captura 2 (DEP-M, DEP-M+T3,
  IBL-REACC S1, AG-100, CF-4900, CF-5900, PM-100, PM-100B, PM-101, ...).
- AG-100 (en DEP) tiene los puntos vistos en captura 3 (M1H, M1V, M1P, M1F,
  M2V, M2P, M2A, R1H, R1V, R1F, R1P, R1A, ...).

### Fase 3 — Sample reader FFT (≈ 2-3 sesiones)

**Objetivo**: extraer espectros FFT de un punto conocido.

Nota: los tags `odcd` / `oddt` que mencionaba Eka no aparecen en BUNGE.
`rbm-dev scan --tags` da `vcps` (1 931 424 records, 53%) y `vcfw`
(1 322 008, 36%) como dominantes — esos son los samples reales. El
enlace desde un punto a sus muestras vive en algún sitio del descriptor
`vdpm.0x38+`, todavía sin parsear.

Sub-fase 3a (reconocimiento) — ✅ completada 2026-05-28:

- Mapeado contra M1H de AG-100 (record `vdpm` 336982). El path
  verificado es `vdpm.0x10 → pdcd (índice) → 0x44 → primer vdps →
  0x18 → primer vcps`.
- 5 `vdps` (uno por timestamp) encadenados vía `0x14`, con Fmax /
  n_lines / units / CARGA en offsets conocidos.
- 13 `vcps` por espectro (122 floats c/u = 1586 ≈ 1600 líneas).
- Documentado en `FORMAT.md §5`. Pendiente para 3b: `vcfw` waveform,
  `vddt` (otros tipos), escalado de amplitudes.

Sub-fase 3b (implementación) — ✅ completada 2026-05-29:

- Parsers en `records/sample_index.py` (`pdcd`) y `records/sample.py`
  (`vdps`, `vcps`) con unit tests sobre fixtures sintéticos.
- `walk_spectra(reader, point)` en `tree.py` con política WARN-no-abort.
- `models.Spectrum` (frozen dataclass) con metadata + amplitude np.ndarray.
- Subcomando `rbm extract FILE --point NAME --equipment SUBSTR --limit N
  --out DIR` que emite `{eq}__{point}__{idx}_{ts}.parquet` + `.png`.
  El flag `--equipment` resuelve la ambigüedad cuando el long_name del
  punto se repite en múltiples equipos (caso típico de "MOTOR LOA
  HORIZONTAL").
- `export/parquet_samples.py` con una fila por espectro (schema
  alineado con PLAN §3.5), `export/spectrum_plot.py` con PNG
  matplotlib eje lineal.
- Tests: 11 unit + 3 integración (timestamps cuadran con gold,
  amplitude shape=1586, ambigüedad falla con exit 2).

**Definition of done cumplida**: extraemos los 5 espectros de M1H de
AG-100 con timestamps idénticos al gold de AMS y picos coincidentes
en frecuencia (25 Hz fundamental, 50/100 Hz armónicos, picos a 540 y
840 Hz como en el screenshot de AMS).

**Resuelto después (2026-05-30, ver §5.6)**:

- ~~Escalado de amplitudes~~: RESUELTO. El espectro de display es la banda
  baja `vdps[0xC8:0x200]` (78 bins) concatenada con la cadena `vcps`;
  velocidad ×48.5 → mm/s, aceleración ×1.30 → G's. Ya no emitimos crudo.
- ~~Padding 14 bins (1586 vs 1600)~~: RESUELTO — el espectro real son 1664
  bins (78 baja + 1586 cadena), truncados a 1600; no faltaban bins.

### Fase 4 — Verificación visual contra AMS (≈ 0.5 sesión) — ✅ completada parcial 2026-05-29

**Objetivo**: validar (con humano en el loop) que lo extraído coincide con lo que vería
un analista en AMS.

Verificaciones realizadas contra capturas de AMS de M1H (MOTOR LOA
HORIZONTAL de AG-100 en DEPURADORA):

- **Jerarquía**: 7 de 15 áreas comparadas nombre-a-nombre con AMS
  (CONTRA INCENDIOS, IMPULSIÓN DE MAR, NAVES, PASILLO DE BOMBAS,
  PELETIZACION, DEPURADORA, CALDERAS). 4/5 match perfecto incluyendo
  orden; CALDERAS tiene un swap A↔B en PM-6904 porque AMS ordena
  alfabéticamente y nosotros por chain-order — confirmado como
  decisión consciente (ver memoria del proyecto). 8 áreas grandes
  pendientes de verificación visual pero con conteos locked en tests.
- **FFT M1H 2020-02-19**: frecuencias de picos cuadran (los 24 picos
  de la "Lista de Picos" de AMS están en los bins correctos de
  nuestro `rbm extract`), units calibradas (mm/s), timestamps
  idénticos. **Amplitudes RESUELTAS (2026-05-30)**: tras anteponer la
  banda baja `vdps[0xC8:0x200]` y aplicar ×48.5, los 24 picos casan
  con el gold a ±5–10% (logcorr +0.999); ver `FORMAT.md §5.6`.
- **FFT aceleración (PeakVue + HF)**: validado en PM-6901-A (M2P/B1P,
  PeakVue) y PM-6901-B (M1F, alta frecuencia fmax 6000) con escala ×1.30
  → G's, residual median ≈1.00 y logcorr +0.995/+0.998.
- **Waveform M1H 2020-02-19**: Pc(+) 0.483 vs AMS 0.483 (calibrado vía
  `vdfw.0x28`), Pk(-) -0.510 vs -0.510, sample_rate y units exactos.

**Definition of done**: cumplida — extracción estructuralmente correcta
y calibrada para FFT (mm/s y G's) y waveform (G's). No queda deuda de
calibración de amplitudes.

### Fase 5 — Waveforms (≈ 1-2 sesiones) — 🚧 sub-5a completada 2026-05-29

Sub-fase 5a (reconocimiento) — ✅:

- Cadena verificada: `pdcd.0x5C → vdfw → 0x18 → vcfw chain`. Dos
  punteros nuevos en `pdcd` (0x5C / 0x60) que sub-3a había pasado
  por alto al limitar el sweep a 0x00-0x4C.
- `vdfw` (descriptor por waveform): timestamp `0x34`, n_samples `0x2C`,
  sample_period `0x24`, RPM `0x38`, CARGA `0x3C`, units `0x6C`.
- `vcfw` (datos): 244 int16 LE por record en 0x18, chain via 0x14.
- Para M1H 19-feb-2020: 488 muestras (de 512 nominales) a 2560 Hz,
  Pc/Pk cuadran con AMS dentro del 2%. Documentado en `FORMAT.md §5.5`.

Sub-fase 5b (implementación) — ✅ completada 2026-05-29:

- `records/waveform.py` con `parse_vdfw_descriptor`, `walk_vdfw_chain`
  y `read_vcfw_samples` (análogo a `sample.py`; vcfw = 244 int16 LE/record).
- `pdcd` extendido con punteros vdfw (0x5C/0x60) en `sample_index.py`.
- `models.Waveform` (frozen dataclass) con timestamp, n_samples,
  sample_rate_hz, rpm, units, samples `np.ndarray` calibrados.
- `walk_waveforms(reader, point)` en `tree.py` (paralelo a
  `walk_spectra`; reusa el helper `_resolve_pdcd_links`).
- `rbm extract` con flag `--type fft|waveform|both` (default `both`).
  Filename: `{eq}__{point}__{fft|waveform}_{idx}_{ts}.parquet|.png`.
- `export/parquet_samples.write_waveform_parquet` +
  `export/waveform_plot.render_waveform_png`.
- Tests: 12 unit (`test_waveform.py`) + 2 integración (M1H 5 waveforms
  con timestamps gold; Pc/Pk del 19-feb dentro del 2% del gold de AMS).

**Hallazgo clave (calibración resuelta)**: cada `vdfw` lleva en `0x28`
un float32 `scale_factor` (display units por cuenta int16). Aplicado a
las muestras crudas reproduce el gold de AMS al < 0.3% (Pc 0.483 G,
Pk -0.510 G en M1H 19-feb). A diferencia del FFT, la waveform **no
hereda** la deuda de calibración de §5.6.

### Fase 6 — Export masivo (≈ 1 sesión) — ✅ completada 2026-05-29

**Objetivo**: dump completo de la base.

**Decisión de diseño** (consultada con humano, §7.4): **un Parquet por
equipo y por tipo de muestra** —
`samples/area=X/equipment=Y__fft.parquet` y `…__waveform.parquet`— en
lugar de un fichero unificado con `sample_type` discriminando. Esquemas
limpios sin columnas nullables, a costa de duplicar rutas por equipo.

Entregables completados:

- `export/parquet_samples.py`: writers batch `write_spectra_parquet` /
  `write_waveforms_parquet` (una fila por muestra) + `sample_id`
  determinista (SHA-1 de `point_rec:sample_rec:type`). Los writers de
  una sola muestra de `extract` quedan como wrappers sobre los batch:
  un único esquema compartido.
- `export/manifest.py`: `manifest.parquet` global, una fila por muestra
  **sin arrays** (índice maestro), con columnas type-específicas
  nullables (fmax/n_lines para FFT; sample_rate/rpm/n_samples para
  waveform) + `parquet_path` relativo.
- `export/dataset.py`: `export_dataset()` camina la jerarquía una vez,
  escribe `hierarchy.json` (árbol **completo**, no filtrado), y por cada
  equipo emite sus Parquet por tipo. Serial o
  `ProcessPoolExecutor` (un equipo por proceso, mmap reabierto en cada
  worker). Filtros por área (long_name o short_code, case-insensitive) y
  por tipo. Progress bar `rich`, logging agregado y `ExportSummary`.
  Política WARN-no-abort por equipo: una máquina corrupta no aborta el run.
- `rbm export FILE --out dataset/ [--types fft,waveform] [--areas …]
  [--parallel N]` operativo (default `--types fft,waveform`).
- Tests: 11 unit (`test_export_parquet.py` writers+manifest;
  `test_export_dataset.py` orquestación sobre fixture sintético + CLI) +
  3 integración (`test_integration_export.py`: layout DEPURADORA, M1H con
  5 FFT + 5 waveform en manifest y ficheros, paridad serial↔parallel).

**Definition of done cumplida**: `dataset/` se genera completo; carga vía
`pyarrow.dataset(..., partitioning="hive")` inyecta `area` desde la ruta;
M1H aparece con sus 5+5 muestras. Verificado sobre BUNGE (CONTRA
INCENDIOS: 4 equipos, 647 FFT + 647 waveform en < 1 s; DEPURADORA en los
tests de integración). Benchmark del fichero completo (1.86 GB) pendiente
de medir cuando se ejecute el export total.

**Notas / aplazado**:

- `ProcessPoolExecutor` usa el start-method `fork` por defecto en Linux y
  emite un `DeprecationWarning` (proceso multihilo). Es benigno —cada
  worker reabre su propio mmap sin estado compartido—; migrar a `spawn`
  si alguna vez molesta.
- `hierarchy.json` siempre refleja el árbol completo aunque `--areas`
  filtre; el filtro sólo restringe muestras y manifest (decisión
  consciente: la jerarquía es el mapa canónico de la BD).

### Fase 7 (opcional) — Refinamientos

- Field Notes (best effort, dado el historial de dificultad).
- Bandas de alarma y plantillas de análisis.
- Mejoras de performance.
- Documentación final del formato en `docs/FORMAT.md` como spec pública.

## 6. Estrategia de testing

**Tres capas**:

1. **Unit tests con fixtures sintéticos**. Un script `make_synthetic_fixture.py` genera
   un `.rbm` mínimo (1 área, 1 equipo, 1 punto, 2 muestras FFT de 16 líneas) que se
   commit al repo en `tests/fixtures/`. Estos tests corren rápido y cubren la lógica del
   parser sin depender del fichero del cliente.

2. **Integration tests contra el `.rbm` real**. Marcados con `@pytest.mark.integration`,
   se saltan si la variable de entorno `RBM_TEST_FILE` no está definida. Verifican
   propiedades agregadas: nº de áreas esperado, presencia de strings conocidos, conteos
   plausibles. No comprueban byte-a-byte (el fichero es de un cliente real).

3. **Verificación visual humana** (no automatizada). Documentada en `VERIFICATION.md`.

**Lo que NO se commitea al repo**: el `.rbm` real (1.86 GB, datos del cliente BUNGE).
Está en otro directorio (`AMS databases/` fuera del repo) y se referencia via
`RBM_TEST_FILE`. `.gitignore` excluye explícitamente:

```
*.rbm
*.RBM
dataset/
samples/
.rbm-cache/
```

## 7. Plan de ejecución agéntica desde CLI

> **Histórico**: este bloque describe la intención original de lanzar
> cada fase como un agente en worktree con branch `phase-NN-*`. En la
> práctica el repo es single-dev y se trabaja directo sobre `master`
> con commits granulares por feature; sólo se abre branch para
> experimentos arriesgados. Las convenciones de §7.3 (idioma de
> código y docs, type hints, structlog en vez de print, etc.) sí
> siguen vigentes.

### 7.1 Briefing por agente (plantilla)

Cada fase se lanza con un prompt que incluye:

- Contexto: link a este `PLAN.md` y al `docs/FORMAT.md` actual.
- Objetivo concreto de la fase.
- Lista de entregables exactos.
- "Definition of done" como checklist verificable.
- Restricciones: no modificar código fuera de los módulos de la fase, mantener tests
  verdes, no añadir deps sin aprobación previa, commits pequeños con mensajes
  descriptivos en inglés.
- Branch destino: `phase-NN-short-name`.

### 7.2 Worktree e isolation

- Cada agente trabaja en un worktree con `isolation: "worktree"`.
- Branch naming: `phase-NN-short-name` (p.ej. `phase-01-reader-and-header`).
- Al terminar, el agente devuelve diff + resumen de tests; el humano revisa y mergea.

### 7.3 Convenciones de código aplicables a todos los agentes

- Idioma del código y comentarios: **inglés** (más universal, futura colaboración).
- Idioma de los docs `.md`: **español** (continuidad, audiencia inicial).
- Mensajes de log: **inglés**.
- Docstrings: **inglés**, estilo Google.
- Type hints obligatorios en todas las funciones públicas.
- Sin `print()` — siempre `structlog`.
- Sin `# type: ignore` salvo justificación en comentario adyacente.

### 7.4 Qué NO delegar a agentes

- Decisiones de diseño que cambien el contrato público de la CLI o el formato de
  salida (esquema Parquet, layout del dataset, etc.). Se discuten con humano antes.
- Verificación visual contra screenshots de AMS.
- Cualquier hipótesis nueva sobre el formato binario: se discute, se valida con
  `tools/hex_inspect.py` con humano, y solo entonces se implementa.

## 8. Decisiones consolidadas

Resumen de lo cerrado en la conversación previa:

| Decisión | Valor |
|---|---|
| Lenguaje | Python 3.13 |
| Gestor | uv (sin Python global) |
| Repo | `joserb/ams-extract` (privado) |
| Branch principal | `master` (existente) |
| Paquete | `ams_extract` |
| CLI principal | `rbm` |
| CLI dev | `rbm-dev` |
| Subcomandos MVP | `info`, `tree`, `extract`, `export` |
| Output principal | Parquet por equipo, partición Hive por área |
| Output índice | `manifest.parquet` global |
| Output jerarquía | `hierarchy.json` |
| Logging | structlog, **JSON desde MVP** |
| Política de errores | saltar + log, `--strict` opcional |
| CI | GitHub Actions **desde Fase 2** |
| Tipos en MVP | FFT primero; waveforms en Fase 5 |
| Encoding | cp1252 con fallback a cp850 |

## 9. Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| Formato de sample distinto al documentado por Eka (era oilAnalysis, no vibration) | Alta | Alto | Fase 4 con verificación visual; iteración temprana sobre fichero real. |
| Encoding mixto cp1252/cp850 produce caracteres erróneos | Media | Bajo | Fallback chain en `decode_string`; revisar manualmente nombres acentuados. |
| Escalado de amplitudes incorrecto (forma OK, magnitud off) | Alta | Medio | Comparar contra valores OVERALL conocidos del propio fichero (vimos "OVERALL VALUE - 4.165 mm/Seg"). |
| Ciclos en cadenas enlazadas por corrupción | Baja | Medio | Detección de visitados; límite de profundidad en el walker. |
| Performance lenta (1.8GB tarda horas) | Media | Bajo | mmap + lectura selectiva; paralelización en export. |
| Cambios de formato entre versiones AMS 5.x | Media | Medio | Capturar versión del header desde Fase 1; rechazar versiones no testeadas con warning claro. |
| Nombres de equipos colisionan tras sanitización | Baja | Bajo | Sufijo numérico determinista en `naming.py`; mapeo en `hierarchy.json`. |

## 10. Glosario

- **AMS**: Asset Management Solutions / Machinery Manager. Software de Emerson.
- **CSI**: Computational Systems Inc., empresa original que creó RBMware. Adquirida
  por Emerson; su tecnología es la base de AMS Machinery Manager.
- **RBM / RBMware**: Reliability Based Maintenance. Producto y formato originales de CSI.
- **MT4.00**: "Master Trend 4.00", firma del header. Master Trend fue el software
  predecesor de RBMware en los años 90.
- **FFT**: Fast Fourier Transform. Espectro en frecuencia (amplitud vs Hz).
- **Waveform / forma de onda**: serie temporal de amplitud vs tiempo (antes de la FFT).
- **PeakVue**: técnica patentada de Emerson/CSI para detectar fallos de baja energía
  (rodamientos, engranajes) mediante demodulación de alta frecuencia.
- **Overall**: valor RMS o pico-pico de la señal completa, sin descomponer.
- **TWist**: software de TWave para análisis de vibraciones (destino de la migración).
- **DAF42.DLL**: librería de bajo nivel de RBMware que implementa el acceso a records.
  No la usamos — re-implementamos su funcionalidad pura.
- **Hive partitioning**: convención `key=value/` en rutas de fichero, entendida
  nativamente por pandas/polars/duckdb/spark.

## 11. Referencias

- Eka Siswanto, *RBMware (\*.RBM) File Format*, 2018.
  https://ekasiswanto.wordpress.com/2018/01/17/rbmware-rbm-file-format/
- AMP Maintenance Forums, *export data from/to RBMware*.
  https://www.maintenance.org/topic/export-data-from-to-rbmware
- Emerson, *AMS Machinery Manager User Guide v5.61*, 2014.
  https://www.emerson.com/documents/automation/manuals-guides-ams-machinery-manager-v5-61-en-39478.pdf
- TWave T8 Explorer (ecosistema destino).
  https://www.twave.io/en/blog/t8-explorer-en

---

## 12. Para retomar la próxima sesión

Última pausa: 2026-05-30 tras **resolver la calibración FFT completa**
(velocidad mm/s + aceleración G's). Commits por delante de
`origin/master` esperando push manual.

### Estado del repo

- `master` es el branch de trabajo. Todas las fases 0–6 están
  mergeadas, más la calibración FFT (Fase 4 cerrada en lo funcional).
  CI matrix corre en push/PR. Convención: trabajar directo sobre master,
  sin `phase-NN-*` branches salvo experimentos arriesgados.
- Working tree limpio salvo `scripts/investigate_fft_calibration.py`
  (diagnóstico throwaway de la calibración FFT, ya resuelta; borrar o
  no commitear).
- Tests verdes (unit + integración con `RBM_TEST_FILE` definido),
  incl. validación de PeakVue y alta frecuencia (fmax 6000) en G's.
  Ruff + `pyright src/` limpios.
- `rbm tree FILE --out tree.json` genera la jerarquía completa
  (`schema_version=3`, `phase="phase-2b-equipment-count-fix"`).
- `rbm extract FILE --point NAME [--equipment SUBSTR] --type fft|waveform|both
  --limit N --out DIR` emite Parquet + PNG por espectro FFT y/o waveform.
  **Todo calibrado**: FFT velocidad en mm/s, FFT aceleración en G's,
  waveform en G's. Sin deuda de calibración.
- `rbm export FILE --out dataset/ [--types fft,waveform] [--areas …]
  [--parallel N]` genera el dataset completo (hierarchy.json +
  manifest.parquet + samples/area=X/equipment=Y__{fft,waveform}.parquet).

### Primer paso al volver

La calibración FFT (antigua Opción A) está **resuelta** — ver §5.6 de
`FORMAT.md`. Lo que queda es **Fase 7 (refinamientos)**, por orden de valor:

1. **`vddt` — series temporales de tendencias**. Layout **RESUELTO**
   (2026-05-30, validado 47/47 vs gold; ver `FORMAT.md §5.7` y ADR-0006):
   slots de 41 B, overall en `+0x04` ×25.4 → mm/s, ts de la muestra
   siguiente en `+0x24`. **Falta implementarlo en código**: `models.Trend`
   + `walk_trends` + emisión en `extract`/`export` + tests (análogo a
   `walk_spectra`/`walk_waveforms`). Etiquetar las 7 bandas queda aparte
   (necesita gold por banda).
2. **Benchmark del export total de BUNGE** (1.86 GB) — medir tiempos
   serial vs `--parallel N`.
3. **Short codes nativos** de áreas/equipos/puntos (continuation block
   `gicm.0xE0+`, stride 10 bytes; equivalentes para vdpm/gdcm).
4. **Plantillas** (`DEP-M`, `IBL-REACC S1`, …): hoy filtradas; escanear
   `vdpm` no alcanzados si se quieren exponer.
5. **Bandas de alarma** y **field notes** (best effort).

### Preguntas abiertas

Ninguna bloqueante. Para referencia:

1. ~~**Calibración amplitudes FFT**~~: RESUELTA (2026-05-30, `FORMAT.md §5.6`).
   Velocidad ×48.5 → mm/s, aceleración ×1.30 → G's, banda baja `vdps[0xC8:0x200]`.
2. **Padding waveform 488 vs 512**: 24 muestras "fantasma" en el descriptor.
3. **Short codes nativos de áreas/equipos/puntos**: viven en el
   continuation block de `gicm` (`0xE0+`) y en zonas equivalentes
   para vdpm/gdcm. Cerrarían §4.6.
4. **Plantillas (`DEP-M`, `IBL-REACC S1`, …)**: hoy filtradas. Fase 7.
5. **`vddt` mapeo completo**: series temporales de tendencias
   (Valores Globales / SUBSINCRONO / …). Parcialmente decodificado;
   falta el layout valor↔timestamp por muestra. Fase 7.
6. **i32 signed deltas en `gicm.0x60+`, `vdps.0x0C-0x10`, `vcps.0x0C-0x10`,
   `vcfw.0x0C-0x10`**: pattern repetido en todos los records, sin
   función identificada.
7. **Tags poco frecuentes** (`gina`, `gddr`, `odla`, `pdla`, `gdnp`,
   `pdpa`, `gshr`, `gdpn`, `gdnl`, `gsdh`, …): mapear cuando se crucen.

### Atajos útiles ya implementados

- Ver árbol rápido: `uv run rbm tree "AMS databases/BUNGE CARTAGENA marzo 2.0.rbm"`.
- Volcar hex de un record: `uv run rbm-dev dump-record FILE --rec N`.
- Seguir cadena enlazada: `uv run rbm-dev follow-chain FILE --from N --at-offset M`.
- Regenerar fixture: `uv run python scripts/make_synthetic_fixture.py` y commitear.
- Tests de integración: `RBM_TEST_FILE="..." uv run pytest -m integration`.

---

## Apéndice A — Comandos de uso esperados (post-MVP)

```bash
# Información rápida sobre un fichero
uv run rbm info db.rbm

# Volcar la jerarquía
uv run rbm tree db.rbm --out tree.json

# Inspeccionar 3 espectros de un punto concreto
uv run rbm extract db.rbm \
  --point "BOMBA LA VERTICAL PEAKVUE" \
  --limit 3 \
  --out samples/

# Export completo
uv run rbm export db.rbm \
  --out dataset/ \
  --types fft \
  --parallel 4

# Herramientas de desarrollo
uv run rbm-dev scan --tags db.rbm
uv run rbm-dev dump-record db.rbm --rec 70
uv run rbm-dev follow-chain db.rbm --from 70
```

## Apéndice B — Carga del dataset en Polars / DuckDB

```python
import polars as pl

# todo el dataset, area y equipment como columnas:
df = pl.scan_parquet("dataset/samples/", hive_partitioning=True)

# filtrar por área y rango de fechas, sin cargar arrays:
recent = (
    pl.scan_parquet("dataset/manifest.parquet")
      .filter(pl.col("area") == "EXTRACCION")
      .filter(pl.col("timestamp_utc") > "2024-01-01")
      .collect()
)

# cargar espectros de una máquina concreta:
machine = pl.read_parquet("dataset/samples/area=EXTRACCION/equipment=MOTOR_EXT_01.parquet")
```

```sql
-- DuckDB:
SELECT area, equipment, COUNT(*) AS samples
FROM read_parquet('dataset/samples/**/*.parquet', hive_partitioning=true)
GROUP BY area, equipment
ORDER BY samples DESC;
```
