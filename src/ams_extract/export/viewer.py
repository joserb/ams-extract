"""On-demand viewer over an exported VibDataset (``rbm serve``).

Unlike the inventory report (which reads the ``.rbm`` directly), the viewer
serves an **already exported** dataset: it reads the VibDataset machine
documents and per-asset Parquet tables, builds an in-memory sample index and
renders each plot **on demand** via the existing matplotlib renderers.

The pure helpers (:func:`build_viewer_html`, :func:`render_sample_png`) are
socket-free so they can be unit-tested directly; :func:`serve` wraps them in a
``ThreadingHTTPServer``.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse

import numpy as np
import pyarrow.parquet as pq
import structlog

from ams_extract.export.spectrum_plot import render_spectrum_png
from ams_extract.export.trend_plot import render_trend_png
from ams_extract.export.vibdataset_contract import (
    DATASET_FILE,
    MACHINE_DOC_FILE,
    MACHINE_PARTITION_PREFIX,
    SPECTRA_FILE,
    TRENDS_FILE,
    WAVES_FILE,
)
from ams_extract.export.waveform_plot import render_waveform_png
from ams_extract.models import Point, Spectrum, Trend, Waveform

_log = structlog.get_logger(__name__)


class ViewerError(ValueError):
    """Raised when the dataset is missing required files or a sample is bad."""


def load_manifest(dataset_dir: Path) -> list[dict[str, Any]]:
    """Read a VibDataset directory into viewer sample rows.

    Raises:
        ViewerError: If the dataset is missing ``dataset.json``.
    """
    dataset_path = dataset_dir / DATASET_FILE
    if not dataset_path.exists():
        raise ViewerError(f"no {DATASET_FILE} under {dataset_dir}")

    rows: list[dict[str, Any]] = []
    for machine_dir in sorted(dataset_dir.glob(f"{MACHINE_PARTITION_PREFIX}*")):
        if not machine_dir.is_dir():
            continue
        rows.extend(_load_machine_rows(machine_dir))
    return rows


def _dt_from_us(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1_000_000, tz=UTC)


def _viewer_sample_id(*parts: object) -> str:
    raw = ":".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _read_json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _machine_context(machine_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    doc_path = machine_dir / MACHINE_DOC_FILE
    if not doc_path.exists():
        raise ViewerError(f"missing {MACHINE_DOC_FILE}: {doc_path}")
    doc = _read_json(doc_path)
    machine = cast("dict[str, Any]", doc["machine"])
    points = {point["id"]: point for point in cast("list[dict[str, Any]]", doc.get("points", []))}
    metrics = _load_metrics(machine_dir)
    return machine, points, metrics


def _load_metrics(machine_dir: Path) -> dict[str, dict[str, Any]]:
    path = machine_dir / "metrics.parquet"
    if not path.exists():
        return {}
    rows = cast("list[dict[str, Any]]", pq.read_table(path).to_pylist())
    return {row["metric_id"]: row for row in rows}


def _base_row(
    *,
    machine_dir: Path,
    machine: dict[str, Any],
    point: dict[str, Any],
    sample_type: str,
    timestamp_utc: datetime,
    sample_id: str,
    table_file: str,
    row_index: int,
) -> dict[str, Any]:
    path = cast("list[str]", machine.get("path") or [])
    area_long = path[0] if path else ""
    machine_id = cast("str", machine["id"])
    return {
        "sample_id": sample_id,
        "area": area_long,
        "area_long_name": area_long,
        "equipment": machine_id,
        "equipment_long_name": machine.get("name") or machine_id,
        "point_record_num": 0,
        "point_long_name": point.get("name") or point["id"],
        "point_short_code": point["id"],
        "timestamp_utc": timestamp_utc,
        "sample_type": sample_type,
        "_machine_dir": str(machine_dir),
        "_table_file": table_file,
        "_row_index": row_index,
    }


def _load_machine_rows(machine_dir: Path) -> list[dict[str, Any]]:
    machine, points, metrics = _machine_context(machine_dir)
    rows: list[dict[str, Any]] = []

    spectra_path = machine_dir / SPECTRA_FILE
    if spectra_path.exists():
        spectra_rows = cast(
            "list[dict[str, Any]]",
            pq.read_table(spectra_path).to_pylist(),
        )
        for idx, row in enumerate(spectra_rows):
            point = points.get(row["point_id"], {"id": row["point_id"], "name": row["point_id"]})
            rows.append(
                _base_row(
                    machine_dir=machine_dir,
                    machine=machine,
                    point=point,
                    sample_type="FFT",
                    timestamp_utc=_dt_from_us(row["t"]),
                    sample_id=_viewer_sample_id(machine["id"], "FFT", idx),
                    table_file=SPECTRA_FILE,
                    row_index=idx,
                )
            )

    waves_path = machine_dir / WAVES_FILE
    if waves_path.exists():
        wave_rows = cast(
            "list[dict[str, Any]]",
            pq.read_table(waves_path).to_pylist(),
        )
        for idx, row in enumerate(wave_rows):
            point = points.get(row["point_id"], {"id": row["point_id"], "name": row["point_id"]})
            rows.append(
                _base_row(
                    machine_dir=machine_dir,
                    machine=machine,
                    point=point,
                    sample_type="WAVEFORM",
                    timestamp_utc=_dt_from_us(row["t"]),
                    sample_id=_viewer_sample_id(machine["id"], "WAVEFORM", idx),
                    table_file=WAVES_FILE,
                    row_index=idx,
                )
            )

    trends_path = machine_dir / TRENDS_FILE
    if trends_path.exists():
        trend_rows = cast("list[dict[str, Any]]", pq.read_table(trends_path).to_pylist())
        for idx, row in enumerate(trend_rows):
            metric = metrics.get(row["metric_id"], {})
            point_id = metric.get("point_id") or row["metric_id"]
            point = points.get(point_id, {"id": point_id, "name": point_id})
            rows.append(
                _base_row(
                    machine_dir=machine_dir,
                    machine=machine,
                    point=point,
                    sample_type="TREND",
                    timestamp_utc=_dt_from_us(row["t"]),
                    sample_id=_viewer_sample_id(machine["id"], "TREND", row["metric_id"], idx),
                    table_file=TRENDS_FILE,
                    row_index=idx,
                )
                | {"metric_id": row["metric_id"]}
            )
    return rows


def _make_point(row: dict[str, Any]) -> Point:
    return Point(
        record_num=row["point_record_num"],
        long_name=row["point_long_name"],
        short_code=row["point_short_code"],
    )


def _read_table_row(dataset_dir: Path, row: dict[str, Any]) -> dict[str, Any]:
    machine_dir = Path(row["_machine_dir"])
    if not machine_dir.is_absolute():
        machine_dir = dataset_dir / machine_dir
    rows = cast(
        "list[dict[str, Any]]",
        pq.read_table(machine_dir / row["_table_file"]).to_pylist(),
    )
    return rows[int(row["_row_index"])]


def _spectrum_png(dataset_dir: Path, row: dict[str, Any]) -> bytes:
    r = _read_table_row(dataset_dir, row)
    spectrum = Spectrum(
        record_num=0,
        point_record_num=0,
        timestamp_utc=_dt_from_us(r["t"]),
        fmax_hz=r["fmax_hz"],
        n_lines=r["lines"],
        units=r["unit"],
        carga_pct=0.0,
        amplitude=np.asarray(r["data"], dtype=np.float32),
    )
    buf = io.BytesIO()
    render_spectrum_png(spectrum, _make_point(row), buf)
    return buf.getvalue()


def _waveform_png(dataset_dir: Path, row: dict[str, Any]) -> bytes:
    r = _read_table_row(dataset_dir, row)
    speed_hz = r["speed_hz"]
    waveform = Waveform(
        record_num=0,
        point_record_num=0,
        timestamp_utc=_dt_from_us(r["t"]),
        n_samples=r["n_samples"],
        sample_rate_hz=r["sample_rate_hz"],
        rpm=float(speed_hz) * 60.0 if speed_hz is not None else 0.0,
        units=r["unit"],
        carga_pct=0.0,
        samples=np.asarray(r["data"], dtype=np.float32),
    )
    buf = io.BytesIO()
    render_waveform_png(waveform, _make_point(row), buf)
    return buf.getvalue()


def _trend_png(dataset_dir: Path, row: dict[str, Any]) -> bytes:
    # A trend is a whole series per point: rebuild it from every reading row
    # of this point in the trend parquet (sorted oldest-first), not just the
    # clicked sample_id.
    machine_dir = Path(row["_machine_dir"])
    if not machine_dir.is_absolute():
        machine_dir = dataset_dir / machine_dir
    all_rows = cast(
        "list[dict[str, Any]]",
        pq.read_table(machine_dir / TRENDS_FILE).to_pylist(),
    )
    metric_id = row["metric_id"]
    rows = sorted(
        (r for r in all_rows if r["metric_id"] == metric_id),
        key=lambda x: x["t"],
    )
    if not rows:
        raise ViewerError(f"trend {metric_id!r} is empty")
    trend = Trend(
        record_num=0,
        point_record_num=0,
        units="mm/s",
        timestamps_utc=tuple(_dt_from_us(x["t"]) for x in rows),
        overall=np.asarray([x["value"] for x in rows], dtype=np.float32),
    )
    buf = io.BytesIO()
    render_trend_png(trend, _make_point(row), buf)
    return buf.getvalue()


def render_sample_png(dataset_dir: Path, row: dict[str, Any]) -> bytes:
    """Reconstruct the sample described by ``row`` and render its PNG bytes.

    ``row`` is a viewer row built from VibDataset tables.
    Trends are plotted as the whole per-point series.

    Raises:
        ViewerError: If the sample type is unknown or the row is missing.
    """
    sample_type = row["sample_type"]
    if sample_type == "FFT":
        return _spectrum_png(dataset_dir, row)
    if sample_type == "WAVEFORM":
        return _waveform_png(dataset_dir, row)
    if sample_type == "TREND":
        return _trend_png(dataset_dir, row)
    raise ViewerError(f"unknown sample type {sample_type!r}")


# Light theme only: plots render server-side on a white background, so a dark
# page made them glare. Matches the live viewer (ams_extract.export.live_viewer).
_VIEWER_CSS = """
* { box-sizing: border-box; }
body { font: 14px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  margin: 0 auto; max-width: 1200px; padding: 1.5rem;
  color: #1f2328; background: #f4f5f7; }
h1 { font-size: 1.25rem; margin: 0 0 .25rem; }
header { background:#fff; border:1px solid #e2e4e8; border-radius:10px; padding:1rem 1.25rem; }
header p { color:#57606a; margin:.25rem 0 0; }
input[type=search]{ width:100%; padding:.55rem .8rem; font-size:1rem;
  border:1px solid #d0d7de; border-radius:8px; margin:1rem 0; background:#fff; color:inherit; }
details { background:#fff; border:1px solid #e2e4e8; border-radius:8px;
  margin:.35rem 0; padding:0 .7rem; }
details.area > summary { font-weight:700; }
details.machine { margin-left:1rem; }
details.point { margin-left:1rem; }
summary { cursor:pointer; padding:.45rem .2rem; }
summary:hover { color:#0969da; }
.kind { font-weight:600; color:#57606a; font-size:.8rem; margin-left:1rem; }
.samples { display:flex; flex-wrap:wrap; gap:.35rem; padding:.4rem 0 .5rem 1rem; }
.samples a { font-size:.8rem; padding:.2rem .5rem; border:1px solid #d0d7de; border-radius:6px;
  text-decoration:none; color:#1f2328; background:#fff; cursor:pointer; }
.samples a:hover { border-color:#0969da; color:#0969da; }
.samples a.active { background:#0969da; border-color:#0969da; color:#fff; }
#panel { position:sticky; top:1rem; z-index:5; background:#fff; border:1px solid #e2e4e8;
  border-radius:10px; margin:1rem 0; box-shadow:0 1px 4px rgba(0,0,0,.07); }
#panel-bar { display:flex; align-items:center; gap:.5rem; padding:.5rem .75rem;
  border-bottom:1px solid #eef0f2; }
#panel-title { font-weight:600; font-size:.9rem; flex:1; overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap; }
#panel-close { border:1px solid #d0d7de; background:#f6f8fa; border-radius:6px;
  cursor:pointer; font:inherit; padding:.2rem .6rem; color:#57606a; }
#panel-close:hover { background:#eaeef2; color:#1f2328; }
#plot { text-align:center; padding:.75rem; min-height:80px; }
#plot img { max-width:100%; height:auto; border-radius:6px; }
#plot .placeholder { color:#8b949e; font-style:italic; padding:1rem; }
.hidden { display:none !important; }
"""

_VIEWER_JS = """
(function(){
  var box=document.getElementById('filter');
  var panel=document.getElementById('panel');
  var plot=document.getElementById('plot');
  var titleEl=document.getElementById('panel-title');
  var active=null;

  function closePlot(){
    panel.classList.add('hidden'); plot.innerHTML='';
    if(active){ active.classList.remove('active'); active=null; }
  }
  document.getElementById('panel-close').addEventListener('click', closePlot);
  document.addEventListener('keydown', function(e){ if(e.key==='Escape') closePlot(); });

  document.addEventListener('click',function(e){
    var a=e.target.closest('a.sample'); if(!a) return;
    e.preventDefault();
    if(active) active.classList.remove('active');
    active=a; a.classList.add('active');
    titleEl.textContent=a.getAttribute('data-title')||'Gráfica';
    panel.classList.remove('hidden');
    plot.innerHTML='<div class="placeholder">cargando…</div>';
    var img=new Image();
    img.onload=function(){ plot.innerHTML=''; plot.appendChild(img); };
    img.onerror=function(){ plot.innerHTML='<div class="placeholder">error al renderizar</div>'; };
    img.src=a.getAttribute('href');
    panel.scrollIntoView({block:'nearest'});
  });
  if(box){
    var machines=Array.prototype.slice.call(document.querySelectorAll('details.machine'));
    box.addEventListener('input',function(){
      var q=box.value.trim().toLowerCase();
      machines.forEach(function(m){
        var hit=!q||m.getAttribute('data-name').indexOf(q)!==-1;
        m.classList.toggle('hidden',!hit);
        var area=m.closest('details.area');
        if(hit&&area){area.classList.remove('hidden'); if(q)area.open=true;}
      });
      document.querySelectorAll('details.area').forEach(function(area){
        var any=area.querySelector('details.machine:not(.hidden)');
        area.classList.toggle('hidden',!any);
      });
    });
  }
})();
"""

# Display order and labels for the per-point sample groups.
_KINDS = (("FFT", "Espectros"), ("WAVEFORM", "Ondas"), ("TREND", "Tendencia"))


def _sample_link(row: dict[str, Any], title_prefix: str) -> str:
    ts = row["timestamp_utc"]
    label = ts.strftime("%Y-%m-%d %H:%M") if ts is not None else row["sample_id"]
    title = f"{title_prefix} · {label}"
    return (
        f'<a class="sample" href="/plot/{escape(row["sample_id"], quote=True)}.png"'
        f' data-title="{escape(title, quote=True)}">'
        f"{escape(label)}</a>"
    )


_SampleRow = dict[str, Any]
# area_long -> machine_long -> point_long -> sample_type -> rows
_Tree = dict[str, dict[str, dict[str, dict[str, list[_SampleRow]]]]]


def build_viewer_html(rows: Sequence[_SampleRow], *, title: str = "Dataset") -> str:
    """Build the viewer page (area → machine → point → sample links) from rows."""
    tree: _Tree = {}
    for row in rows:
        area = tree.setdefault(row["area_long_name"] or row["area"], {})
        machine = area.setdefault(row["equipment_long_name"] or row["equipment"], {})
        point = machine.setdefault(row["point_long_name"], {})
        point.setdefault(row["sample_type"], []).append(row)

    area_blocks: list[str] = []
    for area_long, machines in tree.items():
        machine_blocks: list[str] = []
        for eq_long, points in machines.items():
            point_blocks: list[str] = []
            for pt_long, kinds in points.items():
                kind_html: list[str] = []
                for kind, kind_label in _KINDS:
                    samples = kinds.get(kind, [])
                    if not samples:
                        continue
                    prefix = f"{pt_long} · {kind_label}"
                    if kind == "TREND":
                        # One link per point for the whole series.
                        links = _sample_link(min(samples, key=lambda r: r["timestamp_utc"]), prefix)
                        count_label = f"{kind_label} ({len(samples)} lecturas)"
                    else:
                        ordered = sorted(samples, key=lambda r: r["timestamp_utc"])
                        links = "".join(_sample_link(r, prefix) for r in ordered)
                        count_label = f"{kind_label} ({len(samples)})"
                    kind_html.append(
                        f'<div class="kind">{count_label}</div><div class="samples">{links}</div>'
                    )
                point_blocks.append(
                    '<details class="point"><summary>'
                    f"{escape(pt_long)}</summary>{''.join(kind_html)}</details>"
                )
            machine_blocks.append(
                f'<details class="machine" data-name="{escape(eq_long.lower(), quote=True)}">'
                f"<summary>{escape(eq_long)}</summary>{''.join(point_blocks)}</details>"
            )
        area_blocks.append(
            '<details class="area"><summary>'
            f"{escape(area_long)}</summary>{''.join(machine_blocks)}</details>"
        )

    areas_html = "\n".join(area_blocks) or "<p><em>(dataset vacío)</em></p>"
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} — Viewer RBM</title>
<style>{_VIEWER_CSS}</style>
</head>
<body>
<header><h1>{escape(title)}</h1>
<p>{len(rows):,} muestras. Haz clic en una para ver su gráfica.</p></header>
<input type="search" id="filter" placeholder="Filtrar máquinas…" autocomplete="off">
<div id="panel" class="hidden">
  <div id="panel-bar">
    <span id="panel-title">Gráfica</span>
    <button id="panel-close" title="Cerrar (Esc)">✕ Cerrar</button>
  </div>
  <div id="plot"></div>
</div>
<main>
{areas_html}
</main>
<script>{_VIEWER_JS}</script>
</body>
</html>
"""


def _make_handler(
    dataset_dir: Path,
    rows: list[dict[str, Any]],
    page_html: str,
) -> type[BaseHTTPRequestHandler]:
    by_id = {row["sample_id"]: row for row in rows}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass  # silence the default stderr access log

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", page_html.encode("utf-8"))
                return
            if path == "/api/manifest.json":
                payload = json.dumps(
                    [{k: v for k, v in r.items() if k != "amplitude"} for r in rows],
                    default=str,
                ).encode("utf-8")
                self._send(200, "application/json", payload)
                return
            if path.startswith("/plot/") and path.endswith(".png"):
                sample_id = unquote(path[len("/plot/") : -len(".png")])
                row = by_id.get(sample_id)
                if row is None:
                    self._send(404, "text/plain", b"sample not found")
                    return
                try:
                    png = render_sample_png(dataset_dir, row)
                except Exception as exc:
                    _log.warning("plot_failed", sample_id=sample_id, error=str(exc))
                    self._send(500, "text/plain", f"render error: {exc}".encode())
                    return
                self._send(200, "image/png", png)
                return
            self._send(404, "text/plain", b"not found")

    return Handler


def serve(
    dataset_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> ThreadingHTTPServer:
    """Build and return a (not-yet-serving) HTTP server for ``dataset_dir``.

    Validates the dataset, builds a sample index, pre-renders the page HTML and
    returns a :class:`ThreadingHTTPServer`. The caller drives it with
    ``serve_forever`` (so tests can start/stop it). The ``.rbm`` is never
    touched — every plot is rebuilt from the local Parquet on demand.

    Raises:
        ViewerError: If ``dataset_dir`` lacks ``dataset.json``.
    """
    dataset_dir = Path(dataset_dir)
    rows = load_manifest(dataset_dir)
    title = dataset_dir.name or "Dataset"
    page_html = build_viewer_html(rows, title=title)
    handler = _make_handler(dataset_dir, rows, page_html)
    return ThreadingHTTPServer((host, port), handler)
