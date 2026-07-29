# AGENTS.md — ams-extract

## Proyecto

CLI para extraer bases de datos `.rbm` de RBMware / AMS Machinery Manager
(Emerson) a formatos modernos (Parquet + JSON, layout **VibFrame**), sin
depender de la VM Windows XP ni del software AMS original. El formato `.rbm`
está ingeniería-inversa documentado en `docs/FORMAT.md`; las decisiones en
`docs/DECISIONS.md` (ADRs) y el protocolo de validación contra AMS en
`docs/VERIFICATION.md`.

## Autor

Jose RB — joserb@twave.io

## Estructura

```
ams-extract/
├── AGENTS.md              # Guía para agentes (fuente única)
├── CLAUDE.md              # Acceso directo a AGENTS.md
├── docs/
│   ├── FORMAT.md          # formato .rbm (reverse engineering, por secciones §)
│   ├── DECISIONS.md       # ADRs numerados (ADR-0001…)
│   ├── VERIFICATION.md    # protocolo y registro de validación contra AMS
│   └── workplans/         # planes de implementación (ver «Work plans»)
├── samples/               # golds de AMS (parquet/png) usados en validación
├── src/ams_extract/
│   ├── records/           # parsers de records (gicm, vdpm, pdcd, vdps, vddt, pdpa…)
│   ├── export/            # export VibFrame, report HTML, live_viewer, plots
│   ├── tree.py            # walkers de jerarquía y muestras
│   └── cli.py             # CLI `rbm` (info/tree/report/stats/extract/export/
│                          #   alarms/serve)
└── tests/                 # pytest; integración usa RBM_TEST_FILE=<ruta .rbm>
```

El visor de datasets no vive aquí: el visor del ecosistema es
**`vibframe-viewer`** (repo propio, dependencia editable). `rbm serve
<dataset>` es un wrapper fino de su CLI —
`tests/test_viewer_delegation.py` protege esa frontera— y `rbm serve
FILE.rbm` conserva el backend propio (`export/live_viewer.py`), que renderiza
del `.rbm` sin exportar y es herramienta de depuración de este repo. El visor
propio de datasets (`export/viewer.py`) se retiró el 2026-07-29 (workplan 05).

## Comandos

```bash
uv sync
uv run rbm info FILE
uv run rbm export FILE --out DIR --types fft,waveform,trend --parallel 4
uv run rbm extract FILE --point NAME [--equipment SUBSTR] --type both --out DIR
uv run rbm serve DIR            # dataset exportado → delega en vibframe-viewer
uv run rbm serve FILE.rbm       # visor propio directo del .rbm (sin exportar)
uv run vibframe-viewer report DIR -o report.html   # CLI del visor, ya instalado
uv run vibframe-validate DIR --strict   # conformidad VibFrame (CLI de contracts)
RBM_TEST_FILE="…/BUNGE CARTAGENA marzo 2.0.rbm" uv run pytest   # con integración
uv run ruff check src tests && uv run pyright src               # antes de commit
```

## Entorno y convenciones

- WSL (Ubuntu) sobre Windows; Python 3.11+; gestor **`uv`** (único), build
  `hatchling`. El repo vive en el lado Windows
  (`/mnt/c/Users/joser/work/AMS 5.2-VMware/ams-extract`), junto a la VM y
  las bases `.rbm` (`../AMS databases/`).
- **Checkout vecino**: la convención del ecosistema es clonar todos los repos
  (`vibsynth`, `vibsynth-contracts`, `vibsynth-metrics-mapper`, `t8-extract`,
  `ams-extract`, `vibframe-viewer`, `DataWaver`) bajo una misma carpeta y
  consumirlos como editable installs con rutas relativas en
  `[tool.uv.sources]`. Este repo rompe la vecindad por vivir junto a la VM:
  `vibsynth-contracts` sí es vecino (`../../vibsynth/vibsynth-contracts`),
  pero `vibframe-viewer` está en el lado WSL, así que se apunta con **ruta
  absoluta** (`/home/joserb/wslprojects/RESONINS/vibframe-viewer`) — la
  relativa cruzaría siete niveles hasta la raíz. Mismo criterio que t8-extract,
  que apunta con absoluta a los repos del lado Windows.
- **Conformidad VibFrame**: el contrato que usa el runtime está vendorizado
  (`export/vibframe_contract.py`, con el commit de origen anotado);
  `vibsynth-contracts` es dependencia **solo de tests/CI** y nunca se importa
  desde `src/`. `tests/test_vibframe_conformance.py` valida lo que escribe
  `rbm export` con `vibframe-validate` (API y CLI) y hace round-trip de los
  goldens de los tres orígenes. Las columnas requeridas de los cuatro parquet
  se declaran **non-nullable**, como en t8-extract y vibsynth (workplan 06).
- **No emitir lo no validado**: cada escala/decode nuevo exige gold de AMS
  (captura o informe PLOTDATA) registrado en `VERIFICATION.md` y su ADR en
  `DECISIONS.md`. Lo que decodifica sin gold se salta con log.
- Unidades de display: velocidad mm/s (×25.4 desde in/s), aceleración G's.
  El etiquetado canónico es post-proceso con `t8-mapper vibframe --write`
  (ADR-0011), no un paso del export.
- Commits atómicos en imperativo; `pytest` + `ruff` + `pyright src` limpios
  antes de commitear.

## Work plans

Los planes de implementación viven en `docs/workplans/`, un fichero por
plan, nombrados `NN-slug.md` donde `NN` es un contador de dos dígitos que
ordena cronológicamente (usar el siguiente número libre). Cada plan lleva
frontmatter YAML obligatorio:

    ---
    status: designed | in-progress | completed | discarded
    created: YYYY-MM-DD
    updated: YYYY-MM-DD
    ---

Ciclo de vida: un plan nace `designed`; pasa a `in-progress` al empezar a
ejecutarse; termina en `completed`, o en `discarded` si se abandona (se
conserva, no se borra ni se renombra). Mantener `status` y `updated` al día
en cada sesión que trabaje sobre un plan. Los análisis exploratorios y
contratos no son planes y siguen en `docs/` (FORMAT.md, DECISIONS.md,
VERIFICATION.md).

## Relación con el ecosistema

- **vibsynth-contracts**: define el layout VibFrame que el export produce.
  Dependencia de tests/CI: aporta los modelos (`MachineDoc`, `DatasetInfo`),
  el validador `vibframe-validate` y los goldens por origen (`ams-rbm` salió
  de aquí).
- **t8-extract**: productor hermano (backups T8).
- **vibframe-viewer** (`/home/joserb/wslprojects/RESONINS/vibframe-viewer`):
  visor portable del ecosistema (repo propio, antes subpaquete de t8-extract)
  — `vibframe-viewer serve <dataset>` sobre cualquier dataset VibFrame, sea
  de ams-extract, t8-extract, vibsynth o DataWaver. Entra aquí como
  dependencia editable y `rbm serve <dataset>` delega en él; el trabajo sobre
  el visor se hace en su repo, no aquí.
- **t8-metrics-mapper**: etiquetado canónico de las métricas exportadas
  (`t8-mapper vibframe <dataset> --write`).
