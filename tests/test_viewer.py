"""Tests for the on-demand VibDataset viewer (``rbm serve``)."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ams_extract.export.vibdataset_contract import (
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
from ams_extract.export.viewer import (
    ViewerError,
    build_viewer_html,
    load_manifest,
    render_sample_png,
    serve,
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
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
    """Write a minimal VibDataset (one machine, one of each type)."""
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
            "config_generations": [
                {
                    "config_id": "",
                    "valid_from_us": None,
                    "valid_to_us": None,
                    "description": "",
                }
            ],
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
                "unit": "G's",
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


class TestLoadManifest:
    def test_missing_dataset_json_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ViewerError):
            load_manifest(tmp_path)

    def test_loads_rows(self, tmp_path: Path) -> None:
        ds = _build_dataset(tmp_path)
        rows = load_manifest(ds)
        assert len(rows) == 4
        assert {r["sample_type"] for r in rows} == {"FFT", "WAVEFORM", "TREND"}


class TestBuildViewerHtml:
    def test_tree_and_sample_links(self, tmp_path: Path) -> None:
        rows = load_manifest(_build_dataset(tmp_path))
        html = build_viewer_html(rows, title="ds")
        assert "<!DOCTYPE html>" in html
        assert "Bomba EQ" in html
        assert "MOTOR LA H" in html
        assert 'class="sample"' in html
        assert "/plot/" in html
        assert html.count('class="sample"') == 3


class TestRenderSamplePng:
    @pytest.mark.parametrize("stype", ["FFT", "WAVEFORM", "TREND"])
    def test_renders_valid_png(self, tmp_path: Path, stype: str) -> None:
        ds = _build_dataset(tmp_path)
        rows = load_manifest(ds)
        row = next(r for r in rows if r["sample_type"] == stype)
        png = render_sample_png(ds, row)
        assert png.startswith(_PNG_MAGIC)
        assert len(png) > 100

    def test_unknown_type_raises(self, tmp_path: Path) -> None:
        ds = _build_dataset(tmp_path)
        with pytest.raises(ViewerError):
            render_sample_png(ds, {"sample_type": "BOGUS"})


class TestServe:
    def test_live_plot_request(self, tmp_path: Path) -> None:
        ds = _build_dataset(tmp_path)
        rows = load_manifest(ds)
        server = serve(ds, host="127.0.0.1", port=0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urlopen(f"{base}/") as resp:
                assert resp.status == 200
                assert b"<!DOCTYPE html>" in resp.read()
            sid = next(r["sample_id"] for r in rows if r["sample_type"] == "FFT")
            with urlopen(f"{base}/plot/{sid}.png") as resp:
                assert resp.status == 200
                assert resp.headers["Content-Type"] == "image/png"
                assert resp.read().startswith(_PNG_MAGIC)
            with urlopen(f"{base}/api/manifest.json") as resp:
                assert resp.status == 200
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_unknown_sample_returns_404(self, tmp_path: Path) -> None:
        from urllib.error import HTTPError

        ds = _build_dataset(tmp_path)
        server = serve(ds, host="127.0.0.1", port=0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with pytest.raises(HTTPError) as exc:
                urlopen(f"http://127.0.0.1:{port}/plot/deadbeef.png")
            assert exc.value.code == 404
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
