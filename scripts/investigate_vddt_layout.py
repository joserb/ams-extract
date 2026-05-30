"""Throwaway diagnostic: crack the per-sample layout inside a `vddt` record.

vddt = AMS "Valores Globales" + named-bands trend (overall RMS velocity in
in/s = mm/s / 25.4, plus SUBSINCRONO/DESEQUILIBRIO/... bands), a time series
over years. The chain structure is known (pdcd.0x3C/0x40 -> vddt chain via
0x10; per-record date range at 0x18/0x1C; 0x24 = ?). What is NOT solved is
how samples are laid out *inside* a record: stride, value<->timestamp index.

Hard anchors (M1H AG-100, record 336990), from the prior session's gold:
  - 0x5C -> 0.6038  == 15.34 mm/s  (2017-04-20)
  - 0x100 -> 1.4341 == 36.43 mm/s  (2017-07-13, the trend peak)
Scale: overall_mm_s = float32 * 25.4.

This dumps the 6 vddt of M1H and, for 336990, prints every 4-byte slot as
(offset, hex, float32, mm/s-if-plausible, u32-as-date-if-plausible) so the
columnar-vs-interleaved question can be settled by eye.

Run:
  RBM_TEST_FILE="../AMS databases/BUNGE CARTAGENA marzo 2.0.rbm" \
    uv run python scripts/investigate_vddt_layout.py
"""

from __future__ import annotations

import os
import struct
from datetime import UTC, datetime
from pathlib import Path

from ams_extract.reader import RbmReader, decode_inner_pointer

PDCD_FIRST_VDDT = 0x3C
PDCD_LAST_VDDT = 0x40
NEXT_OFF = 0x10
MM_PER_INCH = 25.4

# M1H AG-100 anchors (overall value -> mm/s, date) inside record 336990.
ANCHORS = {0x5C: (0.6038, 15.34, "2017-04-20"), 0x100: (1.4341, 36.43, "2017-07-13")}
M1H_VDDT_CHAIN = [336987, 336988, 336989, 336990, 336991, 336992]


def as_date(u: int) -> str | None:
    """Plausible Unix timestamp in the trend's lifetime (2012-2021)?"""
    if 1_325_376_000 <= u <= 1_640_995_200:  # 2012-01-01 .. 2022-01-01
        return datetime.fromtimestamp(u, UTC).strftime("%Y-%m-%d")
    return None


def as_mm_s(f: float) -> str:
    """A float that, *25.4, lands in a believable overall RMS velocity?"""
    mm = f * MM_PER_INCH
    return f"{mm:7.2f}mm/s" if 0.1 <= mm <= 60.0 else ""


def dump_record(reader: RbmReader, rn: int, *, full: bool) -> None:
    rec = reader.read_record(rn)
    tag = rec[0x08:0x0C]
    (nxt,) = struct.unpack_from("<I", rec, NEXT_OFF)
    (backref,) = struct.unpack_from("<I", rec, 0x14)
    (d0,) = struct.unpack_from("<I", rec, 0x18)
    (d1,) = struct.unpack_from("<I", rec, 0x1C)
    (n24,) = struct.unpack_from("<I", rec, 0x24)
    print(f"\n=== vddt {rn}  tag={tag!r}  next={decode_inner_pointer(nxt)} "
          f"backref={decode_inner_pointer(backref)} ===")
    print(f"  0x18 d0={d0} ({as_date(d0)})   0x1C d1={d1} ({as_date(d1)})   "
          f"0x24 n={n24}")
    if not full:
        return
    print("  off    hex         float32        mm/s?        u32-date?")
    for off in range(0x0C, 0x200, 4):
        raw = rec[off:off + 4]
        (f,) = struct.unpack_from("<f", rec, off)
        (u,) = struct.unpack_from("<I", rec, off)
        date = as_date(u)
        mm = as_mm_s(f)
        mark = " <==ANCHOR" if off in ANCHORS else ""
        # only print interesting rows: a plausible value, a date, or non-zero
        if mm or date or (u != 0 and abs(f) > 1e-12):
            print(f"  0x{off:03X}  {raw.hex():>8}  {f:13.6g}  {mm:>11}  "
                  f"{date or '':>10}{mark}")


def main() -> None:
    path = os.environ.get("RBM_TEST_FILE")
    if not path:
        raise SystemExit("set RBM_TEST_FILE")
    with RbmReader(Path(path)) as reader:
        # First confirm the anchors decode as remembered.
        rec = reader.read_record(336990)
        print("Anchor check on 336990:")
        for off, (val, mm, date) in ANCHORS.items():
            (f,) = struct.unpack_from("<f", rec, off)
            ok = "OK" if abs(f - val) < 1e-3 else "MISMATCH"
            print(f"  0x{off:03X}: got {f:.4f}  expect {val} ({mm} mm/s, {date}) [{ok}]")

        for rn in M1H_VDDT_CHAIN:
            dump_record(reader, rn, full=(rn == 336990))


if __name__ == "__main__":
    main()
