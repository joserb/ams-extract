"""Local VibFrame contract subset used by ``rbm export`` and the GT materializer.

These definitions were imported from ``vibsynth-contracts`` (dataset layout and
``diagnosis.external`` projection columns) and intentionally copied here so
``ams-extract`` does not depend on the vibsynth monorepo at runtime (ADR-0009).

Origin state of this vendorization: VibFrame **0.2.0**, frozen coordinated
state ``ea50b0f3e567`` (2026-08-09: branch ``agent/vibframe-redesign-workplans``,
HEAD ``41e2f5f428b925a4b465fc54300bd2bb7d1a013d`` plus the uncommitted local
diff whose sha256 is ``ea50b0f3e567a5b13937ffad3029e97fdf0883b6e54460ed135874ff70cfe2e1``).
Keep this file small: it covers only the layout, the columns and the mode
signature needed to write AMS RBM exports and their ``ground-truth/``
projections.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Literal, cast

import pyarrow as pa

SCHEMA_VERSION = "0.2.0"

DATASET_FILE = "dataset.json"
MACHINE_DOC_FILE = "machine.json"
METRIC_CATALOG_FILE = "metric_catalog.json"
TRENDS_FILE = "trends.parquet"
SPECTRA_FILE = "spectra.parquet"
WAVES_FILE = "waves.parquet"
MACHINE_PARTITION_PREFIX = "machine="

# Optional sidecar directories of a VibFrame dataset, neither of them written
# by a producer: ``ground-truth/`` carries externally issued diagnostic labels
# (DiagGT, ``vibsynth_contracts.diagnosis.external.GROUND_TRUTH_DIR``) and
# ``analysis/`` carries computed analysis layers
# (``vibsynth_contracts.analysis.layers.ANALYSIS_DIR``). The spec forbids
# deleting them when re-exporting over an existing dataset directory.
GROUND_TRUTH_DIR = "ground-truth"
ANALYSIS_DIR = "analysis"

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
    ColumnSpec("snap_t", "int64", required=False),
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
    ColumnSpec("mode_definition_id", "string", required=False),
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
    ColumnSpec("mode_definition_id", "string", required=False),
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

# ------------------------------------------------------- ground-truth/ layout
#
# Normative 0.2 projections of the DiagGT documents
# (``vibsynth_contracts.diagnosis.external``): the complete projection, the
# policy-selected consolidated view, the findings projection and the
# materialization manifest. The documentary ``*.diaggt.json`` schema stays in
# its own series (``DIAGGT_SCHEMA_VERSION`` 0.1.x) and is not vendored here —
# the extractors build the documents as plain dicts and the normative Pydantic
# models are applied in the tests.

DIAGGT_FILE_SUFFIX = ".diaggt.json"
OBSERVATIONS_FILE = "observations.parquet"
OBSERVATIONS_CONSOLIDATED_FILE = "observations_consolidated.parquet"
FINDINGS_FILE = "findings.parquet"
GT_MATERIALIZATION_FILE = "materialization.json"
GT_MATERIALIZATION_KIND = "gt_materialization"
GT_MATERIALIZATION_SCHEMA_VERSION = "0.2.0"
CONSOLIDATION_POLICY = "dedup-primary-latest/1.0"

OBSERVATIONS_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("document_id", "string"),
    ColumnSpec("observation_id", "string"),
    ColumnSpec("origin", "string"),
    ColumnSpec("record_kind", "string"),
    ColumnSpec("normalized_tag", "string"),
    ColumnSpec("dataset_machine_id", "string", required=False),
    ColumnSpec("external_tag", "string", required=False),
    ColumnSpec("external_name", "string", required=False),
    ColumnSpec("area_code", "string", required=False),
    ColumnSpec("area_name", "string", required=False),
    ColumnSpec("modality", "string"),
    ColumnSpec("observed_at", "string"),
    ColumnSpec("inspection_date", "string", required=False),
    ColumnSpec("status", "string"),
    ColumnSpec("status_source_label", "string", required=False),
    ColumnSpec("alarm", "int8", required=False),
    ColumnSpec("global_status_label", "string", required=False),
    ColumnSpec("diagnosis_text", "string", required=False),
    ColumnSpec("analysis_text", "string", required=False),
    ColumnSpec("recommendation_text", "string", required=False),
    ColumnSpec("rpm1", "float32", required=False),
    ColumnSpec("rpm2", "float32", required=False),
    ColumnSpec("power_kw", "float32", required=False),
    ColumnSpec("source_page", "int32", required=False),
    ColumnSpec("n_findings", "int32"),
)

OBSERVATIONS_CONSOLIDATED_COLUMNS: tuple[ColumnSpec, ...] = (
    *OBSERVATIONS_COLUMNS,
    ColumnSpec("valid_to", "string", required=False),
)

FINDINGS_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("document_id", "string"),
    ColumnSpec("observation_id", "string"),
    ColumnSpec("finding_index", "int32"),
    ColumnSpec("dataset_machine_id", "string", required=False),
    ColumnSpec("observed_at", "string"),
    ColumnSpec("modality", "string"),
    ColumnSpec("record_kind", "string"),
    ColumnSpec("fault_mode", "string", required=False),
    ColumnSpec("fault_group", "string"),
    ColumnSpec("label_quality", "string"),
    ColumnSpec("mapping_rule", "string", required=False),
    ColumnSpec("weight", "float32", required=False),
    ColumnSpec("source_text", "string"),
    ColumnSpec("matched_text", "string", required=False),
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
    """Build a PyArrow schema from VibFrame column specs.

    Required columns are declared non-nullable: a missing value then fails at
    write time here instead of surfacing later as a
    ``columns.null-in-required`` error from ``vibframe-validate``. It is also
    what t8-extract and vibsynth declare — the contract talks about the value,
    not about how the field is declared, but aligning the three producers keeps
    their parquet identical down to the schema.
    """
    return pa.schema(
        [pa.field(col.name, pa_type(col.dtype), nullable=not col.required) for col in columns]
    )


# ----------------------------------------------------- machine.json (0.2)


def prune_nulls(value: Any) -> Any:
    """Recursively drop object properties whose value is ``None``.

    The 0.2 rule for ``machine.json`` (and the reference behaviour of
    ``vibsynth_contracts.dump_machine_doc``): absence and ``null`` are the same
    statement, so a writer never serializes a null property. List elements are
    never dropped — that would change cardinality and order, not just
    representation.
    """
    if isinstance(value, dict):
        mapping = cast(dict[str, Any], value)
        return {
            key: prune_nulls(child)
            for key, child in mapping.items()
            if child is not None
        }
    if isinstance(value, list):
        return [prune_nulls(child) for child in cast(list[Any], value)]
    return value


# ------------------------------------------------ ModeDefinition signature
#
# ``definition_id = "md-" + hex(SHA-256(JCS(payload)))[0:16]`` over the
# null-free semantic payload of the definition blocks (RFC 8785 canonical
# JSON), per the normative algorithm of VibFrame 0.2 and the binding vectors
# of ``vibsynth-contracts/docs/VECTORS-0.2.md`` (V1 = md-602326c3fa5dc798).


def _jcs_bytes(value: Any) -> bytes:
    """RFC-8785-compatible canonical bytes for the JSON types used by modes.

    Mirror of ``vibsynth_contracts.dataset.machine_doc._jcs_bytes`` (state
    ``ea50b0f3e567``): Python's shortest round-trip float representation
    agrees with ECMAScript for the finite physical values these blocks admit;
    integral floats are emitted as integers (``250.0`` → ``250``).
    """

    def encode(item: Any) -> str:
        if item is None or isinstance(item, (bool, str, int)):
            return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("JCS cannot encode non-finite numbers.")
            if item == 0.0:
                return "0"
            magnitude = abs(item)
            if item.is_integer() and magnitude < 1e21:
                return str(int(item))
            rendered = repr(item).lower()
            if "e" not in rendered:
                return rendered
            mantissa, exponent_text = rendered.split("e")
            exponent = int(exponent_text)
            if 1e-6 <= magnitude < 1e21:
                negative = mantissa.startswith("-")
                digits = mantissa.lstrip("-").replace(".", "")
                decimal_at = 1 + exponent
                if decimal_at <= 0:
                    decimal = "0." + "0" * (-decimal_at) + digits
                elif decimal_at >= len(digits):
                    decimal = digits + "0" * (decimal_at - len(digits))
                else:
                    decimal = digits[:decimal_at] + "." + digits[decimal_at:]
                return ("-" if negative else "") + decimal
            sign = "+" if exponent >= 0 else "-"
            return f"{mantissa}e{sign}{abs(exponent)}"
        if isinstance(item, list):
            members = cast(list[Any], item)
            return "[" + ",".join(encode(member) for member in members) + "]"
        if isinstance(item, dict):
            mapping = cast(dict[str, Any], item)
            return "{" + ",".join(
                f"{encode(key)}:{encode(mapping[key])}" for key in sorted(mapping)
            ) + "}"
        raise TypeError(f"unsupported JCS value: {type(item)!r}")

    return encode(value).encode("utf-8")


def semantic_mode_payload(blocks: dict[str, Any]) -> dict[str, Any]:
    """Null-free semantic payload of a mode definition, defaults materialized.

    ``blocks`` maps block names (``waveform`` | ``spectrum`` | ``processing``)
    to their field dicts; ``None``-valued fields and absent blocks are
    omitted, and the semantic default ``grid_kind="hz_uniform"`` of the
    spectrum block is always materialized, so an implicit and an explicit
    default sign identically (vector V6).
    """
    payload: dict[str, Any] = {}
    for name in ("waveform", "spectrum", "processing"):
        block = blocks.get(name)
        if block is None:
            continue
        cleaned = {key: value for key, value in block.items() if value is not None}
        if name == "spectrum":
            cleaned.setdefault("grid_kind", "hz_uniform")
        payload[name] = cleaned
    return payload


def mode_definition_id(blocks: dict[str, Any]) -> str:
    """Deterministic ``md-…`` signature of a mode definition payload."""
    payload = semantic_mode_payload(blocks)
    if not payload.get("waveform") and not payload.get("spectrum"):
        raise ValueError("a mode definition must produce waveform and/or spectrum.")
    digest = hashlib.sha256(_jcs_bytes(payload)).hexdigest()
    return "md-" + digest[:16]
