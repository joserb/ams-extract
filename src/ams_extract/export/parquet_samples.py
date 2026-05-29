"""Per-sample Parquet export.

Sub-fase 3b emits ONE parquet file per spectrum with one row inside,
mirroring the schema sketched in PLAN.md §3.5; sub-fase 5b adds the
parallel writer for waveforms. The full Hive-partitioned dataset layout
(Fase 6) is built on top of these primitives.
"""

# pyright: reportUnknownMemberType=false

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ams_extract.models import Point, Spectrum, Waveform


def write_spectrum_parquet(
    spectrum: Spectrum,
    point: Point,
    path: Path,
) -> None:
    """Serialize one :class:`Spectrum` to a Parquet file.

    Schema: one row with metadata columns + ``amplitude`` as a
    ``list<float32>``. Frequency bins are derivable from ``fmax_hz`` and
    the amplitude length, so they are not stored.
    """
    amplitude = spectrum.amplitude
    table = pa.table(
        {
            "point_record_num": pa.array(
                [spectrum.point_record_num], type=pa.int64()
            ),
            "point_long_name": pa.array([point.long_name], type=pa.string()),
            "point_short_code": pa.array([point.short_code], type=pa.string()),
            "spectrum_record_num": pa.array(
                [spectrum.record_num], type=pa.int64()
            ),
            "timestamp_utc": pa.array(
                [spectrum.timestamp_utc], type=pa.timestamp("us", tz="UTC")
            ),
            "sample_type": pa.array(["FFT"], type=pa.string()),
            "fmax_hz": pa.array([spectrum.fmax_hz], type=pa.float32()),
            "n_lines": pa.array([spectrum.n_lines], type=pa.int32()),
            "units": pa.array([spectrum.units], type=pa.string()),
            "carga_pct": pa.array([spectrum.carga_pct], type=pa.float32()),
            "amplitude": pa.array(
                [amplitude.tolist()], type=pa.list_(pa.float32())
            ),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def write_waveform_parquet(
    waveform: Waveform,
    point: Point,
    path: Path,
) -> None:
    """Serialize one :class:`Waveform` to a Parquet file.

    Schema: one row with metadata columns + ``samples`` as a
    ``list<float32>``. The time axis is derivable from ``sample_rate_hz``
    and the samples length, so it is not stored.
    """
    samples = waveform.samples
    table = pa.table(
        {
            "point_record_num": pa.array(
                [waveform.point_record_num], type=pa.int64()
            ),
            "point_long_name": pa.array([point.long_name], type=pa.string()),
            "point_short_code": pa.array([point.short_code], type=pa.string()),
            "waveform_record_num": pa.array(
                [waveform.record_num], type=pa.int64()
            ),
            "timestamp_utc": pa.array(
                [waveform.timestamp_utc], type=pa.timestamp("us", tz="UTC")
            ),
            "sample_type": pa.array(["WAVEFORM"], type=pa.string()),
            "sample_rate_hz": pa.array([waveform.sample_rate_hz], type=pa.float32()),
            "n_samples": pa.array([waveform.n_samples], type=pa.int32()),
            "rpm": pa.array([waveform.rpm], type=pa.float32()),
            "units": pa.array([waveform.units], type=pa.string()),
            "carga_pct": pa.array([waveform.carga_pct], type=pa.float32()),
            "samples": pa.array(
                [samples.tolist()], type=pa.list_(pa.float32())
            ),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
