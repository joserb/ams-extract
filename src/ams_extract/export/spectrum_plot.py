"""Render an FFT spectrum to PNG via matplotlib.

Emits one PNG per extracted spectrum so the analyst can visually compare
against AMS. The spectrum is the full, calibrated buffer (low band + vcps
chain, scaled to mm/s for velocity); the Y-axis is in ``spectrum.units``
(FORMAT §5.6).
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

import matplotlib

matplotlib.use("Agg")  # headless backend; no display required
import matplotlib.pyplot as plt
import numpy as np

from ams_extract.export._plot_io import save_png
from ams_extract.models import Point, Spectrum


def render_spectrum_png(
    spectrum: Spectrum,
    point: Point,
    path: Path | BinaryIO,
) -> None:
    """Plot ``spectrum`` as amplitude-vs-frequency and write a PNG.

    ``path`` may be a filesystem path or a binary file-like object (e.g. an
    in-memory ``BytesIO``), which lets ``rbm serve`` render plots on demand
    without touching disk.
    """
    amplitude = spectrum.amplitude
    if amplitude.size == 0:
        raise ValueError(
            f"cannot plot spectrum at record {spectrum.record_num}: empty amplitude"
        )
    # Frequency axis: bin i -> i * fmax / n_lines (bin width is fmax/n_lines).
    bin_width = spectrum.fmax_hz / spectrum.n_lines if spectrum.n_lines else 0.0
    freq = (np.arange(amplitude.size, dtype=np.float32) * bin_width).astype(np.float32)

    fig, ax = plt.subplots(figsize=(10, 4))
    try:
        ax.plot(freq, amplitude, linewidth=0.6)
        ax.set_xlabel(f"Frequency (Hz) — Fmax={spectrum.fmax_hz:.0f}")
        ax.set_ylabel(f"Amplitude ({spectrum.units})")
        ax.set_title(
            f"{point.long_name} — {spectrum.timestamp_utc.isoformat()} — "
            f"n_lines={spectrum.n_lines}, CARGA={spectrum.carga_pct:.0f}%"
        )
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, spectrum.fmax_hz)
        fig.tight_layout()
        save_png(fig, path)
    finally:
        plt.close(fig)
