"""Render an FFT spectrum to PNG via matplotlib.

Sub-fase 3b emits one PNG per extracted spectrum so the analyst can
visually compare against AMS. The Y-axis stays in raw vcps units for
now — amplitude scaling/conversion to mm/s is deferred per the open
question in FORMAT §5.5.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless backend; no display required
import matplotlib.pyplot as plt
import numpy as np

from ams_extract.models import Point, Spectrum


def render_spectrum_png(
    spectrum: Spectrum,
    point: Point,
    path: Path,
) -> None:
    """Plot ``spectrum`` as amplitude-vs-frequency and write a PNG to ``path``."""
    amplitude = spectrum.amplitude
    if amplitude.size == 0:
        raise ValueError(
            f"cannot plot spectrum at record {spectrum.record_num}: empty amplitude"
        )
    # Linear frequency axis from 0 to fmax across the actual array length.
    freq = np.linspace(0.0, spectrum.fmax_hz, num=amplitude.size, dtype=np.float32)

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4))
    try:
        ax.plot(freq, amplitude, linewidth=0.6)
        ax.set_xlabel(f"Frequency (Hz) — Fmax={spectrum.fmax_hz:.0f}")
        ax.set_ylabel(f"Amplitude (raw, units={spectrum.units!r})")
        ax.set_title(
            f"{point.long_name} — {spectrum.timestamp_utc.isoformat()} — "
            f"n_lines={spectrum.n_lines}, CARGA={spectrum.carga_pct:.0f}%"
        )
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, spectrum.fmax_hz)
        fig.tight_layout()
        fig.savefig(path, dpi=120)
    finally:
        plt.close(fig)
