---
status: completed
created: 2026-08-05
updated: 2026-08-12
---

# Plan: pesos contextuales del analista (pasada LLM sobre el GT de Bunge)

> **Cierre posterior 2026-08-12** — el overlay vigente es la adenda 0.1.1,
> aplicada por `informes-gt-weights-llm 0.1.1` y desplegada en Bunge. La línea
> determinista 0.4.0 se conserva al lado; las reglas que este plan detectó se
> corrigieron en el workplan 11.

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
cerrada de seis valores, y el aplicador normaliza y cuantiza con la misma
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

`overlays/bunge-cartagena-2026.weights-llm.overlay.json` es el **juicio
auditable**: una entrada por texto de diagnóstico, con el texto verbatim como
clave, el número de observaciones que cubre, la razón en una línea, las
puntuaciones por finding y los re-mapeos. Vive **en el repo**, no junto a los
informes, porque es lo único de este frente que no se puede reproducir
ejecutando código —lo escribió un LLM leyendo el corpus—, así que es lo que hay
que poder revisar en un diff; una copia acompaña a la generación que produjo,
como el resto de artefactos desplegados. Ver `overlays/README.md`.

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

**Estado: COMPLETADO (2026-08-05).** Los cinco pasos, con la segunda
generación desplegada y verificada.

1. **Overlay** `overlays/bunge-cartagena-2026.weights-llm.overlay.json`: 135
   juicios (124 textos de reparto + 11 de finding `unmapped` único), 422
   observaciones cubiertas, 6 re-mapeos. Cada juicio con su razón en una línea;
   cada re-mapeo, con la suya.
2. **`informes/overlay.py`** + `rbm informes-weights` + `overlays/README.md`.
   Suite: 350 → **378** tests (28 nuevos), `ruff` limpio y `pyright src` con los
   3 errores de siempre (`vibframe_viewer.cli`, del entorno que no resuelve el
   editable).
3. **Despliegue**: generación LLM en `<informes>/ground-truth/` y en
   `bunge_cartagena_ams/ground-truth/`; determinista archivada en
   `<informes>/ground-truth/deterministic-0.3.0/` con su `README`. Backup previo
   de las dos copias en `/tmp/wp10-backup-20260805-003345/` con `MD5SUMS` (las
   dos eran byte a byte idénticas).

---

# Informe de auditoría

## Lo que no se movió

6 documentos, **6.669 observaciones**, 823 con findings, **1.321 findings**.
Ninguna observación cambió **nada fuera de `findings`** (comprobado campo a
campo sobre las 6.669), y del bloque `provenance` sólo se movieron `extractor`,
`extracted_at` y `extraction_method`: el `source_sha256` de cada PDF sigue
siendo el mismo y sigue siendo verificable. No se creó ni se borró un solo
finding. Los consolidados conservan sus **3.379 filas** de observación y sus
**628** de finding.

**430 observaciones (52 %) tienen un único finding** y su peso es 1,0 por
construcción: ahí no hay reparto que juzgar y la pasada no toca nada. La
superficie real son las **393** que reparten masa.

## Cuánto se aparta el juicio del `1/n`

| | |
|---|---|
| observaciones con findings | 823 |
| … de reparto (≥ 2 findings) | 393 |
| **observaciones con reparto distinto al `1/n`** | **291** (35 % de 823, 74 % de 393) |
| repartos idénticos al `1/n` | 102 de 393 |
| textos únicos que divergen | 86 de 242 |
| divergencia **L1 media por observación de reparto** | **0,234** (máx. 1,152) |
| distancia de variación total media (L1/2) | 0,117 |
| divergencia media por finding (n = 1.321) | 0,070 |
| observaciones cuya masa suma exactamente 1 | **823 de 823** |

Que 102 de 393 salgan **idénticas** no es que el overlay se las saltara: son
juicios explícitos de empate («las dos con el mismo respaldo en el análisis»,
«una frase leída por dos reglas»). La escala de puntuaciones está diseñada para
que eso se pueda decir sin inventar una diferencia.

El reparto deja de ser un puñado de fracciones: de **7 pesos distintos**
(1, 1/2, 1/3, 1/4, 1/6, 2/3) a **35**.

| peso | determinista | llm |
|---|---|---|
| 1 | 430 | 430 |
| 0,6 | — | 148 |
| 0,5 | 635 | 214 |
| 0,4 | — | 176 |
| 0,333… | 148 | 42 |
| 0,25 | 86 | 87 |
| 0,75 | — | 44 |
| 0,166… | 20 | 23 |
| otros 27 valores | — | 157 |

## Masa por grupo de fallo (`findings.parquet`, 628 filas, masa 389,0)

| grupo | determinista | llm | Δ |
|---|---|---|---|
| STRUCTURE | 103,58 (26,6 %) | 110,58 (28,4 %) | +7,00 |
| BEARING | 62,67 (16,1 %) | 61,84 (15,9 %) | −0,83 |
| LUBRICATION | 48,58 (12,5 %) | 48,63 (12,5 %) | +0,05 |
| LOOSENESS | 44,08 (11,3 %) | 44,86 (11,5 %) | +0,78 |
| ELECTRICAL | 33,25 (8,5 %) | 35,28 (9,1 %) | +2,03 |
| IMBALANCE | 27,58 (7,1 %) | 27,71 (7,1 %) | +0,13 |
| OTHER | 18,83 (4,8 %) | 21,17 (5,4 %) | +2,34 |
| MISALIGNMENT | 20,00 (5,1 %) | 19,59 (5,0 %) | −0,41 |
| **UNMAPPED** | **24,08 (6,2 %)** | **14,40 (3,7 %)** | **−9,68** |
| FLOW | 4,33 (1,1 %) | 2,95 (0,8 %) | −1,38 |
| GEAR | 2,00 (0,5 %) | 2,00 (0,5 %) | 0 |

La lectura de fondo, más allá de los números: **STRUCTURE sube y `UNMAPPED`
baja a la mitad**. Lo primero es el giro más repetido del corpus —«patrón
característico de desequilibrio, *pero* dada la direccionalidad…»— por fin
cuantificado: el analista redirige de continuo del desequilibrio de libro a la
debilidad estructural, y el `1/n` los empataba. Lo segundo tiene dos mitades:
9,7 puntos de masa `unmapped` se van, unos por re-mapeo (3 puntos) y la mayoría
porque el `1/n` daba juicio de fallo a cláusulas administrativas o de estado
que no lo son. **Ojo al interpretarlo**: la masa `unmapped` sigue midiendo la
cobertura de las reglas GTxxx, pero ya no está inflada por texto que no era
diagnóstico.

## Los 6 re-mapeos (21 observaciones)

Todos con `mapping_rule=null` —no hay regla detrás, es juicio— y
`label_quality` ≤ `approximate`.

1. **«Existencia de bandas laterales que podrían estar relacionadas con un
   fallo de barras sueltas o rotas.»** (PM.8033A, 4 obs) →
   `ELECTRICAL / ELECTRICAL_ROTOR`, `approximate`. Barras de rotor rotas es el
   fallo eléctrico de rotor por antonomasia; el texto lo nombra entero y ninguna
   regla lo casa.
2. **«Desbalanceo - Debilidad estructural del motor.»** (VE.1408A, 3 obs) →
   `IMBALANCE / IMBALANCE`, `approximate`. «Desbalanceo» es el sinónimo que el
   analista usa en media docena de fichas; GT001 sólo casa «desequilibri».
3. **«…Lubricación mejorable en rodamientos del ventilador. Huelgo leve.»**
   (VE.1255, 2 obs) → `LOOSENESS / LOOSENESS`, `approximate`. «Huelgo» es
   holgura; GT003/GT004 no lo conocen.
4. **«-Debilidad estructural (seguimiento). -Posible suciedad y/o desgaste en
   la válvula»** (VR.16080, 7 obs) → `OTHER`, `group`. Es un fallo —la
   recomendación manda «Revisar el estado de la válvula»— pero el catálogo
   `FaultMode` no tiene modo de válvula, así que el contrato obliga a `group`
   con `fault_mode` nulo.
5. **«-Deterioro del acoplamiento. - Debilidad estructural del motor.»**
   (PM.0518, 3 obs) → `OTHER`, `group`. Deterioro de acoplamiento no es
   desalineación y tampoco tiene modo canónico: se declara el grupo, no se
   fuerza el modo.
6. **«Ruido en el acople.»** (PM.700, 2 obs) → `OTHER`, `group`. Misma familia
   que los «ruidos mecánicos» de GT024, que no llega a casarlo.

Los otros 17 textos con `unmapped` **se quedan como están**: son peticiones al
cliente («Informar a Preditec si se ha intervenido»), notas de tendencia («Sin
evolución en el último mes», «Menor amplitud»), de estado («Línea 1 de
refinería parada», «Se establece el buen estado») o de contexto operativo
(«Aumento en vibración… por condición operativa (carga)»). No son fallos, así
que reciben puntuación 0,25 —no dejan de estar sin mapear— en vez de un grupo
inventado.

## Spot-check: 20 observaciones, una línea cada una

| # | diagnóstico (recortado) | `1/n` → LLM (en el orden de los findings) | razón |
|---|---|---|---|
| 1 | «Debilidad estructural / Desequilibrio. **Estable. Se establece el buen estado.**» | IMB 0,167→0,364 · STR 0,167→**0,545** · UNM 0,667→**0,091** | dos de las tres cláusulas son de estado; el juicio es la debilidad estructural, que el análisis nombra como causa |
| 2 | «Posible deterioro en rodamientos del motor. **Sin evolución en el último mes.**» | BEA 0,5→**0,923** · UNM 0,5→0,077 | «sin evolución» es tendencia, no un segundo hallazgo |
| 3 | «-Debilidad estructural del motor. **PELIGRO.** -*Posible aparición* de deterioro en el rodamiento» | STR 0,5→**0,75** · BEA 0,5→0,25 | la cláusula estructural lleva el PELIGRO; la del rodamiento va doblemente matizada |
| 4 | «Holguras rotacionales en los rodamientos de la bomba. …frecuencias *posiblemente* asociadas al rodete» | LOO 0,5→**0,75** · FLO 0,5→0,25 | el estado y la recomendación (cambio de rodamientos) cuelgan de las holguras; el rodete es `weak` y va matizado |
| 5 | «Desequilibrio/debilidad estructural.» (PM.9121A) | IMB 0,5→0,4 · STR 0,5→**0,6** | «*ligero grado* de desequilibrio» frente a «el problema radique *fundamentalmente* en una debilidad estructural» |
| 6 | «Frecuencias eléctricas… / Deterioro en rodamientos del motor *(baja amplitud)*» | BEA 0,5→0,4 · ELE 0,5→**0,6** | el análisis se inclina por lo eléctrico («reforzaría el carácter eléctrico»); el rodamiento es la alternativa a descartar con un by-pass |
| 7 | «-Desalineación. -Holguras rotacionales en rodamiento de la bomba» | MIS 0,5→**0,6** · LOO 0,5→0,4 | la desalineación es la causa y las holguras su consecuencia declarada («estos esfuerzos están provocando») |
| 8 | «**Mejor** estado de lubricación. Holguras rotacionales…» (CF.9110S3) | LOO 0,5→**0,75** · LUB 0,5→0,25 | «*mejor*» es una mejora, no un fallo: el hallazgo vivo son las holguras |
| 9 | «**Mejorable** estado de lubricación. Holguras rotacionales…» (mismo equipo) | LOO 0,5→0,4 · LUB 0,5→**0,6** | «*mejorable*» sí es un fallo, y sin matiz; las holguras van con «por el momento no de amplitud demasiado elevada» |
| 10 | «-Desequilibrio, *dentro de histórico*. -Lubricación inadecuada… y holguras *incipientes*. -Frecuencias eléctricas» | IMB 0,333→0,154 · LOO 0,167→**0,308** · LUB 0,167→**0,308** · ELE 0,333→0,231 | el analista saca el desequilibrio del cuadro; lo vivo es lo que ve en el PeakVue |
| 11 | «-Holguras rotacionales *en evolución*. **ALERTA.** -Desequilibrio, dentro de histórico. -Frecuencias eléctricas» | IMB 0,333→0,182 · LOO 0,333→**0,545** · ELE 0,333→0,273 | el marcador de severidad va pegado a las holguras |
| 12 | «-Debilidad estructural, **PELIGRO**. -Lubricación ineficiente. -Holguras rotacionales» | LOO 0,333→0,333 · STR 0,333→**0,5** · LUB 0,333→0,167 | lo estructural fija el PELIGRO y *causa* las holguras; la lubricación entra con «Además» |
| 13 | «Ruido de origen eléctrico.» | ELE 0,5→**0,75** · OTH 0,5→0,25 | una sola afirmación leída por dos reglas: GT013 es la sustantiva, GT024 sólo recoge «ruido» |
| 14 | «-Falta de rigidez / Resonancia… -Lubricación *mejorable* en rodamientos del molino» | RES 0,25→**0,375** · LUB 0,5→0,25 · STR 0,25→**0,375** | el análisis y el estado giran sobre lo estructural; la lubricación es la nota final de mantenimiento |
| 15 | «-Falta de rigidez / Resonancia… -Lubricación *ineficiente*» (MH.1506E) | RES 0,25→0,2 · LUB 0,5→**0,6** · STR 0,25→0,2 | aquí es al revés: el motor está «dentro del histórico» y la recomendación *sólo* pide revisar la lubricación |
| 16 | «Debilidad estructural / Desequilibrio, **excentricidad en polea**» | IMB 0,333→0,4 · STR 0,333→0,4 · ELE 0,333→**0,2** | la excentricidad es «en polea», mecánica: que GT021 la lleve a `ELECTRICAL_ROTOR` no merece un tercio del juicio |
| 17 | «Falta de rigidez / Resonancia en dirección horizontal del motor.» | RES 0,5→0,5 · STR 0,5→0,5 | *sin cambio*: es una conclusión escrita como dos alternativas, y empatarlas es lo correcto |
| 18 | «-Desalineación. -Debilidad estructural.» (PM.9130) | MIS 0,5→0,5 · STR 0,5→0,5 | *sin cambio*: el análisis sostiene las dos por separado («por un lado el 2xRPM… por otro la direccionalidad del 1xRPM») |
| 19 | «-Vibración aleatoria… por estas *posibles causas*: cavitación, lubricación deficiente, deterioro. -Debilidad… -Holguras» | LOO 0,333 · STR 0,333 · LUB 0,167 · FLO 0,167, **todos igual** | *sin cambio*: es un diagnóstico diferencial explícito, y el medio reparto que ya hacía el `1/n` es la lectura correcta |
| 20 | «Se aprecia **buen estado de lubricación** de los rodamientos…» | LUB 0,5→**0,25** · UNM 0,5→**0,75** | el texto afirma lo contrario de lo que GT011 lee: la masa se va a lo que las reglas honestamente no cubren |

## Verificación

- Los **6 documentos** validan contra `DiagGTDocument` de vibsynth-contracts
  **0.1.5** (6.669 observaciones), con `extraction_method="llm"` y
  `extractor="informes-gt-weights-llm 0.1.0"`.
- La masa suma **exactamente 1,0** en las 823 observaciones con findings; ningún
  peso fuera de (0, 1].
- `vibframe-validate --strict` sobre `bunge_cartagena_ams`: **0 errores** y las
  **mismas 15 advertencias** `config.inconsistent-capture-span` de siempre. La
  salida es **byte a byte idéntica** a la de la generación determinista
  (comprobado restaurando el backup, validando y volviendo a desplegar):
  `ground-truth/findings.parquet: 628 finding row(s), 628 with a weight`.
- Suite en verde: 378 pasados, 49 saltados.

## Decisiones

- **El overlay guarda puntuaciones, no pesos.** Escribir 1.321 decimales a mano
  es pedir que alguna observación no sume 1 y que nadie lo note; y un `0,6` no
  dice por qué. Una escala cerrada de seis valores dice «esto es la conclusión,
  esto es un matiz», y la aritmética la hace el aplicador con la misma función
  exacta de la generación determinista. Efecto secundario buscado:
  **puntuaciones iguales reproducen el `1/n` bit a bit**, así que «no cambio
  nada aquí» es un juicio que se puede expresar.
- **Se juzga por texto, no por observación.** Las 823 observaciones son 242
  textos; el mismo diagnóstico reaparece hasta 22 veces como `retrospective`.
  Juzgar por `observation_id` habría multiplicado por tres el fichero con
  copias del mismo juicio y lo habría atado a unos identificadores que una
  re-emisión puede mover. La clave es el texto verbatim: legible, greppable y
  estable frente a la re-emisión.
- **El aplicador lee documentos, no PDF.** El reparto no depende de la
  geometría de la ficha, y exigir 400 MB de PDF y 45 s de `pdfplumber` para
  reordenar unos pesos habría atado este paso a un extra que no necesita. Como
  efecto, la generación LLM se reproduce desde la determinista archivada con un
  comando y sin los informes delante.
- **La masa `unmapped` de una cláusula administrativa baja, no desaparece.**
  Se le da 0,25 y no 0. La spec dice que la masa `unmapped` mide la cobertura de
  las reglas, y «Informar a Preditec si se ha intervenido» **sigue** siendo
  texto que las reglas no cubren: ponerlo a cero sería reclamar una cobertura
  que no existe. Lo que se corrige es tratarlo como *un juicio de fallo más*,
  que es lo que hacía el `1/n`.
- **No se re-mapea nada que ya casara una regla.** Hay al menos dos lecturas de
  GTxxx que el corpus desmiente (§ pendientes), y la tentación de arreglarlas
  desde el overlay es fuerte. Se descarta: un overlay que reescribe lo que
  produjo una regla convierte el fichero de juicio en un parche del
  vocabulario, y entonces ya no se sabe qué versión de las reglas produjo qué.
  El instrumento contra una regla floja es bajarle el peso; contra una regla
  equivocada, cambiar la regla.
- **`label_quality` de un re-mapeo nunca es `direct`.** Si el origen nombrara el
  modo canónico, habría casado una regla. Y cuando el grupo destino no tiene
  `FaultMode` en el catálogo (`OTHER`), el contrato obliga a `group` con
  `fault_mode` nulo: se declara el grupo, no se fuerza un modo cercano.
- **En el dataset sustituye; en el archivo conviven.** El dataset publica una
  sola verdad y el visor lee la que hay; el archivo de informes es donde se
  comparan las generaciones, y por eso la determinista se conserva entera en
  `deterministic-0.3.0/` con su `README`.

## Pendiente

> **Nota (2026-08-05) — las tres reglas ya están arregladas.** El primer
> pendiente de abajo lo ejecutó el
> [workplan 11](11-motor-calibrado-gt-corregido.md): `GT001v2` casa
> «desbalance-», `GT011v2` y `GT021v2` estrenan `RULE_VETOES` y `GT025` recoge
> la excentricidad de polea como fallo de transmisión (`BELT`, grupo sin modo);
> spec en `docs/GROUND_TRUTH.md` §3.3 y §3.3.1. El overlay dejó de casar en 5
> textos, como este plan anticipaba, y esos 5 juicios se re-juzgaron como
> adenda 0.1.1. El diagnóstico de este apartado sigue siendo la lectura
> correcta del problema; lo que ha caducado es el «pendiente».

- **Reglas GTxxx que el corpus desmiente**, encontradas al leerlo entero y que
  este frente sólo ha podido paliar bajando pesos:
  - **GT001 no casa «desbalanceo»**, el sinónimo que el analista usa en varias
    fichas. En «Desbalanceo en el rotor del ventilador *amplificado por
    debilidad en la estructura*» ni siquiera sale un `unmapped`: la cláusula
    casa GT005 y el desequilibrio **desaparece del documento**. Ahí el overlay
    no puede hacer nada — no se inventan findings.
  - **GT021 lleva «excentricidad» a `ELECTRICAL_ROTOR`** sin mirar de qué es la
    excentricidad: «excentricidad en polea» es mecánica.
  - **GT011 dispara con «buen estado de lubricación»**, que afirma lo contrario;
    `HEALTHY_RE` no reconoce esa fórmula.
  - Las tres se arreglan en `rules.py`, no en un overlay. Al hacerlo, este
    overlay dejará de casar y el aplicador lo dirá en voz alta — que es
    exactamente para lo que está esa comprobación.
- **Validar el juicio contra el analista.** Esta pasada es una lectura
  cuidadosa del texto, no una encuesta a quien lo escribió. La comparación con
  el `1/n` mide *cuánto* se apartan las dos lecturas; cuál acierta más sólo lo
  dice el analista o una métrica de evaluación aguas abajo.
- **El primer consumidor.** El contraste por modo de fallo en `vibframe-viewer`
  sigue pendiente (workplan 09), y ahora tiene dos generaciones sobre las que
  medir: la línea base y el juicio. Que la métrica mejore con la segunda es la
  prueba de que el peso contextual sirve para algo.
