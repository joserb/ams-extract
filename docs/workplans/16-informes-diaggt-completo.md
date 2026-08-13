---
status: in-progress
created: 2026-08-13
updated: 2026-08-13
---

# Plan: completar el extractor de informes y mejorar las reglas DiagGT

## Objetivo

Recuperar la información de los informes Preditec que el extractor todavía
deja fuera y mejorar el mapeo determinista de `diagnosis_text` sin convertir
peticiones administrativas, estados sanos ni hipótesis laterales en fallos.
El resultado debe conservar la trazabilidad completa al PDF, versionar toda
regla cuya lectura cambie y volver a producir las dos generaciones del GT del
analista: determinista y contextual.

Este plan continúa los workplans 04, 09, 10 y 11. No cambia por comodidad la
serie documental DiagGT 0.1.5: cualquier necesidad de esquema se diseña primero
en `docs/GROUND_TRUTH.md` y se coordina con `vibsynth-contracts` antes de emitir
un campo nuevo.

## Línea base que se congela al empezar

- 6 informes Bunge 2026, 921 páginas y 6.669 observaciones.
- Extractor determinista vigente: `informes-gt-extract 0.4.0`.
- Generación contextual vigente: `informes-gt-weights-llm 0.1.1`.
- La auditoría del 2026-08-13 sobre `deterministic-0.4.0` encuentra **61
  findings `unmapped` en 22 textos distintos**. Esta cifra sustituye para este
  plan las fotos de 29/33 findings de planes anteriores.
- Las cuatro proyecciones normativas VibFrame 0.2 y los `source_sha256` de los
  PDF quedan congelados antes de cambiar código.

La primera entrega será un script reproducible de auditoría, no otra cuenta
manual: por texto y cláusula mostrará regla, veto, finding, peso, observaciones
afectadas y clasificación del `unmapped`.

## Alcance

### A. Fidelidad geométrica del extractor

1. **`ANÁLISIS` desbordado a la columna derecha.** Recuperar el contenido que
   cae en `right["_pre"]` y asignarlo sólo cuando las anclas de página demuestren
   a qué ficha y modalidad pertenece. Baseline conocido: unos 7 párrafos en
   `CF.9110S1` y `TC.1523A2`; en esta última se pierde el análisis de
   Ultrasonidos de enero, febrero y marzo.
2. **Matriz “Resumen Estado de Máquinas”.** Prototipar la lectura de las
   imágenes de celda por coordenada, con una tabla de filas/fechas/estado antes
   de construir observaciones. El valor esperado está en unas 209 máquinas sin
   ficha y unas 2.000 celdas por informe.
3. **Estudio ad hoc “ACTUALIZACIÓN” de abril.** Preservar el bloque de las
   páginas 134–136 como evidencia vinculada a la ficha, sin deduplicar a ciegas
   el texto reflotado entre columnas.
4. **Evidencia e intervenciones.** Censar las 69 intervenciones, 66 medidas
   numéricas y 45 peticiones/contextos ya detectados en `analysis_text` y
   `recommendation_text`. No se proyectan como findings hasta decidir su forma
   normativa.

### B. Reglas de estado y findings

1. Clasificar los 22 textos `unmapped` actuales en cuatro grupos:
   `true_fault`, `healthy_or_stable`, `administrative_request` y
   `insufficient_context`.
2. Ampliar el vocabulario de estado para fórmulas inequívocas como “se
   establece su buen estado”, “estable” o “sin evolución”, cuidando que una
   cláusula sana no silencie otra cláusula que sí declara un fallo.
3. Añadir reglas sólo para fallos demostrables en el texto, con candidatos
   iniciales: deterioro/suciedad de válvula, deterioro de acoplamiento y bandas
   laterales de barras rotas o sueltas.
4. Mantener `unmapped` cuando el texto sólo pide informar, revisar o confirmar
   una intervención. Bajar el contador no es el objetivo; leer correctamente
   sí.
5. Versionar el id de cualquier regla existente cuya lógica cambie
   (`GTxxxvN`). Las reglas nuevas ocupan ids nuevos a partir de `GT026`; nunca
   se reutiliza un id histórico.
6. Medir antes/después: observaciones y masa por grupo, textos que ganan o
   pierden findings, cambios de `matched_text`, falsos positivos y suma exacta
   de pesos.

### C. Contrato y materialización

Antes de implementar la matriz o evidencia ad hoc se resuelven estas preguntas:

- ¿Una celda de estado sin texto es una `DiagGTObservation` válida o requiere
  un `record_kind`/origen específico?
- ¿Cómo se representa el intervalo temporal de una celda histórica y cómo se
  deduplica frente a una ficha primaria?
- ¿Las intervenciones caben en `record_kind="intervention"` o necesitan una
  proyección separada?
- ¿Dónde viaja una medida citada como evidencia —texto, tabla `evidence` o un
  sidecar de análisis— sin confundirla con una muestra VibFrame?
- ¿Cómo se formaliza el vínculo a las figuras sin reactivar el campo
  `figures`, hoy fuera de esquema?

Si alguna respuesta cambia modelos normativos, se abre primero un workplan en
`vibsynth-contracts`, se actualizan modelo, spec, JSON Schema, validador y
golden, y sólo después se adopta aquí. La matriz puede entregarse inicialmente
como artefacto de auditoría no normativo si el contrato aún no está listo.

## Fases

### Avance 2026-08-13

- **Fase 0 entregada en código**: `scripts/audit_informes_unmapped.py` censará
  cualquier generación sin modificarla y publica hashes fuente, versión de
  `pdfplumber`, reglas/vetos por cláusula, observaciones y masa por grupo. Sobre
  la 0.4.0 local reproduce 6 documentos, 6.669 observaciones, 61 `unmapped`,
  22 textos y masa 44,999997. La clasificación exclusiva queda en 18
  observaciones `true_fault`, 25 `healthy_or_stable`, 17
  `administrative_request` y 1 `insufficient_context`.
- **Fase 1 implementada**: un `_pre` derecho sólo se incorpora a `analysis`
  ante etiqueta de modalidad explícita o ancla léxica inequívoca. Los tests
  reales anclan `CF.9110S1` (Vibraciones) y `TC.1523A2` (Ultrasonidos); el
  corpus descubre además el mismo layout de Inspección visual en `PM.4500`,
  `PM.9700A` y `LA.1249A2`.
  La `ACTUALIZACIÓN` de abril se recupera en la primera página como parte del
  desborde de Ultrasonidos, pero sus páginas de continuación y su forma
  normativa siguen pendientes de la fase 4.
- **Fase 2 implementada, pendiente de documentación/reemisión**: extractor
  0.5.0, `GT004v2` para «huelgo» y reglas nuevas `GT026`–`GT029` para
  válvula, deterioro de acoplamiento, barras rotas/sueltas y ruido en acople.
  Las fórmulas inequívocas de estabilidad/buen estado y línea parada dejan de
  consumir masa; las peticiones de informar/comentar/revisar permanecen
  `unmapped`. En la foto 0.4.0, la lectura actual deja 24 findings `unmapped`
  y masa 20,333332.
- **Documentado en esta sesión**: `GROUND_TRUTH.md`, `VERIFICATION.md` y
  ADR-0023 registran reglas, geometría y auditoría. **Pendiente**: cerrar las
  páginas 135–136 y el contrato de
  evidencia rica; ejecutar overlay/adenda, matriz, reemisión, validación y
  despliegue (fases 3–5). No se ha tocado ningún artefacto desplegado.

### Avance 2026-08-13 — adenda, matriz y despliegue

- **Fase 3 completada**: el overlay sube a 0.1.2 y apunta a
  `informes-gt-extract 0.5.0`. El diff exhaustivo detectó 11 textos cuyas
  claves cambian (35 observaciones) y dos juicios de estado que dejan de tener
  observaciones (7): la adenda re-juzga esos **13 textos / 42 observaciones**
  y sólo esos. Quedan 133 juicios / 415 observaciones y **0 remapeos**: los
  cinco de 0.1.1 ya los cubren reglas deterministas.
- **Spike de matriz completado, emisión normativa aplazada**:
  `scripts/audit_informes_status_matrix.py` lee imágenes 15x15 por coordenada
  de celda y exige un catálogo de siete hashes. Sobre los seis PDF obtiene
  102 páginas, 12.102 iconos, 1.660 celdas históricas únicas, 357 estados
  actuales y 354 máquinas; no hay firmas desconocidas ni discrepancias entre
  informes. DiagGT ya conoce 283 máquinas, 71 son exclusivas de la matriz y el
  crosswalk vigente resuelve 273. El JSON completo se publica junto a los PDF
  como artefacto no normativo; no se fuerzan filas mudas en 0.1.5.
- **Fase 5 completada para las generaciones documentales**: determinista
  0.5.0 archivada junto a 0.4.0/0.3.0 y contextual 0.1.2 desplegada junto a
  los informes y en Bunge, con backup previo en
  `/tmp/ams-wp16-backup-20260813.lD7m8e/`. Los 6 documentos preservan 6.669
  ids y hashes PDF; las cuatro proyecciones de informes contienen 1.308
  findings. Bunge materializa 7 documentos, 7.642 observaciones, 3.620
  consolidadas y 2.281 findings; valida con 0 errores, 731 avisos y 5
  informativos. El aviso adicional declara honestamente obsoleta la capa
  `diaggt-contrast` por el nuevo hash de entrada.
- **Sigue abierta sólo la evidencia rica**: el bloque `ACTUALIZACIÓN` de
  `TC.1523A2` continúa refluyendo por las páginas 134–136 y las
  intervenciones/medidas/peticiones no tienen aún proyección normativa. Se
  preservan en el texto/PDF fuente; no se inventa `record_kind` ni tabla hasta
  coordinar el contrato en `vibsynth-contracts`. Este punto mantiene el plan
  `in-progress`.

### 0. Auditoría reproducible y fixtures

- Crear el censo de cláusulas y `unmapped` de 0.4.0.
- Congelar las páginas/cajas problemáticas y sus textos esperados en fixtures
  pequeños, sin commitear los PDF completos.
- Registrar hashes, versión de `pdfplumber` y conteos base en
  `docs/VERIFICATION.md`.

### 1. Desbordes de `ANÁLISIS`

- Corregir la asignación de `right["_pre"]`.
- Añadir tests sintéticos de geometría y un test de integración por cada una de
  las dos máquinas reales.
- Exigir que ningún campo ajeno cambie en las otras fichas.

### 2. Reglas deterministas

- Separar estado/administración/fallo por cláusula.
- Implementar reglas y vetos versionados.
- Actualizar el destilado de regresión dejando explícitas todas las diferencias
  respecto a 0.4.0.
- Subir la versión del extractor determinista; no se cambia
  `DIAGGT_SCHEMA_VERSION` si los modelos no cambian.

### 3. Overlay contextual

- Aplicar el overlay contra la nueva determinista y recoger los textos que ya
  no casan.
- Re-juzgar sólo esos textos como adenda versionada; no regenerar por intuición
  los juicios intactos.
- Verificar que documentos, geometría y `source_sha256` sólo cambian donde el
  extractor incorporó evidencia antes ausente.

### 4. Matriz y evidencia rica

- Ejecutar el spike de imágenes y medir cobertura por informe.
- Cerrar la decisión de contrato.
- Implementar primero una muestra de un informe y después los seis.
- Resolver el crosswalk de los TAG nuevos con reglas CWxxx auditables; ninguna
  coincidencia aproximada se acepta silenciosamente.

### 5. Reemisión y despliegue

- Archivar la generación determinista anterior.
- Reemitir las dos generaciones y sus cuatro proyecciones 0.2.
- Desplegar en la carpeta de informes y en Bunge preservando backups y
  sidecars ajenos.
- Recalcular análisis derivados sólo después de actualizar sus hashes de
  entrada de forma honesta.

## Tests y verificación

- Unitarios de reglas por cláusula, negaciones, estados y cuantización.
- Regresión sobre todos los textos distintos del corpus.
- Tests geométricos sintéticos para columnas, continuaciones, imágenes y
  desbordes.
- Integración con `INFORMES_TEST_DIR` sobre los seis PDF.
- Validación de cada `*.diaggt.json` y de las cuatro proyecciones.
- `vibframe-validate` sobre una copia del dataset antes de desplegar.
- Idempotencia de materialización y del aplicador de overlay.
- Suite completa, Ruff y Pyright.

## Documentación transversal

En cada fase se corrige la documentación viva al mismo tiempo que el código:

- `GROUND_TRUTH.md`: semántica y reglas GT nuevas; decisiones abiertas que se
  cierren.
- `VERIFICATION.md`: corpus, hashes, conteos y diferencias antes/después.
- `DECISIONS.md`: ADR para cambios de lectura, geometría o contrato.
- `README.md` y `AGENTS.md`: versiones vigentes, comandos y generaciones
  desplegadas.
- Workplans 04, 09, 10 y 11: notas posteriores que retiren cifras o pendientes
  ya superados, sin reescribir su historia.

La fase no se considera cerrada si la prosa sigue presentando como actual una
limitación resuelta o una cifra de una generación anterior.

## Fuera de alcance

- Inferir diagnósticos que el informe no contiene.
- Sustituir el juicio del analista por una pasada LLM opaca.
- Añadir pesos a productores `system-alarm` o `synthetic-truth`; pertenecen a
  sus repos.
- Implementar en este repo el contraste por modo de fallo del visor.

## Criterios de aceptación

1. Los desbordes conocidos se recuperan con asignación geométrica demostrable.
2. Cada diferencia de reglas respecto a 0.4.0 está enumerada, testeada y
   versionada; no se pierde ningún finding verdadero sin una decisión expresa.
3. El overlay detecta el drift y sólo se re-juzgan los textos afectados.
4. La matriz/evidencia no entra en DiagGT hasta tener forma normativa o queda
   publicada explícitamente como artefacto no normativo.
5. Las dos generaciones, las proyecciones 0.2 y el dataset desplegado validan.
6. Toda cifra y versión documental coincide con los artefactos finales.
