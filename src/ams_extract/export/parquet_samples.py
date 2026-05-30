"""Per-equipment Parquet export.

Sub-fase 3b/5b emitted ONE parquet file per sample (used by ``rbm
extract``). Fase 6 (``rbm export``) writes ONE parquet file per equipment
*and per sample type*, with one row per sample — see PLAN.md §3.5 and the
"separate files per type" decision. The single-sample writers are kept as
thin wrappers over the batch writers so ``extract`` and ``export`` share
exactly one schema definition.

Every row carries a deterministic ``sample_id`` (see :func:`sample_id`) so
the per-equipment file can be joined back to ``manifest.parquet``.
"""

# pyright: reportUnknownMemberType=false

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ams_extract.models import Point, Spectrum, Trend, Waveform


def sample_id(
    point_record_num: int,
    sample_record_num: int,
    sample_type: str,
    discriminator: str = "",
) -> str:
    """Return a deterministic, stable id for a single sample.

    The id is a 16-hex-char SHA-1 prefix over
    ``"<point_record_num>:<sample_record_num>:<sample_type>"`` (plus an
    optional ``":<discriminator>"`` suffix). Determinism lets the
    per-equipment Parquet and ``manifest.parquet`` reference the same sample
    across runs without coordination. The discriminator distinguishes rows
    that share a source record — e.g. the individual readings of one trend
    (``vddt``), which all carry the same ``record_num``.
    """
    raw = f"{point_record_num}:{sample_record_num}:{sample_type}"
    if discriminator:
        raw = f"{raw}:{discriminator}"
    return hashlib.sha1(raw.encode("ascii")).hexdigest()[:16]


def write_spectra_parquet(
    items: Sequence[tuple[Spectrum, Point]],
    path: Path,
) -> None:
    """Serialize a batch of ``(spectrum, point)`` pairs to one Parquet file.

    One row per spectrum. Metadata columns + ``amplitude`` as a
    ``list<float32>``. Frequency bins are derivable from ``fmax_hz`` and the
    amplitude length, so they are not stored. Writing an empty ``items``
    still produces a valid zero-row file with the canonical schema.
    """
    table = pa.table(
        {
            "sample_id": pa.array(
                [sample_id(s.point_record_num, s.record_num, "FFT") for s, _ in items],
                type=pa.string(),
            ),
            "point_record_num": pa.array(
                [s.point_record_num for s, _ in items], type=pa.int64()
            ),
            "point_long_name": pa.array(
                [p.long_name for _, p in items], type=pa.string()
            ),
            "point_short_code": pa.array(
                [p.short_code for _, p in items], type=pa.string()
            ),
            "spectrum_record_num": pa.array(
                [s.record_num for s, _ in items], type=pa.int64()
            ),
            "timestamp_utc": pa.array(
                [s.timestamp_utc for s, _ in items], type=pa.timestamp("us", tz="UTC")
            ),
            "sample_type": pa.array(["FFT"] * len(items), type=pa.string()),
            "fmax_hz": pa.array([s.fmax_hz for s, _ in items], type=pa.float32()),
            "n_lines": pa.array([s.n_lines for s, _ in items], type=pa.int32()),
            "units": pa.array([s.units for s, _ in items], type=pa.string()),
            "carga_pct": pa.array([s.carga_pct for s, _ in items], type=pa.float32()),
            "amplitude": pa.array(
                [s.amplitude.tolist() for s, _ in items], type=pa.list_(pa.float32())
            ),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def write_waveforms_parquet(
    items: Sequence[tuple[Waveform, Point]],
    path: Path,
) -> None:
    """Serialize a batch of ``(waveform, point)`` pairs to one Parquet file.

    One row per waveform. Metadata columns + ``samples`` as a
    ``list<float32>``. The time axis is derivable from ``sample_rate_hz``
    and the samples length, so it is not stored. Writing an empty ``items``
    still produces a valid zero-row file with the canonical schema.
    """
    table = pa.table(
        {
            "sample_id": pa.array(
                [
                    sample_id(w.point_record_num, w.record_num, "WAVEFORM")
                    for w, _ in items
                ],
                type=pa.string(),
            ),
            "point_record_num": pa.array(
                [w.point_record_num for w, _ in items], type=pa.int64()
            ),
            "point_long_name": pa.array(
                [p.long_name for _, p in items], type=pa.string()
            ),
            "point_short_code": pa.array(
                [p.short_code for _, p in items], type=pa.string()
            ),
            "waveform_record_num": pa.array(
                [w.record_num for w, _ in items], type=pa.int64()
            ),
            "timestamp_utc": pa.array(
                [w.timestamp_utc for w, _ in items], type=pa.timestamp("us", tz="UTC")
            ),
            "sample_type": pa.array(["WAVEFORM"] * len(items), type=pa.string()),
            "sample_rate_hz": pa.array(
                [w.sample_rate_hz for w, _ in items], type=pa.float32()
            ),
            "n_samples": pa.array([w.n_samples for w, _ in items], type=pa.int32()),
            "rpm": pa.array([w.rpm for w, _ in items], type=pa.float32()),
            "units": pa.array([w.units for w, _ in items], type=pa.string()),
            "carga_pct": pa.array([w.carga_pct for w, _ in items], type=pa.float32()),
            "samples": pa.array(
                [w.samples.tolist() for w, _ in items], type=pa.list_(pa.float32())
            ),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def write_trends_parquet(
    items: Sequence[tuple[Trend, Point]],
    path: Path,
) -> None:
    """Serialize a batch of ``(trend, point)`` pairs to one Parquet file.

    Unlike FFT/waveform, a :class:`Trend` is a *series*: it is exploded to
    ONE row per reading (timestamp + scalar ``overall``), so the file is
    queryable by date like every other sample and joins to
    ``manifest.parquet`` one-to-one. Each reading's ``sample_id`` carries
    its index as the discriminator. Writing an empty ``items`` still
    produces a valid zero-row file with the canonical schema.
    """
    flat: list[tuple[Trend, Point, int]] = [
        (t, p, i) for t, p in items for i in range(len(t.overall))
    ]
    table = pa.table(
        {
            "sample_id": pa.array(
                [
                    sample_id(t.point_record_num, t.record_num, "TREND", str(i))
                    for t, _, i in flat
                ],
                type=pa.string(),
            ),
            "point_record_num": pa.array(
                [t.point_record_num for t, _, _ in flat], type=pa.int64()
            ),
            "point_long_name": pa.array(
                [p.long_name for _, p, _ in flat], type=pa.string()
            ),
            "point_short_code": pa.array(
                [p.short_code for _, p, _ in flat], type=pa.string()
            ),
            "trend_record_num": pa.array(
                [t.record_num for t, _, _ in flat], type=pa.int64()
            ),
            "timestamp_utc": pa.array(
                [t.timestamps_utc[i] for t, _, i in flat],
                type=pa.timestamp("us", tz="UTC"),
            ),
            "sample_type": pa.array(["TREND"] * len(flat), type=pa.string()),
            "units": pa.array([t.units for t, _, _ in flat], type=pa.string()),
            "overall": pa.array(
                [float(t.overall[i]) for t, _, i in flat], type=pa.float32()
            ),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def write_spectrum_parquet(spectrum: Spectrum, point: Point, path: Path) -> None:
    """Serialize a single :class:`Spectrum` (one-row file). See ``extract``."""
    write_spectra_parquet([(spectrum, point)], path)


def write_waveform_parquet(waveform: Waveform, point: Point, path: Path) -> None:
    """Serialize a single :class:`Waveform` (one-row file). See ``extract``."""
    write_waveforms_parquet([(waveform, point)], path)


def write_trend_parquet(trend: Trend, point: Point, path: Path) -> None:
    """Serialize a single :class:`Trend` (one row per reading). See ``extract``."""
    write_trends_parquet([(trend, point)], path)
