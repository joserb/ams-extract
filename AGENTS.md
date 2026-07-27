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
│   ├── export/            # export VibFrame, report HTML, viewer, plots
│   ├── tree.py            # walkers de jerarquía y muestras
│   └── cli.py             # CLI `rbm` (info/tree/report/stats/extract/export/serve)
└── tests/                 # pytest; integración usa RBM_TEST_FILE=<ruta .rbm>
```

## Comandos

```bash
uv sync
uv run rbm info FILE
uv run rbm export FILE --out DIR --types fft,waveform,trend --parallel 4
uv run rbm extract FILE --point NAME [--equipment SUBSTR] --type both --out DIR
RBM_TEST_FILE="…/BUNGE CARTAGENA marzo 2.0.rbm" uv run pytest   # con integración
uv run ruff check src tests && uv run pyright src               # antes de commit
```

## Entorno y convenciones

- WSL (Ubuntu) sobre Windows; Python 3.11+; gestor **`uv`** (único), build
  `hatchling`. El repo vive en el lado Windows
  (`/mnt/c/Users/joser/work/AMS 5.2-VMware/ams-extract`), junto a la VM y
  las bases `.rbm` (`../AMS databases/`).
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

- **vibsynth-contracts**: define el layout VibFrame que el export produce
  (contrato opcional en tests: `MachineDoc`).
- **t8-extract**: productor hermano (backups T8).
- **vibframe-viewer**: visor portable del ecosistema (repo propio, antes
  subpaquete de t8-extract) — `vibframe-viewer serve <dataset>` sobre
  cualquier dataset exportado.
- **t8-metrics-mapper**: etiquetado canónico de las métricas exportadas
  (`t8-mapper vibframe <dataset> --write`).
