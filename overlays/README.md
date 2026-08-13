# overlays/ — conocimiento externo que se aplica sobre lo ya emitido

Ficheros de **entrada externa auditables**: lo que no sale de la base `.rbm`
ni de un PDF, sino de una lectura o una inferencia, escrito a mano (o por un
LLM) y versionado para que se revise en un diff. Cada uno se aplica sobre un
artefacto **ya emitido** —un ground truth, un dataset— y ninguno se mete en el
camino del extractor.

| fichero | qué aporta | lo aplica |
|---|---|---|
| `bunge-cartagena-2026.weights-llm.overlay.json` | el peso de cada finding dentro de su observación | `rbm informes-weights` |
| `bunge-cartagena-2026.bearings-llm.input.json` | la geometría de los rodamientos que el catálogo del ecosistema no tiene | `vibsynth-machines enrich --input` |

## 1. Overlay de pesos

Un **overlay de pesos** (`kind: "diaggt_weight_overlay"`) es un fichero de
juicio: para cada texto de diagnóstico del corpus, cuánto pesa cada uno de sus
findings dentro de la observación, y qué `unmapped` el contexto sí permite
mapear. `ams_extract.informes.overlay` lo aplica sobre los `*.diaggt.json` ya
emitidos y produce la **segunda generación** del ground truth, con
`extraction_method="llm"`.

Vive en el repo, versionado, porque **es la parte auditable**: el reparto que
sale de él no se puede reproducir ejecutando código —lo escribió un LLM
leyendo el corpus—, así que lo que se revisa en un diff es esto. El código que
lo aplica sí es determinista y tiene tests
(`tests/test_informes_overlay.py`).

## Qué guarda y qué no

**Puntuaciones, no pesos.** Cada finding lleva un valor de una escala cerrada
de seis (3 conclusión principal · 2 hallazgo relevante · 1,5 co-principal
repartido · 1 mención secundaria · 0,5 mención lateral · 0,25 residuo sin
juicio). El aplicador normaliza y cuantiza a 10⁻⁶ por el resto mayor, así que
la suma es exactamente 1 por construcción y no por confiar en unos decimales
escritos a mano. **Puntuaciones iguales reproducen el `1/n` determinista**: si
la lectura contextual coincide con la línea base, el overlay lo dice sin
inventarse una diferencia.

Cada juicio lleva su `rationale` en una línea y cada re-mapeo su `why`. Sin
eso el fichero no es auditable, sólo es un montón de números.

### Ficheros

| fichero | corpus | juicios |
|---|---|---|
| `bunge-cartagena-2026.weights-llm.overlay.json` | 6 informes Preditec de BUNGE Cartagena 2026 (`inspection-report`) | 133 textos, 415 observaciones, 0 re-mapeos |

### Uso

```bash
uv run rbm informes-weights <ground-truth-dir> \
    --overlay overlays/bunge-cartagena-2026.weights-llm.overlay.json \
    [--out <dir>]
```

Diseño y auditoría: `docs/workplans/10-pesos-contextuales-llm.md` (v0.1.0),
`docs/workplans/11-motor-calibrado-gt-corregido.md` (adenda v0.1.1) y
`docs/workplans/16-informes-diaggt-completo.md` (adenda v0.1.2). La última
retira los cinco remapeos que ya cubren `GT004v2`/`GT026`–`GT029` y dos
juicios de estado que ahora producen correctamente `findings=[]`.

## 2. Entrada de rodamientos inferidos

`bunge-cartagena-2026.bearings-llm.input.json` es un fichero `--input` del
enriquecedor del ecosistema (`vibsynth-machines enrich`, workplan 10 del
monorepo `vibsynth`): una extensión de catálogo, indexada por la designación
normalizada, con la **geometría** de rodamientos estándar que ese catálogo no
trae. AMS declara la designación verbatim y nada más (`vdpm.0x07E`, workplan
07), y este repo no la resuelve —declara, no resuelve—, así que la geometría
entra por aquí: fuera del código, versionada y revisable.

**Qué es cada entrada.** Nivel 2 de `BearingDefinition`: número de elementos,
diámetro de bola, diámetro primitivo y ángulo de contacto. Se prefiere a
escribir los cuatro factores a mano (nivel 3) porque la geometría se puede
contrastar con cualquier catálogo —un 6316 es 80×170 mm en todos— y porque así
los órdenes salen de las mismas fórmulas que los del catálogo del enriquecedor.
Los campos con guion bajo (`_designations`, `_bore_od_mm`, `_provenance`,
`_basis`, `_orders`) son la auditoría: el enriquecedor los ignora.

**De dónde sale la geometría.** De la inferencia de un LLM
(`_provenance: "llm-inference"`), no de una medida ni de una tabla del
fabricante: por eso `_basis` dice de cada entrada en qué se apoya —las
dimensiones ISO de la talla, el número de elementos de la serie y la regla
`d_ball = 0,3175·(D−d)`, que reproduce exactamente las entradas 6208–6212 y
6307–6312 del catálogo del enriquecedor—, y por eso lo que se enriquece con
ella **nunca es `direct`**.

**Reglas de honestidad**, que son la mitad del fichero:

- Sólo designaciones estándar cuya geometría se conoce con confianza. Lo que
  no —rodillos a rótula (`23248`, `22220`), cilíndricos (`NU216`), las series
  que el catálogo no cubre (`6411`, `60xx`) y lo que ni siquiera es una
  designación (`RED`)— se queda fuera y se lista en el workplan 11 con el
  motivo. Un número plausible pero inventado es peor que la ausencia: el
  consumidor no puede distinguirlo de uno bueno.
- Cada entrada pasa un **sanity check aritmético** antes de entrar:
  `BPFO + BPFI = Z` exacto, `FTF < 0,5`, `BSF` entre 1 y `Z/2`.

Diseño y números: `docs/workplans/11-motor-calibrado-gt-corregido.md`.

Estado desplegado (2026-08-12): tras el reexport VibFrame 0.2 y una nueva
pasada del enriquecedor, Bunge contiene **3.728 entradas** en
`machine.frequencies`, repartidas entre **91 máquinas**. Permanecen **56
designaciones** sin resolver; el extractor conserva siempre el texto AMS
verbatim para que el enriquecimiento pueda repetirse.
