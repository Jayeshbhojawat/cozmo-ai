"""Fast parameter study for the posed-video tier on cached depth.

Rebuilds plans from depth_cache_<n>.npz (no depth model, no pose solve) for
several layout settings and scores each against the tape sheet. Used to
choose the video-tier defaults; the table it prints goes in the report so
the choice is auditable (and the risk of tuning on one home is visible).

    python -m benchmark.video_sweep --captures data/raw/home/spectacular_* \
        --sheet benchmark/ground_truth/home/sheet.json --out benchmark/results/home_sweep
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np

from benchmark.ground_truth import score
from benchmark.run_all import sheet_room_area
from benchmark.sheet import to_ground_truth
from capture.spectacular import load_spectacular
from cli.run import layout_to_json
from reconstruction.layout import analyze
from reconstruction.video_posed import posed_clouds


def evaluate(plan, sheet):
    gt, rep = to_ground_truth(plan, sheet)
    sc = score(plan, gt)
    rel = [abs(w["predicted"] - w["measured"]) / w["measured"]
           for r in gt["rooms"] for w in r["walls"] if w["measured"]]
    names = {r["name"]: r for r in sheet["rooms"]}
    rooms = {r["room_id"]: r for r in plan["rooms"]}
    fp_p = fp_m = 0.0
    for g in gt["rooms"]:
        fp_p += rooms[g["room_id"]]["floor_area_m2"]["value"]
        fp_m += sheet_room_area(names[g["your_name_for_it"]]) or 0
    return {"rooms": len(plan["rooms"]), "wall_err_median": float(np.median(rel)) if rel else None,
            "footprint_err": (fp_p - fp_m) / fp_m if fp_m else None,
            "plan_footprint_m2": sum(r["floor_area_m2"]["value"] for r in plan["rooms"]),
            "ceiling": [(c["room_id"], c["error_m"]) for c in sc["gates"]["ceiling_height"]["rooms"]],
            "openings": sc["gates"]["opening_widths"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--captures", nargs="+", required=True)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ratios", nargs="+", type=float, default=[None, 0.05, 0.1, 0.2, 0.4])
    ap.add_argument("--door-half-widths", nargs="+", type=float, default=[0.42])
    a = ap.parse_args()
    sheet = json.loads(Path(a.sheet).read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for cdir in a.captures:
        cdir = Path(cdir)
        cap = load_spectacular(cdir)
        clouds, used, st = posed_clouds(cap, cdir / "data.mov", max_frames=250,
                                        cache_path=cdir / "depth_cache_250.npz")
        traj = np.array([f.position[[0, 2]] for f in cap.frames])
        cam_y = float(np.median([f.position[1] for f in cap.frames]))
        for ratio, dhw in itertools.product(a.ratios, a.door_half_widths):
            L = analyze(clouds, traj, camera_y=cam_y, occupancy_ratio=ratio, door_half_width=dhw)
            plan = layout_to_json(L, cdir.name, "video", "", {}, {}, sigma_basis="video_posed")
            ev = evaluate(plan, sheet) if plan["rooms"] else {"rooms": 0}
            row = {"capture": cdir.name, "occupancy_ratio": ratio, "door_half_width": dhw, **ev}
            rows.append(row)
            print(json.dumps(row, default=str))
    (out / "sweep.json").write_text(json.dumps(rows, indent=2, default=str))


if __name__ == "__main__":
    main()
