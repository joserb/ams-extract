# Especificación del formato `.rbm`

> Documento vivo. Se irá completando a medida que descubramos y verifiquemos
> detalles del formato binario de RBMware / AMS Machinery Manager (MT4.00).

Estado: Fase 2b completada — secciones §1, §2, §3 y §6 verificadas contra
el fichero real `BUNGE CARTAGENA marzo 2.0.rbm`. Sample records (§5) y
el catálogo exhaustivo de tags de 4 chars (§4) siguen pendientes.

## 1. Estructura general

- Fichero compuesto por **registros de 512 bytes exactos** (verificado).
- Tamaño total siempre múltiplo de 512. En `BUNGE`: 1 857 595 904 / 512 =
  3 628 117 records sin resto.
- Indexación **base-0** (decisión ADR-0001 en `docs/DECISIONS.md`):
  `offset_in_bytes = record_number × 512`.
- Record 0 contiene la cabecera global; el resto son records de jerarquía,
  índices, samples, etc.

## 2. Cabecera (record 0)

Layout verificado en `BUNGE`:

| Offset | Bytes | Campo | Notas |
|---|---|---|---|
| `0x00` | 4 | `header_marker` | `76 05 9f 3c` en `BUNGE`. Función exacta sin confirmar (¿checksum?). |
| `0x04` | 4 | `version_marker` | `01 00 0e 00` en `BUNGE`. Tentativo: codificación de versión MT/AMS. |
| `0x08` | 4 | `db_tag` | ASCII `gddh` — tag de "database header". |
| `0x0C` | 16 | `guid` | Identificador de la base; bytes opacos por ahora. |
| `0x1C` | 6 | `signature` | ASCII `MT4.00`. Validación obligatoria. |
| `0x22` | 22 | reservado | Bytes mixtos no interpretados aún. |
| `0x2C` | 4 | `timestamp_raw` | u32 LE. En `BUNGE` = `0x612f1c6b` = 2021-09-01 06:23:39 UTC (plausible). |
| `0x30` | 40 | reservado | Mezcla de bytes / flags / contadores pequeños. |
| `0x58` | 40 | `description` | Texto cp1252 padded con espacios. En `BUNGE` = `"Preditec"`. |
| `0x80` | ~88 | etiquetas | Strings como `CARGA PORCENTAJE`, `ÁREA`, `EQUIPO`. Tentativo: etiquetas de columnas de UI. |
| `0xD8` | 4 | u32 LE | Posible contador (`5` en `BUNGE`). |
| `0xDC` | 4 | `area_chain_first_record` | u32 LE. Apunta al primer record de la cadena de áreas. En `BUNGE` = `70`. |
| `0xE0+` | variable | tabla de punteros | Más u32 LE con números de record; función exacta sin confirmar. |

Parser: `ams_extract.records.header.parse_header()` extrae signature,
description, db_tag, guid, version_marker, timestamp_raw y
area_chain_first_record. El resto se queda como bytes crudos accesibles via
`RbmReader.read_record(0)`.

## 3. Jerarquía (Áreas → Equipos → Puntos)

### 3.1 Áreas (Fase 2)

El header de la base no usa una cadena enlazada para las áreas; tiene **dos
punteros independientes** a records que contienen nombres:

- `0xDC` → record con _layout "simple list"_.
- `0xE4` → record con _layout "prefixed list"_.

Ver ADR-0002 en `docs/DECISIONS.md` para el razonamiento.

#### Layout "simple list" (record 70 en BUNGE)

| Offset | Tamaño | Campo |
|---|---|---|
| `0x000` | 32 | nombre de área 1 (cp1252, space-padded) |
| `0x020` | 32 | nombre de área 2 |
| `0x040` | 32 | nombre de área 3 |
| `0x060` | 32 | nombre de área 4 |
| `0x080` | 32 | nombre de área 5 |
| `0x0A0` | 192 | padding (espacios) — fin de la lista de nombres |
| `0x180` | 32 | concatenación de códigos cortos (4 chars cada uno, hasta 8) |
| `0x1A0` | 32 | concatenación de códigos cortos (continúa) |
| `0x1C0` | 64 | padding |

#### Layout "prefixed list" (record 69 en BUNGE)

| Offset | Tamaño | Campo |
|---|---|---|
| `0x00` | 4 | u32 LE — timestamp candidato |
| `0x04` | 4 | version marker (e.g. `02 00 0e 00`) |
| `0x08` | 4 | tag `gits` (ASCII) |
| `0x0C` | 4 | reservado |
| `0x10` | 52 | tabla de u32 LE — punteros aún sin interpretar |
| `0x44` | 124 | mezcla de bytes / floats / flags |
| `0xC0` | 32 | nombre de área 1 |
| `0xE0` | 32 | nombre de área 2 |
| ... | ... | hasta 10 nombres consecutivos |
| `0x1E0` | 32 | nombre de área 10 (último slot) |

Parser: `ams_extract.tree.walk_areas()` lee ambos punteros, recorre cada
record con la heurística descrita en ADR-0002 y devuelve `list[Area]`.

### 3.2 Equipos y Puntos (Fase 2b)

Cadena enlazada desde cada `Area` a sus `Point` (ver ADR-0003):

```
Area
  └─ gdts record           (uno por área)
       └─ gicm record      (chunks de hasta 12 equipos; encadenados por
                            gicm.0x0C → next gicm)
            └─ gdcm record (uno por equipo)
                 └─ gipm record   (uno por equipo)
                      └─ vdpm record  (uno por punto)
```

**Convención de punteros**: los punteros _internos_ a estos records
(tabla 0x10 del area prefix-list, gicm slot pointers, etc.) se almacenan
con un offset de **+1** sobre el record base-0 — reservando `0` como
sentinela de fin-de-lista. Helper único:
`ams_extract.reader.decode_inner_pointer`.

#### `gdts` record (area-to-equipment-chain intermediate)

| Offset | Tamaño | Campo |
|---|---|---|
| `0x00` | 8 | preámbulo (timestamp + version marker) |
| `0x08` | 4 | tag ASCII `gdts` |
| `0x14` | 4 | u32 LE (+1 encoded) — puntero a record `gsts` (función no usada por el walker actual) |
| `0x18` | 4 | u32 LE (+1 encoded) — puntero al **primer `gicm`** del área |
| `0x1C` | 4 | u32 LE (+1 encoded) — puntero al **último `gicm`** del área (mismo que 0x18 para áreas ≤ 12 equipos) |

#### `gicm` record (equipment list with names)

| Offset | Tamaño | Campo |
|---|---|---|
| `0x00` | 8 | preámbulo |
| `0x08` | 4 | tag ASCII `gicm` |
| `0x0C` | 4 | u32 LE (+1 encoded) — **next gicm** del chain (`0` = última) |
| `0x10` | 48 | hasta 12 punteros u32 LE (+1 encoded) a records `gdcm` (uno por equipo del chunk); `0` antes del slot 12 termina la lista |
| `0x40` | 32 | reservado / no interpretado |
| `0x60` | 80 | i32 LE signed deltas (uno por equipo del chunk; función exacta sin confirmar — posibles offsets de timestamp o de orden) |
| `0xB0` | 336 | hasta 12 slots de **28 bytes** con el nombre del equipo (cp1252, space-padded) |

Áreas con > 12 equipos encadenan vía `0x0C`. EXTRACCION (36 equipos en
BUNGE) usa 3 records `gicm` consecutivos.

#### `gdcm` record (equipment instance)

| Offset | Tamaño | Campo |
|---|---|---|
| `0x00` | 8 | preámbulo |
| `0x08` | 4 | tag ASCII `gdcm` |
| `0x10` | 4 | u32 LE (+1 encoded) — puntero a `gscm` (no usado por el walker) |
| `0x14` | 4 | u32 LE (+1 encoded) — puntero al `gipm` del equipo |
| `0x24+` | variable | u32/float parámetros del equipo (no interpretados) |

#### `gipm` record (point list per equipment)

| Offset | Tamaño | Campo |
|---|---|---|
| `0x00` | 8 | preámbulo |
| `0x08` | 4 | tag ASCII `gipm` |
| `0x0C` | 4 | reservado (`0` en BUNGE) |
| `0x10` | 432 | bytes opacos: floats de configuración, flags por punto, etc. |
| `0x1C0` | 64 | hasta 16 punteros u32 LE (+1 encoded) a records `vdpm` (uno por punto del equipo); `0` antes del slot 16 termina la lista |

#### `vdpm` record (point)

| Offset | Tamaño | Campo |
|---|---|---|
| `0x00` | 8 | preámbulo (timestamp + version) |
| `0x08` | 4 | tag ASCII `vdpm` |
| `0x10` | 8 | flags / mini-header (no interpretado) |
| `0x18` | 32 | `long_name` (cp1252, space-padded) — p.ej. `MOTOR LA HORIZONTAL` |
| `0x38+` | variable | resto del descriptor: template (`ESTÁNDAR`, …), unidades, Fmax, líneas, alarmas. Pendiente de Fase 3. |

Parser: `ams_extract.tree.walk_hierarchy()` recorre la cadena entera y
devuelve `list[Area]` con `equipment` y `points` poblados.

**Observación operativa**: `rbm-dev scan --tags` sobre BUNGE encuentra
6141 records `vdpm` en disco pero el walker sólo emite 3795. La
diferencia son plantillas de análisis (DEP-M, IBL-REACC S1, …) y
versiones históricas de puntos editados; al no estar enlazadas desde la
jerarquía de áreas no llegan al output. Si se necesitase extraerlas,
habría que escanear el fichero buscando records `vdpm` no alcanzados.

## 4. Tags de 4 chars

Mapeo parcial extraído de `rbm-dev scan --tags` sobre BUNGE (los más
frecuentes y los relevantes para Fase 2b):

| Tag | Frecuencia | Significado verificado |
|---|---|---|
| `vcps` | 1 931 424 | sample data (vibration channel parameters/samples) — pendiente Fase 3 |
| `vcfw` | 1 322 008 | sample data (vibration channel waveform?) — pendiente Fase 3 |
| `vdps` | 157 160 | sample data variant — pendiente |
| `vdfw` | 157 055 | sample data variant — pendiente |
| `vdpm` | 6 141 | point descriptor (incluye plantillas) |
| `gdsc` | 6 504 | aún sin confirmar (¿descriptor general?) |
| `gicm` | 26 | equipment list chunk (uno por área pequeña; varios por área grande) |
| `gdcm` | 347 | equipment instance |
| `gscm` | 347 | sibling de `gdcm` — función pendiente |
| `gipm` | 344 | point list por equipo |
| `gdts` | 16 | one per area + 1 extra |
| `gits` | 1 | prefix-list area record |
| `gddh` | 1 | database header tag (record 0) |

## 5. Sample record (`oddt` / `tddo`)

Pendiente (Fase 3). La cabecera del PLAN.md mencionaba estos nombres
basados en Eka, pero `rbm-dev scan --tags` sugiere que los tags reales
son `vcps` / `vcfw` / `vdps` / `vdfw`. A confirmar en Fase 3.

## 6. Encoding y strings

- **cp1252 (Windows-1252)** confirmado en el fichero real: `0xC1 = 'Á'`
  aparece en strings como `CARGA PORCENTAJE/ÁREA/EQUIPO` en la cabecera.
- Fallback a **cp850 (CSI/DOS antiguo)** previsto pero no necesario en
  `BUNGE`.
- Último fallback: **latin-1 con replacement** para garantizar que
  `decode_string()` nunca lanza excepción.
- **Padding**: campos de anchura fija vienen rellenos con `0x20` (espacio)
  y/o `0x00` (NUL). Helper único `strip_padding()` los elimina antes de
  decodificar.

Implementación: `ams_extract.encoding`.

## 7. Incógnitas abiertas

- Layout exacto de `0x22-0x2B` y `0x30-0x57` en la cabecera.
- Función de los u32 LE en el "rebozado" de cada record (preámbulo
  `0x00-0x07`): timestamps, contadores, versión… aún sin confirmar.
- Estructura interna de los records de sample (`vcps` / `vcfw`):
  cómo se distingue FFT de waveform, dónde van Fmax / n_lines / unidades
  / window / n_avgs, y cómo se enlazan a su punto (`vdpm`). Fase 3.
- Marker para distinguir un `vdpm` "real" (alcanzable desde la jerarquía
  de áreas) de uno "plantilla". Hoy se filtran por construcción al
  recorrer sólo lo enlazado.
- Significado preciso de los i32 signed deltas en `gicm.0x60+` y
  `vdpm.0x10+`. No bloqueante para la jerarquía actual.
- Resto de la lista inicial en `docs/PLAN.md` §4.6.
