---
status: in-progress
created: 2026-08-13
updated: 2026-08-13
---

# Plan: mejorar los metadatos de punto sin inventar semántica

## Objetivo

Hacer que cada `PointDoc` describa mejor qué canal es, dónde mide y con qué
evidencia, aprovechando lo que AMS declara en el `.rbm` y las convenciones
estables de nombres. La mejora debe distinguir tres niveles:

1. **declarado** en un campo binario o de configuración;
2. **derivado determinista** de evidencia conservada, como el nombre del punto;
3. **inferido** por relación con puntos hermanos.

Un campo sin evidencia suficiente queda ausente. El plan no añadirá una clave
ad hoc a `machine.json`: si VibFrame no tiene dónde expresar componente o
procedencia por campo, se coordina primero el contrato o se conserva la mejora
como dato interno no emitido.

## Línea base

Sobre Bunge existen 5.203 puntos y 232 nombres distintos:

- `location`: 5.108 puntos (98,2 %).
- `direction`: 4.220 puntos (81,1 %); 983 sin dirección.
- `bearing_designations`: 1.520 puntos (29,2 %), verbatim.
- `nominal_speed_rpm`: 5.203 puntos (100 %).
- `kind`, `sensor` y `speed_source`: no se declaran hoy.
- El componente (`motor`, `bomba`, `reductor`, eje, campana…) sólo sobrevive
  dentro de `PointDoc.name`; no hay un campo de componente en `PointDoc` y su
  destino natural es el grafo `machine.definition`.

Estas cifras son baseline, no objetivos de cobertura. Una mejora se acepta por
precisión y procedencia, no por rellenar más celdas.

## Preguntas que se responden antes de escribir

### Qué declara realmente AMS

- ¿Existe en `vdpm`, `pdcd`, `pdpa` u otro record un tipo de canal/sensor que
  distinga acelerómetro, transductor de velocidad, entrada estática, tacómetro
  o fórmula?
- ¿La unidad/configuración describe el sensor físico o sólo la magnitud que AMS
  presenta después de integrar/derivar?
- ¿Hay un campo que declare el origen de RPM —constante, tacómetro físico,
  tacómetro virtual o extracción de frecuencia— para `PointDoc.speed_source`?
- ¿Los slots de rodamiento tienen rol/lado o son únicamente una lista plana?
- ¿Hay identificadores nativos de componente o pareja de punto además del
  `long_name` de 32 bytes?

Las pantallas necesarias para contestar estas preguntas se solicitan mediante
el catálogo del workplan 19. Hasta recibir ese gold no se promueve un decode
tentativo al export.

### Qué puede inferirse del nombre

- Componente: motor, bomba, reductor, ventilador, centrífuga, campana, eje de
  entrada/salida y niveles intermedios.
- Lado y dirección ya emitidos: revisar truncamientos, contradicciones y
  variantes no cubiertas.
- Rol del punto: vibración normal, PeakVue, alta frecuencia, alta resolución,
  corriente u otra magnitud no vibratoria.
- Relación entre variantes del mismo punto físico: velocidad, PeakVue/HF y
  pares ortogonales H/V/A.

La salida del parser de nombre pasa a ser una estructura de evidencia, no un
puñado de strings independientes. Debe conservar qué tokens/regla produjeron
cada conclusión y cuándo hubo ambigüedad.

## Diseño por capas

### 1. Censo de metadatos

Crear una auditoría reproducible sobre los 5.203 puntos con:

- nombre original y normalizado;
- `location`/`direction` actuales y evidencia;
- designaciones y RPM nominal;
- tipos de medida observados, unidades, Fmax, líneas y plantillas enlazadas;
- candidatos de componente/rol/pareja;
- contradicciones dentro de una máquina;
- campos VibFrame que podrían rellenarse y nivel de confianza.

El resultado agregado se commitea como fixture/reporte sin incluir información
del cliente que no esté ya destilada en `bunge_point_names.json`.

### 2. Metadatos declarados

Por cada campo binario confirmado:

1. documentar layout y gold en `FORMAT.md`/`VERIFICATION.md`;
2. añadir parser puro y modelo interno;
3. probar record sintético + integración real;
4. emitir sólo si la semántica coincide exactamente con el campo VibFrame.

Candidatos: `PointDoc.kind`, `sensor.type`, `speed_source`, rol de slots de
rodamiento y un identificador nativo estable. `sensor.type` no se deduce sólo
de `unit`: una señal presentada en velocidad puede venir de un acelerómetro
integrado.

### 3. Componente y grafo

El componente no se introduce como una extensión local de `PointDoc`.

- El parser puede producir un `component_hint` interno, con regla y calidad.
- Se evalúa si el hint debe alimentar a `vibsynth-machines` para resolver o
  completar nodos de `machine.definition`.
- Si hace falta una referencia explícita punto→nodo, se diseña primero en
  `vibsynth-contracts` mediante el procedimiento de cambio de formato.
- La procedencia debe declarar `point-name-regex` y calidad `approximate`; una
  coincidencia textual nunca se firma como `direct`.

No se duplicará el grafo dentro de cada punto ni se parseará semántica de ids
opacos.

### 4. Puntos hermanos y direcciones ausentes

Prototipar un matcher conservador dentro de cada máquina:

- mismo componente y lado explícitos;
- texto estructural idéntico tras separar el lado/dirección ya reconocidos y
  retirar sólo sufijos cerrados de adquisición (`PeakVue`, HF, HR, `(P)`…);
- un único candidato hermano con dirección explícita;
- ausencia de evidencia contradictoria.

La inferencia se mide primero en modo informe. Para emitirla hace falta un
lugar normativo donde declarar su procedencia/calidad; si el contrato no lo
permite, se conserva como propuesta para el enriquecedor. No se amplía el regex
para fingir que la dirección estaba escrita.

### 5. Rodamientos y frecuencias observadas

- Auditar los 186 puntos que declaran varios rodamientos: no asignar DE/NDE ni
  componente a cada slot si AMS no lo declara.
- Verificar que `frequency_refs` del dataset enriquecido corresponde a
  frecuencias observadas por el punto y no sólo a frecuencias existentes en la
  máquina.
- Mantener siempre `bearing_designations` verbatim aunque el enriquecedor las
  resuelva.

Esta fase coordina con `vibsynth-machines`; este repo declara materia prima y
no incorpora un catálogo de rodamientos.

## Fases de implementación

1. **Censo y taxonomía**: reporte reproducible y casos ambiguos.
2. **Parser de evidencia del nombre**: compatibilidad exacta con los 232 golds
   actuales antes de añadir componentes/roles.
3. **Decodes confirmados por gold**: uno por campo, con ADR independiente si
   cambia el significado emitido.
4. **Gate de contrato**: resolver procedencia por campo y referencia a
   componente antes de emitir inferencias nuevas.
5. **Export y postprocesos**: reexport Bunge, `t8-mapper`,
   `vibsynth-machines enrich` y comparación estructural antes/después.

### Estado de ejecución (2026-08-13)

En curso sin nuevos golds de AMS. La primera sesión se limita a las capas
deterministas que no cambian el documento VibFrame emitido:

- evidencia estructurada de `location` y `direction`, conservando regla y
  texto normalizado, con ambigüedad explícita;
- candidatos internos conservadores de componente y variante de adquisición;
- censo agregado reproducible a partir del corpus destilado de 232 nombres;
- prototipo en modo informe para asociaciones de puntos hermanos.

El censo reproducible del corpus confirma los 5.203 puntos y, sin cambiar los
campos emitidos, clasifica 4.831 candidatos de componente no ambiguos, 80
ambiguos y 292 ausentes; para variante de adquisición clasifica 2.058 y deja
3.145 ausentes. Una ejecución contra la RBM real confirma además 1.520 puntos
con rodamiento, 186 con varios slots y RPM nominal en los 5.203. El matcher de
hermanos propone dirección para sólo 18 puntos (13 H, 5 V); son resultados de
informe, no escritura.

Los posibles decodes de `kind`, `sensor`, `speed_source`, rol de slots de
rodamiento e identificador nativo quedan bloqueados: no se parsean ni se
emiten hasta disponer de golds del workplan 19. También queda pendiente el
gate de contrato para cualquier procedencia por campo o referencia a
componente; por ello esta sesión no añade claves a `machine.json`.

## Tests y mediciones

- Corpus completo de nombres con resultados y evidencia esperados.
- Casos negativos: tokens parciales, dos componentes, dos direcciones, puntos
  sin lado y nombres truncados.
- Tests de asociación de hermanos con cero/uno/varios candidatos.
- Integración contra `RBM_TEST_FILE`: 5.203 puntos, conteos y golds de campos
  binarios.
- Conformidad del `machine.json` null-free con el contrato actual.
- Auditoría before/after por campo: `declared`, `derived`, `inferred`,
  `ambiguous`, `absent`.
- Idempotencia del enriquecedor y cero referencias colgantes.

## Documentación transversal

- `FORMAT.md`: retirar el falso pendiente de `vddt` y actualizar todos los
  offsets/campos que el censo confirme o descarte.
- `VERIFICATION.md`: catálogo de golds usado, ejemplos positivos/negativos y
  cobertura medida.
- `DECISIONS.md`: una ADR por nueva inferencia emitida o cambio de contrato.
- `README.md`/`AGENTS.md`: separar metadatos AMS declarados de los añadidos por
  enriquecimiento.
- Workplans 07, 08, 11 y 14: notas posteriores con el destino final de los
  flecos, sin alterar sus cifras históricas.

## Fuera de alcance

- Inventar sensor, componente o tacómetro por frecuencia típica.
- Resolver rodamientos dentro de `ams-extract`.
- Convertir designaciones verbatim en una definición de máquina sin
  procedencia.
- Hacer obligatorios campos opcionales VibFrame para los otros productores.

## Criterios de aceptación

1. Cada campo nuevo puede rastrearse a bytes AMS, texto original o una regla de
   inferencia explícita.
2. Ambigüedad significa ausencia; no hay ganador por orden de regex.
3. No aparece una clave local fuera del contrato VibFrame.
4. Cualquier cambio común aterriza primero en contracts con modelo, spec,
   validador y golden coordinados.
5. Bunge reexportado valida, conserva sus 5.203 puntos y no pierde las
   declaraciones verbatim existentes.
6. Las cifras y limitaciones de toda la documentación coinciden con la nueva
   auditoría.
