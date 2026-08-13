---
status: designed
created: 2026-08-13
updated: 2026-08-13
---

# Plan: catálogo de golds AMS y cierre de incógnitas binarias

## Objetivo

Cerrar las incógnitas binarias que aún afectan a datos útiles, empezando por
un catálogo ejecutable de pantallazos y exportaciones que pedir a AMS. Cada
nuevo decode seguirá la regla del repo: evidencia de la UI o PLOTDATA,
hipótesis binaria reproducible, ADR, tests y sólo entonces emisión.

El plan separa dos clases:

- **gold visible**: un valor, estado o configuración que AMS muestra y puede
  capturarse;
- **experimento de mutación**: bytes administrativos sin representación
  visible directa, que sólo se entienden cambiando un campo en una copia de la
  base y comparando records antes/después.

No todo byte desconocido merece un parser. Se prioriza lo que cambia una
salida VibFrame/DiagGT o evita saltarse información real.

## Protocolo de captura

Cada solicitud `AMS-GOLD-###` debe entregar, siempre que la pantalla lo permita:

1. PNG sin recortar de la ventana completa, escala 100 %, con título,
   breadcrumb de área/equipo/punto, nombre de pantalla y fecha visible.
2. Punto y timestamp exactos, modalidad/tipo de medida, unidad, Fmax, líneas,
   RPM y carga.
3. Pantallazo de configuración que gobierna el dato y pantallazo o tabla del
   dato observado; nunca uno de los dos sin el otro.
4. Export PLOTDATA/listado asociado en texto o CSV cuando AMS lo ofrezca.
5. Nombre de la base, versión AMS/MT y zona horaria local.
6. SHA-256 del fichero recibido y relación con el `source_sha256` de la base.

Convención propuesta:

```text
AMS-GOLD-003__REF__PM-9101-A__M1H__20210519__alarm-limits.png
AMS-GOLD-003__REF__PM-9101-A__M1H__20210519__trend.png
AMS-GOLD-003__REF__PM-9101-A__M1H__20210519__plotdata.csv
```

Los ficheros con datos de cliente viven fuera de Git. El repo conserva en
`docs/VERIFICATION.md` el id, hashes, pantalla, punto/fecha, valores
transcritos, conclusión y ADR que los consumió. Si se crea un destilado para
tests, debe contener sólo el mínimo numérico necesario.

## Catálogo inicial de pantallazos

### Prioridad P0 — datos hoy omitidos o semántica de alarma

| ID | Pantalla/conjunto solicitado | Caso concreto | Incógnita que cierra | Evidencia mínima de aceptación |
|---|---|---|---|---|
| `AMS-GOLD-001` | Configuración completa de límites + gráfica de tendencia con líneas y leyenda | PM-9101-A, M1H, REF; misma captura que mostró “Advertencia” ~0,95 G | Dónde vive el nivel **Advertencia** y cómo se relaciona con C/D | valores de todos los límites, unidad, nombres de niveles, línea visible y PLOTDATA de fechas alrededor de un cruce |
| `AMS-GOLD-002` | “Lista Ptos de Tendc” con columna ALARM + gráfica y configuración del punto | DT-0070, M1P PeakVue; filas marcadas `Bs` y `Vl` | Significado y fuente binaria de **Bs/Vl** | fechas/valores exactos de al menos dos `Bs`, el `Vl`, umbrales del punto y vista donde AMS explica/leyenda esos códigos |
| `AMS-GOLD-003` | Lista/detalle de alarmas con valor, C, D y cualquier índice/severidad mostrado | 3 ejemplos C y 5 ejemplos D repartidos desde justo sobre D hasta los máximos de Bunge | Ley exacta de `gdsc.0x1A` en zona D (41–100) | texto `gdnl`, valor, C/D, fecha, nivel/índice visible y suficiente rango para contrastar modelos lineal/log/saturado |
| `AMS-GOLD-004` | Configuración `pdpa`/`pdla`, gráfica y nota de alarma de la banda | PM-0CI/1, /2 y /3, banda `1 - 20 KHz` | 15 notas omitidas por unidad `pdla` frente a texto | unidad mostrada en plantilla, columna, umbral y nota para una fecha exacta de cada máquina |
| `AMS-GOLD-005` | Configuración y alarma de `Mp Wave` en sets HF | Los 3 casos omitidos restantes de §5.9 | Si la discrepancia es plantilla histórica, tipo de banda o decode de unidad | nombre/id de set, unidad de Mp Wave, C/D, valor y nota de las tres observaciones |

### Prioridad P1 — metadatos de punto y plantillas

| ID | Pantalla/conjunto solicitado | Muestra | Incógnita que cierra | Evidencia mínima de aceptación |
|---|---|---|---|---|
| `AMS-GOLD-006` | Propiedades completas del punto/sensor | un M1H de velocidad, un PeakVue, un HF, un punto axial y `CONSUMO INTENSIDAD (A)` | `PointDoc.kind`, sensor físico frente a magnitud presentada y campos de sensor disponibles | todas las pestañas de punto/transductor, unidad, tipo de sensor, sensibilidad y procesamiento/integración si aparecen |
| `AMS-GOLD-007` | Fuente de velocidad/tacómetro del punto o set de adquisición | PM-9101-A M1H, AG-100 M1H y un equipo de velocidad variable | Semántica de `PointDoc.speed_source` y diferencia RPM nominal/análisis/medida | fuente seleccionada, RPM nominal, RPM de captura y cualquier canal de referencia |
| `AMS-GOLD-008` | Propiedades de rodamientos del punto | AG-100 LOA/LA y DT-0070 motor/reductora | Si los 7 slots tienen rol, orden, lado o componente | pantalla que muestre cada designación y su etiqueta/posición, no sólo la lista compacta |
| `AMS-GOLD-009` | Analysis Parameter Set completo | sets estándar, HF, PeakVue y reductora con slots residuales | Campos `pdpa.0x148+`, Fmax/líneas por análisis y significado de tipos restantes | todas las bandas, tipos, rangos, Fmax, líneas y opciones no visibles en la tabla actual |
| `AMS-GOLD-010` | Alarm Limit Set completo | set 5 M1H, PeakVue y uno HF | Array `pdla.0x6C` (1.7[13]) y campos no decodificados | todas las pestañas/opciones, incluidos warning/baseline/low value y unidades por slot |

### Prioridad P2 — cobertura estructural y administración

| ID | Pantalla/conjunto solicitado | Muestra | Incógnita que cierra | Evidencia mínima de aceptación |
|---|---|---|---|---|
| `AMS-GOLD-011` | Árbol/listado de equipos expandido con conteo | EXTRACCION, PREPARACION, REFINERIA, IMPULSIÓN DE MAR, PARQUE TANQUES, FULL-FAT, OBSOLETOS y OSMOSIS | Verificación visual pendiente de 8 áreas | una secuencia legible por área que incluya primero/último equipo y total; export/listado si existe |
| `AMS-GOLD-012` | Propiedades de base de datos/About | Bunge | offsets de cabecera relacionados con versión/metadata visible | versión MT/AMS, descripción, fechas y propiedades completas de la base |
| `AMS-GOLD-013` | Field notes/notas del punto y usuario que firma | un punto con varias notas `gdnl` y uno sin nota | relación entre field notes, `gdsc`, `gdnl`, usuario y offsets auxiliares | pantalla de lista + detalle de la misma nota con fecha, autor, texto y nivel |
| `AMS-GOLD-014` | Gestión de plantillas frente a puntos reales | un `vdpm` de plantilla y uno enlazado a equipo, si la UI los distingue | Marker para distinguir `vdpm` real/plantilla | misma plantilla vista desde administración y desde un punto que la usa, con ids/nombres visibles |
| `AMS-GOLD-015` | Lista con short code nativo y nombre largo | área NAVES y un área con varios chunks `gicm` | Uso de los short codes de 10 bytes y deltas del `gicm` | listado/export que muestre ambos identificadores para los mismos equipos y su orden |

## Experimentos binarios separados

Los siguientes objetivos no se cierran con una captura estática. Se ejecutan
sólo sobre una copia de laboratorio de la base, nunca sobre el original:

| ID | Mutación controlada | Comparación | Objetivo |
|---|---|---|---|
| `AMS-EXP-001` | cambiar únicamente descripción/propiedad visible de la base | record 0 antes/después | offsets `0x22–0x57` y metadatos de cabecera |
| `AMS-EXP-002` | crear/editar una field note con autor y severidad conocidos | `gdsc`/`gdnl` nuevos antes/después | deltas, links, flags y usuario |
| `AMS-EXP-003` | cambiar un único límite warning/C/D de una banda | `pdla` antes/después | array 1.7 y campos de alarma no interpretados |
| `AMS-EXP-004` | cambiar Fmax/líneas de una sola plantilla sin tomar datos | `pdpa` antes/después | bloque `0x148+` y residuos de edición |
| `AMS-EXP-005` | crear una plantilla y asignarla/desasignarla a un punto | records `vdpm`/`pdcd`/directorios antes/después | marker plantilla-real y enlaces de set |
| `AMS-EXP-006` | cambiar sólo fuente de velocidad o sensor, si la UI lo permite | descriptor del punto antes/después | offsets candidatos de `kind`, sensor y `speed_source` |

Cada experimento registra: copia de partida, acción exacta, records añadidos o
modificados, diff hexdump acotado y reversión. No se deduce un layout de una
sola mutación si varios campos cambian juntos.

## Flujo de cierre por incógnita

1. **Solicitar** el bundle del catálogo y marcarlo `requested`.
2. **Recibir y verificar** hashes/metadatos; marcar `captured`.
3. **Localizar** los bytes candidatos en la misma muestra/timestamp.
4. **Contrastar** al menos dos valores y un caso negativo; marcar `explained`.
5. **Documentar** FORMAT + VERIFICATION y crear ADR.
6. **Implementar** parser/modelo/walker con tests sintéticos.
7. **Integrar** contra Bunge completo y medir cobertura/excepciones.
8. **Emitir** sólo si todas las escalas/unidades/semánticas tienen gold;
   marcar `adopted`. Si no, queda `documented-not-emitted`.

El catálogo vivo tendrá estados cerrados:
`needed`, `requested`, `captured`, `explained`, `adopted`,
`documented-not-emitted`, `discarded`.

## Orden de ejecución

### Ola 1 — alarmas

`AMS-GOLD-001…005` y `AMS-EXP-002/003`. Objetivo: explicar warning/Bs/Vl,
ajustar zona D y decidir las 18 alarmas omitidas.

### Ola 2 — metadatos de punto

`AMS-GOLD-006…010` y `AMS-EXP-004/006`, coordinada con el workplan 17.

### Ola 3 — cobertura y campos administrativos

`AMS-GOLD-011…015` y `AMS-EXP-001/005`. Son mejoras no bloqueantes y se
priorizan después de los datos que hoy se saltan.

## Tests y aceptación de un decode

- Parser puro sobre bytes sintéticos, con límites y valores inválidos.
- Dos o más golds reales y un caso negativo.
- Censo completo de records: cobertura, valores distintos y outliers.
- Comparación exacta o tolerancia declarada con UI/PLOTDATA.
- El dato nuevo no altera decodes ya validados del mismo record.
- Integración con `RBM_TEST_FILE` y, si se emite, conformidad VibFrame.
- Política skip-with-log para variantes no validadas.

## Documentación transversal

- Crear en `VERIFICATION.md` el índice vivo del catálogo y enlazar cada id a
  su conclusión/ADR.
- Corregir `FORMAT.md` al cerrar o descartar cada offset; retirar pendientes
  ya resueltos, incluido el texto residual que aún aplaza `vddt`.
- Actualizar `DECISIONS.md` con una ADR por semántica adoptada, no por cada
  pantallazo.
- Enlazar el workplan 17 desde las capturas de punto y el 16 cuando una alarma
  afecte a DiagGT.
- Mantener README/AGENTS en términos de lo que se emite, no de hipótesis
  exploratorias.

## Fuera de alcance

- Documentar exhaustivamente todos los bytes opacos sin valor de producto.
- Capturar o commitear información de cliente fuera del protocolo acordado.
- Editar la base original o usar una mutación de laboratorio como gold sin
  comprobarla en una base real.
- Emitir warning/Bs/Vl como niveles VibFrame nuevos sin coordinar antes el
  vocabulario del contrato.

## Criterios de aceptación

1. El catálogo P0 tiene bundle completo o una razón explícita de descarte.
2. Warning/Bs/Vl, zona D y las 18 alarmas omitidas terminan en uno de dos
   estados honestos: emitidos con gold o documentados como no emitibles.
3. Cada decode adoptado lleva FORMAT, VERIFICATION, ADR y tests.
4. Las 8 áreas pendientes quedan cotejadas o identificadas individualmente
   como no accesibles.
5. Ninguna hipótesis exploratoria aparece en README/AGENTS como capacidad.
6. La documentación ya no contiene pendientes contradictorios con decisiones
   posteriores.
