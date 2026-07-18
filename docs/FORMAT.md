# Especificación del formato `.rbm`

> Documento vivo. Se irá completando a medida que descubramos y verifiquemos
> detalles del formato binario de RBMware / AMS Machinery Manager (MT4.00).

Estado: Fases 0–6 completadas + **calibración FFT resuelta (2026-05-30)** +
**tendencias `vddt` resueltas (2026-05-30)**. Secciones §1, §2, §3, §5 y §6
verificadas contra el fichero real `BUNGE CARTAGENA marzo 2.0.rbm`. Los
sample records (§5) están totalmente decodificados y calibrados: FFT
velocidad (mm/s), FFT aceleración —PeakVue + alta frecuencia— (G's),
waveform (G's) y tendencias de Valores Globales (mm/s, §5.7). Pendiente
menor: etiquetar las 7 bandas del `vddt` y el catálogo exhaustivo de tags
poco frecuentes (§4).

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

Un chunk lógico `gicm` puede contener hasta **20 equipos**. Cuando tiene
≤ 12, todo cabe en un único registro físico de 512 bytes. Cuando tiene
13-20, los nombres 13-20 viven en el **registro físico inmediatamente
siguiente** (sin tag propio — es un bloque de continuación del mismo
chunk lógico, no un nuevo `gicm`).

Registro principal del chunk:

| Offset | Tamaño | Campo |
|---|---|---|
| `0x00` | 8 | preámbulo |
| `0x08` | 4 | tag ASCII `gicm` |
| `0x0C` | 4 | u32 LE (+1 encoded) — **next gicm** del chain (`0` = última) |
| `0x10` | 80 | hasta **20 punteros** u32 LE (+1 encoded) a records `gdcm` (uno por equipo del chunk); `0` antes del slot 20 termina la lista |
| `0x60` | 80 | i32 LE signed deltas (uno por equipo del chunk; función exacta sin confirmar) |
| `0xB0` | 336 | hasta **12 slots** de 28 bytes con el nombre del equipo (cp1252, space-padded) |

Registro de continuación (`gicm_record + 1`, sólo si el chunk tiene > 12 equipos):

| Offset | Tamaño | Campo |
|---|---|---|
| `0x000` | 224 | hasta **8 slots** adicionales de 28 bytes con los nombres de los equipos 13-20 |
| `0x0E0` | 200 | hasta **20 short codes nativos** de 10 bytes (e.g. `"AG-100"`, `"PM-501"`). Aún no parseados en código; cerrará la incógnita de §4.6 cuando se haga. |
| `0x1A8` | 88 | flags `01 00 01 00 …` + zero padding (función desconocida) |

Áreas con > 20 equipos encadenan vía `gicm.0x0C`. En BUNGE:

- DEPURADORA: 2 chunks (20 + 8 = 28)
- EXTRACCION: 3 chunks (20 + 20 + 13 = 53)
- PREPARACION: 5 chunks (20 + 20 + 20 + 20 + 7 = 87)
- REFINERIA: 5 chunks (20 + 20 + 20 + 20 + 10 = 90)
- NAVES: 1 chunk con bloque de continuación (18)

> **Historia**: la versión inicial de este spec asumía 12 slots por
> chunk. Coincidía con lo que cabía en el record físico pero erraba en
> chunks grandes — chunk 0 de DEP tiene 20 equipos y nos comíamos PM-501
> en adelante. Hallazgo y fix el 2026-05-28 cotejando contra capturas de
> AMS (DEP completa).

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

Mapeo extraído de `rbm-dev scan --tags` sobre BUNGE más la función
verificada en cada fase:

| Tag | Frecuencia | Función verificada | Confirmado en |
|---|---|---|---|
| `vcps` | 1 931 424 | bloque de 122 floats de datos FFT | Fase 3a |
| `vcfw` | 1 322 008 | bloque de int16 LE para datos de waveform (244 muestras/record) | Fase 5a |
| `vdps` | 157 160 | descriptor de un espectro FFT individual | Fase 3a |
| `vdfw` | 157 055 | descriptor de un waveform individual (n_samples, sample_period, units) | Fase 5a |
| `vdpm` | 6 141 | point descriptor (config: template, RPM, alarmas; incluye plantillas) | Fase 2b + 3a |
| `pdcd` | (no listado por scan) | índice de tipos de medida por punto ("Set Colección Datos Primar") | Fase 3a |
| `vddt` | (no listado por scan) | series de tendencias (Valores Globales + bandas). **RESUELTO**: slots de `13+band_count·4` B, overall en `+0x04`, ts de la muestra siguiente off-by-one; unidad por el espectro del punto (velocidad ×25.4 → mm/s). Validado 47/47; 7 bandas etiquetadas (§5.7) | 2026-05-30 |
| `gdsc` | 6 504 | aún sin confirmar (¿descriptor general?) | — |
| `gicm` | 26 | equipment list chunk (20 slots + continuation) | Fase 2b (ADR-0004) |
| `gdcm` | 347 | equipment instance | Fase 2b (ADR-0003) |
| `gscm` | 347 | sibling de `gdcm` — función pendiente | — |
| `gipm` | 344 | point list per equipment | Fase 2b (ADR-0003) |
| `gdts` | 16 | índice área → equipment chain | Fase 2b (ADR-0003) |
| `gits` | 1 | área list "prefix-list" | Fase 2a (ADR-0002) |
| `gddh` | 1 | database header tag (record 0) | Fase 1 |
| `pdpa` | 41 | plantilla de análisis (bandas + rangos + umbrales de alarma); compartida entre puntos | §5.8 |
| `gdnl` | (varios) | informes de alarma en texto literal (`"SUBSINCRONO - … - C Alarm"`) | §5.8 |

## 5. Sample records — FFT chain

Verificado en `BUNGE` durante la sub-fase 3a (2026-05-28) contra el
punto piloto **M1H (MOTOR LOA HORIZONTAL) de MECLADOR AGITADOR
AG-100**, cuyo gold data conocemos de la UI de AMS (Fmax=1000 Hz,
n_lines=1600, RPM=1455, CARGA=100%, 5 espectros con timestamps
`2019-10-15`, `2019-11-12`, `2019-12-12`, `2020-01-21`, `2020-02-19`).

### 5.1 Modelo

```
vdpm (point)
  └── 0x10 → pdcd ("Set Colección Datos Primar" — índice del punto)
        ├── 0x04 → vcfw (waveform chain head — pendiente §5.5)
        ├── 0x38 → vdpm (back-ref al propio punto)
        ├── 0x3C → vddt (primer record de tendencias; Valores Globales — §5.7)
        ├── 0x40 → vddt (último record de tendencias — §5.7)
        ├── 0x44 → vdps (primer espectro FFT, el más antiguo)
        └── 0x48 → vdps (último espectro FFT, el más reciente)

vdps chain (espectros FFT ordenados de antiguo a moderno):
  vdps → 0x14 → vdps siguiente (0 = último)
              0x18 → primer vcps de la cadena de datos de este espectro
              0x1C → ¿back-ref a pdcd? (siempre el mismo para los 5 vdps de M1H)
              0x20 → float32 Fmax (Hz)
              0x24 → u32 LE Unix timestamp (segundos, UTC; el huso local
                     varía CET/CEST a lo largo del año)
              0x28 → float32 RPM × 2 (¿o CPM?) — para M1H da 2920, RPM nativa
                     en vdpm.0x164 = 1455
              0x2C → float32 CARGA % (100.0 en M1H)
              0x50 → u32 LE n_lines (1600 en M1H)
              0x78 → ASCII 8 bytes — units, p.ej. "plg/segs"
                     (= pulgadas/segundo; AMS lo convierte a mm/seg en
                     pantalla cuando configurado en SI)

vcps chain (datos amplitud de un espectro):
  vcps → 0x14 → siguiente vcps (0 = fin de cadena de este espectro)
              0x18 hasta 0x1FF → 122 × float32 LE (amplitud bin a bin)

Total por espectro: ~13 vcps × 122 = 1586 floats (n_lines=1600 nominal;
los últimos ~14 bins quedan implícitos o como zero-pad, pendiente de
afinar).
```

### 5.2 `pdcd` record — índice de tipos de medida por punto

| Offset | Tamaño | Campo |
|---|---|---|
| `0x00` | 8 | preámbulo |
| `0x08` | 4 | tag ASCII `pdcd` |
| `0x04` | 4 | u32 LE (+1 encoded) — primer `vcfw` (waveform chain) |
| `0x10` | 32 | descripción ASCII (`"Set Colección Datos Primar     "`) |
| `0x38` | 4 | u32 LE (+1 encoded) — back-ref al `vdpm` del punto |
| `0x3C` | 4 | u32 LE (+1 encoded) — **primer `vddt`** (cadena de tendencias / Valores Globales, más antiguo) |
| `0x40` | 4 | u32 LE (+1 encoded) — **último `vddt`** (más reciente) |
| `0x44` | 4 | u32 LE (+1 encoded) — primer `vdps` de la cadena FFT (más antiguo) |
| `0x48` | 4 | u32 LE (+1 encoded) — último `vdps` de la cadena FFT (más reciente) |

### 5.3 `vdps` record — descriptor de un espectro FFT

| Offset | Tamaño | Campo |
|---|---|---|
| `0x00` | 8 | preámbulo |
| `0x08` | 4 | tag ASCII `vdps` |
| `0x0C` | 4 | i32 LE signed (función desconocida) |
| `0x10` | 4 | i32 LE signed (función desconocida) |
| `0x14` | 4 | u32 LE (+1 encoded) — **siguiente `vdps`** en el tiempo (`0` = último) |
| `0x18` | 4 | u32 LE (+1 encoded) — **primer `vcps`** de la cadena de datos de este espectro |
| `0x1C` | 4 | u32 LE (+1 encoded) — apunta al `pdcd` del punto (back-ref compartido) |
| `0x20` | 4 | float32 LE — **Fmax (Hz)** |
| `0x24` | 4 | u32 LE — **Unix timestamp (UTC, segundos)** |
| `0x28` | 4 | float32 LE — RPM × 2 (interpretación tentativa) |
| `0x2C` | 4 | float32 LE — **CARGA %** |
| `0x50` | 4 | u32 LE — **n_lines** (típico 1600) |
| `0x78` | 8 | ASCII — **units** (e.g. `"plg/segs"`) |

### 5.4 `vcps` record — bloque de datos de amplitud

| Offset | Tamaño | Campo |
|---|---|---|
| `0x00` | 8 | preámbulo |
| `0x08` | 4 | tag ASCII `vcps` |
| `0x0C` | 4 | i32 LE signed (delta / chain backwards) |
| `0x10` | 4 | i32 LE signed (función desconocida) |
| `0x14` | 4 | u32 LE (+1 encoded) — **siguiente `vcps`** en la misma cadena (`0` = fin) |
| `0x18`–`0x1FF` | 488 | **122 × float32 LE** — amplitudes consecutivas del espectro |

### 5.5 Waveform chain (sub-fase 5a, mapeado contra M1H 19-feb-2020)

Estructura paralela a la de FFT, anclada en `pdcd` con **dos punteros
adicionales** que sub-3a no había probado (sweep limitado a 0x00-0x4C):

```
pdcd
  ├── 0x5C → vdfw (primer descriptor waveform, más antiguo)
  └── 0x60 → vdfw (último descriptor waveform, más reciente)

vdfw chain (chronological, oldest → newest):
  vdfw → 0x14 → vdfw siguiente  (0 = último)
              0x18 → primer vcfw (data chain head)
              0x1C → back-ref al pdcd
              0x24 → float32 sample_period (1/sample_rate; M1H: 3.9e-4 s = 1/2560)
              0x28 → float32 scale_factor (display units por cuenta int16;
                     M1H 19-feb: 3.7548e-05 G/cuenta)
              0x2C → u32 n_samples (M1H: 512)
              0x34 → u32 Unix timestamp UTC
              0x38 → float32 RPM (no Fmax como en vdps)
              0x3C → float32 CARGA %
              0x6C → ASCII 8 bytes — units (e.g. "G's")

vcfw chain (datos de la waveform):
  vcfw → 0x14 → siguiente vcfw  (0 = fin)
              0x18 hasta 0x1FF → 244 × int16 LE (muestras acel. centradas;
                     amplitud calibrada = int16 × scale_factor de vdfw.0x28)
```

**Calibración de amplitud — RESUELTA (sub-fase 5b, 2026-05-29)**. A
diferencia del FFT (§5.6, deuda abierta), la waveform sí calibra: cada
`vdfw` lleva en `0x28` un float32 `scale_factor` (display units por cuenta
int16). Para M1H 19-feb-2020, `scale_factor = 3.7548e-05 G/cuenta`;
aplicado a las muestras crudas (max=12862, min=-13575) da Pc(+)=0.483 G y
Pk(-)=-0.510 G, idéntico al gold de AMS (error < 0.3%). El factor es
**por-waveform** (varía entre adquisiciones: 3.84e-05 para 15-oct,
3.7548e-05 para el resto). `walk_waveforms` aplica el factor y emite
`Waveform.samples` ya en unidades de display.

> **Unidad de display (2026-05-31)**: tras `scale_factor`, la waveform queda
> en su unidad nativa — **G's** para aceleración (se deja tal cual) e
> **in/s** para velocidad. AMS muestra velocidad en mm/s, así que
> `walk_waveforms` aplica además **×25.4** a las waveforms de velocidad
> (units `plg/segs`/`in/sec`) → `mm/s`, igual que el FFT/trend de velocidad.
> En BUNGE: 503 waveforms son de velocidad (resto G's).

Para M1H 19-feb-2020 BUNGE: 2 vcfw records → 488 muestras decoded
(24 menos que las 512 nominales — pendiente entender el padding).
Cotejado contra el screenshot AMS:

| Métrica | AMS | Decodificado | Match |
|---|---|---|---|
| Pc(+) | 0.483 G | 0.482 G | ✓ 0.2% |
| Pk(-) | -0.510 G | -0.500 G | ✓ 2% |
| n_samples (nominal) | 512 | 512 (en vdfw) | ✓ |
| n_samples (reales decoded) | — | 488 | -4.7% |
| sample_rate | 2560 Hz (= 2.56 × Fmax_FFT) | 2560 Hz | ✓ |
| Duration | 0.20-0.21 s | 0.191 s | ≈ |
| Units | G | G | ✓ |

> **Actualización sub-5b**: con `scale_factor` (vdfw.0x28) aplicado, Pc/Pk
> mejoran a 0.483 / -0.510 (antes 0.482 / -0.500 con la escala empírica
> de sub-5a). La calibración deja de ser deuda para la waveform.

**Hipótesis descartada en sub-5a**: "AMS reconstruye FFT desde
waveform". La waveform almacenada (488 muestras / 0.19 s) no permite
una FFT de 1600 líneas con resolución 0.625 Hz/bin como muestra AMS —
necesitaría 4096 muestras / 1.6 s. Conclusión: `vcps` (FFT) y `vcfw`
(waveform) son representaciones independientes en el fichero, y la
deuda de calibración de amplitudes del FFT (§5.5) sigue abierta.

### 5.6 Calibración y banda baja del FFT — RESUELTO (2026-05-30)

> Histórico: esta sección registró durante meses una "discrepancia
> estructural" — los ratios AMS/decoded parecían no constantes (16 a 2330)
> y el pico dominante de AMS (M1H 14.68 Hz) "ausente". Se llegó a cerrar
> como *no recuperable*. **Era falso**: faltaba leer la banda baja y
> aplicar la escala. El error venía de comparar un espectro **incompleto**
> (le faltaban los 78 bins de baja) contra el gold.

**Reconstrucción del espectro completo.** El espectro de display de AMS
tiene dos piezas:

1. **Bins 0..77 (0–48.75 Hz)** — viven en la **cola del propio record
   `vdps`**, en offsets `0xC8..0x1FF` (78 float32 contiguos = 312 bytes).
   `(0x200 - 0xC8) / 4 = 78` exactos. Aquí caen 1X/2X de giro y, a menudo,
   el pico mayor.
2. **Bins 78..1663** — la cadena `vcps` (≈1586 floats). De ahí que la
   cadena "empezara en la línea 78".

Espectro completo = `concat(vdps[0xC8:0x200], cadena_vcps)` truncado a
`n_lines` (1600). Bin `i` → frecuencia `i · Fmax / n_lines` (0.625 Hz/bin
con Fmax=1000). Sin offset una vez antepuesta la banda baja.

**Calibración de amplitud (velocidad).** Una sola escala:
`mm/s = VELOCITY_SCALE · raw`, con `VELOCITY_SCALE = 48.5` (pooled median
48.8 / mean 48.4 sobre 72 picos; ≈ pulgadas→mm 25.4 × ~1.9 de
ventana/normalización). Las unidades crudas de velocidad aparecen como
`plg/segs`, `in/sec` o `pul/sg` (variantes de pulgadas/segundo); todas se
calibran igual y se emiten como `mm/s`.

**Validación (3 máquinas, 3 RPM distintas, gold de la "Lista de Picos"):**

| Punto | RPM | logcorr | escala | CV |
|---|---|---|---|---|
| AG-100 M1H 2020-02-19 | 1455 | +0.999 | 48.0 | 0.04 |
| PM-6901-A M1H 2026-01-20 | 3000 | +0.999 | 48.7 | 0.04 |
| AR-1211 M1H 2026-03-26 | 1500 | +0.998 | 47.9 | 0.05 |

Picos por pico dentro de ±5–10% (incl. el dominante AG-100 14.68 Hz:
5.059 mm/s gold vs 4.76 decoded). Test de nulidad: barriendo offsets
0..160 bins, **78 es el único** con logcorr>0.90. Implementado en
`records/sample.py` (`read_vdps_low_band`, `assemble_spectrum`,
`VELOCITY_SCALE_MM_S`) y aplicado en `tree.walk_spectra`.

**Aceleración (`G's`) — RESUELTO (2026-05-30).** ~38% de los `vdps` son
espectros de aceleración (units `G's`): puntos **PeakVue** (fmax 1000,
demodulación HP 10 kHz para rodamientos/engranajes) y **Alta Frecuencia
(HF)** (fmax 6000). Misma reconstrucción que velocidad (banda baja en
`vdps[0xC8:0x200]` + cadena, offset 0 tras ensamblar) pero **distinta
escala**: `G's = ACCEL_SCALE_G · raw`, con `ACCEL_SCALE_G = 1.30`. No hay
conversión de unidad (G's→G's) y los valores son **RMS** (velocidad es
"PC"/pico), de ahí que el factor difiera del 48.5. Las unidades se quedan
en `G's`. Validado en 3 espectros, los dos tipos de aceleración:

| Punto | Tipo | Fmax | residual gold/calib | logcorr |
|---|---|---|---|---|
| PM-6901-A M2P 24-01-24 | PeakVue | 1000 | ±8% (24 picos) | — |
| PM-6901-A B1P 24-01-24 | PeakVue | 1000 | median 0.998 | +0.995 |
| PM-6901-B M1F 25-01-24 | HF | 6000 | median 1.009, 24/24 ±10% | +0.998 |

El mismo ×1.30 vale para PeakVue (fmax 1000) y HF (fmax 6000) → es una
constante de digitización del formato, independiente de Fmax.

> **Nota — aceleración derivada de M1H**: para puntos de *velocidad* (M1H,
> etc.) AMS muestra además una "aceleración" que NO está almacenada: la
> deriva como `a = v·2πf` (ratio gold/derivado constante 0.716 ≈ 1/√2,
> RMS-vs-pico). No la emitimos; sería una columna derivada de la velocidad.

**Pendientes menores del FFT:**

- ~~**Padding 1586 vs 1600**~~: RESUELTO — los 14 que "faltaban" no eran
  el tema; el espectro real son 1664 bins (78 baja + 1586 cadena),
  truncados a 1600. La cadena tiene incluso ~64 bins por encima de Fmax.
- ~~**`vcfw` (waveform)**~~: RESUELTO en sub-5b. Layout: 244 int16 LE
  por record (no float32 como `vcps`), cadena de 2 records = 488 muestras
  para M1H. Calibración vía `vdfw.0x28` (ver §5.5). Parser en
  `records/waveform.py`, walker `walk_waveforms`.
- **`vddt` (pdcd.0x3C, 0x40)**: tras inspección no es complemento del
  espectro sino series temporales de tendencias. Mapeo completo
  aplazado a Fase 7 si queremos exponer "Valores Globales" o bandas
  con nombre.
- **Significado preciso de los i32 deltas en `vcps.0x0C`/`0x10` y
  `vdps.0x0C`/`0x10`**. No bloquea ninguna fase activa.

### 5.7 `vddt` — series de tendencias (Valores Globales + bandas) — RESUELTO (2026-05-30)

Los records `vddt` almacenan la **tendencia temporal** que AMS pinta como
"Gráf. tendencia de Valores Globales": el overall RMS velocity (mm/s) más
las bandas con nombre (SUBSINCRONO, DESEQUILIBRIO, DESALINEACION, HOLGURAS,
11-40X RPM, 1-20KHz) muestreados a lo largo de años. El parámetro principal
es "RMSVelocidad en mm/Seg".

**Cadena**: `pdcd.0x3C` = primer `vddt` (más antiguo), `pdcd.0x40` = último
(mismo patrón first/last que `vdps` 0x44/0x48). Los `vddt` se encadenan por
`0x10` (+1-encoded, `0` = fin). Para M1H AG-100: 6 records (336987→336992).

**Cabecera del record `vddt`**:

| Offset | Tamaño | Campo |
|---|---|---|
| `0x00` | 8 | preámbulo |
| `0x08` | 4 | tag ASCII `vddt` |
| `0x10` | 4 | u32 LE (+1 encoded) — **siguiente `vddt`** (`0` = último) |
| `0x14` | 4 | u32 LE (+1 encoded) — back-ref al `pdcd` |
| `0x18` | 4 | u32 LE — Unix ts de la **primera** muestra del record (`d0`) |
| `0x1C` | 4 | u32 LE — Unix ts de la **última** muestra del record (`d1`) |
| `0x24` | 4 | u32 LE — **band_count**: nº de columnas-banda por slot (**no** es nº de muestras). Varía por época dentro de un mismo punto (7 al inicio, luego 4…); fija el stride |
| `0x2F` | … | inicio del primer **slot** de muestra (ver abajo) |

**Slots de muestra** — secuencia de slots de tamaño **`13 + band_count·4`**
(p.ej. 41 B para `band_count=7`, 29 B para 4, 17 B para 1), el primero en
offset `0x2F`:

| Offset (dentro del slot) | Tamaño | Campo |
|---|---|---|
| `+0x00` | 4 | flags por slot (alarma/estado; **no** es un marcador fijo — el `d3 fa ff 00` que se ve en AG-100 es dato del punto, varía) |
| `+0x04` | 4 | **float32 overall** (Valores Globales) en la unidad nativa del punto |
| `+0x08` | `band_count·4` | **band_count × float32** — bandas (ver etiquetas) |
| `+0x08+band_count·4` | 4 | u32 LE — Unix ts de la muestra **SIGUIENTE** (ver regla de fechas) |

Se itera por stride hasta que el overall sale de rango o el ts es `0`/no
plausible (fin de los slots vivos). El `band_count` (`0x24`) **no** indica
el tipo de medida — un mismo punto de velocidad mezcla records con 7 y 4
bandas (reconfiguración del análisis a lo largo del tiempo).

**Regla de fechas (la clave del decode)**: el timestamp guardado en `+0x24`
de un slot es la fecha de la muestra **siguiente**, no la suya. Por tanto:

```
fecha[0]  = vddt.0x18 (d0, primera muestra del record)
fecha[k]  = timestamp en slot[k-1].+0x24   (para k ≥ 1)
```

La última muestra de cada record toma su fecha del `+0x24` del slot anterior;
su propio `+0x24` suele ser `0`. La primera muestra del record siguiente
toma su fecha del `d0` de ese record.

**Unidad / escala**: el `vddt` no almacena unidad. La unidad nativa la marca
la medida primaria del punto (`vdps.0x78`): **velocidad** (`plg/segs`…) → el
overall está en in/s y AMS muestra mm/s, `mm/s = raw × 25.4` (factor de
conversión puro, distinto del 48.5 del FFT). **Aceleración** (`G's`,
PeakVue/HF) → en G's. `walk_trends` emite hoy **solo velocidad** (mm/s);
los trends de aceleración decodifican estructuralmente pero su escala de
overall no está confirmada contra gold, así que se saltan (§7.4).

**Etiquetas de las bandas** (template de velocidad, `band_count=7`), cada
columna validada **62/62** contra el PLOTDATA por-banda de M1H AG-100.
**Unidades mixtas** dentro del slot:

| Columna | Offset | Banda | Unidad |
|---|---|---|---|
| 0 | `+0x08` | **Mp Wave** (F.Onda Pico Máx) | **G's** (raw, sin ×25.4) |
| 1 | `+0x0C` | SUBSINCRONO | mm/s (×25.4) |
| 2 | `+0x10` | DESEQUILIBRIO | mm/s |
| 3 | `+0x14` | DESALINEACION | mm/s |
| 4 | `+0x18` | HOLGURAS | mm/s |
| 5 | `+0x1C` | 11-40 X RPM | mm/s |
| 6 | `+0x20` | 1-20 KHz | sin confirmar (gold vacío) |

**Validación del overall**: 62 lecturas decodificadas para M1H AG-100; los
primeros 47 coinciden **EXACTO** (fecha + valor) con la tabla gold de AMS
(PLOTDATA "Valore Globale"), incluido el duplicado del 13-jul-2017 (6.01 y
36.43 mm/s el mismo día). Anclas: `slot +0x04 = 0.6038 → 15.34 mm/s`
(20-abr-2017), `… = 1.4341 → 36.43 mm/s` (13-jul-2017, pico del trend).

**Implementado** (2026-05-30): `records/trend.py`, `tree.walk_trends`,
`models.Trend`, export (`__trend.parquet`, una fila por lectura) y CLI
(`rbm extract --type trend`, `rbm export --types …,trend`). Desde 2026-07-18
(ADR-0010) `walk_trends` también emite las **bandas etiquetadas** del template
de velocidad (`Trend.bands`, columnas 0–5 con sus unidades mixtas; la columna
6 "1-20 KHz" no se emite por escala sin confirmar) y `rbm export` las escribe
como métricas VibFrame propias (`band_<slug>__<punto>`). Los trends de
aceleración siguen pendientes.

### 5.8 `pdpa` — config de análisis del punto (bandas / rangos / alarmas)

Parcialmente mapeado (2026-05-31). Define qué bandas tiene un punto, sus
rangos de frecuencia y sus umbrales de alarma — la "definición" de los
indicadores que luego viven como columnas en el `vddt` (§5.7).

**Son PLANTILLAS COMPARTIDAS**: en BUNGE solo hay **41 records `pdpa`** (de
3,6M records), agrupados en ~records 120-160; los 5203 puntos referencian
una de ellas. → la config de una máquina **generaliza** a todas las que
comparten plantilla.

| Offset | Campo |
|---|---|
| `0x08` | tag `pdpa` |
| `0x10` | nombre de plantilla (`"Estandar 1500 rpm (S)"`, `"REDUCTORA <300 rpm (S)"`, `"Alta resolucion (HR)"`…) |
| `0x34` | **nombres de banda**: 12 slots × 14 chars, relleno `INDEFINID`. **Mismo orden que las columnas del `vddt`** (validado: pdpa "Estandar 1500 rpm" = `[Mp Wave, SUBSINCRONO, DESEQUILIBRIO, DESALINEACION, HOLGURAS, 11-40 X RPM, 1-20 KHz]`) |
| `~0xF0+` | floats de **umbrales de alarma** y **rangos de frecuencia**, intercalados |

- **Umbrales**: tripletes recurrentes tipo `[0.7, 1.5, 2.5, 10.5]` =
  (¿baseline?, **Alerta/C**, **Peligro/D**, ¿máx?). Gold-consistente:
  SUBSINCRONO de M1H pasa a C ~1.44 y D ~2.24 ≈ alerta 1.5 / peligro 2.5.
- **Rangos de frecuencia**: fijos (`1000`/`20000` Hz = banda 1-20 KHz) y
  **rpm-escalados** (`0x164`/`0x17C` = 40×RPM, borde de "11-40 X RPM";
  diff plantilla 1500 vs 3000 rpm los aísla).

**Enlace punto→plantilla**: el `vdpm` lleva la familia de plantilla en `0x4B`
(`:ESTÁNDAR`) y los **rodamientos** en `0x07E` (`6204`/`6208`, frecuencias de
fallo). La variante rpm se casa por nombre + rpm del punto.

**Pendiente**: segmentar el offset exacto por-banda de
`[freq_lo, freq_hi, alerta, peligro]` y el índice numérico limpio
punto→`pdpa`. Necesitaría una captura del diálogo de bandas/alarmas de AMS.
También: los records `gdnl` guardan informes de alarma en texto literal
(`"SUBSINCRONO - 1.986 mm/Seg - C Alarm"`).

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

Resueltas en sub-fase 3a:

- ~~Cómo se enlazan los samples a su punto~~: vía `vdpm.0x10 → pdcd`,
  y `pdcd` actúa como índice de cadenas por tipo de medida.
- ~~Dónde se almacenan Fmax / n_lines / units / timestamp por
  espectro~~: en el record `vdps` (ver §5.3).
- ~~Layout interno de `vcps`~~: header de 24 bytes + 122 float32 LE
  consecutivos (ver §5.4).

Resueltas en Fase 5 / calibración (2026-05-30):

- ~~Estructura interna de `vcfw` y `vdfw` (waveforms)~~: RESUELTO (§5.5).
  `vdfw` descriptor (timestamp 0x34, scale_factor 0x28, …); `vcfw` =
  244 int16 LE/record. Calibrado a G's vía `vdfw.0x28`.
- ~~Escalado/normalización de las amplitudes en `vcps` para casar con
  el eje Y de AMS~~: RESUELTO (§5.6). Espectro completo = banda baja
  `vdps[0xC8:0x200]` + cadena `vcps`; velocidad ×48.5 → mm/s,
  aceleración ×1.30 → G's.
- ~~Reconciliación entre `n_lines = 1600` y los 1586 floats de la
  cadena `vcps`~~: RESUELTO (§5.6). El espectro real son 1664 bins
  (78 baja + 1586 cadena), truncados a 1600.
- ~~**`vddt` — layout de muestras**~~: RESUELTO (§5.7). Slots de 41 B,
  overall en `+0x04` (×25.4 → mm/s), ts de la muestra siguiente en
  `+0x24`. Validado 47/47 vs gold.

Pendientes:

- Layout exacto de `0x22-0x2B` y `0x30-0x57` en la cabecera (Fase 1).
- Función de los u32 LE en el "rebozado" de cada record (preámbulo
  `0x00-0x07`): timestamps, contadores, versión… aún sin confirmar.
- **`vddt` — etiquetado de las 7 bandas** (cuál es SUBSINCRONO,
  DESEQUILIBRIO, …). Requiere gold del PLOTDATA por banda. No bloquea
  emitir el overall (Valores Globales).
- Marker para distinguir un `vdpm` "real" de uno "plantilla". Hoy se
  filtran por construcción al recorrer sólo lo enlazado.
- Significado preciso de los i32 signed deltas en `gicm.0x60+`,
  `vdpm.0x10+`, `vdps.0x0C`/`0x10` y `vcps.0x0C`/`0x10`. No bloquean
  ninguna fase actual.
- Padding waveform 488 vs 512 (24 muestras "fantasma" en el descriptor).
- Resto de la lista inicial en `docs/workplans/01-plan-general.md` §4.6.
