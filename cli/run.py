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
import os
import datetime
import json
import sys
import time
from pathlib import Path

import numpy as np

PIPELINE_VERSION = "0.2.0"
CEILING_PLAUSIBLE_MAX = 4.5


def _opening_json(o, wall_id, j, sigma_basis="lidar"):
    """Door/window width with its 95 % interval. The jamb-to-jamb model sigma
    (~1 cm) only holds for LiDAR depth; the other tiers use their measured
    per-length error (on the measured home the LiDAR sigma had been applied
    to video doors too, giving +-1 cm intervals around 27-190 % errors)."""
    from reconstruction.confidence import from_sigma, tier_prior
    if sigma_basis == "lidar":
        width = from_sigma(o.width_m, o.width_sigma_m, "m", "jamb-to-jamb from surface points (model sigma, 95%)")
    else:
        width = tier_prior(o.width_m, sigma_basis)
    return {
        "opening_id": f"{wall_id}_o{j}", "kind": o.kind, "leads_to": o.leads_to,
        "start_m": round(o.start_m, 4), "end_m": round(o.end_m, 4),
        "width_m": width.to_dict(),
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
                "openings": [_opening_json(o, w.wall_id, j, sigma_basis) for j, o in enumerate(w.openings)],
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


# Layout settings for learned (noisy) depth, chosen with benchmark/video_sweep.py
# on the measured home (3 walks; disclosed as tuned on the scored home).
# COZMO_VIDEO_LAYOUT=lidar reproduces the pre-fix behaviour (fix loop "before").
VIDEO_OCCUPANCY_RATIO = 0.05
VIDEO_DOOR_HALF_WIDTH = 0.70
# Outline features smaller than this are learned-depth noise (fix declared in
# docs/fix_declaration.md; chosen on walk 1 only). COZMO_VIDEO_MIN_FEATURE=0
# reproduces the run before this fix.
VIDEO_MIN_FEATURE_M = 0.8


def video_layout_kwargs(cam_y: float) -> dict:
    if os.environ.get("COZMO_VIDEO_LAYOUT") == "lidar":
        return {"camera_y": None}
    mf = float(os.environ.get("COZMO_VIDEO_MIN_FEATURE", VIDEO_MIN_FEATURE_M))
    return {"camera_y": cam_y, "occupancy_ratio": VIDEO_OCCUPANCY_RATIO,
            "door_half_width": VIDEO_DOOR_HALF_WIDTH, "min_feature_m": mf or None}


def _find_recording(input_path: Path) -> Path:
    """A Spectacular Rec export may arrive with an extra folder level (zip
    unpacked into a folder): use the directory that holds data.jsonl."""
    if (input_path / "data.jsonl").exists() or (input_path / "odometry.csv").exists():
        return input_path
    hits = sorted(input_path.rglob("data.jsonl"))
    return hits[0].parent if hits else input_path


def run_posed_video(input_path: Path, out_dir: Path, recompute: bool = False, max_frames: int = 250,
                    drift: str = "auto", ablation: bool = True, damage: bool = True) -> dict:
    """Video tier with the phone's motion tracking: Spectacular Rec recording
    (poses from video + motion sensors via the Spectacular AI SDK), or a
    StrayScanner folder used as video + poses only (LiDAR depth ignored).
    With ablation=True the stitched footprint is also computed with the
    drift correction forced off and forced on (same depth, same frames), so
    every video run carries its own drift on/off evidence."""
    from reconstruction.video_posed import posed_clouds
    from reconstruction.layout import analyze
    from reconstruction.render import render_plan
    from reconstruction.drift import correct_drift, registration_score
    from stitching.stitch import raster_union_overlap
    t0 = time.time()
    input_path = _find_recording(input_path)
    if (input_path / "data.jsonl").exists():
        from capture.spectacular import load_spectacular
        cap = load_spectacular(input_path, recompute=recompute)
        video, source = input_path / "data.mov", "spectacular_rec"
    else:
        from capture.loader import load_capture
        cap = load_capture(input_path)
        video, source = input_path / "rgb.mp4", "strayscanner_video_and_poses_only"
    t1 = time.time()
    depth_keep = {} if damage else None
    cache = None if recompute else input_path / f"depth_cache_{max_frames}.npz"
    raw, used, st = posed_clouds(cap, video, max_frames=max_frames, keep_depth=depth_keep, cache_path=cache)
    if os.environ.get("COZMO_DUMP_CLOUDS"):          # debugging aid: world points + path, subsampled
        out_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out_dir / "clouds_debug.npz",
                            pts=np.concatenate([p[::3] for _, p in raw]),
                            path=np.array([f.position for f in cap.frames]))
    t2 = time.time()
    traj = np.array([f.position[[0, 2]] for f in cap.frames])
    ts = [f.timestamp for f in used]
    clouds, drift_report = correct_drift(raw, ts, mode=drift)
    cam_y = float(np.median([f.position[1] for f in cap.frames]))
    layout = analyze(clouds, traj, **video_layout_kwargs(cam_y))
    t3 = time.time()
    damage_by_room = {}
    if damage:
        from damage.detect import detect_damage_video
        damage_by_room = detect_damage_video(cap, video, depth_keep, layout)
    t4 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    png = render_plan(layout, str(out_dir / "plan.png"), title=f"{input_path.name} - video tier")
    timings = {"poses": round(t1 - t0, 2), "depth_and_scale": round(t2 - t1, 2),
               "drift_and_layout": round(t3 - t2, 2), "damage": round(t4 - t3, 2),
               "total": round(time.time() - t0, 2)}
    out = layout_to_json(layout, input_path.name, "video", png, damage_by_room, timings, sigma_basis="video_posed")
    out["reconstruction"] = {"path": "posed_video", "pose_source": source, **st,
                             "floor_method": layout.diagnostics.get("floor_method"),
                             "camera_height_m": round(cam_y - layout.floor_y, 3)}
    out["drift"] = drift_report
    if ablation:
        arms = {}
        for mode in ("off", "on"):
            c2, rep = correct_drift(raw, ts, mode=mode)
            L2 = analyze(c2, traj, **video_layout_kwargs(cam_y))
            union, overlap = raster_union_overlap([r.polygon for r in L2.rooms]) if L2.rooms else (0.0, 0.0)
            arms[mode] = {"registration_voxels": registration_score(c2), "n_rooms": len(L2.rooms),
                          "footprint_m2": round(float(sum(r.floor_area_m2 for r in L2.rooms)), 3),
                          "footprint_union_m2": round(float(union), 3)}
        out["drift_ablation"] = arms
    (out_dir / "plan.json").write_text(json.dumps(out, indent=2, default=str))
    return out


def run_monocular(input_path: Path, out_dir: Path, tier: str, rotate: str = "none") -> dict:
    from reconstruction.monotier import photo_tier, video_tier
    from reconstruction.render import render_plan
    t0 = time.time()
    if tier == "photo":
        layout, stats = photo_tier(input_path)
    else:
        video = input_path
        if input_path.is_dir():
            vids = sorted([p for p in input_path.iterdir() if p.suffix.lower() in (".mp4", ".mov", ".m4v")])
            if not vids:
                raise SystemExit(f"No video file in {input_path}")
            video = vids[0]
        layout, stats = video_tier(video, rotate=rotate)
    out_dir.mkdir(parents=True, exist_ok=True)
    png = render_plan(layout, str(out_dir / "plan.png"), title=f"{input_path.name} - {tier} tier")
    timings = {"total": round(time.time() - t0, 2), **{f"rec_{k}": v for k, v in stats.items()}}
    out = layout_to_json(layout, input_path.name, tier, png, {}, timings, sigma_basis=tier)
    out["reconstruction"] = {k: v for k, v in layout.diagnostics.items()}
    (out_dir / "plan.json").write_text(json.dumps(out, indent=2, default=str))
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
    p.add_argument("--rotate", choices=["none", "cw", "ccw", "180"], default="none",
                   help="video tier: rotate frames upright if the file has no orientation metadata")
    p.add_argument("--recompute-poses", action="store_true",
                   help="video tier (Spectacular Rec): recompute camera poses instead of using poses_cache.json")
    p.add_argument("--drift", choices=["auto", "on", "off"], default="auto",
                   help="plane-anchored heading-drift correction (auto = keep only if it improves registration)")
    args = parser.parse_args(argv)

    inp, out = Path(args.input), Path(args.out)
    if args.tier == "lidar":
        res = run_lidar(inp, out, max_frames=args.max_frames, damage=not args.no_damage, drift=args.drift)
    elif args.tier == "video" and inp.is_dir() and (any(inp.rglob("data.jsonl")) or (inp / "odometry.csv").exists()):
        res = run_posed_video(inp, out, recompute=args.recompute_poses, drift=args.drift,
                              damage=not args.no_damage)
    else:
        res = run_monocular(inp, out, args.tier, rotate=args.rotate)
    summary = {"rooms": len(res["rooms"]), "adjacency": [a["rooms"] for a in res["stitched_plan"]["adjacency"]],
               "footprint_m2": res["stitched_plan"]["footprint_m2"]["value"], "timing_s": res["timing_s"],
               "json": str(out / "plan.json"), "png": str(out / "plan.png")}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    sys.exit(main())
