---
status: completed
created: 2026-07-09
updated: 2026-08-05
---

# Plan: sustituir `rbm export` por VibDataset

> **Nota 2026-08-10** — histórico escrito contra **VibFrame 0.1**: lo que aquí
> se llama `metrics.parquet` es hoy `metric_catalog.json`; ver ADR-0019 y el
> workplan 12.

**Fecha**: 2026-07-09 · **Estado**: completado (histórico) — ejecutado en
`cf4b240`; el formato se llama ahora **VibFrame** y su conformidad continúa
en `03-vibframe-conformidad.md`.

## Resumen

`rbm export` pasará a escribir el formato VibDataset importado
conceptualmente de `vibsynth-contracts`, sin depender del paquete en runtime.
El formato legacy (`manifest.parquet` + `samples/`) queda obsoleto. Las
herramientas de visualización del repo deben seguir funcionando sobre el nuevo
layout.

## Cambios clave

- Añadir en `ams-extract` un contrato local mínimo con `SCHEMA_VERSION`,
  nombres de archivos y columnas copiadas de `vibsynth-contracts.dataset`.
- Reemplazar el exportador actual:
  - `rbm export` limpia siempre `--out` antes de escribir.
  - Se añaden guardas para no borrar `/`, home, cwd del repo, `.git`, ni rutas
    sospechosas.
  - La salida raíz conserva `report.html` como extra útil.
- Escribir una carpeta por asset:
  - `machine=<equipment.short_code>/`
  - `MachineInfo.id = equipment.short_code`
  - `MachineInfo.name = equipment.long_name`
  - `MachineInfo.path = [area.long_name, equipment.long_name]`
- Escribir por asset:
  - `machine.json`
  - `metrics.parquet`
  - `trends.parquet`
  - `spectra.parquet`
  - `waves.parquet`
- Actualizar `rbm serve dataset/` para leer VibDataset en vez de
  `manifest.parquet`.

## Mapeos iniciales

- `unit == "mm/s"` -> `signal_family="velocity"`.
- `unit == "G's"` -> `signal_family="acceleration"`.
- FFT `proc_mode_id`: `VEL_<fmax>` o `ACC_<fmax>`.
- Waveform `proc_mode_id`: `WAVE_VEL_<sample_rate>` o
  `WAVE_ACC_<sample_rate>`.
- Waveform `speed_hz = rpm / 60` cuando `rpm > 0`.
- FFT `speed_hz = null` hasta localizar RPM fiable en AMS.
- Tendencia validada:
  - `metric_id="overall_velocity_rms__<point_id>"`
  - `name="overall_velocity_rms"`
  - `statistic="spectrum_rms"`
  - `signal_family="velocity"`
  - `detector="rms"`
  - `unit="mm/s"`.

## Gaps AMS a documentar

- Dirección/localización de punto desde nombres o campos `vdpm`.
- Sensores: tipo, sensibilidad, rango, montaje.
- Modos reales: ventana, promedios, overlap, detector, power, demodulación.
- RPM en FFT y contexto operativo por snapshot.
- Configuración `pdpa`: bandas, alarmas, umbrales y parámetros por punto.
- Short codes nativos de equipos en continuación `gicm`.
- Tendencias por banda y tendencias de aceleración.
- Estados de máquina/carga como métricas reservadas `speed`, `load`, `state`.

## Tests

- Unit tests de schemas locales y escritura PyArrow.
- Tests de guardas de borrado de `--out`.
- Tests de `rbm export` con fixture sintético: `dataset.json`, `report.html`,
  carpetas `machine=*`.
- Tests de lectura viewer sobre VibDataset mínimo.
- Integración con `RBM_TEST_FILE`: exportar `DEPURADORA`, validar que M1H
  conserva 5 FFT, 5 waveform y 62 tendencias con valores gold.
- Actualizar docs/README/PLAN para declarar obsoleto el formato anterior.
