"""Tape-measure sheet -> ground truth, without knowing the pipeline's wall ids.

The person measuring labels walls A, B, C... clockwise from the door wall
(docs: measurements sheet). The pipeline numbers walls its own way. This
module finds the correspondence automatically, per room:

  * every sheet room is tried against every plan room;
  * walls are aligned as a cyclic sequence, both directions, any start;
  * plan walls may be skipped (tiny stubs the tape person ignored), at a
    cost equal to their length, so a skipped wall must be genuinely short;
  * rooms are assigned one-to-one by minimum total cost (Hungarian).

Then openings are matched on the corresponding wall by width. Sheet
openings with no prediction are MISSED; predicted openings in a matched
room that the sheet does not list are PHANTOMS. Both count against the
opening gate. The output is the same ground-truth JSON that
`benchmark/ground_truth.py score` reads, so scoring is unchanged.

Sheet format (JSON, centimetres, repeated readings averaged):
{
  "capture_id": "...",
  "measured_with": "steel tape",
  "rooms": [
    {"name": "bedroom",
     "walls_cm": [[312.5, 312.7], [281.0, 281.2], ...],      # A, B, C... clockwise
     "ceiling_cm": [[251.0, 251.2]],
     "openings": [{"kind": "door", "wall": "A", "width_cm": [81.5, 81.6]},
                  {"kind": "window", "wall": "C", "width_cm": [120.1]}]}
  ]
}

    python -m benchmark.sheet --plan outputs/<cap>/plan.json --sheet sheets/home.json \
        --out benchmark/ground_truth/<cap>.json
"""
from __future__ import annotations

import argparse
import json
import re
import string
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

SKIP_PER_M = 1.0          # cost of leaving a plan wall unmatched, per metre of it
UNMATCHED_SHEET = 5.0     # cost of a sheet wall with no plan wall (should not happen)


def _mean(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    v = [x for x in v if x is not None]
    return float(np.mean(v)) if v else None


def _align(sheet, plan):
    """Ordered alignment of sheet lengths onto plan lengths (both metres,
    plan already rotated/reversed). Every sheet wall takes one plan wall in
    order; plan walls may be skipped. Returns (cost, mapping list)."""
    m, n = len(sheet), len(plan)
    INF = 1e18
    D = np.full((m + 1, n + 1), INF)
    D[0, 0] = 0.0
    back = {}
    for j in range(1, n + 1):
        D[0, j] = D[0, j - 1] + SKIP_PER_M * plan[j - 1]
        back[(0, j)] = (0, j - 1, None)
    for i in range(1, m + 1):
        D[i, 0] = D[i - 1, 0] + UNMATCHED_SHEET
        back[(i, 0)] = (i - 1, 0, None)
        for j in range(1, n + 1):
            match = D[i - 1, j - 1] + abs(sheet[i - 1] - plan[j - 1])
            skip = D[i, j - 1] + SKIP_PER_M * plan[j - 1]
            if match <= skip:
                D[i, j], back[(i, j)] = match, (i - 1, j - 1, (i - 1, j - 1))
            else:
                D[i, j], back[(i, j)] = skip, (i, j - 1, None)
    mapping = [None] * m
    i, j = m, n
    while (i, j) != (0, 0):
        pi, pj, pair = back[(i, j)]
        if pair is not None:
            mapping[pair[0]] = pair[1]
        i, j = pi, pj
    return float(D[m, n]), mapping


def match_room(sheet_lengths, plan_walls):
    """Best cyclic alignment over start and direction. Returns
    (cost, {sheet_index: plan_wall_index})."""
    n = len(plan_walls)
    lengths = [w["length_m"]["value"] for w in plan_walls]
    best = (float("inf"), {})
    for direction in (1, -1):
        for start in range(n):
            order = [(start + direction * k) % n for k in range(n)]
            cost, mp = _align(sheet_lengths, [lengths[o] for o in order])
            if cost < best[0]:
                best = (cost, {i: order[j] for i, j in enumerate(mp) if j is not None})
    return best


def _letter(i):
    return string.ascii_uppercase[i]


def to_ground_truth(plan: dict, sheet: dict) -> tuple[dict, dict]:
    rooms = plan["rooms"]
    srooms = sheet["rooms"]
    C = np.full((len(srooms), len(rooms)), 1e6)
    maps = {}
    for a, sr in enumerate(srooms):
        sl = [_mean(v) / 100.0 for v in sr["walls_cm"]]
        for b, pr in enumerate(rooms):
            cost, mp = match_room(sl, pr["walls"])
            C[a, b] = cost / max(1, len(sl))
            maps[(a, b)] = mp
    # Rooms the capturer already labelled (photo folders "01_room1" ->
    # sheet room "room1"): that correspondence is ground truth, not a guess.
    def _norm(x):
        return "".join(ch for ch in x.lower() if ch.isalnum())
    for a, sr in enumerate(srooms):
        nm = _norm(sr.get("name", ""))
        for b, pr in enumerate(rooms):
            if re.fullmatch(r"room_\d+", pr["room_id"]):
                continue                      # pipeline's own numbering, not a capturer label
            pid = _norm(pr["room_id"])
            if nm and len(nm) >= 3 and pid.endswith(nm) and not pid.endswith("room" + nm):
                C[a, :] = np.where(np.arange(len(rooms)) == b, C[a, b] - 1e3, 1e6)
    ra, rb = linear_sum_assignment(C)
    report = {"room_matches": []}
    gt_rooms = []
    for a, b in zip(ra, rb):
        sr, pr = srooms[a], rooms[b]
        mp = maps[(a, b)]
        letter_to_wall = {_letter(i): pr["walls"][j]["wall_id"] for i, j in mp.items()}
        report["room_matches"].append({"sheet_room": sr.get("name", f"room{a+1}"), "plan_room": pr["room_id"],
                                       "mean_abs_wall_diff_m": round(float(C[a, b]), 3),
                                       "walls": letter_to_wall})
        walls = []
        for w in pr["walls"]:
            meas = None
            for i, j in mp.items():
                if pr["walls"][j]["wall_id"] == w["wall_id"]:
                    meas = _mean(sr["walls_cm"][i]) / 100.0
            walls.append({"wall_id": w["wall_id"], "predicted": w["length_m"]["value"],
                          "observed": w["observed"], "measured": meas})
        # openings: match per wall by width
        preds = [(w["wall_id"], o) for w in pr["walls"] for o in w["openings"]]
        used, missed, op_rows = set(), [], {}
        for so in sr.get("openings", []):
            wid = letter_to_wall.get(so["wall"].upper())
            width = _mean(so["width_cm"]) / 100.0
            cands = [o for (wwid, o) in preds if wwid == wid and o["opening_id"] not in used]
            if not cands:   # wall mapping can be off by a stub: accept any unused opening within 25 cm width
                cands = [o for (_, o) in preds if o["opening_id"] not in used
                         and abs(o["width_m"]["value"] - width) < 0.25]
            if cands:
                o = min(cands, key=lambda o: abs(o["width_m"]["value"] - width))
                used.add(o["opening_id"])
                op_rows[o["opening_id"]] = width
            else:
                missed.append({"near_wall_id": wid, "kind": so["kind"], "measured": width})
        openings = [{"opening_id": o["opening_id"], "kind": o["kind"], "predicted": o["width_m"]["value"],
                     "exists": o["opening_id"] in op_rows, "measured": op_rows.get(o["opening_id"])}
                    for (_, o) in preds]
        ceil = sr.get("ceiling_cm")
        ceil_m = None
        if ceil:
            vals = [_mean(c) for c in ceil]
            ceil_m = float(np.mean([v for v in vals if v is not None])) / 100.0
        gt_rooms.append({"room_id": pr["room_id"], "your_name_for_it": sr.get("name", ""),
                         "ceiling_height_m": {"predicted": pr["ceiling_height_m"]["value"],
                                              "pipeline_observed_ceiling": pr["ceiling_observed"],
                                              "measured": ceil_m},
                         "walls": walls, "openings": openings, "missed_openings": missed})
    unmatched = [srooms[a].get("name") for a in range(len(srooms)) if a not in set(ra)]
    report["sheet_rooms_not_found_in_plan"] = unmatched
    gt = {"capture_id": plan["capture_id"], "measured_with": sheet.get("measured_with"),
          "footprint_m2": sheet.get("footprint_m2"), "rooms": gt_rooms, "matching": report}
    return gt, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    plan = json.loads(Path(a.plan).read_text())
    gt, rep = to_ground_truth(plan, json.loads(Path(a.sheet).read_text()))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(gt, indent=2))
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
