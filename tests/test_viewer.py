"""Tests for the on-demand Parquet viewer (``rbm serve``).

Builds a tiny dataset on disk with the real Parquet writers, then exercises
the socket-free helpers (manifest load, HTML build, model reconstruction +
PNG render) plus one live request against a ThreadingHTTPServer.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import numpy as np
import pytest

from ams_extract.export.manifest import write_manifest
from ams_extract.export.parquet_samples import (
    sample_id,
    write_spectra_parquet,
    write_trends_parquet,
    write_waveforms_parquet,
)
from ams_extract.export.viewer import (
    ViewerError,
    build_viewer_html,
    load_manifest,
    render_sample_png,
    serve,
)
from ams_extract.models import Point, Spectrum, Trend, Waveform

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_TS = datetime(2020, 2, 19, 10, 2, 50, tzinfo=UTC)


def _point() -> Point:
    return Point(record_num=100, long_name="MOTOR LA H", short_code="MOTOR_LA_H")


def _build_dataset(tmp_path: Path) -> Path:
    """Write a minimal but valid dataset (one machine, one of each type)."""
    ds = tmp_path / "ds"
    point = _point()
    fft_rel = "samples/area=A/equipment=EQ__fft.parquet"
    wv_rel = "samples/area=A/equipment=EQ__waveform.parquet"
    tn_rel = "samples/area=A/equipment=EQ__trend.parquet"

    spectrum = Spectrum(
        record_num=101, point_record_num=100, timestamp_utc=_TS,
        fmax_hz=1000.0, n_lines=8, units="mm/s", carga_pct=100.0,
        amplitude=np.arange(8, dtype=np.float32),
    )
    waveform = Waveform(
        record_num=201, point_record_num=100, timestamp_utc=_TS,
        n_samples=8, sample_rate_hz=2560.0, rpm=1455.0, units="G's", carga_pct=100.0,
        samples=np.linspace(-0.5, 0.5, 8, dtype=np.float32),
    )
    trend = Trend(
        record_num=301, point_record_num=100, units="mm/s",
        timestamps_utc=(_TS, datetime(2020, 3, 1, tzinfo=UTC)),
        overall=np.asarray([1.0, 1.5], dtype=np.float32),
    )
    write_spectra_parquet([(spectrum, point)], ds / fft_rel)
    write_waveforms_parquet([(waveform, point)], ds / wv_rel)
    write_trends_parquet([(trend, point)], ds / tn_rel)

    def _row(stype: str, rec: int, relpath: str, disc: str = "") -> dict[str, Any]:
        return {
            "sample_id": sample_id(100, rec, stype, disc),
            "area": "A", "area_long_name": "AREA A",
            "equipment": "EQ", "equipment_long_name": "Bomba EQ",
            "point_record_num": 100, "point_long_name": "MOTOR LA H",
            "point_short_code": "MOTOR_LA_H", "timestamp_utc": _TS,
            "sample_type": stype, "units": "mm/s", "parquet_path": relpath,
        }

    rows = [
        _row("FFT", 101, fft_rel),
        _row("WAVEFORM", 201, wv_rel),
        _row("TREND", 301, tn_rel, "0"),
        _row("TREND", 301, tn_rel, "1"),
    ]
    write_manifest(rows, ds / "manifest.parquet")
    return ds


class TestLoadManifest:
    def test_missing_manifest_raises(self, tmp_path: Path) -> None:
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
        # FFT + waveform = 2 single-sample links; trend collapses to one link
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
