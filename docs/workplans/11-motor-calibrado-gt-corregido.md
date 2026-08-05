---
status: in-progress
created: 2026-08-05
updated: 2026-08-05
---

# Plan: reglas GT corregidas, rodamientos inferidos y el `path` del export

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
