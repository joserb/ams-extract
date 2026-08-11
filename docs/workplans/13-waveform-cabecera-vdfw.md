---
status: completed
created: 2026-08-12
updated: 2026-08-12
---

# Plan: reconstruir la waveform completa desde `vdfw` + `vcfw`

## Problema

El exportador interpreta la cadena `vcfw` como el buffer completo de la
waveform. Eso omite las primeras 150 muestras, almacenadas como `int16` en
`vdfw.0xD4..0x1FF`, y publica en su lugar el zero-padding del último record
`vcfw`. Para un bloque nominal de 512 muestras, antes salían 488 valores: 362
de señal y 126 ceros; el buffer real es 150 + 362 = 512.

La interpretación anterior de ADR-0017 ("AMS no escribe las últimas 150") es
incorrecta. La estructura es análoga a la FFT: el descriptor guarda la primera
porción de datos y la cadena contiene la continuación redondeada a records
físicos completos.

## Evidencia

- Las 137.208 waveforms de Bunge tienen exactamente 150 `int16` en
  `vdfw.0xD4..0x1FF`; ninguna cabecera es enteramente cero.
- En las 137.208, la cadena `vcfw` mide
  `244 * ceil((n_samples - 150) / 244)` y todo lo posterior a
  `n_samples - 150` es cero.
- `concat(vdfw_head, vcfw)[:n_samples]` da la longitud nominal en las 137.208,
  para todos los tamaños 256..16.384.
- El orden `vdfw_head + vcfw` tiene menor salto de frontera que el inverso en
  agregado (mediana 1.232 frente a 1.841 counts) y sigue el orden físico de
  records.
- En el gold AG-100 M1H 2020-02-19 conserva Pc/Pk (+0,483/-0,510 G), pero
  corrige el RMS de 0,1575 a 0,1875 G: el gold de extremos anterior no podía
  detectar la omisión.

## Implementación

1. ✅ Decodificar `vdfw.0xD4..0x1FF` como 150 `int16` y exponer un helper
   probado.
2. ✅ Ensamblar `head + chain`, exigir al menos `n_samples` valores y truncar sólo
   el padding físico posterior al nominal.
3. ✅ Emitir `Waveform.n_samples == nominal_n_samples == len(samples)`; retirar la
   nota que describía longitudes divergentes.
4. ✅ Sustituir tests que fijaban 488/4148 por tests de 512/4096 y de orden de
   muestras.
5. ✅ Añadir ADR-0020, marcar ADR-0017 como superseded y corregir FORMAT,
   VERIFICATION, modelos y workplans históricos mediante notas, sin borrar el
   rastro de la interpretación anterior.

## Verificación

- **Unit tests**: 63/63 del parser, walker y writer afectados.
- **Gold e integración real**: 5/5 pruebas de waveform; AG-100 M1H conserva
  Pc/Pk y sale con 512 muestras.
- **Barrido estructural**: 137.208/137.208 waveforms con longitud nominal,
  padding cero eliminado y cero fallos.
- **Export real VibFrame 0.2**: 347 equipos, 311 con datos, cero fallos y
  137.208 waveforms. Auditoría de los Parquet: cero divergencias entre
  `len(data)` y `n_samples`.
- **Calidad**: Ruff limpio; Pyright 0 errores. Suite: 407 passed, 50 skipped y
  2 fallos de conformidad ajenos al cambio. El checkout editable vecino de
  `vibsynth-contracts` avanzó a unidades UN/CEFACT mientras el contrato
  vendorizado de este repo sigue pineado a `ea50b0f3e567`; por ello el
  `vibframe-validate --strict` instalado ya no puede validar este pin hasta la
  siguiente migración coordinada.
