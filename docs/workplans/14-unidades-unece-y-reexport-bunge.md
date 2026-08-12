---
status: completed
created: 2026-08-12
updated: 2026-08-12
---

# Plan: unidades UNECE y reexport enriquecido de Bunge

## Objetivo

Adoptar la identidad de unidad vigente de VibFrame 0.2 —el UN/CEFACT
Recommendation 20 Common Code en `unit`, dejando `mm/s`, `g`, `Hz` y `%`
como etiquetas de presentación— y regenerar el dataset Bunge con la
reconstrucción completa de waveforms de ADR-0020.

## Contrato

La correspondencia que declara `vibsynth-contracts/units.py` es:

| Magnitud | Label | Common Code |
|---|---|---|
| velocidad de vibración | `mm/s` | `C16` |
| aceleración | `g` | `K40` |
| frecuencia | `Hz` | `HTZ` |
| porcentaje | `%` | `P1` |

El layout sigue en `SCHEMA_VERSION = "0.2.0"`. Se re-vendoriza el
subconjunto local desde el checkout coordinado de `vibsynth-contracts`
(HEAD `782fac98cdb9` más su implementación local de unidades; sello compuesto
de las fuentes copiadas `99a44bffc879`).

## Implementación

- [x] Incorporar al contrato vendorizado los cuatro Common Codes que usa AMS.
- [x] Convertir las unidades sólo en la frontera VibFrame; el modelo del parser
   conserva las labels AMS/display para decidir familia y calibración.
- [x] Actualizar tests y documentación que afirmaban que `unit`
   transporta labels.
- [x] Validar el export sintético con la API y CLI actuales de
   `vibframe-validate`.

## Despliegue Bunge

- [x] Respaldar `dataset.json`, `ground-truth/` y `analysis/` del dataset
   desplegado.
- [x] Reexportar la base completa con FFT, waveform y trend, conservando los
   sidecars y `dataset.json:path = ["Bunge Cartagena"]`.
- [x] Ejecutar `t8-mapper vibframe --write` para rematerializar el etiquetado
   canónico contra los Common Codes.
- [x] Ejecutar `vibsynth-machines enrich --write` para poblar
   `machine.frequencies` desde las designaciones de rodamiento declaradas.
- [x] Pasar `vibframe-validate` y auditar conteos, longitudes de onda,
   cobertura canónica y frecuencias enriquecidas.

## Resultado

El 2026-08-12 se completó la migración y el despliegue:

- suite: 411 tests unitarios y 25 de integración real en verde; `ruff` y
  `pyright` limpios;
- export: 347 máquinas, 137.270 espectros, 137.208 ondas y 1.571.433 filas de
  tendencia; cero fallos y cero ondas con `len(data) != n_samples`;
- unidades: sólo `C16`/`K40` en las tablas de señal y
  `C16`/`K40`/`HTZ`/`P1` en los 24.684 descriptores;
- mapper: 23.590 métricas etiquetadas (95,6 %), 1.094 huecos de catálogo y
  cero diferencias en la segunda ejecución;
- enrich: definición en 347 máquinas y 3.728 frecuencias en 91 máquinas;
  segunda ejecución con cero cambios y 56 designaciones no resueltas;
- los 24 ficheros de `ground-truth/` y `analysis/` se conservaron byte a byte
  y `dataset.json:path` sigue siendo `["Bunge Cartagena"]`.

El validador termina con **0 errores**. `--strict` continúa fallando por 730
avisos de procedencia, no de layout: 588 `analysis.stale-input` porque las dos
capas preservadas declaran los hashes de la emisión anterior, y 142
`definition.undocumented-node-type` generados por los tipos de nodo que usa el
enriquecedor actual. Regenerar las capas de análisis y normalizar ese catálogo
de tipos son trabajos externos a esta migración; no se reescribieron sus
metadatos para ocultar la obsolescencia.
