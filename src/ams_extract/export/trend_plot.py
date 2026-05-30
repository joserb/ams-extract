"""Render a "Valores Globales" trend to PNG via matplotlib.

``rbm extract --type trend`` emits one PNG per point so the analyst can
visually compare the overall RMS velocity series against the AMS trend
plot. The Y-axis is in calibrated display units (mm/s; the inch->mm scale
applied in :func:`ams_extract.tree.walk_trends`), the X-axis is time.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless backend; no display required
import matplotlib.pyplot as plt
import numpy as np

from ams_extract.models import Point, Trend


def render_trend_png(
    trend: Trend,
    point: Point,
    path: Path,
) -> None:
    """Plot ``trend`` as overall-vs-time and write a PNG to ``path``."""
    if trend.overall.size == 0:
        raise ValueError(
            f"cannot plot trend at record {trend.record_num}: no readings"
        )
    # matplotlib plots datetime64 as a date axis; drop tz (all UTC) so numpy
    # accepts the conversion.
    dates = np.array(
        [t.replace(tzinfo=None) for t in trend.timestamps_utc], dtype="datetime64[s]"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4))
    try:
        ax.plot(dates, trend.overall, marker="o", markersize=3, linewidth=0.8)
        ax.set_xlabel("Date")
        ax.set_ylabel(f"Overall ({trend.units})")
        ax.set_title(
            f"{point.long_name} — Valores Globales — "
            f"{len(trend.overall)} readings "
            f"({trend.timestamps_utc[0]:%Y-%m-%d} → "
            f"{trend.timestamps_utc[-1]:%Y-%m-%d})"
        )
        ax.grid(True, alpha=0.3)
        ax.set_ylim(bottom=0.0)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(path, dpi=120)
    finally:
        plt.close(fig)
