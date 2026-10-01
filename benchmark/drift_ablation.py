"""Drift-accountability ablation (Part 2): stitched footprint with the
plane-anchored heading correction OFF (VIO poses as recorded) vs ON (always
applied), plus what the default AUTO mode decided, for one capture.

    python -m benchmark.drift_ablation --input <capture> --out benchmark/results/drift_<name>

Writes ablation.json and ablation.png (both plans side by side). If a
ground-truth file is given (--gt, see benchmark/ground_truth_template.py),
the footprint error against it is included for both arms.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
import numpy as np

from capture.loader import load_capture
from reconstruction.backproject import iter_frame_clouds
from reconstruction.drift import correct_drift, registration_score
from reconstruction.layout import analyze
from stitching.stitch import raster_union_overlap


def run(input_dir: Path, out_dir: Path, max_frames=900, gt_path=None):
    cap = load_capture(input_dir)
    fs = max(1, len(cap.frames) // max_frames)
    used = list(iter_frame_clouds(cap, 2, 4, fs))
    fc = [(f.position, p) for f, p in used]
    ts = [f.timestamp for f, _ in used]
    traj = np.array([f.position[[0, 2]] for f in cap.frames])
    gt = json.loads(Path(gt_path).read_text()) if gt_path else None

    arms = {}
    for mode in ("off", "on", "auto"):
        clouds, rep = correct_drift(fc, ts, mode=mode)
        L = analyze(clouds, traj)
        union, overlap = raster_union_overlap([r.polygon for r in L.rooms]) if L.rooms else (0.0, 0.0)
        arm = {"drift_report": {k: v for k, v in rep.items() if k != "chunks"},
               "registration_voxels": registration_score(clouds),
               "n_rooms": len(L.rooms), "footprint_union_m2": round(union, 3),
               "overlap_m2": round(overlap, 3),
               "rooms": {r.room_id: round(r.floor_area_m2, 3) for r in L.rooms}}
        if gt and gt.get("footprint_m2"):
            arm["footprint_error_pct"] = round(100 * (union - gt["footprint_m2"]) / gt["footprint_m2"], 2)
        arms[mode] = (arm, L)

    out_dir.mkdir(parents=True, exist_ok=True)
    fig, axs = plt.subplots(1, 2, figsize=(14, 7))
    for ax, mode in zip(axs, ("off", "on")):
        arm, L = arms[mode]
        for r in L.rooms:
            ax.add_patch(Polygon(r.polygon, closed=True, fill=False, lw=2))
            c = r.polygon.mean(0)
            ax.text(c[0], c[1], f"{r.floor_area_m2:.2f}", ha="center", fontsize=7)
        ax.autoscale_view()
        ax.set_aspect("equal")
        ax.set_title(f"drift correction {mode.upper()}: footprint {arm['footprint_union_m2']:.2f} m², "
                     f"reg. voxels {arm['registration_voxels']}")
    fig.tight_layout()
    fig.savefig(out_dir / "ablation.png", dpi=110)
    plt.close(fig)
    result = {"capture": input_dir.name, **{m: a for m, (a, _) in arms.items()}}
    (out_dir / "ablation.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--gt")
    a = ap.parse_args()
    r = run(Path(a.input), Path(a.out), gt_path=a.gt)
    for m in ("off", "on", "auto"):
        print(m, {k: r[m][k] for k in ("registration_voxels", "n_rooms", "footprint_union_m2", "overlap_m2")},
              "applied" if r[m]["drift_report"].get("applied") else "not applied")
