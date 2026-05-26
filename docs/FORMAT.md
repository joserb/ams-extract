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

Pendiente (Fase 2). Hipótesis a verificar:

- El record apuntado por `area_chain_first_record` contiene una lista de
  nombres de área en slots de 32 bytes (verificado: `BUNGE` record 70 base-0
  contiene 5 nombres: `FULL-FAT`, `PARQUE TANQUES`, `OBSOLETOS`, `SERVICIOS`,
  `OSMOSIS`). Cómo se enlaza al siguiente record de áreas y cómo se
  alcanzan los equipos por área queda por descubrir.

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
