"""Global ``manifest.parquet`` writer.

The manifest is the master index of the dataset: one row per sample, with
NO amplitude arrays, so "what did I measure, where and when?" can be
answered without loading a single spectrum. See PLAN.md §3.5.

Rows are produced by the dataset orchestrator (one per emitted FFT or
waveform sample) as plain dicts so they survive pickling across worker
processes. :data:`MANIFEST_FIELDS` is the canonical, ordered schema; the
type-specific numeric columns are nullable because a given row is either
an FFT (``fmax_hz`` / ``n_lines``) or a waveform
(``sample_rate_hz`` / ``rpm`` / ``n_samples``).
"""

# pyright: reportUnknownMemberType=false

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

# (column name, pyarrow type). Order is the on-disk column order.
MANIFEST_FIELDS: list[tuple[str, pa.DataType]] = [
    ("sample_id", pa.string()),
    ("area", pa.string()),
    ("area_long_name", pa.string()),
    ("equipment", pa.string()),
    ("equipment_long_name", pa.string()),
    ("point_record_num", pa.int64()),
    ("point_long_name", pa.string()),
    ("point_short_code", pa.string()),
    ("timestamp_utc", pa.timestamp("us", tz="UTC")),
    ("sample_type", pa.string()),
    ("units", pa.string()),
    ("fmax_hz", pa.float32()),
    ("n_lines", pa.int32()),
    ("sample_rate_hz", pa.float32()),
    ("rpm", pa.float32()),
    ("n_samples", pa.int32()),
    ("parquet_path", pa.string()),
]

MANIFEST_SCHEMA = pa.schema(MANIFEST_FIELDS)


def write_manifest(rows: Sequence[dict[str, Any]], path: Path) -> None:
    """Write ``rows`` to ``path`` as ``manifest.parquet``.

    Each row is a dict whose keys are a subset of :data:`MANIFEST_FIELDS`
    names; missing keys default to ``None`` (null). An empty ``rows`` still
    produces a valid zero-row file carrying :data:`MANIFEST_SCHEMA`.
    """
    columns = {
        name: pa.array([row.get(name) for row in rows], type=dtype)
        for name, dtype in MANIFEST_FIELDS
    }
    table = pa.table(columns, schema=MANIFEST_SCHEMA)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
