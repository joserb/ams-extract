---
status: completed
created: 2026-08-04
updated: 2026-08-12
---

# Plan: definición de máquina desde AMS (fase C del marco ML)

> **Nota 2026-08-10** — histórico escrito contra **VibFrame 0.1**: `proc_modes`
> lo sustituyen `mode_definitions`/`mode_bindings` y `fault_frequencies_order`
> está prohibido (catálogo único `machine.frequencies`); ver ADR-0019 y el
> workplan 12.

**Fecha**: 2026-08-04 · **Estado**: **COMPLETADO**. `PointDoc.location` y
`PointDoc.direction` salen ya poblados del export, derivados del nombre del
punto; `vdpm.0x07E` (designación de rodamiento) y `vdpm.0x164` (RPM nominal)
quedan decodificados y probados, pero **no emitidos**: el contrato no tiene
hueco para ellos hasta las fases A/B del marco.

> **Continúa en el workplan 08** (mismo día, 2026-08-04): el contrato abrió
> el hueco (`PointDoc.bearing_designations` / `nominal_speed_rpm`, workplan
> 04 de `vibsynth-contracts`) y la emisión se hizo en
> [`08-emision-de-la-definicion-de-punto.md`](08-emision-de-la-definicion-de-punto.md).
> El decode y sus golds, abajo, no cambian; el «por qué no se emite todavía»
> es el estado en que cerró este plan.
>
> **Estado operativo 2026-08-12** — Bunge está reexportado en VibFrame 0.2:
> las declaraciones crudas salen en `PointDoc` y el enriquecedor externo las
> proyecta a `machine.frequencies`. Este productor sigue sin escribir
> `definition` ni `definition_provenance`.

Ejecuta la **fase C** del plan marco *Marco de definiciones de máquina en
VibFrame para ML*
(`/mnt/c/Users/joser/work/vibsynth/docs/work-plans/08-marco-definiciones-maquina-ml.md`),
la de mejor ratio valor/esfuerzo: AMS es el único origen del ecosistema que
guarda algo aprovechable para definir la máquina, y estaba sin leer.

## Contexto

Los `machine.json` que produce `rbm export` describen bien la adquisición
(`proc_modes`, unidades, plantillas de alarma) y casi nada de la máquina:
`fault_frequencies_order` vacío, `definition` a `None`, y los cuatro campos
opcionales de cada punto —`location`, `direction`, `sensor`, `speed_source`—
hardcodeados a `None` desde que se escribió `_build_machine_doc()`. Para el
ML que viene detrás (fase E del marco) eso significa que ni se sabe qué
rodamiento mide un punto ni de qué lado del eje está.

Dos vetas, distintas en naturaleza:

1. **El nombre del punto.** AMS no tiene campos estructurados de ubicación:
   tiene un `long_name` de 32 bytes por punto, y ahí escribió el analista
   componente, lado y dirección (`MOTOR LOA HORIZONTAL`,
   `Reductor Lado Libre Peakvue`). Es texto, pero es texto con una convención
   muy estable.
2. **Dos campos binarios documentados y nunca parseados**: `vdpm.0x07E`
   (designación de rodamiento, anotado en FORMAT §5.8 como «ya no hacen falta
   para el enlace») y `vdpm.0x164` (RPM nominal, citado de pasada en
   ADR-0013).

## Parte 1 — `location` / `direction` desde el nombre del punto

`src/ams_extract/point_naming.py`; `_build_machine_doc()` los emite vía
`_build_point_doc()`.

### Vocabulario observado

Sobre los 5 203 puntos de BUNGE CARTAGENA (232 nombres distintos, volcados en
`tests/fixtures/bunge_point_names.json`):

| Evidencia en el nombre | `location` |
|---|---|
| `LA` (lado acople) | `DE` |
| `LOA` (lado opuesto acople), `LCA` (lado contrario acople) | `NDE` |
| `Lado Acople`, `Lado Motor` (lado por donde entra el accionamiento) | `DE` |
| `Lado Libre`, `Lado Op(uesto) Motor`, `Lad Op Mot`, `Lado Contrario` | `NDE` |

`HORIZONTAL` / `VERTICAL` / `AXIAL` → `H` / `V` / `A`, emparejados **por
prefijo** porque el campo de 32 bytes obliga a truncar: `Horiz`, `Vert`,
`Verti`, `Horizont`, `Horizonta` conviven con la palabra entera, y a veces
pegadas al sufijo de adquisición (`Horiz(P)`).

`LCA` ≡ `LOA` se apoya en dato, no en el diccionario: las máquinas que usan
ambas las usan sobre el mismo componente y en puntos que son variantes de
adquisición del mismo sitio (`CENTRIFUGA LOA VERTICAL` +
`CENTRIFUGA LCA VERTICAL (HF)`; `Reductor LOA Horiz` +
`Reductor LCA Horiz (P)`).

### Reglas conservadoras

- El token tiene que aparecer **literalmente**: `LA`/`LOA`/`LCA` como palabra
  suelta (`LAMINADOR` y `Salida` no son lados), la dirección como prefijo de
  una palabra.
- **Evidencia contradictoria → `None`**, nunca un ganador arbitrario. No
  ocurre en BUNGE (0 nombres ambiguos), pero la guarda está.
- Un nombre que **no declara** lado o dirección se queda a `None`: no se
  infiere la dirección de un punto PeakVue por la del punto de velocidad
  vecino, ni el lado de un `Eje Entrada` por el resto de la máquina.
- La única precedencia es que la frase NDE se comprueba antes que la DE,
  porque `Lado Op Motor` contiene `Motor`.
- El **componente** (`MOTOR`, `Reductor`, `BOMBA`, `CENTRIFUGA`…) se
  reconoce a simple vista pero **no se extrae**: el contrato no tiene campo
  donde ponerlo (es del grafo cinemático, fase A/B) y el nombre completo va
  igualmente en `PointDoc.name`.

### Cobertura medida (5 203 puntos reales)

| | puntos | % |
|---|---|---|
| `location` resuelto | **5 108** | 98,2 % |
| `direction` resuelto | **4 220** | 81,1 % |
| ambos | 4 169 | 80,1 % |
| al menos uno | 5 159 | 99,2 % |
| ninguno | 44 | 0,8 % |

Reparto: `DE` 2 734 / `NDE` 2 374; `V` 2 326, `H` 1 316, `A` 578.

Lo que queda fuera **no es un fallo de las reglas, es ausencia de dato**:

- Sin lado (95 puntos): `Campana Vertical`, `Eje Entrada Horizontal`,
  `Reductor Entrada Axial`, `1º Eje Rodam Sup Peakv 1000Hz` — nombran el eje
  o el componente, no el rodamiento.
- Sin dirección (983 puntos): los puntos cuyo nombre gasta el hueco en el
  tipo de medida — `MOTOR LOA ALTA FRECUENCIA (HF)`,
  `MOTOR LOA ALTA RESOLUCION (HR)`, `Motor Lado Acople Peakvue`,
  `Reductor Lado Motor [HF]`. AMS los toma habitualmente en la misma
  dirección que su punto de velocidad hermano, pero el dato no está escrito
  y adivinarlo es exactamente lo que estas reglas no hacen.
- 44 puntos sin ninguna de las dos (`Campana Peakvue`, `Reductor (HF)`,
  `CONSUMO INTENSIDAD (A)` — este último ni siquiera es vibración).

Esas cifras son el **techo de esta evidencia**, no un umbral que perseguir:
subirlas exige otra fuente (el grafo de la máquina, o anotación humana), no
reglas más agresivas.

### Tests

`tests/test_point_naming.py` (48 tests). El corpus real entra como fixture
committeado: los 232 nombres distintos con su recuento y el `location`/
`direction` esperado de cada uno, de modo que las reglas se prueban contra la
base entera sin necesitar la base. Un test de integración
(`RBM_TEST_FILE`) comprueba que ese inventario sigue siendo el del `.rbm`, y
`test_export_dataset.py` cubre el cableado hasta el `machine.json`.

## Parte 2 — decode de `vdpm.0x07E` y `vdpm.0x164`

`records/point.py`: `parse_vdpm_bearings()` y `parse_vdpm_nominal_rpm()`.
Layout nuevo en FORMAT §3.2.

### `0x07E` — designaciones de rodamiento

```
0x07C  1 B   = 1 en los 5 203 puntos (función desconocida)
0x07D  1 B   u8: cuántos slots están rellenos (0-7)
0x07E  7×14  designaciones cp1252 space-padded; sin usar = "INDEFINID"
0x0E0        fin del bloque
```

Verificación: el contador de `0x07D` concuerda **slot a slot** con el
centinela en los 5 203 puntos, **0 discrepancias** — es lo que descarta que
14 o 7 sean casualidad. Los valores conocidos salen: AG-100 `MOTOR LOA
HORIZONTAL` → `6204`, `6208`, los dos que FORMAT §5.8 ya citaba.

Hallazgos:

- **Es por punto, no por máquina**: el mismo motor de AG-100 declara
  `6204`/`6208` en su punto LOA y `6205`/`6208` en el LA; el de DT-0070,
  `6316` en el lado libre y `6322` en el lado acople. Encaja exactamente con
  lo que el ML necesita (BPFO *del rodamiento que ese punto mide*).
- **Cobertura**: 1 520 de 5 203 puntos (29,2 %), 149 de 342 máquinas.
- **79 designaciones distintas**, texto libre: números ISO pelados (`6204`,
  `23248`, `NU216`), con fabricante (`SKF 6308`, `FAG 22220`, `NSK 22220E`),
  con sufijo (`6205/2Z`, `22218 EKC3`, `2309EKTN9C`, `6016M/C4`) y alguna que
  no es designación (`RED`, 20 veces, en puntos de reductora). Normalizar eso
  contra un catálogo es trabajo del enriquecedor; el parser devuelve el crudo.
- `6317` —el rodamiento que el marco señalaba como ausente del catálogo de
  vibsynth-machines, allí como `SKF-6317`— aparece aquí en 45 puntos.

### `0x164` — RPM nominal

float32 LE, en **RPM** (no Hz, sin factor 2). Golds:

- PM-9101-A `MOTOR LOA HORIZONTAL` → **2 900,0**, que es exactamente el
  `RPM = 2900,0 (48,33 Hz)` de la captura de AMS con la que se cerró
  ADR-0013.
- AG-100 `MOTOR LOA HORIZONTAL` → **1 455,0** (bytes `00 e0 b5 44`), la RPM
  del punto piloto de FORMAT §5.

Hallazgos:

- La declaran **todos** los puntos (114 valores distintos, 9–3 000 RPM). No
  hay centinela de «sin definir».
- Es la velocidad del **eje del punto**, ya propagada por la reductora en el
  propio dato: DT-0070 declara 1 500 en el motor y 32, 30 y 9,6 en los ejes
  sucesivos del reductor Toaster.
- AMS prerrellena con ella la RPM de análisis de cada medida: coincide con
  `vdps.0x28` en **134 183 de los 137 270 espectros** (97,8 %). Donde
  difiere, son máquinas de velocidad variable con el analista tecleando la
  velocidad medida (p.ej. `Bomba Centrifuga PM-0CI/1`, nominal 1 800 con
  análisis entre 1 000 y 1 690).
- **Corrección a ADR-0013**: su aviso «AG-100 M1H: análisis 2920 = 2 × la
  nominal 1455» no se reproduce. Los 5 espectros de ese punto llevan 1 455
  crudo, igual que sus `vdfw`; y en los 137 270 espectros de la base no hay
  **ni un solo** caso de razón 2. La decisión de ADR-0013 (emitir el crudo de
  `vdps.0x28`, sin dividir) se sostiene igual —el gold de PM-9101-A la
  sostiene, y su nominal es también 2 900—, pero el ejemplo decae. Anotado
  con fecha en el propio ADR y corregido en FORMAT §5.1.

### Por qué no se emite todavía

El marco es explícito: la fase A (procedencia y escalones de la definición en
`vibsynth-contracts`) y la B (el enriquecedor) aterrizan juntas y **antes** de
que los productores emitan la forma nueva. Hoy `MachineDoc` no tiene dónde
poner una designación de rodamiento ni una RPM nominal por punto:
`fault_frequencies_order` son órdenes ya calculadas, y calcularlas aquí
exigiría meter un catálogo de rodamientos en este repo — justo la pieza que
la fase B tiene y este repo no. Emitir órdenes derivadas de una designación
sin declarar de dónde salen violaría además la regla de la casa («no emitir
lo no validado») y el `definition_provenance` que la fase A está diseñando
precisamente para eso.

Así que el decode queda **listo y probado, sin consumidor**: 26 tests en
`tests/test_point.py`, unitarios sobre records sintéticos con el layout real
más una clase de integración contra BUNGE con los golds de arriba.

## Estado y lo que queda para las fases A/B

Hecho aquí:

- `PointDoc.location` / `PointDoc.direction` poblados (98,2 % / 81,1 %).
- `parse_vdpm_bearings()` / `parse_vdpm_nominal_rpm()` decodificados,
  verificados y documentados en FORMAT §3.2.

Dónde aterrizará lo decodificado cuando el contrato tenga hueco:

| Dato AMS | Destino previsto | Fase |
|---|---|---|
| designación (`6204`, `SKF 6308`) | entrada del enriquecedor → `BearingDefinition` del catálogo → `fault_frequencies_order` (`BPFO_DE`, `BPFI_DE`, `BSF`, `FTF`) | B |
| RPM nominal por punto | velocidad de eje del grafo (`definition`), y base de órdenes de las frecuencias de fallo | A/B |
| procedencia de todo lo anterior | `definition_provenance` — `source: declared` para lo que AMS declara, `quality: direct` para un BPFO de catálogo, `approximate` para lo derivado del nombre del punto | A |

Cuando exista `definition_provenance`, el `location`/`direction` que este
workplan emite también debería declararse: son `approximate` por
construcción (regex sobre un nombre escrito a mano), y el mapper de la fase E
debe poder ponerles techo.

Pendiente propio de este repo, sin bloquear a nadie:

- `location` sólo distingue `DE`/`NDE`; en máquinas con varios componentes
  (motor + reductora + bomba) dos puntos distintos comparten valor. El
  componente vive hoy sólo en `PointDoc.name`; su sitio es el grafo de la
  fase A.
- Los 983 puntos sin dirección son casi todos PeakVue/HF. Si alguna vez hace
  falta, la vía honesta es cruzarlos con su punto de velocidad hermano
  (mismo componente y lado, misma máquina) y declararlo como inferencia, no
  ampliar el regex.
- `vdpm.0x7C` (constante 1) sigue sin interpretar, como el resto del
  descriptor más allá de los campos de FORMAT §3.2.

## Nota de entorno

`[tool.uv.sources]` apuntaba a `~/wslprojects/RESONINS/vibframe-viewer`, de
donde el visor se movió el 2026-07-31: `uv sync` fallaba y
`tests/test_viewer_delegation.py` con él. Corregido a
`~/wslprojects/vibframe-viewer` en commit propio antes de empezar; el
criterio (ruta absoluta porque este repo vive en el lado Windows) no cambia.
