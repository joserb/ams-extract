---
status: completed
created: 2026-08-12
updated: 2026-08-13
---

# Plan: revisión documental integral

## Objetivo

Revisar toda la documentación viva de `ams-extract` después de cerrar la
migración a VibFrame 0.2, la adopción de Common Codes UN/CEFACT y el reexport
del corpus RESONINS. El resultado debe distinguir con claridad el estado
vigente de los registros históricos, eliminar contradicciones y dejar las
deudas asignadas al repositorio que realmente las posee.

## Alcance

- [x] Inventariar los documentos raíz, especificaciones, ADRs, protocolo de
  verificación, guías de overlays, fixtures y todos los workplans.
- [x] Contrastar comandos, rutas, versiones, cifras y estados contra `master`,
  el contrato VibFrame vigente y los datasets desplegados en RESONINS.
- [x] Corregir afirmaciones obsoletas sin reescribir el registro histórico:
  las fotos antiguas se conservan, pero se rotulan como superadas cuando
  corresponda.
- [x] Separar las deudas propias de `ams-extract` de las que pertenecen a
  `vibsynth`, `t8-extract`, `vibsynth-metrics-mapper` o
  `vibsynth-machines`.
- [x] Comprobar enlaces y rutas locales, referencias a símbolos/comandos,
  estados de workplans y ausencia de residuos del layout VibFrame 0.1
  presentados como vigentes.
- [x] Ejecutar la suite, `ruff`, `pyright` y los checks documentales
  reproducibles; registrar el resultado y cerrar el plan.

## Criterios de aceptación

1. `README.md`, `AGENTS.md` y los documentos normativos describen el mismo
   estado operativo del productor AMS.
2. `VERIFICATION.md` presenta el reexport Bunge 0.2 como completado y explica
   con precisión los avisos que impiden el modo estricto.
3. Los workplans históricos mantienen sus decisiones originales, con notas
   posteriores explícitas allí donde una limitación quedó resuelta.
4. El corpus RESONINS se describe con su auditoría real: 32 datasets 0.2,
   30 conformes al validador actual y dos demos de `vibsynth` aún con labels
   de unidad legacy; Bunge y los 29 datasets T8 usan Common Codes.
5. No quedan enlaces Markdown internos rotos ni referencias vigentes a
   módulos retirados, rutas antiguas o artefactos 0.1.

## Resultado

- Revisados los **24 documentos Markdown** del repo, incluido el acceso
  `CLAUDE.md`, las especificaciones, los 15 workplans, overlays y fixtures.
- El estado vivo converge en VibFrame 0.2, contrato vendorizado
  `99a44bffc879` y Common Codes `C16`/`K40`/`HTZ`/`P1`. Las menciones 0.1 que
  sobreviven están rotuladas como historial o sustituidas por un ADR posterior.
- La auditoría RESONINS queda registrada: 32 raíces 0.2; Bunge y 29 T8 sin
  errores; dos demos de `vibsynth` pendientes de regenerar por unidades legacy.
- `docs/GROUND_TRUTH.md` se mejoró editorialmente. El 2026-08-13 se
  resincronizaron byte a byte las dos copias externas de cortesía
  `FORMATO_GROUND_TRUTH.md`: la de los informes y la desplegada dentro del
  dataset Bunge de RESONINS.
- Verificación final: **0 enlaces internos rotos**, `git diff --check` limpio,
  **411 passed / 50 skipped**, Ruff limpio y Pyright con **0 errores**.
