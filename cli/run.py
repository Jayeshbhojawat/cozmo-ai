#!/usr/bin/env python3
"""One command per capture.

    python -m cli.run capture --input <folder> --tier lidar --out outputs/<name>

LiDAR tier input: a StrayScanner export folder (rgb.mp4, depth/, confidence/,
odometry.csv, imu.csv, camera_matrix.csv). A single continuous walk can
cover one room or a whole property; rooms, doors and adjacency are found
automatically and the stitched plan comes out of the same command.

Video tier input: a folder containing one walkthrough video (or a path to
the video file). Photo tier input: a folder of per-room sub-folders of
stills. See docs/capture_protocol.md.

Writes <out>/plan.json (schema/capture_schema.json) and <out>/plan.png.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

import numpy as np

PIPELINE_VERSION = "0.2.0"
CEILING_PLAUSIBLE_MAX = 4.5


def _opening_json(o, wall_id, j):
    from reconstruction.confidence import from_sigma
    return {
        "opening_id": f"{wall_id}_o{j}", "kind": o.kind, "leads_to": o.leads_to,
        "start_m": round(o.start_m, 4), "end_m": round(o.end_m, 4),
        "width_m": from_sigma(o.width_m, o.width_sigma_m, "m",
                              "jamb-to-jamb from surface points (model sigma, 95%)").to_dict(),
    }


def layout_to_json(layout, capture_id, tier, render_path, damage_by_room, timings, sigma_basis="lidar"):
    from reconstruction.confidence import from_sigma, lower_bound, tier_prior
    rooms_json = []
    for r in layout.rooms:
        walls = []
        for w in r.walls:
            if sigma_basis == "lidar":
                length = from_sigma(w.length_m, w.length_sigma_m, "m",
                                    "bounded by the two perpendicular wall planes (model sigma, 95%)"
                                    if w.observed else "wall not observed; boundary inferred from free space")
            else:
                length = tier_prior(w.length_m, sigma_basis)
            walls.append({
                "wall_id": w.wall_id, "observed": bool(w.observed), "n_support_points": int(w.n_support),
                "p0": [round(float(w.p0[0]), 4), round(float(w.p0[1]), 4)],
                "p1": [round(float(w.p1[0]), 4), round(float(w.p1[1]), 4)],
                "length_m": length.to_dict(),
                "openings": [_opening_json(o, w.wall_id, j) for j, o in enumerate(w.openings)],
            })
        if r.ceiling_observed:
            ceiling = (from_sigma(r.ceiling_height_m, r.ceiling_sigma_m, "m",
                                  "ceiling plane minus floor plane, per room (model sigma, 95%)")
                       if sigma_basis == "lidar" else tier_prior(r.ceiling_height_m, sigma_basis))
        else:
            ceiling = lower_bound(r.ceiling_height_m, CEILING_PLAUSIBLE_MAX, "m",
                                  "ceiling NOT observed in this capture: value is the highest surface seen "
                                  "(lower bound); upper bound is a plausibility limit, not a measurement")
        area = (from_sigma(r.floor_area_m2, r.area_sigma_m2, "m2", "propagated from every wall-plane sigma")
                if sigma_basis == "lidar" else tier_prior(r.floor_area_m2, sigma_basis, "m2", power=2))
        dmg = damage_by_room.get(r.room_id, [])
        rooms_json.append({
            "room_id": r.room_id, "visited": bool(r.visited), "partial": bool(r.partial),
            "wall_coverage": round(r.wall_coverage, 3),
            "ceiling_observed": bool(r.ceiling_observed), "ceiling_height_m": ceiling.to_dict(),
            "floor_area_m2": area.to_dict(),
            "polygon": [[round(float(x), 4), round(float(y), 4)] for x, y in r.polygon],
            "walls": walls, "damage_regions": dmg, "scope_line_items": _scope(dmg),
        })

    adjacency = []
    for a, b in layout.adjacency:
        via = None
        for r in layout.rooms:
            if r.room_id != a:
                continue
            for w in r.walls:
                for j, o in enumerate(w.openings):
                    if o.leads_to == b:
                        via = f"{w.wall_id}_o{j}"
        adjacency.append({"rooms": [a, b], "via_opening": via})

    total_area = sum(r.floor_area_m2 for r in layout.rooms)
    total_sigma = float(np.sqrt(sum(r.area_sigma_m2 ** 2 for r in layout.rooms)))
    from reconstruction.confidence import from_sigma as fs, tier_prior as tp
    footprint = (fs(total_area, total_sigma, "m2", "sum of room areas (rooms are disjoint by construction)")
                 if sigma_basis == "lidar" else tp(total_area, sigma_basis, "m2", power=2))
    return {
        "capture_id": capture_id, "tier": tier,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "pipeline_version": PIPELINE_VERSION,
        "confidence_note": ("All intervals are 95%. LiDAR-tier intervals come from the measurement model "
                            "(surface-point scatter + per-surface bias + scale term); see "
                            "benchmark/calibration report for coverage against ground truth."
                            if sigma_basis == "lidar" else
                            f"{tier}-tier intervals are priors (no depth sensor; scale from assumed camera height)."),
        "plan_frame": {"theta_deg": round(float(np.degrees(layout.theta_rad)), 3),
                       "origin": [round(float(v), 4) for v in layout.origin],
                       "note": "plan x,y = world (x,z) rotated by -theta so walls are axis-aligned, minus origin"},
        "rooms": rooms_json,
        "stitched_plan": {"rooms_placed": [r.room_id for r in layout.rooms], "adjacency": adjacency,
                          "footprint_m2": footprint.to_dict(), "render_path": render_path},
        "timing_s": timings,
    }


def _scope(damage):
    items = []
    for d in damage:
        verb = {"water_stain": "Stain-block prime and repaint", "crack": "Rake out, fill and repaint crack"}
        items.append({"item": verb.get(d["damage_class"], "Repair"), "surface_id": d["surface_id"],
                      "quantity": round(max(d["extent_m2"]["value"], 0.1), 3), "unit": "m2",
                      "damage_region_id": d["region_id"]})
        if d["concealed_flag"]["flagged"]:
            items.append({"item": "Investigate concealed damage: " + d["concealed_flag"]["rule"],
                          "surface_id": d["surface_id"], "quantity": 1, "unit": "ea",
                          "damage_region_id": d["region_id"]})
    return items


def run_lidar(input_dir: Path, out_dir: Path, max_frames: int = 900, damage: bool = True,
              drift: str = "auto") -> dict:
    from capture.loader import load_capture
    from reconstruction.backproject import iter_frame_clouds
    from reconstruction.layout import analyze
    from reconstruction.render import render_plan

    t0 = time.time()
    cap = load_capture(input_dir)
    fs = max(1, len(cap.frames) // max_frames)
    used = list(iter_frame_clouds(cap, min_confidence=2, stride=4, frame_stride=fs))
    if not used:
        raise SystemExit(f"No depth frames found in {input_dir}/depth -- is this a LiDAR capture?")
    from reconstruction.drift import correct_drift
    frame_clouds, drift_report = correct_drift([(f.position, p) for f, p in used],
                                               [f.timestamp for f, _ in used], mode=drift)
    traj = np.array([f.position[[0, 2]] for f in cap.frames])
    t1 = time.time()
    layout = analyze(frame_clouds, traj)
    t2 = time.time()

    damage_by_room = {}
    if damage:
        from damage.detect import detect_damage
        damage_by_room = detect_damage(cap, layout)
    t3 = time.time()

    out_dir.mkdir(parents=True, exist_ok=True)
    png = render_plan(layout, str(out_dir / "plan.png"), title=f"{input_dir.name} - LiDAR tier")
    timings = {"load_and_backproject": round(t1 - t0, 2), "layout": round(t2 - t1, 2),
               "damage": round(t3 - t2, 2), "total": round(time.time() - t0, 2)}
    out = layout_to_json(layout, input_dir.name, "lidar", png, damage_by_room, timings)
    out["drift"] = drift_report
    (out_dir / "plan.json").write_text(json.dumps(out, indent=2))
    return out


def run_monocular(input_path: Path, out_dir: Path, tier: str) -> dict:
    try:
        from reconstruction.sfm import monocular_layout
    except ImportError:
        raise SystemExit(f"The {tier} tier is not implemented in this build yet "
                         "(see docs/compliance_matrix.md). Use --tier lidar.")
    from reconstruction.render import render_plan
    t0 = time.time()
    layout, stats = monocular_layout(input_path, tier)
    out_dir.mkdir(parents=True, exist_ok=True)
    png = render_plan(layout, str(out_dir / "plan.png"), title=f"{input_path.name} - {tier} tier")
    timings = {"total": round(time.time() - t0, 2), **{f"sfm_{k}": v for k, v in stats.items()}}
    out = layout_to_json(layout, input_path.name, tier, png, {}, timings, sigma_basis=tier)
    (out_dir / "plan.json").write_text(json.dumps(out, indent=2))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cozmo AI capture pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("capture", help="Process one capture into dimensioned + stitched plans")
    p.add_argument("--input", required=True)
    p.add_argument("--tier", required=True, choices=["lidar", "video", "photo"])
    p.add_argument("--out", required=True)
    p.add_argument("--max-frames", type=int, default=900)
    p.add_argument("--no-damage", action="store_true")
    p.add_argument("--drift", choices=["auto", "on", "off"], default="auto",
                   help="plane-anchored heading-drift correction (auto = keep only if it improves registration)")
    args = parser.parse_args(argv)

    inp, out = Path(args.input), Path(args.out)
    if args.tier == "lidar":
        res = run_lidar(inp, out, max_frames=args.max_frames, damage=not args.no_damage, drift=args.drift)
    else:
        res = run_monocular(inp, out, args.tier)
    summary = {"rooms": len(res["rooms"]), "adjacency": [a["rooms"] for a in res["stitched_plan"]["adjacency"]],
               "footprint_m2": res["stitched_plan"]["footprint_m2"]["value"], "timing_s": res["timing_s"],
               "json": str(out / "plan.json"), "png": str(out / "plan.png")}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    sys.exit(main())
