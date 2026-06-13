"""On-demand viewer served straight from a ``.rbm`` (``rbm serve FILE.rbm``).

Unlike the dataset viewer (:mod:`ams_extract.export.viewer`, which serves an
already exported Parquet dataset), this backend keeps a single read-only
``RbmReader`` open over the database and renders everything lazily:

* startup only walks the area → machine → point hierarchy (fast — no sample
  payloads), so the server is ready almost immediately even on a big database;
* expanding a machine fetches its points + per-type counts on demand
  (``/api/machine/<rec>``);
* expanding a point lists its samples by descriptor (``/api/point/<rec>/<kind>``,
  record-number + timestamp, no payloads read);
* clicking a sample renders its PNG on the fly from the ``.rbm``
  (``/plot/<point>/<kind>/<id>.png``).

The ``.rbm`` is memory-mapped read-only, so a single shared reader is safe to
use concurrently across :class:`ThreadingHTTPServer` worker threads.

The pure helpers (:func:`build_live_html`, :func:`render_point_sample_png`) are
socket-free so they can be unit-tested directly.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import io
import json
from collections.abc import Sequence
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import structlog

from ams_extract.export.spectrum_plot import render_spectrum_png
from ams_extract.export.trend_plot import render_trend_png
from ams_extract.export.waveform_plot import render_waveform_png
from ams_extract.models import Area, Point
from ams_extract.reader import RbmReader
from ams_extract.tree import (
    point_sample_refs,
    point_sample_summary,
    walk_hierarchy,
    walk_spectra,
    walk_trends,
    walk_waveforms,
)

_log = structlog.get_logger(__name__)


class LiveViewerError(ValueError):
    """Raised when the database cannot be opened or a request is malformed."""


def render_point_sample_png(reader: RbmReader, point: Point, kind: str, sample_id: int) -> bytes:
    """Render the PNG for one sample of ``point`` straight from the ``.rbm``.

    ``kind`` is ``"fft"``, ``"waveform"`` or ``"trend"``. For FFT/waveform,
    ``sample_id`` is the descriptor ``record_num`` to match; for trend it is
    ignored (the whole per-point series is plotted).

    Raises:
        LiveViewerError: If ``kind`` is unknown or the sample is not found.
    """
    buf = io.BytesIO()
    if kind == "fft":
        spectrum = next((s for s in walk_spectra(reader, point) if s.record_num == sample_id), None)
        if spectrum is None:
            raise LiveViewerError(f"spectrum {sample_id} not found for point")
        render_spectrum_png(spectrum, point, buf)
    elif kind == "waveform":
        waveform = next(
            (w for w in walk_waveforms(reader, point) if w.record_num == sample_id),
            None,
        )
        if waveform is None:
            raise LiveViewerError(f"waveform {sample_id} not found for point")
        render_waveform_png(waveform, point, buf)
    elif kind == "trend":
        trend = next(walk_trends(reader, point), None)
        if trend is None or trend.overall.size == 0:
            raise LiveViewerError("trend series is empty for point")
        render_trend_png(trend, point, buf)
    else:
        raise LiveViewerError(f"unknown sample kind {kind!r}")
    return buf.getvalue()


# Light theme only: the plots are rendered server-side on a white background,
# so a dark page made them glare. A consistent light UI keeps the white PNGs
# from standing out.
_CSS = """
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
summary { cursor:pointer; padding:.45rem .2rem; }
summary:hover { color:#0969da; }
.point { margin:.3rem 0 .5rem 1rem; padding:.4rem 0; border-top:1px solid #eef0f2; }
.point-name { font-weight:600; margin-bottom:.25rem; }
button.kind { font:inherit; font-size:.8rem; margin:.1rem .35rem .1rem 0; padding:.2rem .6rem;
  border:1px solid #d0d7de; border-radius:6px; background:#f6f8fa; color:#1f2328; cursor:pointer; }
button.kind:hover:not([disabled]){ background:#eaeef2; }
button.kind[disabled]{ opacity:.45; cursor:default; }
.samples { display:flex; flex-wrap:wrap; gap:.35rem; padding:.4rem 0 .3rem 1rem; }
.samples a { font-size:.8rem; padding:.2rem .5rem; border:1px solid #d0d7de; border-radius:6px;
  text-decoration:none; color:#1f2328; background:#fff; cursor:pointer; }
.samples a:hover { border-color:#0969da; color:#0969da; }
.samples a.active { background:#0969da; border-color:#0969da; color:#fff; }
.loading { color:#8b949e; font-style:italic; padding:.3rem 1rem; }
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

_KIND_LABELS = (("fft", "Espectros"), ("waveform", "Ondas"), ("trend", "Tendencia"))

_JS = """
(function(){
  var panel=document.getElementById('panel');
  var plot=document.getElementById('plot');
  var titleEl=document.getElementById('panel-title');
  var box=document.getElementById('filter');
  var active=null;

  function closePlot(){
    panel.classList.add('hidden'); plot.innerHTML='';
    if(active){ active.classList.remove('active'); active=null; }
  }
  document.getElementById('panel-close').addEventListener('click', closePlot);
  document.addEventListener('keydown', function(e){ if(e.key==='Escape') closePlot(); });

  function showPlot(href, title, chip){
    if(active) active.classList.remove('active');
    active=chip||null; if(active) active.classList.add('active');
    titleEl.textContent=title||'Gráfica';
    panel.classList.remove('hidden');
    plot.innerHTML='<div class="placeholder">cargando…</div>';
    var img=new Image();
    img.onload=function(){ plot.innerHTML=''; plot.appendChild(img); };
    img.onerror=function(){ plot.innerHTML='<div class="placeholder">error al renderizar</div>'; };
    img.src=href;
    panel.scrollIntoView({block:'nearest'});
  }

  function kindButton(pt, name, kind, label, count){
    var b=document.createElement('button');
    b.className='kind'; b.textContent=label+' ('+count+')';
    if(count<1){ b.disabled=true; return b; }
    b.addEventListener('click', function(){
      if(kind==='trend'){ showPlot('/plot/'+pt+'/trend/0.png', name+' · '+label, b); return; }
      var holder=b.parentNode.querySelector('.samples[data-kind="'+kind+'"]');
      if(holder){ holder.classList.toggle('hidden'); return; }
      holder=document.createElement('div');
      holder.className='samples'; holder.setAttribute('data-kind', kind);
      holder.innerHTML='<span class="loading">cargando…</span>';
      b.parentNode.appendChild(holder);
      fetch('/api/point/'+pt+'/'+kind).then(function(r){return r.json();}).then(function(d){
        holder.innerHTML='';
        if(!d.samples.length){
          holder.innerHTML='<span class="loading">(sin muestras)</span>'; return; }
        d.samples.forEach(function(s){
          var a=document.createElement('a');
          a.textContent=s.ts; a.href='#';
          a.addEventListener('click', function(e){ e.preventDefault();
            showPlot('/plot/'+pt+'/'+kind+'/'+s.id+'.png', name+' · '+label+' · '+s.ts, a); });
          holder.appendChild(a);
        });
      }).catch(function(){ holder.innerHTML='<span class="loading">error</span>'; });
    });
    return b;
  }

  function loadMachine(det){
    var eq=det.getAttribute('data-eq');
    var body=document.createElement('div');
    body.innerHTML='<div class="loading">cargando puntos…</div>';
    det.appendChild(body);
    fetch('/api/machine/'+eq).then(function(r){return r.json();}).then(function(d){
      body.innerHTML='';
      if(!d.points.length){ body.innerHTML='<div class="loading">(sin puntos)</div>'; return; }
      d.points.forEach(function(p){
        var row=document.createElement('div'); row.className='point';
        var name=document.createElement('div'); name.className='point-name';
        name.textContent=p.name; row.appendChild(name);
        _KINDS.forEach(function(k){
          row.appendChild(kindButton(p.rec, p.name, k[0], k[1], p[k[0]])); });
        body.appendChild(row);
      });
    }).catch(function(){ body.innerHTML='<div class="loading">error al cargar</div>'; });
  }

  document.querySelectorAll('details.machine').forEach(function(det){
    det.addEventListener('toggle', function(){
      if(det.open && !det.dataset.loaded){ det.dataset.loaded='1'; loadMachine(det); }
    });
  });

  if(box){
    var machines=Array.prototype.slice.call(document.querySelectorAll('details.machine'));
    box.addEventListener('input', function(){
      var q=box.value.trim().toLowerCase();
      machines.forEach(function(m){
        var hit=!q||m.getAttribute('data-name').indexOf(q)!==-1;
        m.classList.toggle('hidden', !hit);
      });
      document.querySelectorAll('details.area').forEach(function(area){
        var any=area.querySelector('details.machine:not(.hidden)');
        area.classList.toggle('hidden', !any);
        if(q&&any) area.open=true;
      });
    });
  }
})();
""".replace("_KINDS", json.dumps([[k, lbl] for k, lbl in _KIND_LABELS]))


def build_live_html(areas: Sequence[Area], *, title: str = "Base de datos") -> str:
    """Build the lazy viewer page (area → machine; points loaded on demand).

    Only the hierarchy is embedded; each machine carries its ``gdcm`` record
    number in ``data-eq`` so the client can fetch its points on first open.
    """
    area_blocks: list[str] = []
    for area in areas:
        machine_blocks: list[str] = []
        for eq in area.equipment:
            machine_blocks.append(
                f'<details class="machine" data-eq="{eq.record_num}" '
                f'data-name="{escape(eq.long_name.lower(), quote=True)}">'
                f"<summary>{escape(eq.long_name)}</summary></details>"
            )
        count = f'<span style="font-weight:400;color:#888"> — {len(area.equipment)} máquinas</span>'
        area_blocks.append(
            '<details class="area"><summary>'
            f"{escape(area.long_name)}{count}</summary>"
            f"{''.join(machine_blocks)}</details>"
        )

    n_machines = sum(len(a.equipment) for a in areas)
    areas_html = "\n".join(area_blocks) or "<p><em>(base de datos vacía)</em></p>"
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} — Visor RBM</title>
<style>{_CSS}</style>
</head>
<body>
<header><h1>{escape(title)}</h1>
<p>{len(areas):,} áreas · {n_machines:,} máquinas. Despliega una máquina para
cargar sus puntos y muestras; haz clic en una muestra para ver su gráfica.</p></header>
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
<script>{_JS}</script>
</body>
</html>
"""


def _make_handler(
    reader: RbmReader,
    points_by_rec: dict[int, Point],
    eq_points: dict[int, list[Point]],
    page_html: str,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass  # silence the default stderr access log

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: object) -> None:
            self._send(200, "application/json", json.dumps(payload, default=str).encode())

        def _machine_points(self, eq_rec: int) -> None:
            pts = eq_points.get(eq_rec)
            if pts is None:
                self._send(404, "text/plain", b"machine not found")
                return
            out: list[dict[str, Any]] = []
            for pt in pts:
                s = point_sample_summary(reader, pt)
                out.append(
                    {
                        "rec": pt.record_num,
                        "name": pt.long_name,
                        "fft": s.spectra.count,
                        "waveform": s.waveforms.count,
                        "trend": s.trend.count,
                    }
                )
            self._json({"points": out})

        def _point_samples(self, pt_rec: int, kind: str) -> None:
            point = points_by_rec.get(pt_rec)
            if point is None:
                self._send(404, "text/plain", b"point not found")
                return
            try:
                refs = point_sample_refs(reader, point, kind)
            except ValueError:
                self._send(400, "text/plain", b"bad sample kind")
                return
            samples = [
                {"id": r.record_num, "ts": r.timestamp_utc.strftime("%Y-%m-%d %H:%M")}
                for r in refs
            ]
            self._json({"samples": samples})

        def _plot(self, pt_rec: int, kind: str, sample_id: int) -> None:
            point = points_by_rec.get(pt_rec)
            if point is None:
                self._send(404, "text/plain", b"point not found")
                return
            try:
                png = render_point_sample_png(reader, point, kind, sample_id)
            except LiveViewerError as exc:
                self._send(404, "text/plain", f"{exc}".encode())
                return
            except Exception as exc:
                _log.warning("live_plot_failed", point=pt_rec, kind=kind, error=str(exc))
                self._send(500, "text/plain", f"render error: {exc}".encode())
                return
            self._send(200, "image/png", png)

        def do_GET(self) -> None:
            # path is one of: / | /api/machine/<rec> | /api/point/<rec>/<kind>
            #                 | /plot/<rec>/<kind>/<id>.png
            parts = [p for p in self.path.split("?", 1)[0].split("/") if p]
            if not parts:
                self._send(200, "text/html; charset=utf-8", page_html.encode())
                return
            try:
                if parts[0] == "api" and len(parts) == 3 and parts[1] == "machine":
                    self._machine_points(int(parts[2]))
                    return
                if parts[0] == "api" and len(parts) == 4 and parts[1] == "point":
                    self._point_samples(int(parts[2]), parts[3])
                    return
                if parts[0] == "plot" and len(parts) == 4 and parts[3].endswith(".png"):
                    self._plot(int(parts[1]), parts[2], int(parts[3][: -len(".png")]))
                    return
            except ValueError:
                self._send(400, "text/plain", b"bad request")
                return
            self._send(404, "text/plain", b"not found")

    return Handler


class _LiveServer(ThreadingHTTPServer):
    """``ThreadingHTTPServer`` that closes its backing ``RbmReader`` on shutdown."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        reader: RbmReader,
    ) -> None:
        super().__init__(server_address, handler)
        self._reader = reader

    def server_close(self) -> None:
        super().server_close()
        self._reader.close()


def serve(
    file: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> ThreadingHTTPServer:
    """Build and return a (not-yet-serving) live server over the ``.rbm`` ``file``.

    Opens a single read-only :class:`RbmReader`, walks the hierarchy once for
    the page, and returns a server that renders every plot on demand. The
    caller drives it with ``serve_forever``; ``server_close`` releases the
    reader.

    Raises:
        LiveViewerError: If the database cannot be opened/parsed.
    """
    file = Path(file)
    try:
        reader = RbmReader(file)
    except Exception as exc:
        raise LiveViewerError(f"cannot open {file}: {exc}") from exc
    try:
        areas = walk_hierarchy(reader)
        points_by_rec: dict[int, Point] = {}
        eq_points: dict[int, list[Point]] = {}
        for area in areas:
            for eq in area.equipment:
                eq_points[eq.record_num] = list(eq.points)
                for pt in eq.points:
                    points_by_rec[pt.record_num] = pt
        page_html = build_live_html(areas, title=file.name)
    except Exception:
        reader.close()
        raise
    handler = _make_handler(reader, points_by_rec, eq_points, page_html)
    return _LiveServer((host, port), handler, reader)
