#!/usr/bin/env python3
"""Fidelidad muestral de los diagnósticos previos recuperados (v0.2.0).

Uso:
    python verify_previous.py <dir_con_pdfs> <dir_ground_truth> [n_por_informe]

Toma una muestra aleatoria (semilla fija) de observaciones `retrospective` de
cada `*.diaggt.json` y comprueba que su `diagnosis_text` aparece **literal** en
el texto de la columna de la que salió, extraído por una vía independiente del
extractor: `page.crop(...).extract_text()` de pdfplumber, que reconstruye el
texto con su propio motor de layout en vez de con `words_to_lines`.

Un fallo aquí significa que el extractor está inventando o pegando texto de
sitios distintos; es la verificación que en v0.1 se hizo a mano sobre 240
muestras y que aquí queda como script reproducible.

Acompañante de `ams_extract.informes` (workplan 09): vive en `scripts/` y no
en `src/` porque es un arnés de verificación que necesita los PDFs originales
(49-73 MB) y no participa en la emisión. Se ejecuta con el extra instalado:

    uv run --extra informes python scripts/verify_previous.py <pdfs> <gt-dir>
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import pdfplumber

COLUMN_SPLIT_X = 297.0
HEADER_Y = 45.0
FOOTER_MARGIN = 40.0
SEED = 20260728


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def column_texts(page) -> list[str]:
    """Texto de cada columna por la vía nativa de pdfplumber (independiente)."""
    out = []
    y0, y1 = HEADER_Y, page.height - FOOTER_MARGIN
    for x0, x1 in ((0, COLUMN_SPLIT_X), (COLUMN_SPLIT_X, page.width)):
        crop = page.crop((x0, y0, x1, y1))
        out.append(flat(crop.extract_text() or ""))
    return out


def main() -> None:
    pdf_dir = Path(sys.argv[1])
    gt_dir = Path(sys.argv[2])
    per_doc = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    rng = random.Random(SEED)

    total = ok = 0
    failures: list[tuple] = []
    for gt_path in sorted(gt_dir.glob("*.diaggt.json")):
        doc = json.loads(gt_path.read_text(encoding="utf-8"))
        if doc["provenance"].get("origin") != "inspection-report":
            continue
        pdf_path = pdf_dir / doc["provenance"]["source_ref"]
        retro = [o for o in doc["observations"]
                 if o["record_kind"] == "retrospective" and o["diagnosis_text"]]
        sample = rng.sample(retro, min(per_doc, len(retro)))
        by_page: dict[int, list[dict]] = defaultdict(list)
        for o in sample:
            by_page[o["source_page"]].append(o)
        with pdfplumber.open(pdf_path) as pdf:
            for pno, obs in sorted(by_page.items()):
                page = pdf.pages[pno - 1]
                # el bloque puede desbordar a una página de continuación (§3.3);
                # en Abril la continuación de la p134 es la p136, con el estudio
                # ad-hoc «ACTUALIZACIÓN» en medio.
                pool = column_texts(page)
                for extra in (pno, pno + 1):
                    if extra < len(pdf.pages):
                        pool += column_texts(pdf.pages[extra])
                for o in obs:
                    total += 1
                    if any(flat(o["diagnosis_text"]) in t for t in pool):
                        ok += 1
                    else:
                        failures.append((pdf_path.name, pno, o["observation_id"],
                                         o["diagnosis_text"]))
        print(f"  {gt_path.name}: {len(sample)} muestras")

    print(f"\nFidelidad muestral de previos: {ok}/{total} "
          f"({ok / total * 100:.1f} %)")
    for f in failures:
        print(f"  [FALLO] {f[0]} p{f[1]} {f[2]}\n          {f[3]!r}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
