---
status: completed
created: 2026-08-04
updated: 2026-08-13
---

# Plan: hogar del extractor de informes y línea base de pesos por finding

> **Nota 2026-08-10** — histórico escrito contra **VibFrame 0.1**: las vistas
> consolidadas son hoy las cuatro proyecciones normativas 0.2 (sin CSV) y el
> `crosswalk.csv` es artefacto de herramienta, no formato; ver ADR-0019 y el
> workplan 12.
>
> **Estado operativo 2026-08-12** — la generación determinista vigente es
> `informes-gt-extract 0.4.0`; la contextual es
> `informes-gt-weights-llm 0.1.1`. Ambas materializan las cuatro proyecciones
> normativas 0.2. El fixture 0.2.0 citado debajo se conserva a propósito como
> línea base de regresión de las reglas anteriores.
>
> **Estado operativo 2026-08-13** — el workplan 16 sustituyó la publicación
> por `informes-gt-extract 0.5.0` y `informes-gt-weights-llm 0.1.2`; las
> generaciones citadas arriba quedan como historia reproducible.

**Frente B.2** del plan «GT experto cuantificable». Dos cosas que van juntas
porque la segunda no cabe en un script suelto: **dar hogar** al extractor de
informes dentro de `ams_extract` (con tests de regresión) y **cuantificar** el
juicio del analista repartiendo una masa 1 por observación entre sus findings.

## Contexto

El GT de los informes Preditec (workplan 04, spec `docs/GROUND_TRUTH.md`) lo
produce hoy `extract_informes_gt.py`, un script de 874 líneas que vive suelto
en `../Informes Bunge Cartagena 2026/ground-truth/` con una copia desplegada
en el dataset. No tiene tests, no está en el paquete, no lo toca `ruff` ni
`pyright`, y su `SCHEMA_VERSION` se quedó en `"0.1.0"` mientras la spec iba
por 0.1.4 — el documento emitido declara una versión que no es la que produce.
Es el productor `inspection-report` de referencia del ecosistema: 6.669
observaciones, el único GT de analista que existe.

La segunda mitad es la que motiva el frente: **un finding hoy no dice cuánto
pesa**. Un diagnóstico de cuatro cláusulas («desequilibrio, holguras,
lubricación, rodamiento») y uno de una sola («desequilibrio») producen findings
indistinguibles, así que cualquier métrica que compare un diagnóstico
automático contra el GT tiene que tratar las cuatro etiquetas del primero como
si cada una fuese la afirmación central. El analista no dijo eso: repartió su
juicio.

## Diseño

### 1. Hogar: `src/ams_extract/informes/`

| Módulo | Qué es | Dependencias |
|---|---|---|
| `rules.py` | vocabularios DiagGT y mapeo texto→finding (GTxxx, estados, pesos) | stdlib |
| `parse.py` | geometría de la ficha en PDF y construcción del documento DiagGT | + `pdfplumber` |
| `consolidate.py` | consolidados planos `observations` y `findings` | + `pyarrow` |
| `cli.py` | `rbm informes …` | + `typer` |

`pdfplumber` entra como **extra** (`ams-extract[informes]`), no como
dependencia dura: quien sólo lee `.rbm` no necesita un parser de PDF. El
import vive dentro del comando, como el de `pyarrow` en
`export/diag_gt.py`, así que el CLI arranca sin el extra instalado y falla con
un mensaje claro sólo si se pide `informes`.

`rules.py` no importa nada fuera de stdlib **a propósito**: es la capa que los
tests de regresión ejercitan sin PDFs (ver §3) y la que cambia cuando cambia el
vocabulario del analista.

**Los dos scripts acompañantes** —`crosswalk_gt.py` (tabla TAG ↔ `machine_id`)
y `verify_previous.py` (fidelidad muestral contra el texto crudo de pdfplumber)—
se adoptan en `scripts/`, no en `src/`, y siguen usando pandas: el primero es
un post-proceso que se ejecuta una vez por par (informes, dataset) y produce
una tabla curada a mano, y el segundo es un arnés de verificación que necesita
los PDFs. Ninguno de los dos participa en la emisión. A cambio, el extractor
integrado aprende a **proyectar** `crosswalk.csv` sobre sus consolidados (la
spec §2.4 ya dice que esa tabla es la fuente del mapeo y el consolidado su
proyección), que es lo que da a `findings.parquet` su columna de join sin
tener que re-ejecutar el crosswalk.

**Las dos copias sueltas** (`…/Informes Bunge Cartagena 2026/ground-truth/` y
`~/wslprojects/RESONINS/datasets/bunge_cartagena_ams/ground-truth/`) quedan
donde están como **artefactos desplegados**; no se borran ni se sincronizan. La
relación queda anotada en la cabecera del subpaquete y en `AGENTS.md`: el
código vivo es el del repo, esas copias son el sello de la emisión de
2026-07-28. Ojo al leerlas después del paso 4 de este plan: los ficheros que
tienen al lado ya no los produjo ese script, sino
`ams_extract.informes` 0.3.0, y su `provenance.extractor` lo dice.

`SCHEMA_VERSION` pasa de `"0.1.0"` a la constante del contrato (0.1.5 con este
plan). El desalineado era un bug: el documento declaraba 0.1.0 emitiendo
0.1.4.

### 2. Pesos: una masa por observación repartida por cláusulas

`CLAUSE_SPLIT_RE` ya trocea el diagnóstico en cláusulas —el analista escribe
listas separadas por punto o por guion de viñeta— pero hoy sólo se usa para
decidir si el texto entero es un texto de estado. Las `FINDING_RULES` se
aplican sobre el texto completo.

Nueva regla, en tres pasos:

1. **Clasificar cada cláusula**. Una cláusula es *de estado* si casa la familia
   «… en buen estado / máquina parada / no medida / fuera de servicio» y no
   casa ninguna regla de fallo; es un *marcador* si es exactamente una etiqueta
   del vocabulario global de estado («ALERTA», «PELIGRO», «SEGUIMIENTO»…), que
   el analista repite dentro del texto y que no dice nada del fallo; el resto
   son *cláusulas de juicio*. Estado y marcador no reciben masa. Si no queda
   ninguna cláusula de juicio, `findings=[]` — el mismo resultado que hoy da la
   comprobación por texto entero.
2. **Repartir**. Cada una de las `n` cláusulas de juicio recibe `1/n`. Dentro
   de una cláusula, sus findings se reparten esa fracción a partes iguales. Una
   cláusula de juicio que ninguna regla reconoce cede su `1/n` al finding
   `unmapped`.
3. **Fusionar** por `(fault_group, fault_mode)`, sumando masas, quedándose con
   la regla de menor índice (el orden de `FINDING_RULES` es la prioridad de
   siempre) y con su `matched_text`. El resultado se ordena por ese mismo
   índice, con el `unmapped` al final.

La masa emitida suma **exactamente 1** en toda observación con findings. El
`unmapped` deja de ser un caso de todo-o-nada (hoy sólo aparece cuando el texto
entero no casa nada) y pasa a medir **qué fracción del juicio no cubren las
reglas**, que es justo la métrica de cobertura que el frente busca.

Cuantización: las fracciones son exactas (`Fraction`) y se redondean a 6
decimales por el método del **resto mayor** —unidades de 10⁻⁶, el sobrante se
reparte entre las mayores partes fraccionarias— para que la suma en enteros sea
exactamente 10⁶ y nunca supere el 1 que exige el contrato.

Lo que **no** cambia: `extraction_method` sigue siendo `"pdf_text_parse"` (el
peso sale del mismo parseo determinista, no de un modelo), las reglas GTxxx
siguen siendo las mismas 24, y el aplanado de `observations.parquet` sigue
uniendo modos con «+» sin mirar los pesos (compat).

Restricción del contrato (`DiagGTFinding.weight`, 0.1.5): en una observación o
**todos** los findings llevan peso o ninguno, y la suma es ≤ 1. Este extractor
siempre pone peso a todos.

### 3. Regresión contra la salida vieja

Los seis `*.diaggt.json` de 2026-07-28 son el golden. Como pesan 5,8 MB y los
PDFs (49–73 MB) no están en el repo, el fixture es su **destilado**: los 251
`diagnosis_text` distintos del corpus con los findings que el extractor 0.2.0
les asignó. El test re-ejecuta el mapeo sobre cada texto y compara. Es
regresión byte-a-byte de la capa que este plan toca —el mapeo— sin arrastrar
los PDFs ni los JSON completos.

La geometría (columnas, continuaciones, invariante de anclas) sólo se puede
verificar con los PDFs: va en un test marcado `integration` que se salta si
`INFORMES_TEST_DIR` no apunta a la carpeta de informes, igual que
`RBM_TEST_FILE` en el resto de la suite.

Diferencias medidas del mapeo nuevo contra el viejo sobre las 6.669
observaciones (prototipo, antes de implementar):

| | textos distintos | observaciones |
|---|---|---|
| idénticas | 233 | 6.624 |
| gana un `unmapped` parcial | 11 | 34 |
| cambia el `matched_text` | 7 | 11 |
| **pierde algún finding** | **0** | **0** |

Los 11 `matched_text` que cambian son todos del mismo tipo y a mejor: la
alternativa `rodamiento.*deterior` de GT012 casaba **cruzando cláusulas**
(«rodamientos del conjunto. Posible deterioro»), y por cláusula casa el
fragmento que de verdad nombra el fallo («deterioro en rodamiento»).

### 4. `findings.parquet`

Consolidado nuevo junto a `observations.parquet`, una fila por finding, con las
columnas que declara el contrato: `document_id`, `observation_id`,
`dataset_machine_id`, `observed_at`, `modality`, `record_kind`, `fault_mode`,
`fault_group`, `label_quality`, `mapping_rule`, `weight`, `source_text`.

Se deriva del **mismo conjunto deduplicado** que `observations.parquet`
(primary gana a retrospective; entre retrospectivos gana el informe más
reciente): si no, un diagnóstico previo citado por seis informes contaría seis
veces al agregar masa por modo de fallo.

## Pasos

1. Workplan (este documento) y `docs/GROUND_TRUTH.md` a 0.1.5 con §weight.
2. Adoptar el extractor tal cual en `src/ams_extract/informes/` + extra
   `informes` + `rbm informes` + fixture destilado y test de regresión que
   reproduce la salida 0.2.0.
3. Pesos por cláusula (`rules.py`) y su test.
4. `findings.parquet` en `consolidate.py` y su test.
5. Re-emitir los 6 informes: `*.diaggt.json` 0.1.5 con pesos +
   `observations.parquet/.csv` + `findings.parquet`, desplegar al dataset
   `bunge_cartagena_ams` (backup previo) y verificar con
   `vibframe-validate --strict`.

## Hecho

**Estado: COMPLETADO (2026-08-05).** Los cinco pasos, con la re-emisión de los
6 informes desplegada y verificada.

1. **Subpaquete `src/ams_extract/informes/`** (`rules`, `parse`,
   `consolidate`) + extra `informes` (pdfplumber) + comando `rbm informes` +
   los dos acompañantes en `scripts/`. `SCHEMA_VERSION` deja de decir `"0.1.0"`.
   Suite: 313 → **333** tests (20 nuevos), `ruff` y `pyright src` limpios (los
   3 errores de `pyright` de `vibframe_viewer.cli` son de siempre, del entorno
   que no resuelve el editable).
2. **Pesos por cláusula** en `rules.map_findings` (extractor 0.3.0, DiagGT
   0.1.5). 345 tests.
3. **`findings.parquet`** en `consolidate` y en el comando. 350 tests.
4. **Re-emisión** de los 6 informes (49–73 MB de PDF, ~7 s cada uno) y
   despliegue a las dos copias: `<informes>/ground-truth/` y
   `bunge_cartagena_ams/ground-truth/`. Backup previo en
   `/tmp/wp09-backup-<ts>/` con `MD5SUMS`.
5. **Spec `GROUND_TRUTH.md` a 0.1.5** (§2.5 `weight`, §3.3 reparto por
   cláusulas y marcador de severidad, §4 y §5.1 `findings.parquet`, §7
   productores) y las dos copias de cortesía `FORMATO_GROUND_TRUTH.md`
   sincronizadas.

### La re-emisión, número a número

Lo que **no** se movió: 6 documentos, **6.669 observaciones** (1.670 primarias
+ 4.999 retrospectivas), 826 fichas de máquina, invariante de anclas
4.960 = 4.960, 6 páginas de continuación arrastradas, y el bloque `provenance`
entero —incluido el `source_sha256` de cada PDF— salvo `extracted_at` y
`extractor`. Ningún campo de ninguna observación cambió fuera de `findings`.
La lectura de pdfplumber 0.11.10 reproduce la geometría de la emisión de julio
sin una sola diferencia.

Lo que cambió, exactamente lo previsto:

| | observaciones |
|---|---|
| findings idénticos | 6.624 |
| gana un `unmapped` parcial | 34 |
| se mueve el `matched_text` (GT012) | 11 |
| pierde algún finding | **0** |

Pesos: **823 observaciones** con findings (12,3 % de 6.669), **1.321 findings**
en los seis documentos, y la masa suma **exactamente 1,0 en las 823**. Reparto:

| peso | findings |
|---|---|
| 1 | 430 |
| 1/2 | 635 |
| 1/3 (0,333333 / 0,333334) | 148 |
| 1/4 | 86 |
| 1/6 | 20 |
| 2/3 | 2 |

`findings.parquet`: **628 filas** sobre las 3.379 del consolidado (389
observaciones tras la deduplicación), 600 con `dataset_machine_id`, masa total
389,0 = una unidad por observación. Por grupo: STRUCTURE 103,6 · BEARING 62,7 ·
LUBRICATION 48,6 · LOOSENESS 44,1 · ELECTRICAL 33,3 · IMBALANCE 27,6 ·
**UNMAPPED 24,1** · MISALIGNMENT 20,0 · OTHER 18,8 · FLOW 4,3 · GEAR 2,0. Ese
UNMAPPED es el 6,2 % de la masa: la cobertura que le falta a las reglas GTxxx,
por fin medible.

`observations.parquet`/`.csv`: mismas 3.379 filas, mismas claves, mismo orden.
La única diferencia con la emisión de julio es `alarm`, que pasa de float64 de
pandas (`2.0`) a **int8** (`2`) — el tipo que declara VibFrame para esa escala
— en 2.151 filas. `fault_modes`/`fault_groups` no se mueven: los `unmapped`
nuevos no entran en el aplanado (§5).

Verificación: los 6 documentos validan contra `DiagGTDocument` de
vibsynth-contracts 0.1.5, y `vibframe-validate --strict` sobre el dataset da
**0 errores** y las **mismas 15 advertencias** que daba antes de tocar nada
(todas `config.inconsistent-capture-span` sobre `spectra.parquet`, del control
de generaciones que contracts añadió en su workplan 05 — comprobado
restaurando el ground truth viejo y volviendo a validar). Nuevo en el informe:
`ground-truth/findings.parquet: 628 finding row(s), 628 with a weight`. La capa
`analysis/diaggt-contrast` no se tocó.

## Decisiones

- **La masa la lleva el `unmapped`, no se pierde.** La alternativa era dejar
  que la suma bajara de 1 y que el consumidor leyera el hueco como «otros
  implícito». Se descarta para este productor: la spec ya manda «no callar lo
  no mapeado» (§2.5) y un hueco silencioso es exactamente callarlo. El
  contrato admite suma < 1 porque otro productor puede reservar masa; éste no
  la reserva.
- **Los marcadores de severidad no son cláusulas de juicio.** Sin esta regla,
  un «-Desequilibrio del ventilador. ALERTA. -Debilidad estructural.» repartía
  1/3 a un `unmapped` que sólo cubría la palabra «ALERTA»: 44 de las 124
  cláusulas no cubiertas del corpus son la etiqueta global repetida dentro del
  texto. El vocabulario es el mismo cerrado que ya valida la cabecera de la
  ficha.
- **Reparto uniforme, no ponderado por longitud ni por severidad.** Es una
  *línea base determinista*: reproducible, explicable en una frase y sin
  parámetro que ajustar. Cualquier reparto más fino (por severidad de la
  cláusula, por orden de mención) es una hipótesis sobre cómo escribe el
  analista que habría que validar contra él, no contra el texto.
- **El crosswalk no se integra.** Ver §1. El extractor lee `crosswalk.csv` del
  directorio de salida y proyecta el `dataset_machine_id` sobre los dos
  consolidados (3.239 de 3.379 filas resueltas desde 273 entradas), que es lo
  que necesitaba `findings.parquet` para tener su clave de join sin volver a
  ejecutar nada.
- **El CSV se escribe con LF**, no con el CRLF del dialecto `excel` de
  `csv.writer`: es el salto con el que nació `observations.csv` y el fichero se
  lee en Linux. (`observations_system.csv`, del productor de alarmas, sí quedó
  con CRLF; no se toca aquí.)

## Pendiente

Este apartado es la lista al cierre del plan. Las reglas GT001/GT011/GT021 y
GT025 se resolvieron y versionaron en el workplan 11; cualquier cifra de
`unmapped` restante debe medirse sobre la generación 0.4.0 antes de convertirla
en una tarea nueva.

- **Vista de contraste con pesos**: `analysis/diaggt-contrast` sigue leyendo
  `observations`, que es lo que necesita (`alarm` contra `alarm`). El primer
  consumidor de `findings.parquet` será el contraste por modo de fallo, en
  `vibframe-viewer`.
- **Los 33 findings `unmapped`** que quedan (24,1 de masa) son la lista de la
  compra de las reglas **GT026+** (nota 2026-08-05: `GT025` ya está ocupada por
  la excentricidad de polea, workplan 11): «suciedad/desgaste en la válvula»,
  «deterioro del acoplamiento», «bandas laterales de barras rotas», «sin
  evolución en el último mes». Las tres primeras son fallo; la última es un
  texto de estado que `HEALTHY_RE` no reconoce. Ampliar el vocabulario baja la masa `unmapped` sin
  tocar el esquema.
- **`weight` en los otros productores**: las alarmas `gdnl` (`system-alarm`)
  emiten un finding por observación, así que su peso sería siempre 1 y no
  aporta; el sintético (`synthetic-truth`) sí tiene un reparto natural (la
  severidad relativa de cada modo inyectado) y es decisión de su repo.
