"""Render a time-domain waveform to PNG via matplotlib.

Sub-fase 5b emits one PNG per extracted waveform so the analyst can
visually compare against AMS. The Y-axis is in calibrated display units
(``vdfw.0x28`` scale applied in :func:`ams_extract.tree.walk_waveforms`),
so peak values match AMS directly — unlike the FFT, whose amplitude
calibration is still open (FORMAT §5.6).
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
from ams_extract.models import Point, Waveform


def render_waveform_png(
    waveform: Waveform,
    point: Point,
    path: Path | BinaryIO,
) -> None:
    """Plot ``waveform`` as amplitude-vs-time and write a PNG.

    ``path`` may be a filesystem path or a binary file-like object (see
    :func:`ams_extract.export._plot_io.save_png`).
    """
    samples = waveform.samples
    if samples.size == 0:
        raise ValueError(
            f"cannot plot waveform at record {waveform.record_num}: empty samples"
        )
    # Time axis from 0 spanning the actual sample count at the sample rate.
    if waveform.sample_rate_hz > 0.0:
        duration = samples.size / waveform.sample_rate_hz
    else:
        duration = float(samples.size)
    time_s = np.linspace(0.0, duration, num=samples.size, endpoint=False, dtype=np.float32)

    fig, ax = plt.subplots(figsize=(10, 4))
    try:
        ax.plot(time_s, samples, linewidth=0.6)
        ax.set_xlabel(f"Time (s) — sample_rate={waveform.sample_rate_hz:.0f} Hz")
        ax.set_ylabel(f"Amplitude ({waveform.units})")
        ax.set_title(
            f"{point.long_name} — {waveform.timestamp_utc.isoformat()} — "
            f"n_samples={waveform.n_samples}, RPM={waveform.rpm:.0f}, "
            f"CARGA={waveform.carga_pct:.0f}%"
        )
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, duration)
        fig.tight_layout()
        save_png(fig, path)
    finally:
        plt.close(fig)
