"""Ground truth: template generation and scoring.

1. Make a measuring sheet from a pipeline output (every wall, door and
   ceiling the pipeline found, with blanks for the tape/laser value):

       python -m benchmark.ground_truth template --plan outputs/<cap>/plan.json \
           --out benchmark/ground_truth/<cap>.json

   Open the rendered plan.png next to it so you know which wall is which.
   Fill every "measured" you can; leave null what you could not measure.
   Add openings the pipeline MISSED to "missed_openings" (they count as
   misses), and mark detected openings that do not exist with
   "exists": false (phantoms, also misses).

2. Score:

       python -m benchmark.ground_truth score --plan outputs/<cap>/plan.json \
           --gt benchmark/ground_truth/<cap>.json [--out benchmark/results/<cap>_gates.json]

   Reports the Part 2 gates (opening widths, ceiling height), wall-length
   errors, and calibration: the fraction of measured values that fall
   inside the pipeline's stated 95% interval (should be ~95%; much lower
   means the intervals are over-confident and must be widened).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def template(plan: dict) -> dict:
    rooms = []
    for r in plan["rooms"]:
        rooms.append({
            "room_id": r["room_id"],
            "your_name_for_it": "",
            "ceiling_height_m": {"predicted": r["ceiling_height_m"]["value"],
                                 "pipeline_observed_ceiling": r["ceiling_observed"], "measured": None},
            "walls": [{"wall_id": w["wall_id"], "predicted": w["length_m"]["value"],
                       "observed": w["observed"], "measured": None} for w in r["walls"]],
            "openings": [{"opening_id": o["opening_id"], "kind": o["kind"], "predicted": o["width_m"]["value"],
                          "exists": True, "measured": None}
                         for w in r["walls"] for o in w["openings"]],
            "missed_openings": [],
        })
    return {"capture_id": plan["capture_id"], "measured_with": "e.g. Bosch GLM 50C laser / steel tape",
            "how_to_measure": {
                "walls": "interior face to interior face along the wall, at ~1 m height",
                "openings": "clear width between jambs (door frame inner faces), at ~1 m height",
                "ceiling": "floor to ceiling, room centre, laser vertical",
                "missed_openings": "list as {'near_wall_id': ..., 'kind': 'door|window', 'measured': width}"},
            "footprint_m2": None, "rooms": rooms}


def _in_ci(m, truth):
    return m["ci_low"] <= truth <= m["ci_high"]


def score(plan: dict, gt: dict) -> dict:
    by_room = {r["room_id"]: r for r in plan["rooms"]}
    wall_err, ceil_rows, op_rows, inside, total = [], [], [], 0, 0
    n_missed = n_phantom = n_ok = n_scored = 0
    for g in gt["rooms"]:
        r = by_room.get(g["room_id"])
        if r is None:
            continue
        walls = {w["wall_id"]: w for w in r["walls"]}
        ops = {o["opening_id"]: o for w in r["walls"] for o in w["openings"]}
        for gw in g["walls"]:
            if gw["measured"] is None:
                continue
            m = walls[gw["wall_id"]]["length_m"]
            wall_err.append(abs(m["value"] - gw["measured"]))
            total += 1
            inside += _in_ci(m, gw["measured"])
        gc = g["ceiling_height_m"]
        if gc["measured"] is not None:
            m = r["ceiling_height_m"]
            err = abs(m["value"] - gc["measured"]) if r["ceiling_observed"] else None
            ceil_rows.append({"room_id": g["room_id"], "observed": r["ceiling_observed"],
                              "error_m": err, "pass_1_5cm": (err is not None and err <= 0.015)})
            total += 1
            inside += _in_ci(m, gc["measured"])
        for go in g["openings"]:
            if not go["exists"]:
                n_phantom += 1
                n_scored += 1
                continue
            if go["measured"] is None:
                continue
            m = ops[go["opening_id"]]["width_m"]
            err = abs(m["value"] - go["measured"])
            n_scored += 1
            n_ok += err <= 0.02
            op_rows.append({"opening_id": go["opening_id"], "error_m": round(err, 4)})
            total += 1
            inside += _in_ci(m, go["measured"])
        n_missed += len(g.get("missed_openings", []))
        n_scored += len(g.get("missed_openings", []))
    rate = n_ok / n_scored if n_scored else None
    fp = gt.get("footprint_m2")
    pred_fp = plan["stitched_plan"]["footprint_m2"]["value"]
    return {
        "capture_id": plan["capture_id"],
        "gates": {
            "opening_widths": {"pass_rate": rate, "passed": rate is not None and rate >= 0.85,
                               "within_2cm": n_ok, "scored": n_scored, "missed": n_missed, "phantom": n_phantom},
            "ceiling_height": {"rooms": ceil_rows,
                               "passed": bool(ceil_rows) and all(c["pass_1_5cm"] for c in ceil_rows)},
        },
        "wall_length_abs_error_m": {"n": len(wall_err),
                                    "median": sorted(wall_err)[len(wall_err) // 2] if wall_err else None,
                                    "max": max(wall_err) if wall_err else None},
        "footprint_error_pct": round(100 * (pred_fp - fp) / fp, 2) if fp else None,
        "calibration_95ci_coverage": {"inside": int(inside), "total": int(total),
                                      "rate": round(inside / total, 3) if total else None},
        "openings": op_rows,
    }


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("template")
    t.add_argument("--plan", required=True)
    t.add_argument("--out", required=True)
    s = sub.add_parser("score")
    s.add_argument("--plan", required=True)
    s.add_argument("--gt", required=True)
    s.add_argument("--out")
    a = ap.parse_args()
    plan = json.loads(Path(a.plan).read_text())
    if a.cmd == "template":
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(template(plan), indent=2))
        print(f"wrote {a.out}: fill in the 'measured' fields")
    else:
        res = score(plan, json.loads(Path(a.gt).read_text()))
        print(json.dumps(res, indent=2))
        if a.out:
            Path(a.out).write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
