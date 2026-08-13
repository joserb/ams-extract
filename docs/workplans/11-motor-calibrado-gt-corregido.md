---
status: completed
created: 2026-08-05
updated: 2026-08-13
---

# Plan: reglas GT corregidas, rodamientos inferidos y el `path` del export

> **Nota 2026-08-10** — histórico escrito contra **VibFrame 0.1**: su pendiente
> de `snap_t` en el contrato vendorizado quedó resuelto por la migración a 0.2,
> que además prohíbe `fault_frequencies_order`; ver ADR-0019 y el workplan 12.
>
> **Cierre posterior 2026-08-12** — Bunge fue reexportado con
> `--dataset-path`, volvió a etiquetarse y se enriqueció. El resultado actual
> es 3.728 frecuencias en 91 máquinas; los flecos que siguen abiertos se
> señalan como tales debajo.
>
> **Cierre posterior 2026-08-13** — `GT004v2`/`GT026`–`GT029` del workplan 16
> permiten retirar los cinco remapeos que aún conservaba el overlay 0.1.1. La
> publicación vigente es determinista 0.5.0 + contextual 0.1.2.

**Frente O1-A** de la tanda «motor calibrado, GT corregido, corpus al día».
Cuatro entregas que comparten una idea: lo que el frente anterior sólo pudo
*paliar* —bajando pesos, restaurando a mano, dejando designaciones sin
resolver— aquí se arregla en su sitio.

## Contexto

El workplan 10 cerró con una lista de flecos que no se podían tocar desde un
overlay de pesos:

- **Tres reglas GTxxx que el corpus desmiente.** El instrumento contra una
  regla floja es bajarle el peso; contra una regla **equivocada**, cambiar la
  regla. Un overlay que reescribe lo que produjo una regla convierte el fichero
  de juicio en un parche del vocabulario.
- El workplan 08 dejó otro fleco de operación: **`dataset.json:path`** lo pone
  a mano quien cura el dataset y cada re-export se lo lleva por delante.
- Y el enriquecedor del ecosistema (`vibsynth-machines enrich`, workplan 10 del
  monorepo) resuelve por catálogo **711 de 1.612 puntos** de
  `bunge_cartagena_ams`: **56 designaciones** se quedan fuera porque el
  catálogo no las tiene y porque *no se fabrica geometría*.

## Diseño

### 1. Las tres reglas desmentidas (`informes/rules.py`)

Cada una con su caso real del corpus, citado en el cierre del workplan 10:

| regla | qué leía mal | arreglo |
|---|---|---|
| GT001 | sólo casa «desequilibri»; en «**Desbalanceo** en el rotor del ventilador amplificado por debilidad en la estructura» el desequilibrio **desaparece del documento** (la cláusula casa GT005 y no queda ni un `unmapped`) | `GT001v2` casa también «desbalance-» |
| GT011 | dispara con «Se aprecia **buen estado de lubricación** de los rodamientos del conjunto», que afirma lo contrario | `GT011v2` con **veto** + la fórmula entra en el vocabulario de estado |
| GT021 | lleva toda «excentricidad» a `ELECTRICAL_ROTOR` sin mirar de qué: «excentricidad **en polea**» es mecánica | `GT021v2` con veto, y **GT025** la recoge como fallo de transmisión |

Tres decisiones de diseño:

- **El sufijo `vN` versiona la lectura**, como los `IRxxx` del t8-mapper y como
  ya pedía la propia spec («cambiar la lógica de una regla obliga a nuevo id o
  sufijo de versión»). Un finding ya emitido sigue diciendo qué regla lo
  produjo.
- **El veto es un concepto nuevo y explícito** (`RULE_VETOES`), no un
  `(?!...)` escondido en el patrón: el patrón dice qué lee la regla y el veto,
  dónde la frase afirma lo contrario. Se aplica **por cláusula**, la misma
  unidad en la que se aplican las reglas.
- **La excentricidad de polea se declara grupo, no modo.** `BELT` sólo tiene
  `BELT_FAULT` en el catálogo `FaultMode` y el fallo no es la correa sino la
  polea: el contrato prefiere `group` con `fault_mode` nulo a un modo cercano.

### 2. Re-emitir el GT de Bunge

Con las reglas nuevas el reparto de **5 textos** cambia, y con él las claves de
sus findings: el aplicador del overlay lo dirá en voz alta —para eso está esa
comprobación— y esos juicios se **re-juzgan** con el mismo criterio contextual
del workplan 10, como **adenda versionada** del overlay (0.1.0 → 0.1.1), no
como fichero nuevo: el juicio sobre los otros 130 textos no ha cambiado.

Despliegue igual que en el 10: backup previo en `/tmp`, generación determinista
archivada, generación LLM al archivo de informes y al dataset, consolidados
regenerados, `vibframe-validate --strict` en PASS.

### 3. `rbm export --dataset-path`

Opción repetible que escribe `DatasetInfo.path` (los niveles de agrupación por
encima del dataset, de fuera adentro). Sin la opción, el campo no se escribe:
`path` ausente y `path: []` significan cosas distintas y adivinar el nivel de
agrupación desde el nombre del `.rbm` sería inventarlo.

### 4. Rodamientos por inferencia LLM

Las 56 designaciones sin resolver son rodamientos **de catálogo estándar**
(6316, 23248, 22220, NU216…), no piezas exóticas. La geometría de un 6316 no es
un dato que haya que descubrir: está en cualquier catálogo SKF/FAG y es la
misma en todos ellos. La decisión del usuario es explícita: se pueden inferir
con un LLM «aunque nos tenemos que fiar del analista».

Lo que se materializa es un **fichero de entrada externa versionado en el
repo** (`overlays/`, mismo patrón que el overlay de pesos: fuente de verdad
auditable, con la designación verbatim y la procedencia de cada entrada), con
los factores en órdenes del eje —nivel 3 de `BearingDefinition`— que es
exactamente lo que `vibsynth-machines enrich --input` consume.

> **Nota (2026-08-05)**: el cierre entregó **nivel 2** (la geometría: `Z`,
> diámetro de bola, diámetro primitivo, ángulo), no nivel 3 (los cuatro
> factores). El motivo está en «Decisiones» — «La geometría, no los cuatro
> factores»: un lector puede contrastar «6316 = 80×170 mm, 8 bolas» con
> cualquier catálogo, mientras que un `BPFO: 3,0858` sólo se puede creer o no,
> y los órdenes los deriva el enriquecedor con las mismas fórmulas que aplica a
> su catálogo.

Reglas de honestidad, que son la mitad del diseño:

- **Sólo designaciones estándar inequívocas.** Un `6316` o un `22220` lo son;
  `RED` no es una designación y jamás entra; una variante rara o un texto
  dudoso se salta y se **lista**.
- **Sanity check aritmético** sobre cada entrada: `BPFO + BPFI ≈ Z` (número de
  elementos), `FTF < 0,5`, `BSF` coherente con la geometría. Lo que no pasa el
  check no se emite.
- **La calidad no sube por escribirlo en un fichero**: lo inferido es
  `approximate`, nunca `direct`.

## Pasos

1. Workplan (este documento).
2. `rules.py`: `GT001v2`, `GT011v2`, `GT021v2`, `GT025`, `RULE_VETOES` + tests
   con los textos reales; spec y `EXTRACTOR_VERSION` al día.
3. `rbm export --dataset-path` + test.
4. Fichero de rodamientos inferidos + `vibsynth-machines enrich --input`.
5. Re-emisión del GT de Bunge: adenda del overlay, despliegue y verificación.
6. Informe de números en este documento.

## Hecho

**Estado: COMPLETADO (2026-08-05).** Los seis pasos. Commits: `02bcef7`
(workplan), `9d615aa` (las tres reglas + GT025 + vetos), `572869f`
(`--dataset-path`), `b50957c` (rodamientos inferidos), `cb4e46f` (adenda del
overlay y re-emisión).

---

# Informe

## 1. Las reglas, sobre el corpus entero

Las tres correcciones tocan **5 textos y 11 observaciones** de las 6.669, y
ninguna más — comprobado texto a texto contra la generación archivada:

| texto (recortado) | antes | ahora |
|---|---|---|
| «**Desbalanceo** - Debilidad estructural del motor.» (VE.1408A, 3 obs) | STR · UNM | **IMB** · STR |
| «**Desbalanceo** en el rotor del ventilador… Frecuencias eléctricas…» (VE.1255, 1 obs) | STR · ELE | **IMB** · STR · ELE |
| «**Desbalanceo** … Lubricación mejorable … Huelgo leve.» (VE.1255, 2 obs) | STR · LUB · ELE · UNM | **IMB** · STR · LUB · ELE · UNM |
| «Debilidad estructural / Desequilibrio, **excentricidad en polea**.» (RG.1232C, 3 obs) | IMB · STR · **ELE** | IMB · STR · **BELT** |
| «Se aprecia **buen estado de lubricación**…» (CF.9110S3, 2 obs) | **LUB** · UNM | UNM |

Otras **270 observaciones** cambian sólo el `mapping_rule` al id versionado
(`GT001` → `GT001v2`…) de la regla que ya las producía. El resto del corpus
sale idéntico: mismos textos, misma geometría, mismo `source_sha256`.

**Falsos vetos que hubo que cazar.** La primera redacción del veto de GT011
casaba «lubricación» dentro de «**Ine**ficiente lubricación» y «**D**eficiente
lubricación», que son fallos, y se llevó por delante 4 observaciones más. La
frontera de palabra (`\b`) es lo que separa el veto de la censura; el test lo
fija con los seis textos de lubricación del corpus.

## 2. El GT re-emitido

Generación determinista `informes-gt-extract 0.4.0` y contextual
`informes-gt-weights-llm 0.1.1` (overlay 0.1.1). Despliegue igual que en el
workplan 10, con backup previo en `/tmp/wp11-backup-20260805-105247/`:

| generación | dónde |
|---|---|
| determinista 0.4.0 | `<informes>/ground-truth/deterministic-0.4.0/` (nueva, con su README) |
| determinista 0.3.0 | se conserva: es la línea sobre la que se midió el workplan 10 |
| LLM 0.1.1 | `<informes>/ground-truth/` **y** `bunge_cartagena_ams/ground-truth/` |

**Los 5 juicios re-juzgados** (adenda 0.1.1 del overlay, con su `why` dentro
del fichero). El criterio es el mismo del workplan 10, aplicado a un texto que
ahora dice más cosas:

1. **«Desbalanceo - Debilidad estructural del motor.»** — el juicio no cambia
   (empate), pero **el re-mapeo se retira**: lo que rescataba a mano el
   `unmapped` lo casa ya GT001v2, y con mejor calidad (`direct` en vez de
   `approximate`). Un re-mapeo es el parche que se quita cuando la regla se
   arregla.
2. **«Desbalanceo en el rotor del ventilador *posiblemente* amplificado por
   debilidad en la estructura. Frecuencias eléctricas…»** — con el
   desequilibrio de vuelta en la cláusula, la debilidad estructural vuelve a
   ser lo que el texto dice: un amplificador matizado con «posiblemente», no la
   conclusión. IMB 2 · STR 1 · ELE 2 → 0,4 / 0,2 / 0,4.
3. **La misma ficha con lubricación y «Huelgo leve»** — mismo reajuste
   (IMB 2 · STR 1) conservando LUB 1,5 · ELE 1,5 y el re-mapeo de «Huelgo
   leve» a `LOOSENESS`.
4. **«Debilidad estructural / Desequilibrio, excentricidad en polea.»** — el
   motivo de rebajar la excentricidad era que GT021 la llevaba al rotor
   eléctrico. GT025 la etiqueta bien, así que **recupera su tercio**: tres
   afirmaciones enumeradas sin análisis que decida, empatadas (2 · 2 · 2).
5. **«Se aprecia buen estado de lubricación…»** — se queda con un solo finding
   `unmapped` al 1,0. Es la lectura honesta —ninguna regla cubre ese texto—
   pero **no es la ideal**: el diagnóstico es de estado sano y debería producir
   `findings=[]`. Lo impide el vocabulario de estado, que no reconoce «Se
   establece su buen estado»; ver «Pendiente».

**Verificación.**

- Los 6 documentos validan contra `DiagGTDocument` de vibsynth-contracts
  (**0.1.5**), 6.669 observaciones, `extraction_method="llm"`.
- La masa suma **exactamente 1,0** en las 823 observaciones con findings;
  ningún peso fuera de (0, 1]. **Ninguna observación cambia nada fuera de
  `findings`**, y del `provenance` sólo `extractor` y `extracted_at`: el
  `source_sha256` de cada PDF sigue siendo el mismo.
- Consolidados: 3.379 filas de observación (3.239 con `dataset_machine_id`) y
  **629** de finding (antes 628: la nueva es el `BELT` de GT025).
- `vibframe-validate --strict` sobre `bunge_cartagena_ams`: **0 errores** y las
  **mismas 15 advertencias** `config.inconsistent-capture-span` de siempre.

**Masa por grupo** (`findings.parquet`, 628 → 629 filas, masa 389,0 en las dos):

| grupo | overlay 0.1.0 | overlay 0.1.1 | Δ |
|---|---|---|---|
| STRUCTURE | 110,58 | 109,96 | −0,62 |
| BEARING | 61,84 | 61,84 | 0 |
| LUBRICATION | 48,63 | 48,34 | −0,29 |
| LOOSENESS | 44,86 | 44,84 | −0,02 |
| ELECTRICAL | 35,28 | 34,74 | −0,54 |
| IMBALANCE | 27,71 | **28,26** | **+0,55** |
| OTHER | 21,17 | 21,17 | 0 |
| MISALIGNMENT | 19,59 | 19,59 | 0 |
| UNMAPPED | 14,40 | 14,65 | +0,25 |
| FLOW | 2,95 | 2,95 | 0 |
| GEAR | 2,00 | 2,00 | 0 |
| **BELT** | **0** | **0,67** | **+0,67** |

Los desplazamientos son pequeños porque el corpus es grande y los casos, cinco;
lo que importa no es el tamaño sino el signo: el desequilibrio que el analista
escribe «desbalanceo» **existe** en el GT por primera vez, y `BELT` deja de ser
un grupo vacío en un corpus lleno de transmisiones por correa.

## 3. `rbm export --dataset-path`

Repetible, un nivel por ocurrencia, de fuera adentro. Sin la opción el campo no
se escribe. Tests: el documento lo conserva **tras un re-export** (que era el
fleco), el orden de los niveles se respeta y `DatasetInfo` del contrato lo
valida.

## 4. Rodamientos inferidos

`overlays/bunge-cartagena-2026.bearings-llm.input.json`: **14 designaciones**
de bola (62xx y 63xx), nivel 2 de `BearingDefinition` (Z, diámetro de bola,
diámetro primitivo, ángulo 0), cada una con su designación verbatim, su
`_provenance: "llm-inference"` y su `_basis`.

Base de la inferencia, que es lo que hace la entrada auditable: dimensiones ISO
de la talla → `d_pitch = (d + D)/2`; `Z` de la serie (8 en 63xx, 10 en 62xx),
que es la que el catálogo del enriquecedor ya usa en las tallas contiguas; y
`d_ball = 0,3175·(D − d)`, la regla que **reproduce exactamente** las entradas
6208–6212 y 6307–6312 de ese mismo catálogo.

Tres ejemplos con su sanity check (`BPFO + BPFI = Z`, `FTF < 0,5`, `BSF` entre
1 y Z/2):

| designación | geometría | BPFO | BPFI | BSF | FTF | BPFO+BPFI |
|---|---|---|---|---|---|---|
| **6316** (69 slots) | Z 8 · 28,57 / 125 mm | 3,0858 | 4,9142 | 2,0733 | 0,3857 | **8,000 = Z** ✓ |
| **6213** (38 slots) | Z 10 · 17,46 / 92,5 mm | 4,0562 | 5,9438 | 2,5545 | 0,4056 | **10,000 = Z** ✓ |
| **6322** (4 slots) | Z 8 · 41,27 / 175 mm | 3,0567 | 4,9433 | 2,0023 | 0,3821 | **8,000 = Z** ✓ |

`tests/test_bearings_input.py` corre el check sobre las 14, y comprueba además
que los `_orders` que el fichero documenta son los que su geometría produce
—documentación que se desvía es peor que ninguna— y que `d_pitch`/`d_ball`
concuerdan con el `_bore_od_mm` declarado.

**Lo que se saltó, y por qué.** 31 claves normalizadas (40 formas verbatim):

| familia | designaciones | motivo |
|---|---|---|
| rodillos a rótula | `23248` (72), `23120` (45), `22220` (42), `22215`, `22314`, `22218` | el nº de rodillos **por hilera** no lo sé con confianza, y una hilera de más mueve BPFO un 7 % |
| cilíndricos | `NU216` (28), `NU312`, `NU213`, `NU215`, `NU219`, `NU220`, `NU315`, `N208` | ídem: entre 13 y 16 rodillos según fabricante |
| series sin cubrir | `6411` (40), `6014`, `6016`, `6019` | 64xx (extra-pesada) y 60xx (extra-ligera) no siguen la progresión de 62xx/63xx |
| contacto angular y otros | `7720B`, `7315`, `7220B`, `7213B`, `7214B`, `7308`, `QJ322N2`, `29420E`, `3306`, `2309`, `2311K`, `2316`, `2220` | el ángulo de contacto es parte de la designación y de la variante; sin él no hay factores |
| no es una designación | `RED` (20) | es «reductor» tecleado en el hueco del rodamiento |

La designación es inequívoca en casi todos los casos; lo que no es inequívoco
es **mi conocimiento de su geometría**, y ésa es la línea. Un número plausible
pero inventado no se distingue de uno bueno cuando llega al consumidor.

## 5. El enriquecimiento, antes y después

`vibsynth-machines enrich <dataset> --input <fichero> --write` (sólo ejecutado;
el enriquecedor es del monorepo `vibsynth`).

| | antes | después |
|---|---|---|
| máquinas con `fault_frequencies_order` | 73 | **119** |
| entradas de orden | 2.784 | **4.404** |
| puntos con órdenes | 696 | **1.101** de los 1.520 que declaran rodamiento (46 % → **72 %**) |
| máquinas con `definition` | 0 | **347** (mínimo no-vacío, ver abajo) |
| `definition_provenance` | 73, todas `direct` | 347: **330 `approximate`, 17 `weak`, 0 `direct`** |
| designaciones sin resolver | 45 claves | **31** (40 formas verbatim) |

**Idempotencia**: la segunda pasada dice `347 machine.json, 0 to change`.
**Conformidad**: `vibframe-validate --strict` con 0 errores y ningún hallazgo
`definition.*`.

Dos cosas que la pasada trajo y conviene no confundir con el efecto de los
rodamientos inferidos:

- **Las 347 `definition` mínimas** son la regla 3 del workplan 11 del monorepo
  (un nodo, el tipo que delata el nombre de la máquina, la velocidad nominal),
  que es posterior al enriquecimiento de agosto: cualquier pasada de hoy las
  escribe, con o sin este fichero.
- **La calidad ya no es `direct` en ninguna máquina**, ni siquiera en las 73
  que resuelven por catálogo. No es lo que el fichero declara, sino la regla de
  «una calidad por documento, manda la más débil»: el tipo inferido del nombre
  es `approximate`, y arrastra al documento entero. El objetivo de la entrega
  —que lo inferido no se publique como `direct`— se cumple, pero **por el
  camino equivocado**: el enriquecedor sigue tratando unos factores externos
  como `direct`. Ver «Pendiente».

## 6. Suite

| | antes | después |
|---|---|---|
| `uv run pytest` | 377 pasan, 49 saltan | **392 pasan**, 49 saltan (+15) |
| `ruff check src tests` | limpio | limpio |
| `pyright src` | 3 errores (`vibframe_viewer.cli`, del entorno) | los mismos 3 |

Los 15 tests nuevos: 6 sobre las reglas corregidas (con los textos reales del
corpus), 5 sobre el fichero de rodamientos, 4 sobre `--dataset-path`.

**Nota (2026-08-05)**: el «antes» de la fila de `pytest` dice 377 y el cierre
del [workplan 10](10-pesos-contextuales-llm.md) había anotado **378** pasados
con los mismos 49 saltados. Una de las dos cifras está mal por uno y no se
puede saber cuál sin volver a correr la suite en cada commit; se deja anotado.
El delta de este frente (+15 tests nuevos) no depende de ello.

**Un test rojo que no es de este frente**:
`test_the_goldens_round_trip_through_our_writer[vibsynth]` falla ya en `HEAD`
antes de tocar nada, porque el checkout vecino de `vibsynth-contracts` ganó la
columna `snap_t` en `trends.parquet` (etapa 1 del plan de tres del monorepo) y
el contrato vendorizado de este repo aún no la conoce. Es trabajo de
conformidad con su propio alcance —adoptar `snap_t` obliga a emitirlo y a
re-exportar—, no un daño colateral de éste.

## Decisiones

- **El veto es un concepto, no un `(?!…)`.** Meter la negación dentro del
  patrón habría escondido en una expresión regular ilegible la única parte del
  mapeo que dice «aquí la palabra miente». `RULE_VETOES` lo pone en su propia
  tabla, con su motivo, y es lo que documenta la spec en §3.3.1.
- **Se versiona el id de la regla, no sólo el del extractor.** Un finding
  emitido dice `GT011v2` y con eso un consumidor sabe qué lectura lo produjo,
  sin cruzar fechas con la versión de la herramienta. Cuesta que el fixture de
  regresión —anterior al sufijo— tenga que normalizarlo para comparar; se hace
  en una función de tres líneas y se dice por qué.
- **`GT025` declara grupo, no modo.** `BELT` sólo tiene `BELT_FAULT` en el
  catálogo y el fallo es de la polea, no de la correa. El contrato permite
  `group` con `fault_mode` nulo justamente para esto.
- **La adenda no es un overlay nuevo.** El juicio sobre los otros 130 textos no
  ha cambiado y copiar el fichero para tocar cinco entradas habría duplicado
  1.300 líneas de juicio con dos versiones vivas. Lo que se versiona es el
  fichero (`0.1.0` → `0.1.1`), con la adenda dentro diciendo qué revisó y por
  qué.
- **La geometría, no los cuatro factores.** Nivel 2 en vez de nivel 3: un
  lector puede contrastar «6316 = 80×170 mm, 8 bolas» con cualquier catálogo,
  mientras que un `BPFO: 3,0858` sólo se puede creer o no. Y los órdenes salen
  de las mismas fórmulas que los del catálogo del enriquecedor, no de mi
  aritmética.
- **Se salta lo que no se sabe, y se lista.** Es la regla de la casa («no
  emitir lo no validado») aplicada a una inferencia: la mitad del valor de este
  fichero está en las 31 designaciones que **no** están en él.
- **`--dataset-path` no adivina.** Se podría sacar «Bunge Cartagena» del nombre
  del `.rbm`, y sería una invención con aspecto de dato. Sin la opción, el
  campo no se escribe.

## Pendientes al cierre y estado posterior

- ~~**`snap_t` en `trends.parquet`: un test rojo en `HEAD`.**~~ Resuelto por
  la migración 0.2 (workplan 12): `snap_t` forma parte de las tres tablas y el
  golden de vibsynth hace round-trip. Al cerrar este plan, el contrato
  vendorizado aún no llevaba la columna mientras `vibsynth-contracts` ya la
  declaraba opcional; por eso fallaba aquel golden. El `.rbm` no tiene noción
  de snapshot y el valor emitido sigue siendo ausente/null según la capa.
- **El vocabulario de estado no cubre las fórmulas de cierre del analista.**
  «Se establece su buen estado», «Estable», «Sin evolución en el último mes»,
  «Informar a Preditec si se ha intervenido». Con GT011v2 arreglado, la ficha
  «Se aprecia buen estado de lubricación… Se establece su buen estado» acaba
  con un `unmapped` al 1,0 en vez de con `findings=[]`, que es lo que un
  diagnóstico sano debe producir. Es el mismo hallazgo que el workplan 10
  anotó al medir la masa `unmapped`, y toca a más textos que los tres de este
  frente: merece su propio paso, con su medida del corpus antes y después.
- **El enriquecedor no distingue catálogo de entrada externa al firmar la
  calidad.** `direct` es «los números vienen de un catálogo o de órdenes
  explícitas», y unos factores inferidos por un LLM entran por la misma puerta
  que un catálogo verificado. Hoy no se nota en `bunge_cartagena_ams` porque el
  tipo inferido del nombre baja el documento entero a `approximate`, pero en un
  dataset que ya declare `definition` sí se notaría. El arreglo es de
  `vibsynth-machines` (una calidad por entrada de `--input`, o `external-input`
  con techo `approximate`), no de aquí.
- **Las 31 designaciones sin geometría.** El camino honesto no es que las
  invente el mismo que las falla: es una tabla de fabricante o los factores que
  el propio T8 trae en su tabla `bearing`, que ya están en ese formato.
- ~~**Volver a etiquetar el dataset.**~~ Hecho tras el reexport del 2026-08-12
  (workplan 14); `--dataset-path` quedó preservado por el export.
