"""On-demand viewer over an exported Parquet dataset (``rbm serve``).

Unlike the inventory report (which reads the ``.rbm`` directly), the viewer
serves an **already exported** dataset: it reads ``manifest.parquet`` for the
location → machine → point → sample tree and, when the analyst clicks a
sample, reconstructs the model from the per-equipment Parquet and renders the
plot **on demand** to an in-memory PNG via the existing matplotlib renderers
(no pre-generated images).

The pure helpers (:func:`build_viewer_html`, :func:`render_sample_png`) are
socket-free so they can be unit-tested directly; :func:`serve` wraps them in a
``ThreadingHTTPServer``.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import io
import json
from collections.abc import Sequence
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
from ams_extract.export.waveform_plot import render_waveform_png
from ams_extract.models import Point, Spectrum, Trend, Waveform

_log = structlog.get_logger(__name__)


class ViewerError(ValueError):
    """Raised when the dataset is missing required files or a sample is bad."""


def load_manifest(dataset_dir: Path) -> list[dict[str, Any]]:
    """Read ``manifest.parquet`` from ``dataset_dir`` into a list of row dicts.

    Raises:
        ViewerError: If the dataset is missing ``manifest.parquet``.
    """
    manifest_path = dataset_dir / "manifest.parquet"
    if not manifest_path.exists():
        raise ViewerError(f"no manifest.parquet under {dataset_dir}")
    return cast("list[dict[str, Any]]", pq.read_table(manifest_path).to_pylist())


def _make_point(row: dict[str, Any]) -> Point:
    return Point(
        record_num=row["point_record_num"],
        long_name=row["point_long_name"],
        short_code=row["point_short_code"],
    )


def _spectrum_png(dataset_dir: Path, row: dict[str, Any]) -> bytes:
    table = pq.read_table(
        dataset_dir / row["parquet_path"],
        filters=[("sample_id", "==", row["sample_id"])],
    )
    if table.num_rows == 0:
        raise ViewerError(f"spectrum {row['sample_id']} not found in parquet")
    pl = cast("list[dict[str, Any]]", table.to_pylist())
    r = pl[0]
    spectrum = Spectrum(
        record_num=r["spectrum_record_num"],
        point_record_num=r["point_record_num"],
        timestamp_utc=r["timestamp_utc"],
        fmax_hz=r["fmax_hz"],
        n_lines=r["n_lines"],
        units=r["units"],
        carga_pct=r["carga_pct"],
        amplitude=np.asarray(r["amplitude"], dtype=np.float32),
    )
    buf = io.BytesIO()
    render_spectrum_png(spectrum, _make_point(r), buf)
    return buf.getvalue()


def _waveform_png(dataset_dir: Path, row: dict[str, Any]) -> bytes:
    table = pq.read_table(
        dataset_dir / row["parquet_path"],
        filters=[("sample_id", "==", row["sample_id"])],
    )
    if table.num_rows == 0:
        raise ViewerError(f"waveform {row['sample_id']} not found in parquet")
    pl = cast("list[dict[str, Any]]", table.to_pylist())
    r = pl[0]
    waveform = Waveform(
        record_num=r["waveform_record_num"],
        point_record_num=r["point_record_num"],
        timestamp_utc=r["timestamp_utc"],
        n_samples=r["n_samples"],
        sample_rate_hz=r["sample_rate_hz"],
        rpm=r["rpm"],
        units=r["units"],
        carga_pct=r["carga_pct"],
        samples=np.asarray(r["samples"], dtype=np.float32),
    )
    buf = io.BytesIO()
    render_waveform_png(waveform, _make_point(r), buf)
    return buf.getvalue()


def _trend_png(dataset_dir: Path, row: dict[str, Any]) -> bytes:
    # A trend is a whole series per point: rebuild it from every reading row
    # of this point in the trend parquet (sorted oldest-first), not just the
    # clicked sample_id.
    table = pq.read_table(
        dataset_dir / row["parquet_path"],
        filters=[("point_record_num", "==", row["point_record_num"])],
    )
    pl = cast("list[dict[str, Any]]", table.to_pylist())
    rows = sorted(pl, key=lambda x: x["timestamp_utc"])
    if not rows:
        raise ViewerError(f"trend for point {row['point_record_num']} is empty")
    trend = Trend(
        record_num=rows[0]["trend_record_num"],
        point_record_num=rows[0]["point_record_num"],
        units=rows[0]["units"],
        timestamps_utc=tuple(x["timestamp_utc"] for x in rows),
        overall=np.asarray([x["overall"] for x in rows], dtype=np.float32),
    )
    buf = io.BytesIO()
    render_trend_png(trend, _make_point(rows[0]), buf)
    return buf.getvalue()


def render_sample_png(dataset_dir: Path, row: dict[str, Any]) -> bytes:
    """Reconstruct the sample described by ``row`` and render its PNG bytes.

    ``row`` is a manifest row (carrying ``sample_type`` and ``parquet_path``).
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
                        links = _sample_link(
                            min(samples, key=lambda r: r["timestamp_utc"]), prefix
                        )
                        count_label = f"{kind_label} ({len(samples)} lecturas)"
                    else:
                        ordered = sorted(samples, key=lambda r: r["timestamp_utc"])
                        links = "".join(_sample_link(r, prefix) for r in ordered)
                        count_label = f"{kind_label} ({len(samples)})"
                    kind_html.append(
                        f'<div class="kind">{count_label}</div>'
                        f'<div class="samples">{links}</div>'
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

    areas_html = "\n".join(area_blocks) or '<p><em>(dataset vacío)</em></p>'
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
                    [
                        {k: v for k, v in r.items() if k != "amplitude"}
                        for r in rows
                    ],
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

    Validates the dataset, loads the manifest, pre-renders the page HTML and
    returns a :class:`ThreadingHTTPServer`. The caller drives it with
    ``serve_forever`` (so tests can start/stop it). The ``.rbm`` is never
    touched — every plot is rebuilt from the local Parquet on demand.

    Raises:
        ViewerError: If ``dataset_dir`` lacks ``manifest.parquet``.
    """
    dataset_dir = Path(dataset_dir)
    rows = load_manifest(dataset_dir)
    title = dataset_dir.name or "Dataset"
    page_html = build_viewer_html(rows, title=title)
    handler = _make_handler(dataset_dir, rows, page_html)
    return ThreadingHTTPServer((host, port), handler)
