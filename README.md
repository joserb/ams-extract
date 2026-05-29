# ams-extract

CLI tool to extract data from RBMware / AMS Machinery Manager `.rbm` databases
into modern formats (Parquet + JSON), without depending on the legacy Windows XP
VM or the original AMS software.

See [docs/PLAN.md](docs/PLAN.md) for the project plan and roadmap, and
[docs/FORMAT.md](docs/FORMAT.md) for the reverse-engineered `.rbm` format.

## Status

Working end-to-end. The walker extracts the full hierarchy (areas → equipment →
points), FFT spectra and time-domain waveforms, and a mass exporter writes the
whole database to a partitioned Parquet dataset.

- **Velocity FFT** is reconstructed in full and calibrated to **mm/s**
  (validated against AMS on 3 machines, ±5–10%).
- **Acceleration FFT** (PeakVue + high-frequency points) is calibrated to **G's**
  (validated on PeakVue and HF spectra, ±10%).
- **Waveforms** are calibrated to display units (G's), reproducing the AMS
  peak/trough values within ~0.3%.

## Commands

```bash
rbm info   FILE                              # signature, description, counts
rbm tree   FILE [--out tree.json]            # full Areas/Equipment/Points hierarchy
rbm extract FILE --point NAME [--equipment SUBSTR] \
                 --type fft|waveform|both --limit N --out DIR   # Parquet + PNG
rbm export FILE --out dataset/ [--types fft,waveform] \
                [--areas …] [--parallel N]    # full dataset (hierarchy.json +
                                              # manifest.parquet + per-equipment Parquet)
```

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
| **Total samples** | **274,478** |
| Time span | 2019-10 → 2026-03 (~7 years) |

Spectra come in several resolutions — Fmax mostly 1000 Hz (velocity + PeakVue),
2000 Hz, and 6000 Hz (high-frequency acceleration), each 1600 lines.

## Quick start

```bash
uv sync
uv run rbm --help
uv run rbm tree "path/to/database.rbm" --out tree.json
```

Load the exported dataset with any Parquet reader, e.g. Polars:

```python
import polars as pl
df = pl.scan_parquet("dataset/samples/", hive_partitioning=True)   # area as a column
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
