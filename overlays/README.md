# overlays/ — juicios de peso sobre un ground truth ya emitido

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

## Ficheros

| fichero | corpus | juicios |
|---|---|---|
| `bunge-cartagena-2026.weights-llm.overlay.json` | 6 informes Preditec de BUNGE Cartagena 2026 (`inspection-report`) | 135 textos, 422 observaciones, 6 re-mapeos |

## Uso

```bash
uv run rbm informes-weights <ground-truth-dir> \
    --overlay overlays/bunge-cartagena-2026.weights-llm.overlay.json \
    [--out <dir>]
```

Diseño y auditoría: `docs/workplans/10-pesos-contextuales-llm.md`.
