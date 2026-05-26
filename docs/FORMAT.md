# Especificación del formato `.rbm`

> Documento vivo. Se irá completando a medida que descubramos y verifiquemos
> detalles del formato binario de RBMware / AMS Machinery Manager (MT4.00).

Estado: Fase 1 completada — secciones §1, §2 y §6 verificadas contra el
fichero real `BUNGE CARTAGENA marzo 2.0.rbm`. El resto sigue pendiente.

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

### 3.2 Equipos y Puntos

Pendiente (Fase 2b). Pistas observadas:

- La captura de la UI de AMS muestra que cada área contiene una mezcla de
  **plantillas** (DEP-M, DEP-M+T3, IBL-REACC S1 en DEP) y **equipos reales**
  (AG-100, CF-4900, PM-100, …). Hay que distinguirlas o documentar que se
  exportan ambas.
- La tabla de u32 LE del layout "prefixed list" (offsets `0x10`-`0x44` en
  record 69 de BUNGE) podría contener los punteros a las cadenas de
  equipos por área. Hipótesis a validar leyendo esos records.

## 4. Tags de 4 chars

Pendiente. Fase 4 mapeará exhaustivamente con `rbm-dev scan --tags`.

## 5. Sample record (`oddt` / `tddo`)

Pendiente (Fase 3).

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
- Significado de los u32 después de `0xDC` (¿array de punteros a más
  records de áreas, a equipos, o índices auxiliares?).
- Cómo se identifica el tipo de un record arbitrario (¿tag de 4 chars en
  un offset fijo? ¿depende del tipo?).
- Resto de la lista inicial en `docs/PLAN.md` §4.6.
