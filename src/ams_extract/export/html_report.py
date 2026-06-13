"""Render the database inventory as a self-contained interactive HTML page.

One ``.html`` file, no external dependencies: inline CSS, a collapsible
``<details>`` tree (area → machine) that works without scripting, plus a
small inline ``<script>`` adding a live machine filter (degrades gracefully
when JS is disabled). Backs ``rbm report`` and the ``report.html`` that
``rbm export`` drops into the dataset directory.

All names that originate from the database are escaped with
:func:`html.escape` before interpolation.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

from ams_extract.report import AreaInventory, InventoryReport, MachineInventory
from ams_extract.tree import TypeSummary

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  font: 14px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  margin: 0; padding: 1.5rem; max-width: 1100px; margin: 0 auto;
  color: #1a1a1a; background: #fafafa;
}
@media (prefers-color-scheme: dark) {
  body { color: #e6e6e6; background: #161616; }
  header, details { background: #1f1f1f !important; border-color: #333 !important; }
  th { background: #262626 !important; }
  tr:nth-child(even) td { background: #1c1c1c !important; }
  input { background: #262626; color: #e6e6e6; border-color: #444; }
}
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
header {
  background: #fff; border: 1px solid #e2e2e2; border-radius: 8px;
  padding: 1rem 1.25rem; margin-bottom: 1.25rem;
}
.meta { color: #666; font-size: .85rem; }
.totals { margin-top: .75rem; display: flex; flex-wrap: wrap; gap: .5rem 1.25rem; }
.totals b { font-variant-numeric: tabular-nums; }
.controls { margin-bottom: 1rem; }
input[type=search] {
  width: 100%; padding: .55rem .75rem; font-size: 1rem;
  border: 1px solid #ccc; border-radius: 6px;
}
details {
  background: #fff; border: 1px solid #e2e2e2; border-radius: 8px;
  margin-bottom: .6rem; padding: 0 .75rem;
}
summary {
  cursor: pointer; padding: .6rem .25rem; font-weight: 600;
  list-style-position: inside;
}
summary .badges { font-weight: 400; color: #666; font-size: .85rem; }
table { width: 100%; border-collapse: collapse; margin: .25rem 0 .75rem; }
th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #eee; }
th { background: #f5f5f5; font-size: .78rem; text-transform: uppercase; color: #555; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.dates { white-space: nowrap; color: #555; font-size: .85rem; }
.machine { font-weight: 600; }
.zero { color: #bbb; }
.hidden { display: none !important; }
.empty { color: #999; font-style: italic; padding: .5rem .25rem; }
.viewer-link {
  margin-top: .75rem; font-size: .9rem;
}
.viewer-link a { color: #1a6; font-weight: 600; text-decoration: none; }
.viewer-link a:hover { text-decoration: underline; }
.viewer-link code {
  background: #eee; padding: .1rem .35rem; border-radius: 4px; font-size: .85em;
}
@media (prefers-color-scheme: dark) { .viewer-link code { background: #2a2a2a; } }
"""

_FILTER_JS = """
(function () {
  var box = document.getElementById('filter');
  if (!box) return;
  var areas = Array.prototype.slice.call(document.querySelectorAll('details.area'));
  box.addEventListener('input', function () {
    var q = box.value.trim().toLowerCase();
    areas.forEach(function (area) {
      var rows = area.querySelectorAll('tr.machine-row');
      var anyVisible = false;
      rows.forEach(function (row) {
        var hit = !q || row.getAttribute('data-name').indexOf(q) !== -1;
        row.classList.toggle('hidden', !hit);
        if (hit) anyVisible = true;
      });
      area.classList.toggle('hidden', !anyVisible);
      if (q) area.open = anyVisible;
    });
  });
})();
"""


def _fmt_date(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d") if dt is not None else "—"


def _date_span(summary: TypeSummary) -> str:
    if summary.count == 0:
        return "—"
    first = _fmt_date(summary.first)
    last = _fmt_date(summary.last)
    return first if first == last else f"{first} → {last}"


def _count_cls(n: int) -> str:
    return "num zero" if n == 0 else "num"


def _machine_row(m: MachineInventory) -> str:
    name = escape(m.equipment_long)
    data_name = escape(m.equipment_long.lower(), quote=True)
    return (
        f'<tr class="machine-row" data-name="{data_name}">'
        f'<td class="machine">{name}</td>'
        f'<td class="num">{m.n_points}</td>'
        f'<td class="{_count_cls(m.spectra.count)}">{m.spectra.count:,}</td>'
        f'<td class="dates">{_date_span(m.spectra)}</td>'
        f'<td class="{_count_cls(m.waveforms.count)}">{m.waveforms.count:,}</td>'
        f'<td class="dates">{_date_span(m.waveforms)}</td>'
        f'<td class="{_count_cls(m.trend.count)}">{m.trend.count:,}</td>'
        f'<td class="dates">{_date_span(m.trend)}</td>'
        "</tr>"
    )


def _area_block(area: AreaInventory) -> str:
    sp = sum(m.spectra.count for m in area.machines)
    wv = sum(m.waveforms.count for m in area.machines)
    tn = sum(m.trend.count for m in area.machines)
    badges = (
        f'<span class="badges">— {len(area.machines)} máquinas · '
        f"{sp:,} espectros · {wv:,} ondas · {tn:,} tendencias</span>"
    )
    if area.machines:
        rows = "\n".join(_machine_row(m) for m in area.machines)
        body = (
            "<table>"
            "<thead><tr>"
            "<th>Máquina</th><th>Pts</th>"
            "<th>Espectros</th><th>Fechas</th>"
            "<th>Ondas</th><th>Fechas</th>"
            "<th>Tendencias</th><th>Fechas</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    else:
        body = '<div class="empty">(sin máquinas)</div>'
    return (
        '<details class="area">'
        f"<summary>{escape(area.long_name)} {badges}</summary>"
        f"{body}"
        "</details>"
    )


def render_inventory_html(
    report: InventoryReport, *, viewer_url: str | None = None
) -> str:
    """Return the full HTML document for ``report`` as a string.

    When ``viewer_url`` is given, the header shows a link to the on-demand
    viewer (``rbm serve``) plus a reminder of how to start it. It is left
    ``None`` for the standalone ``rbm report`` (which has no dataset to serve).
    """
    title = report.description or report.source or "Inventario RBM"
    sp, wv, tn = report.spectra, report.waveforms, report.trend
    meta_bits: list[str] = []
    if report.source:
        meta_bits.append(escape(Path(report.source).name))
    if report.signature:
        meta_bits.append(f"formato {escape(report.signature)}")
    meta_line = " · ".join(meta_bits)

    viewer_html = (
        f'<div class="viewer-link">📈 <a href="{escape(viewer_url, quote=True)}">'
        "Abrir visor de espectros / ondas / tendencias</a> "
        "<span class=\"meta\">— requiere <code>rbm serve</code> en marcha</span></div>"
        if viewer_url
        else ""
    )

    areas_html = (
        "\n".join(_area_block(a) for a in report.areas)
        if report.areas
        else '<div class="empty">(sin áreas)</div>'
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} — Inventario RBM</title>
<style>{_CSS}</style>
</head>
<body>
<header>
<h1>{escape(title)}</h1>
<div class="meta">{meta_line}</div>
<div class="totals">
<span>{report.n_areas:,} áreas</span>
<span>{report.n_machines:,} máquinas</span>
<span>{report.n_points:,} puntos</span>
<span><b>{sp.count:,}</b> espectros</span>
<span><b>{wv.count:,}</b> ondas</span>
<span><b>{tn.count:,}</b> tendencias</span>
</div>
{viewer_html}
</header>
<div class="controls">
<input type="search" id="filter" placeholder="Filtrar máquinas…" autocomplete="off">
</div>
<main>
{areas_html}
</main>
<script>{_FILTER_JS}</script>
</body>
</html>
"""


def write_inventory_html(
    report: InventoryReport, output_path: Path, *, viewer_url: str | None = None
) -> None:
    """Render ``report`` and write it as UTF-8 HTML to ``output_path``."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_inventory_html(report, viewer_url=viewer_url), encoding="utf-8"
    )
