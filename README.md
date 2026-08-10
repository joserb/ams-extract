# ams-extract

CLI tool to extract data from RBMware / AMS Machinery Manager `.rbm` databases
into modern formats (Parquet + JSON), without depending on the legacy Windows XP
VM or the original AMS software.

See [docs/workplans/01-plan-general.md](docs/workplans/01-plan-general.md) for the project plan and roadmap,
[docs/FORMAT.md](docs/FORMAT.md) for the reverse-engineered `.rbm` format, and
[docs/GROUND_TRUTH.md](docs/GROUND_TRUTH.md) for **DiagGT**, the diagnosis
ground-truth interchange format this repo hosts and produces (`rbm alarms`,
`rbm informes`).

## Status

Working end-to-end and validated on the full reference database. The walker
extracts the complete hierarchy (areas → equipment → points), FFT spectra,
time-domain waveforms and the "Valores Globales" trend, and a mass exporter
writes the whole database to a partitioned Parquet dataset (the full 1.73 GiB
BUNGE database exports in ~19 s with `--parallel 4`, with sample counts
matching AMS exactly).

The exported layout is **VibFrame 0.2** (`schema_version` `0.2.0`): three
parquet tables per machine partition plus `metric_catalog.json` — the metric
descriptors are a null-free JSON catalog, not a fourth parquet — with
`mode_definitions`/`mode_bindings` in `machine.json` and the fault-frequency
catalog under `machine.frequencies`. The `ground-truth/` sidecar carries the
four normative 0.2 projections. The spec is `docs/VIBFRAME.md` (and the id
conventions, `docs/VECTORS-0.2.md`) in `vibsynth-contracts`.

- **Velocity FFT** is reconstructed in full and calibrated to **mm/s**
  (validated against AMS on 3 machines, ±5–10%).
- **Acceleration FFT** (PeakVue + high-frequency points) is calibrated to **G's**
  (validated on PeakVue and HF spectra, ±10%).
- **Waveforms** are calibrated to display units — **G's** for acceleration
  (AMS peak/trough within ~0.3%) and **mm/s** for velocity.
- **Trends** ("Valores Globales", overall RMS velocity) are decoded to **mm/s**
  (validated 47/47 against the AMS trend table for M1H AG-100), plus the named
  bands of the velocity template — Mp Wave (G's), SUBSINCRONO, DESEQUILIBRIO,
  DESALINEACION, HOLGURAS, 11-40 X RPM (mm/s) — each column validated 62/62
  against the AMS per-band PLOTDATA and exported as its own VibFrame metric.

## Commands

```bash
rbm info   FILE                              # signature, description, counts
rbm tree   FILE [--out tree.json]            # full Areas/Equipment/Points hierarchy
rbm report FILE [--out report.html] [--area SUBSTR]   # interactive HTML inventory
rbm stats  summary  FILE [--area SUBSTR]     # machines + sp/wv/tn data totals
rbm stats  machines FILE [--area SUBSTR] [--sort total|sp|wv|tn|name] [--limit N]
rbm stats  points   FILE --equipment SUBSTR [--area SUBSTR]   # per-point counts
rbm extract FILE --point NAME [--equipment SUBSTR] \
                 --type fft|waveform|trend|both --limit N --out DIR   # Parquet + PNG
rbm export FILE --out dataset/ [--types fft,waveform,trend] \
                [--areas …] [--dataset-path LEVEL]… \
                [--parallel N]                # VibFrame 0.2 (dataset.json +
                                              # machine=<asset>/{machine.json,
                                              #   metric_catalog.json, spectra,
                                              #   waves, trends} + report.html)
rbm alarms FILE [--out dataset/ground-truth] [--name STEM] \
                [--client C] [--plant P] [--consolidate] \
                [--skip-hash]                 # AMS's own alarms
                                              # as a DiagGT ground-truth document
rbm informes PDFDIR [--out DIR]               # the analyst's diagnoses,
                                              # from the inspection report PDFs
rbm informes-weights GTDIR --overlay OVERLAY.json [--out DIR]
                                              # re-weight an emitted DiagGT with
                                              # a contextual judgement overlay
rbm serve  FILE.rbm | dataset/ [--host H] [--port N] [--no-browser]  # on-demand viewer
```

`sp` = FFT spectra, `wv` = waveforms, `tn` = trend readings.

`rbm report` reads the `.rbm` directly (no extraction) and writes a single
self-contained HTML file: a collapsible locations → machines tree where each
machine shows how many spectra/waveforms/trends it holds and the date span
(first → last) of each type, plus a live machine filter. `rbm export` drops the
same `report.html` into the dataset directory.

`rbm alarms` publishes the alarm verdicts AMS itself stored per point
(`"SUBSINCRONO - 1.986 mm/Seg - C Alarm"`, FORMAT §5.9) as a DiagGT document
with `origin="system-alarm"` — one observation per alarm whose value is
confirmed against the point's `pdla` thresholds (991/991 coherent in the
reference database; 973 emitted, 18 skipped for a unit mismatch). It is
ground truth *about* the dataset, written next to it, never inside the
`machine=` partitions. `--skip-hash` leaves the `.rbm` unhashed: faster (the
sha256 of 1.73 GiB is most of the run) at the price of weaker provenance.

`rbm informes` builds the *other* DiagGT ground truth of the same spec — the
**analyst's**, with `origin="inspection-report"` — out of a directory of
inspection report PDFs: one `<report>.diaggt.json` per PDF plus the normative
VibFrame 0.2 projections of the sidecar — `observations.parquet` (complete),
`observations_consolidated.parquet` (the deduplicated selection),
`findings.parquet` and the `materialization.json` manifest — with
each diagnosis mapped to fault modes by the `GTxxx` rules. There is no CSV:
`observations.csv` and friends left the format in 0.2 and a re-materialization
deletes them. It needs the
`informes` extra (`uv sync --extra informes`, which brings `pdfplumber`) and
aborts if the anchor invariant of the page layout breaks.

`rbm informes-weights` re-weights an already emitted ground truth: it reads the
`*.diaggt.json` (not the PDFs — the geometry is untouched), applies a
judgement overlay from `overlays/` and writes a second generation with
`extraction_method="llm"`, where each observation's judgement mass is shared
out over its findings by how the analyst's text weighs them. It aborts if the
overlay does not match the documents.

`rbm export --dataset-path` writes `dataset.json:path`, the grouping levels
above the dataset ("Bunge Cartagena"), outermost first and repeatable. It is
the one field that does not come out of the `.rbm`; without the option it is
not written.

`rbm serve` opens an interactive on-demand viewer and picks its backend from
the argument:

- an **exported dataset directory** → delegates to `vibframe-viewer`, the
  ecosystem viewer shared by every VibFrame producer (installed as an editable
  dependency): hierarchy tree, timeline, spectra, waves, trends and parameter
  matrix plotted in the browser. `vibframe-viewer report
  <dataset> -o report.html` writes the static report of the same data.
- a **`.rbm` file** → renders straight from the database, this repo's own
  debugging backend. Startup only walks the area → machine hierarchy (instant,
  even on a full database); machines, points and samples load lazily as you
  drill in, and each plot is rendered on the fly from the `.rbm`. No `export`
  needed.

Either way nothing is pre-rendered, and it binds to loopback only by default.

## Reference database

Metrics from the real client database used for development and validation
(`BUNGE CARTAGENA marzo 2.0.rbm`, CSI/Emerson MT4.00 format), as extracted by
this tool:

| Metric | Value |
|---|---|
| File size | 1.73 GiB (3,628,117 records of 512 B) |
| Areas (zones) | 15 |
| Equipment (machines) | 347 |
| Measurement points | 5,203 |
| FFT spectra | 137,270 |
| &nbsp;&nbsp;— velocity (mm/s) | 85,698 |
| &nbsp;&nbsp;— acceleration / PeakVue / HF (G's) | 51,572 |
| Waveforms | 137,208 |
| **Total FFT + waveform** | **274,478** |
| Trend readings ("Valores Globales", mm/s) | 151,691 |
| Time span | 2013 → 2026 (~13 years; trends reach back furthest) |

The FFT + waveform counts above match the full `rbm export` output (default
types) exactly; trends are an opt-in type.

Spectra come in several resolutions — Fmax mostly 1000 Hz (velocity + PeakVue),
2000 Hz, and 6000 Hz (high-frequency acceleration), each 1600 lines.

## Quick start

```bash
uv sync
uv run rbm --help
uv run rbm tree "path/to/database.rbm" --out tree.json
```

Load the exported VibFrame with any Parquet reader, e.g. Polars:

```python
import json
import polars as pl
spectra = pl.scan_parquet("dataset/machine=*/spectra.parquet")
waves = pl.scan_parquet("dataset/machine=*/waves.parquet")
trends = pl.scan_parquet("dataset/machine=*/trends.parquet")

# The metric descriptors that `trends.metric_id` resolves against are NOT a
# parquet table: since VibFrame 0.2 they are `metric_catalog.json`, one
# null-free JSON document per machine partition.
catalog = json.loads(open("dataset/machine=AG-100/metric_catalog.json").read())
metrics = pl.DataFrame(catalog["metrics"])
```

## Quality gates

```bash
uv run pytest
uv run ruff check .
uv run pyright src/
```

Integration tests run against a real `.rbm` when `RBM_TEST_FILE` points to one;
they are skipped otherwise.

The export is checked against the shared VibFrame contract:
`tests/test_vibframe_conformance.py` runs `vibframe-validate` (from
`vibsynth-contracts`, a test-only dependency) over what `rbm export` writes and
round-trips the goldens of every producer. To validate a dataset by hand:

```bash
uv run vibframe-validate dataset/ --strict
```

## License

MIT — see [LICENSE](LICENSE).
