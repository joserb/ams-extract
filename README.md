# ams-extract

CLI tool to extract data from RBMware / AMS Machinery Manager `.rbm` databases
into modern formats (Parquet + JSON), without depending on the legacy Windows XP
VM or the original AMS software.

See [docs/workplans/01-plan-general.md](docs/workplans/01-plan-general.md) for the project plan and roadmap, and
[docs/FORMAT.md](docs/FORMAT.md) for the reverse-engineered `.rbm` format.

## Status

Working end-to-end and validated on the full reference database. The walker
extracts the complete hierarchy (areas → equipment → points), FFT spectra,
time-domain waveforms and the "Valores Globales" trend, and a mass exporter
writes the whole database to a partitioned Parquet dataset (the full 1.8 GiB
BUNGE database exports in ~19 s with `--parallel 4`, with sample counts
matching AMS exactly).

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
                [--areas …] [--parallel N]    # VibFrame (dataset.json +
                                              # machine=<asset>/... + report.html)
rbm serve  FILE.rbm | dataset/ [--host H] [--port N] [--no-browser]  # on-demand viewer
```

`sp` = FFT spectra, `wv` = waveforms, `tn` = trend readings.

`rbm report` reads the `.rbm` directly (no extraction) and writes a single
self-contained HTML file: a collapsible locations → machines tree where each
machine shows how many spectra/waveforms/trends it holds and the date span
(first → last) of each type, plus a live machine filter. `rbm export` drops the
same `report.html` into the dataset directory.

`rbm serve` opens an interactive on-demand viewer and picks its backend from
the argument:

- a **`.rbm` file** → renders straight from the database. Startup only walks
  the area → machine hierarchy (instant, even on a full database); machines,
  points and samples load lazily as you drill in, and each plot is rendered on
  the fly from the `.rbm`. No `export` needed.
- an **exported dataset directory** → reads the VibFrame tables and renders
  each plot on demand from the local Parquet.

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
import polars as pl
spectra = pl.scan_parquet("dataset/machine=*/spectra.parquet")
waves = pl.scan_parquet("dataset/machine=*/waves.parquet")
trends = pl.scan_parquet("dataset/machine=*/trends.parquet")
```

## Quality gates

```bash
uv run pytest
uv run ruff check .
uv run pyright src/
```

Integration tests run against a real `.rbm` when `RBM_TEST_FILE` points to one;
they are skipped otherwise.

## License

MIT — see [LICENSE](LICENSE).
