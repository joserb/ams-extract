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

EXTRACTOR_VERSION = "informes-gt-extract 0.3.0"
"""Herramienta y versión que se anota en ``provenance.extractor``.

0.3.0 reparte la masa de juicio entre las cláusulas del diagnóstico
(``weight``, DiagGT 0.1.5); 0.2.0 fue el fix de geometría de la auditoría de
lectura completa (2026-07-28). La adopción en el paquete, por sí sola, no
cambió lo que el extractor lee.
"""
