---
status: completed
created: 2026-07-29
updated: 2026-08-05
---

# Plan: convergencia de visores — `rbm serve <dataset>` delega en `vibframe-viewer`

> **Nota (2026-08-05)**: las rutas `~/wslprojects/RESONINS/vibframe-viewer` de
> este documento son las de entonces: el visor **se movió a
> `~/wslprojects/vibframe-viewer` el 2026-07-31**, fuera ya de RESONINS, y
> `t8-extract` salió detrás el 2026-08-08 a `~/wslprojects/t8-extract`. En
> RESONINS sólo quedan los datos (`DATA/`, `datasets/`, `informes/`).
> `[tool.uv.sources]` apunta hoy a
> `/home/joserb/wslprojects/vibframe-viewer`; el criterio —ruta **absoluta**,
> porque este repo vive en el lado Windows— no cambia. Lo cuenta la «Nota de
> entorno» del [workplan 07](07-definicion-de-maquina-desde-ams.md), que fue
> donde se arregló el `pyproject.toml`.

**Fecha**: 2026-07-29 · **Estado**: **COMPLETADO**. `rbm serve` sobre un
dataset exportado delega en el visor del ecosistema (`vibframe-viewer`,
dependencia editable por ruta absoluta); el visor propio de datasets
(`export/viewer.py`, 559 líneas, + `tests/test_viewer.py`) se retiró; el
backend directo del `.rbm` (`export/live_viewer.py`) se conserva como
herramienta de depuración del repo. Verificado sobre
`~/wslprojects/RESONINS/datasets/bunge_cartagena_ams` (347 máquinas).

Ejecuta la **Parte 4** (y el paso 4 de la Parte 1 + la Parte 5, en lo que toca
a este repo) del workplan 03 de t8-extract
(`~/wslprojects/t8-extract/docs/workplans/03-unificacion-repos-extraccion.md`)
— el visor
`vibframe_viewer` dejó de ser subpaquete de t8-extract el 2026-07-27 y vive en
el repo `vibframe-viewer`.

## Contexto

Este repo mantenía **dos** visores propios sobre `rbm serve`, elegidos según
el argumento:

- `export/viewer.py` — dataset VibFrame exportado: índice en memoria de las
  tablas Parquet y render PNG bajo demanda con los renderers matplotlib;
- `export/live_viewer.py` — el `.rbm` directo, sin exportar: jerarquía en el
  arranque y muestras/PNG perezosos desde la base memory-mapped.

El primero duplicaba —peor: PNG estáticos frente a Plotly, sin timeline ni
matriz de parámetros— lo que `vibframe-viewer` ya hace para cualquier
productor VibFrame. El segundo no tiene equivalente: lee el formato de origen,
que solo entiende este repo.

## Hecho

1. **Dependencia**. `vibframe-viewer` entra en `[project.dependencies]` con
   `[tool.uv.sources]` `{ path = "/home/joserb/wslprojects/RESONINS/vibframe-viewer",
   editable = true }`.

   *Ruta absoluta, a propósito*: la convención del ecosistema es checkout
   vecino con rutas relativas, pero este repo vive en el lado Windows junto a
   la VM y las bases `.rbm` (`/mnt/c/Users/joser/work/AMS 5.2-VMware/`),
   mientras que `vibframe-viewer` (vecino de t8-extract) está en el lado WSL
   (`~/wslprojects/RESONINS/`). No hay vecindad real: la relativa sería
   `../../../../../../../home/joserb/…`, siete niveles hasta la raíz. Se usa
   la absoluta, con el mismo criterio que t8-extract, que ya apunta con rutas
   absolutas `/mnt/c/...` a `vibsynth-contracts` y `vibsynth-metrics-mapper`.
   `vibsynth-contracts` sí es vecino desde aquí y sigue relativo
   (`../../vibsynth/vibsynth-contracts`). Documentado en `AGENTS.md` y en un
   comentario del `pyproject.toml`.

2. **Delegación**. `rbm serve DIR` construye el `argv` del visor y llama a
   `vibframe_viewer.cli.main` (API pública: `pyright --strict` rechaza importar
   su `_cmd_serve`, que es lo que hace t8-extract); el bucle de servicio, el
   navegador y el Ctrl-C son del visor, y su código de salida se propaga.
   `rbm serve FILE.rbm` no cambia.

3. **Código muerto retirado**: `src/ams_extract/export/viewer.py` y
   `tests/test_viewer.py`. Nada más lo importaba. Se conservan:
   - `export/live_viewer.py` y sus tests — sin equivalente en el visor común;
   - los renderers matplotlib (`spectrum_plot`, `trend_plot`, `waveform_plot`,
     `_plot_io`) — los usa `rbm extract` para los PNG y el `live_viewer`;
   - `export/html_report.py` — es el inventario del `.rbm` (`rbm report`), no
     un visor de datasets.

4. **Tests**: `tests/test_viewer_delegation.py` sustituye a `test_viewer.py` y
   protege la frontera — que el paquete esté instalado, que las opciones de
   `rbm serve` lleguen traducidas al CLI del visor, que el código de salida se
   propague, y que un dataset con la forma que escribe `rbm export` sea legible
   de punta a punta por el visor (servidor real, `/` y `/api/tree`). La
   cobertura del visor en sí vive en su repo.

5. **Documentación**: `AGENTS.md` (visor del ecosistema, convención de checkout
   vecino y por qué aquí se rompe, comandos) y `README.md` (`rbm serve` con sus
   dos backends). La convención `docs/workplans/NN-slug.md` con frontmatter
   `status`/`created`/`updated` ya estaba adoptada en este repo.

## Verificación

- `uv run pytest`: 233 passed, 40 skipped (antes 238/40: −9 de `test_viewer.py`,
  +4 de `test_viewer_delegation.py`). `ruff check src tests` y
  `pyright src` (strict) limpios.
- Smoke real: `uv run rbm serve ~/wslprojects/RESONINS/datasets/bunge_cartagena_ams
  --port 8731 --no-browser` → índice HTTP 200, `/api/tree` con 347 máquinas bajo
  «Bunge Cartagena» (`origin: ams-rbm`, `generator: ams-extract`) y
  `/api/totals` = 137.270 espectros / 137.208 ondas / 1.571.433 puntos de
  tendencia.

## Flecos

- El empaquetado `.vibframe.zip` (Parte 3 del workplan 03) tocaría a `rbm
  export --zip`; fuera de alcance aquí.
- `rbm report` sigue siendo propio y no tiene equivalente en el visor: es el
  inventario del `.rbm` sin exportar. Si algún día `vibframe-viewer report`
  cubre el caso «antes de exportar», habría que revisarlo.
