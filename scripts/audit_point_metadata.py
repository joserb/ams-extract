"""Regenerate the aggregate, non-identifying point-name metadata census."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ams_extract.point_naming import audit_name_corpus, propose_sibling_directions

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "tests" / "fixtures" / "bunge_point_names.json"
DEFAULT_OUTPUT = ROOT / "tests" / "fixtures" / "bunge_point_metadata_audit.json"


def _rbm_summary(rbm_path: Path) -> dict[str, object]:
    """Aggregate declarations and report-only proposals without sample payloads."""
    from ams_extract.reader import RbmReader
    from ams_extract.tree import walk_hierarchy

    with RbmReader(rbm_path) as reader:
        areas = walk_hierarchy(reader)
    machines = [equipment for area in areas for equipment in area.equipment]
    points = [point for equipment in machines for point in equipment.points]
    proposals = [
        proposal
        for equipment in machines
        for proposal in propose_sibling_directions(
            [point.long_name for point in equipment.points]
        )
    ]
    return {
        "areas": len(areas),
        "machines": len(machines),
        "points": len(points),
        "bearing_designations": {
            "declared": sum(bool(point.bearing_designations) for point in points),
            "multiple_slots": sum(len(point.bearing_designations) > 1 for point in points),
        },
        "nominal_speed_rpm": {
            "declared": sum(point.nominal_speed_rpm is not None for point in points),
        },
        "sibling_direction_proposals": {
            "report_only": len(proposals),
            "by_direction": {
                direction: sum(proposal.direction == direction for proposal in proposals)
                for direction in ("A", "H", "V")
            },
        },
    }


def _render(corpus_path: Path, rbm_path: Path | None = None) -> str:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    result = audit_name_corpus(corpus["names"])
    result["source"] = corpus_path.name
    if rbm_path is not None:
        result["live_rbm"] = _rbm_summary(rbm_path)
    return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--rbm",
        type=Path,
        help="add aggregate declarations and sibling proposals from a real RBM",
    )
    parser.add_argument(
        "--check", action="store_true", help="fail if the committed report is stale"
    )
    args = parser.parse_args()
    if args.rbm is not None and args.out == DEFAULT_OUTPUT:
        parser.error("--rbm requires an explicit --out to preserve the committed census")
    rendered = _render(args.corpus, args.rbm)
    if args.check:
        if not args.out.exists() or args.out.read_text(encoding="utf-8") != rendered:
            parser.error(f"{args.out} is stale; regenerate without --check")
        return 0
    args.out.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
