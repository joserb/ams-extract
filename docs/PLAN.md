# Plan de proyecto: `ams-extract`

> Herramienta CLI en Python para extraer datos de bases RBMware / AMS Machinery Manager
> (ficheros `.rbm`) a formatos modernos (Parquet + JSON), sin depender de la VM Windows XP
> ni del software AMS original.

Versión del documento: 0.2 (decisiones consolidadas tras revisión)
Última actualización: 2026-05-27

Repo: `git@github.com:joserb/ams-extract.git` (privado)

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

### 4.1 Estructura general

- Fichero compuesto por **registros de 512 bytes exactos**. Tamaño total siempre múltiplo
  de 512 (verificado: 1 857 595 904 / 512 = 3 628 117 records sin resto).
- Cada registro se direcciona por número entero. Pendiente de confirmar
  experimentalmente si la indexación es base-0 (offset = `n * 512`) o base-1
  (offset = `(n-1) * 512`). Eka Siswanto describe base-1 pero su ejemplo numérico encaja
  con base-0. **Resolveremos en Fase 1** leyendo el primer puntero conocido del header
  y validando contra el contenido en el offset resultante.
- El registro 0 contiene la cabecera global.

### 4.2 Cabecera (registro 0) — observado

```
offset  bytes               significado tentativo
0x00    76 05 9f 3c         ?? (¿checksum del header?)
0x04    01 00 0e 00         ?? (¿versión 1.14?)
0x08    67 64 64 68 ...     20 bytes — ¿hash / GUID DB?
0x1C    "MT4.00"            firma de versión
0x22    08 02 00 00         ?
0x28    00 00 00 00         ?
0x2C    6b 1c 2f 61         posible timestamp (LE u32) — verificar
0x30    0f 00 29 00         ?
0x40-0x7F  "Preditec   ..."  descripción de la base (nombre integrador)
0x80    01 00 + "CARGA PORCENTA[J]REA   EQUIPO" — etiquetas de campos
0xD8+   array de uint32 LE con punteros (record numbers) a la primera cadena de áreas
```

A confirmar/refinar en Fase 1.

### 4.3 Jerarquía (según Eka + lo que vemos)

```
Database (record 0)
  └─ Area records             (lista de hasta 22 areas por record, con cadena al siguiente)
       └─ stdg / gdts          (registro intermedio: punteros a equipos del área)
            └─ Equipment records
                 └─ mcdg / gdcm  (registro intermedio: punteros a puntos del equipo)
                      └─ mpig / gipm  (puntos del equipo)
                           └─ mpdo / opdm  (descripción individual del punto)
                                └─ dcod / odcd  (record_num_start, record_num_end de samples)
                                     └─ tddo / oddt  (sample: timestamp, descripción, array float32)
```

Convención: los nombres de tag de 4 chars se leen **al revés** porque la documentación
de Eka los presenta tanto en orden lógico como en orden de bytes en disco. La
implementación adoptará un convenio único (probablemente el orden tal y como aparece en
disco) y lo mantendrá consistente con tests.

### 4.4 Tags de 4 chars observados en el fichero real

Detectados en el dump:

- `pdla`, `pdsh` — relacionados con puntos (`pdla` = "point data, long"?
  `pdsh` = "point data, short"?).
- `vcfw`, `vcps`, `vcpsh` — relacionados con FFT/sample data (`vc` = "vibration channel"?).
- `gddh` — aparece en cabecera (offset 0x08).

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

- Indexación base-0 vs base-1 (resolver en Fase 1).
- Encoding exacto en cada campo (cp1252 confirmado mayormente).
- Estructura interna del `oddt` para distinguir tipos de muestra.
- Cómo se almacenan las bandas de alarma ("FALLO ELECTRIC", "HOLGURAS"…).
- Plantillas de análisis ("REDUCTORA 50-150 rpm (S)") — ¿records aparte o duplicadas?
- Field Notes / Notepad Observations — sabidamente problemático.

## 5. Hoja de ruta por fases

Cada fase es atómica: deja el proyecto en estado verde (tests pasando, `rbm --help`
funciona) y entrega valor incremental. Pensadas para ejecutarse como tareas agénticas
independientes desde la CLI.

### Fase 0 — Bootstrap (≈ 0.5 sesión)

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

### Fase 1 — Reader y header (≈ 1 sesión)

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

### Fase 2 — Jerarquía + CI (≈ 1-2 sesiones)

**Objetivo**: walker top-down hasta el nivel de Point, y CI verde.

Entregables:

- Parsers de Area, Equipment, Point (cadenas enlazadas).
- Walker recursivo con detección de ciclos / records inválidos.
- `models.py` poblado.
- `naming.py` con sanitización determinista.
- Subcomando `rbm tree FILE --out tree.json`.
- Sanity check vs lo que sabemos: 14 áreas, ~895 puntos PEAKVUE, decenas de plantillas.
- **GitHub Actions** con matrix Linux/macOS/Windows, Python 3.13: ruff + pyright + pytest.

**Definition of done**: `tree.json` se genera y abre; conteos de áreas/equipos/puntos
cuadran con lo observado (±5%). El JSON valida contra un schema simple. CI pasa en
todas las plataformas.

### Fase 3 — Sample reader FFT (≈ 2-3 sesiones)

**Objetivo**: extraer espectros FFT de un punto conocido.

Entregables:

- Parser de `odcd` (rango de samples) y `oddt` (sample individual).
- Discriminación de tipo: por ahora "FFT" o "OTROS" (con log). El resto se aborda en
  Fase 5.
- Decodificación de timestamp + descripción + array float32.
- Subcomando `rbm extract FILE --point NAME --limit 3 --out samples/` que produce:
  - `samples/{point}_{idx}.parquet` (esquema unificado).
  - `samples/{point}_{idx}.png` (matplotlib, log-y, ejes etiquetados).
- Tests con valores plausibles (no NaN, no infinitos, longitudes coherentes).

**Definition of done**: extraemos 3 espectros de un punto BUNGE conocido, se grafican,
la forma del espectro tiene picos plausibles (no es ruido blanco ni constante).

### Fase 4 — Verificación visual contra AMS (≈ 0.5 sesión)

**Objetivo**: validar (con humano en el loop) que lo extraído coincide con lo que vería
un analista en AMS.

Entregables:

- Protocolo de verificación en `docs/VERIFICATION.md`.
- Humano abre en la VM el mismo punto + timestamp en AMS y toma screenshot.
- `scripts/compare_with_screenshot.py` pone lado a lado el PNG extraído y el screenshot.
- Iteración sobre Fase 3 si hay discrepancias (escalado, ejes, ordenación).

**Definition of done**: al menos 2 espectros de 2 puntos distintos coinciden visualmente
con AMS dentro de tolerancia razonable.

### Fase 5 — Waveforms (≈ 1-2 sesiones)

Análogo a Fase 3 pero para waveforms. Identificación del tag y desambiguación.
Generación de PNGs en eje temporal (no frecuencia). Mismo esquema unificado en Parquet.

### Fase 6 — Export masivo (≈ 1 sesión)

**Objetivo**: dump completo de la base.

Entregables:

- `rbm export FILE --out dataset/` itera todos los equipos y escribe la estructura de
  §3.5 (hierarchy.json + manifest.parquet + samples/area=X/equipment=Y.parquet).
- Progress bars con `rich`, logging agregado, filtros por área/tipo.
- Paralelización con `--parallel N` (ProcessPoolExecutor por equipo).
- Benchmark documentado: tiempo total para el `.rbm` de BUNGE.

**Definition of done**: `dataset/` se genera completo. Carga vía
`pl.scan_parquet("dataset/samples/", hive_partitioning=True)` funciona. Objetivo blando:
< 30 minutos en máquina moderna.

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

La intención es lanzar las fases con agentes (Claude Code u otros) en worktrees aislados,
desde tu CLI local.

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
