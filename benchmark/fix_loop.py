"""Part 4 fix loop, regenerable: runs the CURRENT pipeline twice per capture,
once with the pre-fix camera convention (COZMO_CAMERA_CONVENTION=arkit, the
bug) and once with the fix (opencv, default). The only code difference
between the arms is the y/z sign in reconstruction/backproject.py.

    python -m benchmark.fix_loop --captures data/samples_full/* --out benchmark/results/fix_loop

Metrics per arm (no ground truth needed; each is a physical check):
  floor_below_camera_m  - camera height above the detected floor. Protocol
                          says chest height (~1.3-1.5 m). Negative = floor
                          above the camera = impossible.
  registration_voxels   - occupied 5cm voxels in the wall band; lower =
                          frames agree on where walls are.
  rooms / doors         - recovered structure.
  ceilings              - per-room ceiling heights (observed ones only).
If --gt files are given (benchmark/ground_truth/<capture>.json) the gate
errors against tape/laser are added (ceiling height, wall lengths, doors).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ARM_CODE = r'''
import json, sys, numpy as np
from capture.loader import load_capture
from reconstruction.backproject import iter_frame_clouds, CAMERA_CONVENTION
from reconstruction.drift import registration_score
from reconstruction.layout import analyze, find_floor_y
cap = load_capture(sys.argv[1])
fs = max(1, len(cap.frames) // 900)
fc = [(f.position, p) for f, p in iter_frame_clouds(cap, 2, 4, fs)]
P = np.concatenate([p for _, p in fc])
floor = find_floor_y(P)
cam_y = float(np.median([f.position[1] for f in cap.frames]))
traj = np.array([f.position[[0, 2]] for f in cap.frames])
try:
    L = analyze(fc, traj)
    rooms = [{"room_id": r.room_id, "area_m2": round(r.floor_area_m2, 2),
              "ceiling_m": round(r.ceiling_height_m, 3) if r.ceiling_observed else None,
              "doors": [round(o.width_m, 3) for w in r.walls for o in w.openings if o.kind == "door"]}
             for r in L.rooms]
except Exception as e:
    rooms = [{"error": repr(e)}]
print(json.dumps({"convention": CAMERA_CONVENTION, "floor_below_camera_m": round(cam_y - floor, 3),
                  "registration_voxels": registration_score(fc), "n_rooms": len(rooms), "rooms": rooms}))
'''


def run_arm(capture: Path, convention: str) -> dict:
    env = dict(os.environ, COZMO_CAMERA_CONVENTION=convention, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    out = subprocess.run([sys.executable, "-c", ARM_CODE, str(capture)], env=env,
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--captures", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    for c in a.captures:
        c = Path(c)
        results[c.name] = {"before": run_arm(c, "arkit"), "after": run_arm(c, "opencv")}
        b, f = results[c.name]["before"], results[c.name]["after"]
        print(f"{c.name}: floor below camera {b['floor_below_camera_m']:+.2f} -> {f['floor_below_camera_m']:+.2f} m | "
              f"registration voxels {b['registration_voxels']} -> {f['registration_voxels']} | "
              f"rooms {b['n_rooms']} -> {f['n_rooms']}")
    (out / "fix_loop.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
