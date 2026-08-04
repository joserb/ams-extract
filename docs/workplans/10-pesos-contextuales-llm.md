---
status: designed
created: 2026-08-05
updated: 2026-08-05
---

# Plan: pesos contextuales del analista (pasada LLM sobre el GT de Bunge)

**Frente B.3** del plan «GT experto cuantificable». El workplan 09 dejó una
**línea base determinista**: la masa de juicio de cada observación repartida
`1/n` entre las cláusulas del diagnóstico. Este plan la contrasta con una
**lectura contextual** —un LLM leyendo `diagnosis_text` + `analysis_text` +
`recommendation_text` de las 823 observaciones con findings— que decide qué
cláusula es *la conclusión* y cuál es *mención lateral*, y materializa ese
juicio en un overlay versionable y un aplicador con tests.

## Contexto

El `1/n` es honesto y reproducible, pero es ciego a lo que el analista
enfatiza. El corpus lo grita:

- «Examinando sus firmas espectrales se aprecia excitación coincidente con el
  1xRPM, indicativo de ligero grado de desequilibrio. […] **no se descarta que
  el problema radique fundamentalmente en una debilidad estructural**» —
  desequilibrio y debilidad estructural no son media observación cada uno.
- «-Desequilibrio, **por el momento en niveles dentro de histórico**» — el
  analista está diciendo explícitamente que eso *no* es el hallazgo.
- «Debilidad estructural / Desequilibrio. **Estable. Se establece el buen
  estado.**» — el `1/n` le da **2/3 de la masa al `unmapped`** que sólo cubre
  «Estable» y «Se establece el buen estado»: dos cláusulas sin juicio de fallo.

La tercera es el caso puro de artefacto: el reparto por cláusulas cuenta como
juicio todo lo que no reconoce como estado, y el vocabulario de estado del
extractor (`HEALTHY_RE`, `STOPPED_RE`…) no cubre las fórmulas administrativas
(«Informar a Preditec si se ha intervenido»), las de tendencia («Sin evolución
en el último mes») ni las de buen estado que no dicen «en buen estado».

`extraction_method="llm"` existe en el vocabulario DiagGT desde 0.1.0 y no lo
usaba nadie. Este es su primer productor.

## Diseño

### 1. Qué se juzga y qué no

De las 823 observaciones con findings, **430 tienen un único finding**: su peso
es 1,0 por construcción y no hay reparto que juzgar. Las **393 restantes** son
la superficie real, y se reducen a **124 textos de diagnóstico distintos** —
los informes mensuales repiten el histórico, así que el mismo texto reaparece
como `retrospective` hasta 22 veces. Se juzga **una vez por texto** y se
reutiliza.

A esos 124 se suman los **11 textos de finding único `unmapped`** (29
observaciones), que no necesitan peso pero sí una decisión de re-mapeo. Total:
**135 textos juzgados, 422 observaciones**.

El contexto de un texto es la **unión** de los `analysis_text` y
`recommendation_text` con los que aparece: el retrospectivo cita el diagnóstico
sin su análisis, y el análisis del primario es el mejor contexto disponible
para él. 54 de los 124 textos multi-finding no tienen análisis en ningún
documento; ahí el juicio sale del propio diagnóstico (orden, cobertura,
adjetivos de matiz) y es deliberadamente conservador.

### 2. La escala: puntuaciones, no pesos a mano

El overlay **no guarda pesos**. Guarda una puntuación por finding en una escala
cerrada de cinco valores, y el aplicador normaliza y cuantiza con la misma
aritmética exacta del workplan 09 (`Fraction` + resto mayor a 10⁻⁶):

| puntuación | lectura |
|---|---|
| 3 | **conclusión principal** — el análisis se centra ahí, o de ahí sale el estado |
| 2 | **hallazgo relevante** — segunda afirmación real, co-principal |
| 1,5 | **co-principal repartido** — una conclusión escrita como dos alternativas |
| 1 | **mención secundaria** — se afirma, pero el análisis no la sostiene |
| 0,5 | **mención lateral** — matizada («posible», «leve», «dentro de histórico») |
| 0,25 | **residuo sin juicio** — cláusula administrativa o de estado caída en `unmapped` |

Ventajas de guardar la puntuación y no el peso: el juicio es legible («esto es
la conclusión, esto es un matiz»), no hay decimales escritos a mano que no
sumen 1, y **puntuaciones iguales reproducen exactamente el `1/n`** — cuando la
lectura contextual coincide con la línea base, el overlay lo dice sin
inventarse una diferencia.

### 3. Los criterios de lectura

Los que el corpus impone, en orden de fuerza:

1. **La redirección del analista.** «patrón característico de desequilibrio,
   **pero** dada la direccionalidad […] el problema radica en una debilidad
   estructural» es el giro más repetido del corpus: nombra el patrón de libro y
   lo descarta en favor de la causa real. La causa se lleva la conclusión.
2. **Qué cláusula fija el estado.** «Las amplitudes no son admisibles, se
   establece el estado de PELIGRO» ata la severidad a un hallazgo concreto; y
   el marcador de severidad escrito dentro del texto («-Holguras rotacionales
   en evolución. **ALERTA.** -Desequilibrio…») señala a qué cláusula pertenece.
3. **El matiz explícito.** «posible», «leve», «ligeras», «incipiente», «por el
   momento en niveles dentro de histórico», «de baja amplitud» bajan a mención
   lateral. El analista ya puso el matiz; el peso sólo lo aritmetiza.
4. **El orden de la recomendación.** Cuando el análisis no decide, decide la
   primera acción correctiva: es donde el analista pone el dinero.
5. **La mejora no es un fallo.** «**Mejor** estado de lubricación» (frente a
   «mejorable») es una nota de evolución favorable, no una afirmación de fallo:
   baja a secundaria y la masa se va al hallazgo que sigue vivo.
6. **Causa antes que consecuencia.** «desalineación […] **estos esfuerzos están
   provocando** la aparición de holguras rotacionales»: la causa manda.
7. **Dos reglas sobre la misma frase son una lectura.** «Holgura estructural /
   Falta de rigidez» dispara GT004 y GT023 sobre las mismas palabras: no son
   dos hallazgos y se quedan empatados (1,5 y 1,5), que es lo que ya hacía el
   `1/n` dentro de la cláusula.

### 4. Re-mapeo de `unmapped` (§2 del encargo)

De los 23 textos distintos con finding `unmapped` (64 observaciones), los que
el texto **sí** identifica pasan a un grupo concreto con `mapping_rule=null`
—no hay regla GTxxx detrás, es juicio— y `label_quality` **nunca `direct`**:
un peso LLM no sube la calidad de un mapeo. Cuando el grupo destino no tiene
`FaultMode` canónico (OTHER) el contrato obliga a `label_quality="group"` con
`fault_mode` nulo; cuando sí lo tiene, `approximate`.

El resto —fórmulas administrativas («Informar a Preditec si se ha
intervenido»), de tendencia («Sin evolución en el último mes»), de estado
(«Línea 1 de refinería parada») y de contexto operativo («Aumento en vibración
por condición operativa (carga)»)— **se queda `unmapped`**: no son fallos, y
lo que reciben es puntuación 0,25, no un grupo inventado.

### 5. El overlay y el aplicador

`ground-truth/weights-llm.overlay.json` (en el archivo de informes, junto a la
generación determinista) es el **juicio auditable**: una entrada por texto de
diagnóstico, con el texto verbatim como clave, el número de observaciones que
cubre, la razón en una línea, las puntuaciones por finding y los re-mapeos.

`src/ams_extract/informes/overlay.py` lo aplica sobre los `*.diaggt.json` ya
emitidos —no sobre los PDF: la geometría no se toca, sólo el reparto— y produce
la **segunda generación**:

- `provenance.extraction_method` → `"llm"`, `provenance.extractor` →
  `"informes-gt-weights-llm 0.1.0"`, `extracted_at` nuevo. **Todo lo demás del
  bloque intacto**, incluido el `source_sha256` del PDF: el documento fuente es
  el mismo y su hash sigue siendo verificable.
- Los findings conservan `source_text`, `matched_text`, `fault_mode`,
  `fault_group`, `label_quality` y `mapping_rule` salvo re-mapeo explícito.
  Sólo cambia `weight`.
- Ningún finding se crea ni se borra. Las observaciones sin entrada en el
  overlay salen byte a byte iguales salvo el peso (que tampoco cambia).

El aplicador **falla ruidosamente** si el overlay está desfasado: una entrada
cuyos findings no casan exactamente con los del documento, una puntuación ≤ 0,
un re-mapeo sobre un finding que no era `unmapped`, un destino con
`label_quality="direct"` o que rompe la invariante `group`/`fault_mode`. Un
overlay que no se puede aplicar entero no se aplica.

CLI: `rbm informes-weights <ground-truth-dir> --overlay <fichero> --out <dir>`,
que reescribe los documentos y re-consolida `observations` y `findings` con el
consolidador de siempre.

### 6. Dónde queda cada generación

| generación | dónde | extractor |
|---|---|---|
| determinista (`1/n`) | `<informes>/ground-truth/deterministic-0.3.0/` | `informes-gt-extract 0.3.0` |
| LLM (contextual) | `<informes>/ground-truth/` **y** `<dataset>/ground-truth/` | `informes-gt-weights-llm 0.1.0` |

La determinista se **conserva** en el archivo de informes, en subcarpeta
propia y con su `README`, para poder comparar las dos. En el dataset
`bunge_cartagena_ams` la LLM **sustituye** a la determinista (backup previo en
`/tmp`), porque el dataset publica una sola verdad y el visor lee la mejor
disponible.

## Pasos

1. Workplan (este documento).
2. Overlay `weights-llm.overlay.json` con los 135 juicios.
3. `informes/overlay.py` + `rbm informes-weights` + tests.
4. Despliegue: segunda generación al archivo y al dataset, consolidados
   regenerados, determinista archivada.
5. Verificación (`DiagGTDocument` 0.1.5, suma de pesos,
   `vibframe-validate --strict`) e informe de auditoría en este documento.

## Hecho

_(pendiente)_

## Decisiones

_(pendiente)_
