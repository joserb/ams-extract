"""``rbm serve <dataset>`` delegates to the external ``vibframe-viewer``.

The dataset viewer lives in the ecosystem repo ``vibframe-viewer`` (Parts 1
and 4 of t8-extract's workplan 03); ams-extract's own ``export/viewer.py``
was dropped on 2026-07-29. What is left here is a thin wrapper, and these
tests guard that boundary: that the package is installed, that the ``rbm``
options reach its CLI correctly translated, and that a dataset shaped like
the ones ``rbm export`` writes is actually readable by it. The viewer's own
coverage lives in its repo.

The ``.rbm`` backend (``rbm serve FILE.rbm``) is *not* delegated: it renders
straight from the database with no export, and stays as this repo's own
debugging tool (see ``tests/test_live_viewer.py``).
"""

from __future__ import annotations

import argparse
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from typer.testing import CliRunner

from ams_extract.cli import app as rbm_app
from ams_extract.export.vibframe_contract import (
    DATASET_FILE,
    MACHINE_DOC_FILE,
    METRICS_COLUMNS,
    METRICS_FILE,
    SCHEMA_VERSION,
    SPECTRA_COLUMNS,
    SPECTRA_FILE,
    TRENDS_COLUMNS,
    TRENDS_FILE,
    WAVES_COLUMNS,
    WAVES_FILE,
    ColumnSpec,
    schema,
)

runner = CliRunner()

_TS = datetime(2020, 2, 19, 10, 2, 50, tzinfo=UTC)
_T_US = int(_TS.timestamp() * 1_000_000)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_table(path: Path, rows: list[dict[str, Any]], columns: tuple[ColumnSpec, ...]) -> None:
    pa_schema = schema(columns)
    arrays = {
        field.name: pa.array([row.get(field.name) for row in rows], type=field.type)
        for field in pa_schema
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(arrays, schema=pa_schema), path)


def _build_dataset(tmp_path: Path) -> Path:
    """Write a minimal VibFrame dataset (one machine, one of each type)."""
    ds = tmp_path / "ds"
    machine = ds / "machine=EQ"
    _write_json(
        ds / DATASET_FILE,
        {
            "schema_version": SCHEMA_VERSION,
            "name": "ds",
            "generator": "test",
            "created_at": "2020-01-01T00:00:00Z",
            "description": "",
        },
    )
    _write_json(
        machine / MACHINE_DOC_FILE,
        {
            "schema_version": SCHEMA_VERSION,
            "source": {
                "origin": "ams-rbm",
                "extractor": "test",
                "extracted_at": "2020-01-01T00:00:00Z",
                "source_ref": "fixture.rbm",
                "device": None,
            },
            "machine": {
                "id": "EQ",
                "name": "Bomba EQ",
                "path": ["AREA A", "Bomba EQ"],
                "fault_frequencies_order": {},
                "definition": None,
            },
            "points": [
                {
                    "id": "MOTOR_LA_H",
                    "name": "MOTOR LA H",
                    "location": None,
                    "direction": None,
                    "sensor": None,
                    "speed_source": None,
                }
            ],
            "proc_modes": [],
            "config_generations": [],
            "states": [],
            "ground_truth": None,
        },
    )
    _write_table(
        machine / METRICS_FILE,
        [
            {
                "metric_id": "overall_velocity_rms__MOTOR_LA_H",
                "config_id": "",
                "point_id": "MOTOR_LA_H",
                "proc_mode_id": None,
                "name": "overall_velocity_rms",
                "path": "MOTOR_LA_H:overall_velocity_rms",
                "statistic": "spectrum_rms",
                "signal_family": "velocity",
                "detector": "rms",
                "unit": "mm/s",
                "integrate": False,
                "band_type": "none",
                "flags": [],
            }
        ],
        METRICS_COLUMNS,
    )
    _write_table(
        machine / SPECTRA_FILE,
        [
            {
                "t": _T_US,
                "point_id": "MOTOR_LA_H",
                "proc_mode_id": "VEL_1000",
                "fmin_hz": 0.0,
                "fmax_hz": 1000.0,
                "lines": 8,
                "spectrum_detector": "peak",
                "power": False,
                "unit": "mm/s",
                "signal_family": "velocity",
                "config_id": "",
                "data": [float(i) for i in range(8)],
            }
        ],
        SPECTRA_COLUMNS,
    )
    _write_table(
        machine / WAVES_FILE,
        [
            {
                "t": _T_US,
                "point_id": "MOTOR_LA_H",
                "proc_mode_id": "WAVE_ACC_2560",
                "sample_rate_hz": 2560.0,
                "n_samples": 8,
                "unit": "g",
                "signal_family": "acceleration",
                "speed_hz": 24.25,
                "config_id": "",
                "data": [-0.5, -0.25, 0.0, 0.25, 0.5, 0.25, 0.0, -0.25],
            }
        ],
        WAVES_COLUMNS,
    )
    _write_table(
        machine / TRENDS_FILE,
        [
            {
                "t": _T_US,
                "metric_id": "overall_velocity_rms__MOTOR_LA_H",
                "value": 1.0,
                "config_id": "",
            },
            {
                "t": _T_US + 86_400_000_000,
                "metric_id": "overall_velocity_rms__MOTOR_LA_H",
                "value": 1.5,
                "config_id": "",
            },
        ],
        TRENDS_COLUMNS,
    )
    return ds


class TestServeDelegation:
    def test_dataset_directory_delegates_translating_the_arguments(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import vibframe_viewer.cli as viewer_cli

        ds = _build_dataset(tmp_path)
        seen: dict[str, argparse.Namespace] = {}

        def _fake_serve(args: argparse.Namespace) -> int:
            seen["args"] = args
            return 0

        monkeypatch.setattr(viewer_cli, "_cmd_serve", _fake_serve)
        result = runner.invoke(
            rbm_app, ["serve", str(ds), "--port", "0", "--host", "0.0.0.0", "--no-browser"]
        )

        assert result.exit_code == 0, result.output
        args = seen["args"]
        assert args.path == ds
        assert (args.host, args.port, args.no_browser) == ("0.0.0.0", 0, True)

    def test_delegation_propagates_the_viewer_exit_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import vibframe_viewer.cli as viewer_cli

        ds = tmp_path / "empty"
        ds.mkdir()
        monkeypatch.setattr(viewer_cli, "_cmd_serve", lambda args: 1)
        result = runner.invoke(rbm_app, ["serve", str(ds), "--no-browser"])
        assert result.exit_code == 1

    def test_missing_source_is_rejected(self, tmp_path: Path) -> None:
        result = runner.invoke(rbm_app, ["serve", str(tmp_path / "nope"), "--no-browser"])
        assert result.exit_code == 1
        assert "not a .rbm file or dataset directory" in result.output


class TestViewerReadsOurLayout:
    """The exported layout is readable by the ecosystem viewer, end to end."""

    def test_index_and_tree_are_served(self, tmp_path: Path) -> None:
        from vibframe_viewer.server import serve as viewer_serve

        ds = _build_dataset(tmp_path)
        server = viewer_serve(ds, host="127.0.0.1", port=0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urlopen(f"{base}/") as resp:
                assert resp.status == 200
                assert b"<!DOCTYPE html>" in resp.read()
            with urlopen(f"{base}/api/tree") as resp:
                assert resp.status == 200
                tree = json.loads(resp.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert "Bomba EQ" in json.dumps(tree, ensure_ascii=False)
