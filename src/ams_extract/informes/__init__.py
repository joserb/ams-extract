"""Ground truth de diagnóstico desde informes PDF de inspección (DiagGT).

Productor ``origin="inspection-report"`` de la spec ``docs/GROUND_TRUTH.md``:
lee los informes mensuales de un analista —hoy los de Preditec para BUNGE
Cartagena— y emite un ``<informe>.diaggt.json`` por documento más los
consolidados planos ``observations`` y ``findings``.

Reparto de módulos:

- :mod:`~ams_extract.informes.rules` — vocabularios DiagGT y mapeo
  texto→finding (reglas GTxxx, textos de estado, pesos). Sólo stdlib: es la
  capa que los tests de regresión ejercitan sin PDFs.
- :mod:`~ams_extract.informes.parse` — geometría de la ficha de máquina en el
  PDF y construcción del documento DiagGT. Necesita ``pdfplumber``, que entra
  como extra (``ams-extract[informes]``) y se importa dentro de las funciones
  que lo usan.
- :mod:`~ams_extract.informes.consolidate` — consolidados planos (§5 de la
  spec) en parquet y CSV.
- :mod:`~ams_extract.informes.cli` — el subcomando ``rbm informes``.

Procedencia del código: hasta 2026-08-04 esto fue ``extract_informes_gt.py``,
un script suelto en ``<informes>/ground-truth/`` (v0.2.0, auditoría de lectura
completa del 2026-07-28). Las copias que siguen en
``../Informes Bunge Cartagena 2026/ground-truth/`` y en
``ground-truth/`` del dataset ``bunge_cartagena_ams`` son **artefactos
desplegados** junto a la salida que produjeron, no código vivo: se conservan
como sello de aquella emisión y no se sincronizan con este subpaquete
(workplan 09).
"""

from __future__ import annotations

__all__ = ["EXTRACTOR_VERSION"]

EXTRACTOR_VERSION = "informes-gt-extract 0.5.0"
"""Herramienta y versión que se anota en ``provenance.extractor``.

0.5.0 recupera los desbordes de ``ANÁLISIS`` demostrables por modalidad,
amplía las fórmulas inequívocas de estado y añade ``GT026`` a ``GT029`` para
fallos que el censo 0.4.0 dejó sin mapa; ``GT004v2`` incorpora «huelgo».
0.4.0 corrigió las tres lecturas que el corpus desmintió (workplan 11):
``GT001v2`` casa también «desbalanceo», ``GT011v2`` no dispara sobre «buen
estado de lubricación» y ``GT021v2`` deja de llevar «excentricidad en polea»
al rotor eléctrico — la recoge ``GT025`` como fallo de transmisión. 0.3.0
repartió la masa de juicio entre las cláusulas del diagnóstico (``weight``,
DiagGT 0.1.5); 0.2.0 fue el fix de geometría de la auditoría de lectura
completa (2026-07-28). La adopción en el paquete, por sí sola, no cambió lo
que el extractor lee.
"""
