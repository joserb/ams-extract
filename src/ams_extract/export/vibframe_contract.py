"""Local VibFrame contract subset used by ``rbm export``.

These definitions were imported from ``vibsynth-contracts.dataset`` on
2026-07-10 (commit ``9e679d2e7689c9537f426c80bded1f5617b6058f``) and
intentionally copied here so ``ams-extract`` does not depend on the vibsynth
monorepo at runtime. Keep this file small: it covers only the layout and
columns needed to write AMS RBM exports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pyarrow as pa

SCHEMA_VERSION = "0.1.0"

DATASET_FILE = "dataset.json"
MACHINE_DOC_FILE = "machine.json"
METRICS_FILE = "metrics.parquet"
TRENDS_FILE = "trends.parquet"
SPECTRA_FILE = "spectra.parquet"
WAVES_FILE = "waves.parquet"
MACHINE_PARTITION_PREFIX = "machine="

Dtype = Literal[
    "int8",
    "int32",
    "int64",
    "uint32",
    "float32",
    "float64",
    "bool",
    "string",
    "list<float32>",
    "list<int32>",
    "list<string>",
]


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """Column descriptor for one VibFrame parquet table."""

    name: str
    dtype: Dtype
    required: bool = True


TRENDS_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("t", "int64"),
    ColumnSpec("metric_id", "string"),
    ColumnSpec("value", "float32"),
    ColumnSpec("alarm", "int8", required=False),
    ColumnSpec("config_id", "string"),
)

SPECTRA_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("t", "int64"),
    ColumnSpec("snap_t", "int64", required=False),
    ColumnSpec("point_id", "string"),
    ColumnSpec("proc_mode_id", "string"),
    ColumnSpec("fmin_hz", "float32"),
    ColumnSpec("fmax_hz", "float32"),
    ColumnSpec("lines", "int32"),
    ColumnSpec("window", "string", required=False),
    ColumnSpec("averages", "int32", required=False),
    ColumnSpec("spectrum_detector", "string", required=False),
    ColumnSpec("power", "bool", required=False),
    ColumnSpec("unit", "string"),
    ColumnSpec("signal_family", "string"),
    ColumnSpec("speed_hz", "float32", required=False),
    ColumnSpec("config_id", "string"),
    ColumnSpec("data", "list<float32>"),
)

WAVES_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("t", "int64"),
    ColumnSpec("snap_t", "int64", required=False),
    ColumnSpec("point_id", "string"),
    ColumnSpec("proc_mode_id", "string"),
    ColumnSpec("sample_rate_hz", "float32"),
    ColumnSpec("n_samples", "int32"),
    ColumnSpec("unit", "string"),
    ColumnSpec("signal_family", "string"),
    ColumnSpec("speed_hz", "float32", required=False),
    ColumnSpec("sync", "bool", required=False),
    ColumnSpec("tacho_rising", "list<float32>", required=False),
    ColumnSpec("tacho_falling", "list<float32>", required=False),
    ColumnSpec("config_id", "string"),
    ColumnSpec("data", "list<float32>"),
)

METRICS_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("metric_id", "string"),
    ColumnSpec("config_id", "string"),
    ColumnSpec("point_id", "string", required=False),
    ColumnSpec("proc_mode_id", "string", required=False),
    ColumnSpec("name", "string", required=False),
    ColumnSpec("path", "string", required=False),
    ColumnSpec("statistic", "string"),
    ColumnSpec("signal_family", "string"),
    ColumnSpec("detector", "string", required=False),
    ColumnSpec("unit", "string"),
    ColumnSpec("integrate", "bool", required=False),
    ColumnSpec("band_type", "string"),
    ColumnSpec("band_low_hz", "float32", required=False),
    ColumnSpec("band_high_hz", "float32", required=False),
    ColumnSpec("band_low_order", "float32", required=False),
    ColumnSpec("band_high_order", "float32", required=False),
    ColumnSpec("frequency_role", "string", required=False),
    ColumnSpec("harmonic_orders", "list<int32>", required=False),
    ColumnSpec("n_sidebands", "int32", required=False),
    ColumnSpec("modulator", "string", required=False),
    ColumnSpec("flags", "list<string>", required=False),
    ColumnSpec("canonical_metric", "string", required=False),
    ColumnSpec("proxy_quality", "string", required=False),
    ColumnSpec("mapping_rule", "string", required=False),
)


def pa_type(dtype: Dtype) -> pa.DataType:
    """Return the PyArrow type for a VibFrame dtype string."""
    match dtype:
        case "int8":
            return pa.int8()
        case "int32":
            return pa.int32()
        case "int64":
            return pa.int64()
        case "uint32":
            return pa.uint32()
        case "float32":
            return pa.float32()
        case "float64":
            return pa.float64()
        case "bool":
            return pa.bool_()
        case "string":
            return pa.string()
        case "list<float32>":
            return pa.list_(pa.float32())
        case "list<int32>":
            return pa.list_(pa.int32())
        case "list<string>":
            return pa.list_(pa.string())


def schema(columns: tuple[ColumnSpec, ...]) -> pa.Schema:
    """Build a PyArrow schema from VibFrame column specs."""
    return pa.schema([(col.name, pa_type(col.dtype)) for col in columns])
