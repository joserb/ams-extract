#!/usr/bin/env python3
"""Crosswalk DiagGT ↔ VibFrame: resuelve `normalized_tag` → `machine_id`.

Uso:
    python crosswalk_gt.py <dir_dataset_vibframe> <dir_ground_truth> [--dry-run]

Entradas:
    <dir_dataset_vibframe>/machine=<machine_id>/machine.json   (particiones VibFrame)
    <dir_ground_truth>/*.diaggt.json                           (documentos DiagGT)

Salidas (en <dir_ground_truth>):
    crosswalk.csv               — tabla explícita tag ↔ machine_id, una fila por
                                  `normalized_tag`, con regla aplicada y candidatos
    crosswalk_ambiguities.md    — ambigüedades, no-matches y máquinas del dataset
                                  sin ground truth, con la resolución propuesta
    observations.parquet, observations_consolidated.parquet, findings.parquet,
    materialization.json        — proyecciones 0.2 re-materializadas con la
                                  columna `dataset_machine_id` proyectada
                                  (esquema explícito del contrato; sin CSV)

El post-proceso es **no destructivo** (spec DiagGT §2.4): los `*.diaggt.json` no
se tocan — el crosswalk vive en `crosswalk.csv` (tabla explícita) y se proyecta
sobre las proyecciones, que son la vista pensada para el join con VibFrame. La
re-materialización la hace `ams_extract.informes.consolidate`, el mismo
materializador del paquete, de modo que las proyecciones y su
`materialization.json` nunca divergen de esquema por culpa de este script.

Reglas de matching (CWxxx, versionadas como las GTxxx del extractor). El
candidato debe cumplir la regla base de la spec (`normalized_tag` ⊂
`norm(machine_id)`); entre los candidatos gana el nivel más fuerte:

    CW001 exact_suffix — el tag es la concatenación de los últimos tokens del
                         machine_id ("PM9442" ⊂ Bomba_Centrifuga_PM_9442).
    CW002 delimited    — el tag es una secuencia completa de tokens, pero no
                         final ("PM9442" en Bomba_Centrifuga_PM_9442_A).
    CW003 substring    — subcadena a secas, sin respetar límites de token
                         ("PM100" en Bomba_Centrifuga_PM_1001). Regla base de
                         la spec; sólo se usa si no hay candidatos mejores.
    CW004 reverse_unique — un `machine_id` no puede ser reclamado por dos tags:
                         gana el de nivel más fuerte, el resto queda sin match
                         (evita que "MA.9306", que no existe en el dataset, se
                         cuelgue de MECLADOR_AGITADOR_MA_9306_B).

Sólo se rellena `dataset_machine_id` cuando el nivel ganador deja exactamente
un candidato. Ambigüedades y no-matches quedan a null y documentados.

Acompañante de `ams_extract.informes` (workplan 09): vive en `scripts/` y no
en `src/` porque es un post-proceso que se ejecuta una vez por par (informes,
dataset) y produce una tabla que se cura a mano. Usa pandas, que no es
dependencia del paquete:

    uv run --with pandas python scripts/crosswalk_gt.py <dataset> <ground-truth>

El extractor integrado *proyecta* el `crosswalk.csv` resultante sobre sus
consolidados, así que basta con re-ejecutar este script cuando cambie el
dataset o la lista de tags, no en cada emisión.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

import pandas as pd

CROSSWALK_VERSION = "informes-gt-crosswalk 0.1.0"

# niveles de match, del más fuerte al más débil
TIERS: list[tuple[str, str]] = [
    ("exact_suffix", "CW001"),
    ("delimited", "CW002"),
    ("substring", "CW003"),
]
TIER_RULE = dict(TIERS)
TIER_ORDER = [t for t, _ in TIERS]


def norm(text: str) -> str:
    """Normaliza para join: mayúsculas, sin diacríticos, sin separadores."""
    t = unicodedata.normalize("NFKD", str(text).upper())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]", "", t)


def area_key(area: str | None) -> str:
    """Clave laxa de área: 'PARQUE DE TANQUES' (informe) == 'PARQUE TANQUES'
    (`machine.path` del dataset). Sólo para control de sanidad y evidencia."""
    return norm(area or "").replace("DE", "")


def tokens(machine_id: str) -> list[str]:
    return [norm(t) for t in re.split(r"[^A-Za-z0-9]+", machine_id) if t]


def match_tier(tag: str, machine_id: str) -> str | None:
    """Nivel de match de `tag` contra `machine_id`, o None si no hay match."""
    toks = tokens(machine_id)
    n = len(toks)
    for i in range(n):
        acc = ""
        for j in range(i, n):
            acc += toks[j]
            if acc == tag:
                return "exact_suffix" if j == n - 1 else "delimited"
            if len(acc) >= len(tag):
                break
    return "substring" if tag in norm(machine_id) else None


# ---------------------------------------------------------------------------
# Lectura del dataset VibFrame
# ---------------------------------------------------------------------------

def read_dataset(dataset_dir: Path) -> pd.DataFrame:
    """Una fila por partición `machine=`: id, nombre legible, área y cobertura."""
    rows = []
    for part in sorted(dataset_dir.glob("machine=*")):
        machine_id = part.name.split("=", 1)[1]
        name = path = None
        mj = part / "machine.json"
        if mj.exists():
            doc = json.loads(mj.read_text(encoding="utf-8")).get("machine", {})
            name = doc.get("name")
            path = " / ".join(doc.get("path") or [])
        rows.append({"machine_id": machine_id, "machine_name": name,
                     "machine_path": path})
    return pd.DataFrame(rows)


def trend_coverage(dataset_dir: Path, machine_id: str) -> tuple[str | None, str | None, int]:
    """(primera, última) fecha de `trends.parquet` y nº de puntos. `t` es µs epoch."""
    f = dataset_dir / f"machine={machine_id}" / "trends.parquet"
    if not f.exists():
        return None, None, 0
    tr = pd.read_parquet(f, columns=["t"])
    if tr.empty:
        return None, None, 0
    lo = pd.to_datetime(tr["t"].min(), unit="us").date().isoformat()
    hi = pd.to_datetime(tr["t"].max(), unit="us").date().isoformat()
    return lo, hi, len(tr)


# ---------------------------------------------------------------------------
# Crosswalk
# ---------------------------------------------------------------------------

def build_crosswalk(tags: pd.DataFrame, machines: pd.DataFrame) -> pd.DataFrame:
    """tags: columnas normalized_tag, external_tag, external_name, area_*."""
    machine_ids = list(machines["machine_id"])
    rows = []
    for rec in tags.itertuples(index=False):
        tag = rec.normalized_tag
        cands = [(m, k) for m in machine_ids if (k := match_tier(tag, m))]
        best = next((t for t in TIER_ORDER if any(k == t for _, k in cands)), None)
        sel = [m for m, k in cands if k == best]
        rows.append({
            "normalized_tag": tag,
            "external_tag": rec.external_tag,
            "external_name": rec.external_name,
            "area_code": rec.area_code,
            "area_name": rec.area_name,
            "dataset_machine_id": sel[0] if best and len(sel) == 1 else None,
            "match_rule": TIER_RULE[best] if best and len(sel) == 1 else None,
            "match_tier": best,
            "n_candidates": len(sel),
            "candidates": "|".join(sel),
            "all_candidates": "|".join(f"{m}:{k}" for m, k in cands),
            "resolution": ("matched" if best and len(sel) == 1
                           else "ambiguous" if best else "unmatched"),
        })
    cw = pd.DataFrame(rows)

    # CW004: un machine_id no puede colgar de dos tags. Gana el nivel más fuerte;
    # si empatan, ninguno (se deja explícito como ambigüedad inversa).
    matched = cw[cw["dataset_machine_id"].notna()]
    for _mid, grp in matched.groupby("dataset_machine_id"):
        if len(grp) == 1:
            continue
        ranks = grp["match_tier"].map(TIER_ORDER.index)
        winners = grp.index[ranks == ranks.min()]
        keep = winners[0] if len(winners) == 1 else None
        for idx in grp.index:
            if idx == keep:
                cw.loc[idx, "match_rule"] = f"{cw.loc[idx, 'match_rule']}+CW004"
                continue
            cw.loc[idx, "dataset_machine_id"] = None
            cw.loc[idx, "match_rule"] = None
            cw.loc[idx, "resolution"] = "reverse_collision"
    return cw.sort_values("normalized_tag").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Informe de ambigüedades
# ---------------------------------------------------------------------------

def md_table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) if c not in (None, "") else "—" for c in r) + " |"
            for r in rows]
    return "\n".join(out)


def write_ambiguities(path: Path, cw: pd.DataFrame, machines: pd.DataFrame,
                      dataset_dir: Path, dataset_name: str) -> None:
    n_tags = len(cw)
    n_ok = int(cw["dataset_machine_id"].notna().sum())
    problems = cw[cw["dataset_machine_id"].isna()]

    def cov(mid: str) -> str:
        lo, hi, n = trend_coverage(dataset_dir, mid)
        return f"{lo}…{hi} ({n} pts)" if lo else "sin trends"

    lines = [
        "# Crosswalk DiagGT ↔ VibFrame — ambigüedades y no-matches",
        "",
        f"Generado por `crosswalk_gt.py` ({CROSSWALK_VERSION}) contra el dataset "
        f"`{dataset_name}` ({len(machines)} particiones `machine=`).",
        "",
        f"- `normalized_tag` únicos en los `*.diaggt.json` por resolver: **{n_tags}**",
        f"- con `dataset_machine_id` resuelto: **{n_ok}** "
        f"({n_ok / n_tags * 100:.1f} %)",
        f"- sin resolver (esta tabla): **{n_tags - n_ok}**",
        "",
        "Reglas aplicadas (ver docstring de `crosswalk_gt.py`): CW001 "
        "`exact_suffix` > CW002 `delimited` > CW003 `substring` (regla base de la "
        "spec, §2.4) + CW004 unicidad inversa. Sólo se rellena "
        "`dataset_machine_id` cuando el nivel ganador deja un único candidato; "
        "lo demás queda a null y documentado aquí — la spec manda no forzar "
        "matches dudosos.",
        "",
        "## 1. Tags sin `dataset_machine_id`",
        "",
    ]
    used = set(cw["dataset_machine_id"].dropna())
    free = machines[~machines["machine_id"].isin(used)]
    rows = []
    for r in problems.itertuples(index=False):
        cands = [c for c in r.all_candidates.split("|") if c]
        cand_txt = ", ".join(f"`{c.split(':')[0]}` ({c.split(':')[1]})" for c in cands)
        same_area = free[free["machine_path"].map(area_key) == area_key(r.area_name)]
        area_txt = ", ".join(f"`{m}`" for m in same_area["machine_id"])
        rows.append([f"`{r.normalized_tag}`", r.external_tag, r.external_name,
                     r.area_name, r.resolution, cand_txt or "sin candidatos",
                     area_txt or "ninguna"])
    lines.append(md_table(
        ["normalized_tag", "TAG informe", "nombre informe", "área", "motivo",
         "candidatos (nivel)", "máquinas libres en la misma área"], rows))
    lines += ["", "## 2. Resolución propuesta", "", AMBIGUITY_NOTES, ""]

    # Ambigüedades resueltas por CW001/CW004 que merecen constancia: tags cuyo
    # conjunto de candidatos bajo la regla base de la spec era > 1.
    lines += ["## 3. Ambigüedades de la regla base resueltas por CW001/CW002", "",
              "Tags donde la regla base de la spec (subcadena) daba varios "
              "candidatos y el nivel de match los desempató sin intervención "
              "manual. Se listan con la cobertura de `trends.parquet` de cada "
              "candidato como evidencia auditable.", ""]
    rows = []
    for r in cw[cw["dataset_machine_id"].notna()].itertuples(index=False):
        cands = [c for c in r.all_candidates.split("|") if c]
        if len(cands) < 2:
            continue
        detail = []
        for c in cands:
            mid, tier = c.split(":")
            mark = "**←**" if mid == r.dataset_machine_id else ""
            detail.append(f"`{mid}` ({tier}, {cov(mid)}) {mark}".strip())
        rows.append([f"`{r.normalized_tag}`", r.external_tag, r.match_rule,
                     f"`{r.dataset_machine_id}`", "<br>".join(detail)])
    lines.append(md_table(
        ["normalized_tag", "TAG informe", "regla", "elegido", "candidatos"], rows))
    lines += ["", SPLIT_HISTORY_NOTE]

    # Máquinas del dataset sin ninguna observación DiagGT
    orphan = free
    lines += ["", f"## 4. Máquinas del dataset sin ground truth ({len(orphan)})", "",
              "No aparecen en los 6 informes 2026 (máquinas obsoletas, fuera de "
              "ruta, o con TAG que el informe no nombra). Se listan para "
              "auditoría del alcance del GT, no son un error del crosswalk.", ""]
    rows = [[f"`{r.machine_id}`", r.machine_name, r.machine_path]
            for r in orphan.itertuples(index=False)]
    lines.append(md_table(["machine_id", "nombre", "área"], rows))
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


AMBIGUITY_NOTES = """\
- **`AG.8011B`, `AG.8013`, `AG.8033E` (PARQUE DE TANQUES)** — no hay ningún
  `AG.80xx` en el dataset: las bombas `PM.8011A` / `PM.8033A` que comparten
  número están en PASILLO DE BOMBAS, son otro equipo y ya tienen su propio tag
  en el informe. Las máquinas físicas sí parecen estar exportadas, pero AMS las
  nombra sin TAG (`AGITADOR`, `AGITADOR_1..3`, `MEZCLADOR`, todas en PARQUE
  TANQUES): el crosswalk por identificador es imposible y asignarlas por orden
  sería inventar. Sin match; resolubles a mano con la lista de equipos de
  planta (columna «máquinas libres en la misma área» de la tabla anterior).
- **`FLOT.4500` (DEPURADORA, «MOTOR REDUCTOR»)** — existe
  `Bomba_Centrifuga_PM_4500` en DEPURADORA, pero es otro equipo (bomba) y ya
  está reclamado por el tag `PM.4500` del propio informe. Sin match.
- **`MA.9451` (REFINERIA, «MEZCLADOR AGITADOR»)** — el dataset sólo tiene
  `Bomba_Centrifuga_PM_9451`, bomba homónima en número y ya reclamada por el
  tag `PM.9451`. Sin match.
- **`PM.9645B`** — el dataset sólo tiene `Bomba_Centrifuga_PM_9645_A`; la
  gemela B no está exportada. Mapear B→A falsearía el GT. Sin match.
- **`PM.9704B`** — el dataset tiene `Bomba_Centrifuga_PM_9704` (sin sufijo),
  que ya es el match exacto del tag `PM.9704`, presente también en el informe.
  La B no existe en el dataset. Sin match.
- **`MA.9306`** — colisión inversa (CW004): el único candidato,
  `MECLADOR_AGITADOR_MA_9306_B`, es el match exacto (CW001) del tag hermano
  `MA.9306B`, que también aparece en el informe. `MA.9306` se queda sin
  máquina propia en el dataset. Sin match.
- **`PM.OSMOSIS1` / `PM.OSMOSIS2` (OSMOSIS)** — el área OSMOSIS del dataset
  tiene exactamente dos bombas, `Bomba_Centrifuga_PM_1001` y
  `Bomba_Centrifuga_PM_1002`, ninguna reclamada por otro tag del informe (que
  no nombra `PM.1001`/`PM.1002`). La correspondencia 1↔1001, 2↔1002 es muy
  plausible (misma área, mismo tipo, mismo cardinal) pero es una **inferencia
  por posición, no un match de identificador**: se deja propuesta y sin
  aplicar. Confirmarla requiere la lista de equipos de planta o el informe en
  papel; si se confirma, la vía es una entrada manual en `crosswalk.csv`.
"""

SPLIT_HISTORY_NOTE = """\
**Caveat — historia partida en dos particiones.** `MA.9606` es el único match
donde los dos candidatos son *la misma máquina física*: ambas particiones
llevan el mismo `machine.name` («MECLADOR AGITADOR MA-9606») y el sufijo `_1`
del `machine_id` es la desambiguación que añade ams-extract ante nombres
repetidos, no un TAG de planta. Sus históricos son complementarios
(2013-02-28…2023-08-24 en `_1`, 2022-08-23…2026-03-25 en la otra), así que el
crosswalk apunta a la partición que cubre la ventana del ground truth
(2025-04…2026-06) y quien quiera el histórico completo debe unir las dos.
Mismo patrón, sin GT asociado, en `AGITADOR`/`AGITADOR_1..3` y
`REDUCTOR_TOASTER_DT_0070`/`_1`.
"""


# ---------------------------------------------------------------------------

def read_gt_tags(gt_dir: Path) -> pd.DataFrame:
    """Tags únicos de TODOS los `*.diaggt.json` del directorio.

    De los documentos fuente, no de una proyección previa: el crosswalk no
    depende de que las proyecciones existan ni de su generación. Los
    documentos con `dataset_machine_id` ya resuelto por su productor (las
    alarmas del sistema) también aportan su tag — el crosswalk no lo pisa,
    porque el materializador sólo proyecta la tabla sobre los tags cuya
    columna venga a null en el documento.
    """
    rows: list[dict[str, object]] = []
    for path in sorted(gt_dir.glob("*.diaggt.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for observation in document["observations"]:
            machine = observation["machine"]
            if machine["dataset_machine_id"]:
                continue  # ya resuelto en origen: nada que crosswalkear
            rows.append({
                "normalized_tag": machine["normalized_tag"],
                "external_tag": machine["external_tag"],
                "external_name": machine["external_name"],
                "area_code": machine["area_code"],
                "area_name": machine["area_name"],
            })
    if not rows:
        return pd.DataFrame(columns=["normalized_tag", "external_tag", "external_name",
                                     "area_code", "area_name"])
    return (pd.DataFrame(rows)
            .drop_duplicates("normalized_tag").sort_values("normalized_tag"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Crosswalk DiagGT ↔ VibFrame")
    ap.add_argument("dataset_dir", type=Path, help="dataset VibFrame (con machine=*)")
    ap.add_argument("gt_dir", type=Path, help="directorio ground-truth con *.diaggt.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="no escribe nada, sólo informa de la cobertura")
    args = ap.parse_args()

    machines = read_dataset(args.dataset_dir)
    if machines.empty:
        raise SystemExit(f"sin particiones machine= en {args.dataset_dir}")
    tags = read_gt_tags(args.gt_dir)
    if tags.empty:
        raise SystemExit(f"sin *.diaggt.json con tags por resolver en {args.gt_dir}")
    cw = build_crosswalk(tags, machines)

    mapping = dict(cw.dropna(subset=["dataset_machine_id"])
                     .set_index("normalized_tag")["dataset_machine_id"])

    n_tags, n_ok = len(cw), int(cw["dataset_machine_id"].notna().sum())
    n_amb = int((cw["resolution"].isin(["ambiguous", "reverse_collision"])).sum())
    n_none = int((cw["resolution"] == "unmatched").sum())

    # control de sanidad: el área del informe debe coincidir con machine.path
    minfo = machines.set_index("machine_id")
    bad_area = [
        (r.normalized_tag, r.dataset_machine_id, r.area_name,
         minfo.loc[r.dataset_machine_id, "machine_path"])
        for r in cw.dropna(subset=["dataset_machine_id"]).itertuples(index=False)
        if area_key(r.area_name) != area_key(minfo.loc[r.dataset_machine_id, "machine_path"])
    ]

    print(f"tags únicos          : {n_tags}")
    print(f"  match único        : {n_ok} ({n_ok / n_tags * 100:.1f} %)")
    print(f"  ambiguos/colisión  : {n_amb}")
    print(f"  sin match          : {n_none}")
    print(f"máquinas del dataset : {len(machines)}")
    print(f"discrepancias de área: {len(bad_area)}")
    for row in bad_area:
        print(f"  [warn] {row}")

    if args.dry_run:
        print("(dry-run: no se ha escrito nada)")
        return

    cw.to_csv(args.gt_dir / "crosswalk.csv", index=False)
    write_ambiguities(args.gt_dir / "crosswalk_ambiguities.md", cw, machines,
                      args.dataset_dir, args.dataset_dir.name)

    # Re-materializa las proyecciones 0.2 con el materializador del paquete —
    # nunca con pandas: el esquema explícito del contrato es suyo.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from ams_extract.informes.consolidate import materialize_ground_truth

    summary = materialize_ground_truth(args.gt_dir, crosswalk=mapping)
    print(f"observaciones        : {summary.observations} "
          f"({summary.consolidated} consolidadas, {summary.findings} findings)")
    print("escrito: crosswalk.csv, crosswalk_ambiguities.md, "
          + ", ".join(p.name for p in summary.written))


if __name__ == "__main__":
    main()
