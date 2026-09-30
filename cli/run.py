#!/usr/bin/env python3
"""One command per capture, as required by the output contract.

Usage:
    python -m cli.run capture --input <folder> --tier lidar|video|photo \
        --room-id living_room --out outputs/living_room

Produces, under --out:
    plan.json     JSON to schema/capture_schema.json
    plan.png      rendered top-down plan
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import numpy as np

from capture.loader import load_capture
from reconstruction.backproject import build_point_cloud
from reconstruction.room_fit import fit_room
from reconstruction.render import render_room_plan
from reconstruction.confidence import interval_for_length, interval_for_height, interval_for_area, Measurement
from damage.detect import detect_damage_for_room

PIPELINE_VERSION = "0.1.0-24h-build"


def _measurement_to_dict(m: Measurement) -> dict:
    return {"value": round(m.value, 4), "unit": m.unit, "ci_low": round(m.ci_low, 4),
            "ci_high": round(m.ci_high, 4), "basis": m.basis}


def run_lidar_capture(input_dir: Path, room_id: str, out_dir: Path, min_confidence: int = 2,
                       stride: int = 3) -> dict:
    cap = load_capture(input_dir)
    points = build_point_cloud(cap, min_confidence=min_confidence, stride=stride, frame_stride=1)
    fit = fit_room(points)

    walls_json = []
    wall_measurements = []
    for i, w in enumerate(fit.walls):
        length_meas = interval_for_length(w.length_m, tier="lidar", n_inliers=w.n_inliers)
        wall_measurements.append(length_meas)
        openings_json = []
        for j, (s, e) in enumerate(w.openings):
            width_m = w.length_m * (e - s)
            width_meas = interval_for_length(width_m, tier="lidar", n_inliers=w.n_inliers)
            openings_json.append({
                "opening_id": f"{room_id}_w{i}_o{j}", "start_frac": round(float(s), 4),
                "end_frac": round(float(e), 4), "width_m": _measurement_to_dict(width_meas),
            })
        walls_json.append({
            "wall_id": f"{room_id}_w{i}", "length_m": _measurement_to_dict(length_meas),
            "p0": [round(float(w.p0[0]), 4), round(float(w.p0[1]), 4)],
            "p1": [round(float(w.p1[0]), 4), round(float(w.p1[1]), 4)],
            "trusted": bool(w.n_inliers > 0), "openings": openings_json,
        })

    ceiling_meas = interval_for_height(fit.ceiling_height_m, tier="lidar")
    area_meas = interval_for_area(fit.floor_area_m2, tier="lidar", wall_measurements=wall_measurements)

    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / "plan.png"
    render_room_plan(fit, str(png_path), room_id=room_id)

    damage_regions = detect_damage_for_room(input_dir, fit, room_id)

    room_json = {
        "room_id": room_id,
        "ceiling_height_m": _measurement_to_dict(ceiling_meas),
        "floor_area_m2": _measurement_to_dict(area_meas),
        "confidence": fit.confidence,
        "walls": walls_json,
        "damage_regions": damage_regions,
        "scope_line_items": _scope_from_damage(damage_regions, room_id),
    }

    output = {
        "capture_id": input_dir.name,
        "tier": "lidar",
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "pipeline_version": PIPELINE_VERSION,
        "confidence_note": (
            "LiDAR-tier intervals are anchored to Part 2's gate targets (openings <=2cm, "
            "ceiling <=1.5cm) and widened for low-support walls or degenerate "
            "(untrusted) geometry. Not yet replaced with measured calibration "
            "from ground truth -- see benchmark report."
        ),
        "rooms": [room_json],
        "stitched_plan": {
            "rooms_placed": [room_id], "adjacency": [],
            "footprint_m2": _measurement_to_dict(area_meas),
            "render_path": str(png_path),
        },
    }

    json_path = out_dir / "plan.json"
    json_path.write_text(json.dumps(output, indent=2))
    return output


def _scope_from_damage(damage_regions: list[dict], room_id: str) -> list[dict]:
    items = []
    for d in damage_regions:
        items.append({
            "item": f"Repair {d['damage_class']}", "surface_wall_id": d["surface_wall_id"],
            "quantity": round(d["extent_m2"]["value"], 3), "unit": "m2",
        })
    return items


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cozmo AI capture pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    cap_p = sub.add_parser("capture", help="Process one capture into a dimensioned plan")
    cap_p.add_argument("--input", required=True, help="Capture folder")
    cap_p.add_argument("--tier", required=True, choices=["lidar", "video", "photo"])
    cap_p.add_argument("--room-id", default="room")
    cap_p.add_argument("--out", required=True)
    cap_p.add_argument("--min-confidence", type=int, default=2)
    cap_p.add_argument("--stride", type=int, default=3, help="Depth-pixel stride (speed/density tradeoff)")

    args = parser.parse_args(argv)

    if args.command == "capture":
        input_dir = Path(args.input)
        out_dir = Path(args.out)
        if args.tier == "lidar":
            result = run_lidar_capture(input_dir, args.room_id, out_dir,
                                        min_confidence=args.min_confidence, stride=args.stride)
        else:
            print(f"Tier '{args.tier}' not yet wired into the CLI in this build.", file=sys.stderr)
            sys.exit(2)
        print(json.dumps({"room_id": args.room_id, "output": str(out_dir / "plan.json")}, indent=2))


if __name__ == "__main__":
    main()
