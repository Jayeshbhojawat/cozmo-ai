"""Per-surface damage detection with metric extent and concealed-damage rules.

Pipeline (LiDAR tier; the video tier uses the same steps with learned,
triangulation-scaled depth in place of LiDAR depth - detect_damage_video):
 1. Sample ~24 RGB frames evenly across the capture (video frame i <-> depth/
    pose frame i; verified: video frame counts equal odometry row counts).
 2. 2D candidate detection with classical, explainable cues (no trained
    model in this build; disclosed in the report):
      water_stain - locally darker, low-saturation blob (V below 75% of the
                    local mean brightness, S < 90)
      crack       - thin dark line: morphological black-hat response,
                    elongated (min-area-rect aspect >= 6), >= 6% of frame
 3. Every candidate is lifted to 3D through the aligned LiDAR depth and
    camera pose, transformed into the plan frame, and ASSIGNED TO A SURFACE:
    the wall plane it lies on (within 8cm, inside the wall's span), the
    floor, or an observed ceiling. Candidates that are not on a building
    surface (furniture, appliances, objects) are discarded - this is also
    the main false-positive filter.
 4. Metric extent from depth: pixel area x z^2/(fx fy), corrected for
    viewing obliquity (divided by |cos| between view ray and surface
    normal, clipped at 0.3). Cracks additionally get a metric length.
 5. Cross-frame de-duplication: same class, same surface, centroids within
    0.3m -> one region (largest extent kept, n_views counted).
 6. Concealed-damage rules, each reported with its id and text when fired.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from reconstruction.backproject import load_depth_confidence
from reconstruction.confidence import from_sigma
from reconstruction.layout import _rot

W_IMG, H_IMG = 960, 720           # working resolution (half of 1920x1440)
STRAIGHT_LINE_RMS_PX = 3.0         # cracks deviate from a straight line by more than this
MIN_VIEWS = 2                      # a region must be re-observed from >=2 sampled frames
MIN_STAIN_M2 = 0.01
MIN_CRACK_M = 0.15

RULES = {
    "WS-BASE": "water staining reaches within 0.20 m of the floor at the wall base -> possible "
               "rising damp or slab/plumbing leak behind the skirting; open up and moisture-meter",
    "WS-CEIL": "stain on the ceiling plane -> possible leak from the floor or roof above; inspect void",
    "CR-LONG": "crack longer than 0.5 m -> check for structural movement behind the finish",
    "CR-OPEN": "crack within 0.15 m of an opening corner -> typical lintel/settlement stress; inspect lintel",
}


DETECTION_STATS: dict = {}


def _water_stains(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1].astype(np.float32), hsv[:, :, 2].astype(np.float32)
    local = cv2.blur(v, (101, 101)) + 1.0
    mask = ((v < 0.75 * local) & (s < 90)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    out = []
    for c in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        area = cv2.contourArea(c)
        if area < 0.003 * W_IMG * H_IMG:
            continue
        m = np.zeros((H_IMG, W_IMG), np.uint8)
        cv2.drawContours(m, [c], -1, 1, -1)
        out.append({"cls": "water_stain", "mask": m.astype(bool), "px_area": float(area), "px_len": 0.0})
    return out


def _cracks(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bh = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    mask = (bh > 25).astype(np.uint8) * 255
    out = []
    for c in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]:
        if len(c) < 20:
            continue
        (_, _), (w, h), _ = cv2.minAreaRect(c)
        long_side, short_side = max(w, h), max(min(w, h), 1.0)
        if long_side / short_side < 6 or long_side < 0.06 * W_IMG:
            continue
        pts = c[:, 0, :].astype(np.float32)
        vx, vy, x0, y0 = cv2.fitLine(pts, cv2.DIST_L2, 0, 0.01, 0.01).ravel()
        rms_perp = float(np.sqrt(np.mean(((pts[:, 0] - x0) * vy - (pts[:, 1] - y0) * vx) ** 2)))
        if rms_perp < STRAIGHT_LINE_RMS_PX:
            continue        # ruler-straight: tile joint, door frame, cable, edge - not a crack
        m = np.zeros((H_IMG, W_IMG), np.uint8)
        cv2.drawContours(m, [c], -1, 1, -1)
        out.append({"cls": "crack", "mask": m.astype(bool), "px_area": float(max(m.sum(), 1)),
                    "px_len": float(long_side)})
    return out


def _surfaces(layout):
    """Flat list of wall surfaces in plan frame: (room, wall, along_axis, coord, lo, hi, normal_plan)."""
    out = []
    for r in layout.rooms:
        for w in r.walls:
            if not w.observed:
                continue
            d = w.p1 - w.p0
            along = 0 if abs(d[0]) >= abs(d[1]) else 1
            normal = np.zeros(2)
            normal[1 - along] = 1.0
            lo, hi = sorted([w.p0[along], w.p1[along]])
            out.append((r, w, along, float(w.p0[1 - along]), lo, hi, normal))
    return out


def _assign_surface(p_uv, h, layout, walls):
    best, best_d = None, 0.08
    for r, w, along, coord, lo, hi, normal in walls:
        if not (lo - 0.05 <= p_uv[along] <= hi + 0.05):
            continue
        dist = abs(p_uv[1 - along] - coord)
        if dist < best_d and -0.05 < h < (r.ceiling_height_m + 0.05):
            best, best_d = ("wall", r, w, normal), dist
    if best:
        return best
    from matplotlib.path import Path as MplPath
    for r in layout.rooms:
        if MplPath(r.polygon).contains_point(p_uv):
            if abs(h) < 0.06:
                return ("floor", r, None, None)
            if r.ceiling_observed and abs(h - r.ceiling_height_m) < 0.06:
                return ("ceiling", r, None, None)
    return None


def detect_damage(cap, layout, n_frames: int = 40) -> dict:
    """LiDAR tier: RGB from rgb.mp4, depth + confidence from the phone."""
    video = Path(cap.root) / "rgb.mp4"
    if not video.exists():
        return {}
    frames = [f for f in cap.frames if cap.depth_path(f.index).exists()]
    if not frames:
        return {}
    picks = [frames[i] for i in np.linspace(0, len(frames) - 1, min(n_frames, len(frames))).astype(int)]

    def samples():
        vc = cv2.VideoCapture(str(video))
        for f in picks:
            vc.set(cv2.CAP_PROP_POS_FRAMES, int(f.index))
            ok, img = vc.read()
            if not ok:
                continue
            depth, conf = load_depth_confidence(cap, f, min_confidence=1)
            yield f, img, depth, conf
        vc.release()

    return _dedupe_and_format(_lift_candidates(samples(), layout, cap.rgb_shape))


def detect_damage_video(cap, video_path, depth_by_index: dict, layout, n_frames: int = 40) -> dict:
    """Video tier: the same detector, with the learned depth (already scaled
    to metres by triangulation, see reconstruction/video_posed.py) standing
    in for LiDAR depth. Coarser depth -> looser metric extent; the surface
    test and the multi-view rule are unchanged."""
    by_idx = {f.index: f for f in cap.frames}
    keys = sorted(k for k in depth_by_index if k in by_idx)
    if not keys:
        return {}
    picks = [keys[i] for i in np.linspace(0, len(keys) - 1, min(n_frames, len(keys))).astype(int)]

    def samples():
        vc = cv2.VideoCapture(str(video_path))
        want, i = set(picks), 0
        while want:
            ok = vc.grab()
            if not ok:
                break
            if i in want:
                ok, img = vc.retrieve()
                if ok:
                    d, m = depth_by_index[i]
                    yield by_idx[i], img, d, m
                want.discard(i)
            i += 1
        vc.release()

    return _dedupe_and_format(_lift_candidates(samples(), layout, cap.rgb_shape))


def _lift_candidates(samples, layout, rgb_shape) -> list:
    """samples: iterable of (frame, bgr image at full RGB res, metric depth
    at any resolution aligned with the image, boolean validity mask)."""
    R = _rot(layout.theta_rad)
    walls = _surfaces(layout)
    raw = []
    for f, img, depth, conf in samples:
        img = cv2.resize(img, (W_IMG, H_IMG))
        dh, dw = depth.shape
        sx, sy = W_IMG / rgb_shape[1], H_IMG / rgb_shape[0]
        fx, fy, cx, cy = f.fx * sx, f.fy * sy, f.cx * sx, f.cy * sy
        T = f.pose_matrix()
        for cand in _water_stains(img) + _cracks(img):
            ys, xs = np.nonzero(cand["mask"])
            if len(xs) > 400:
                sel = np.random.default_rng(0).choice(len(xs), 400, replace=False)
                ys, xs = ys[sel], xs[sel]
            du = np.clip((xs * dw / W_IMG).astype(int), 0, dw - 1)
            dv = np.clip((ys * dh / H_IMG).astype(int), 0, dh - 1)
            ok_d = conf[dv, du]
            if ok_d.mean() < 0.5:
                continue
            z = depth[dv, du][ok_d]
            pc = np.stack([(xs[ok_d] - cx) / fx * z, (ys[ok_d] - cy) / fy * z, z], axis=1)
            pw = pc @ T[:3, :3].T + T[:3, 3]
            uv = pw[:, [0, 2]] @ R.T - layout.origin
            hh = pw[:, 1] - layout.floor_y
            c_uv, c_h = np.median(uv, axis=0), float(np.median(hh))
            surf = _assign_surface(c_uv, c_h, layout, walls)
            if surf is None:
                continue                  # not on a wall/floor/ceiling: furniture or object
            kind, room, wall, normal = surf
            view = np.median(pw, axis=0) - T[:3, 3]
            view /= np.linalg.norm(view) + 1e-9
            if kind == "wall":
                v_plan = view[[0, 2]] @ R.T
                cos = abs(float(v_plan @ normal))
            else:
                cos = abs(float(view[1]))
            zm = float(np.median(z))
            area = cand["px_area"] * zm * zm / (fx * fy) / max(cos, 0.3)
            length = cand["px_len"] * zm / fx / max(cos, 0.3) if cand["cls"] == "crack" else 0.0
            raw.append({"cls": cand["cls"], "kind": kind, "room": room, "wall": wall, "uv": c_uv,
                        "h": c_h, "h_min": float(np.percentile(hh, 2)), "h_max": float(np.percentile(hh, 98)),
                        "area": area, "length": length,
                        "frame": int(f.index)})
    return raw


def _plausible(d):
    if d["cls"] == "water_stain":
        if d["area"] < MIN_STAIN_M2:
            return False
        # thin dark band at the wall base = skirting tile or base shadow, not a stain
        if d["kind"] == "wall" and d["h_min"] < 0.15 and (d["h_max"] - d["h_min"]) < 0.15:
            return False
    if d["cls"] == "crack" and d["length"] < MIN_CRACK_M:
        return False
    return True


def _dedupe_and_format(raw):
    stats = {"candidates_on_surfaces": len(raw)}
    raw = [d for d in raw if _plausible(d)]
    stats["after_size_and_skirting_filters"] = len(raw)
    clusters = []
    for d in sorted(raw, key=lambda d: -d["area"]):
        sid = d["wall"].wall_id if d["wall"] is not None else f"{d['room'].room_id}_{d['kind']}"
        for c in clusters:
            if c["cls"] == d["cls"] and c["sid"] == sid and \
                    np.linalg.norm([*(c["uv"] - d["uv"]), c["h"] - d["h"]]) < 0.3:
                c["n_views"] += 1
                c["h_min"] = min(c["h_min"], d["h_min"])
                c["frames"].append(d["frame"])
                break
        else:
            clusters.append({**d, "sid": sid, "n_views": 1, "frames": [d["frame"]]})

    clusters = [c for c in clusters if c["n_views"] >= MIN_VIEWS]
    stats["after_multi_view_filter"] = len(clusters)
    DETECTION_STATS.clear()
    DETECTION_STATS.update(stats)
    by_room: dict[str, list] = {}
    for i, c in enumerate(clusters):
        rid = c["room"].room_id
        fired = []
        if c["cls"] == "water_stain" and c["kind"] == "wall" and c["h_min"] < 0.20:
            fired.append("WS-BASE")
        if c["cls"] == "water_stain" and c["kind"] == "ceiling":
            fired.append("WS-CEIL")
        if c["cls"] == "crack" and c["length"] > 0.5:
            fired.append("CR-LONG")
        if c["cls"] == "crack" and c["wall"] is not None:
            w = c["wall"]
            d = (w.p1 - w.p0) / max(w.length_m, 1e-9)
            t = float((c["uv"] - w.p0) @ d)
            if any(min(abs(t - o.start_m), abs(t - o.end_m)) < 0.15 for o in w.openings):
                fired.append("CR-OPEN")
        region = {
            "region_id": f"{rid}_dmg{len(by_room.get(rid, []))}",
            "surface_id": c["sid"], "surface_type": c["kind"], "damage_class": c["cls"],
            "centroid_plan_m": [round(float(c["uv"][0]), 3), round(float(c["uv"][1]), 3)],
            "height_above_floor_m": round(c["h"], 3),
            "extent_m2": from_sigma(c["area"], 0.25 * c["area"], "m2",
                                    "pixel area x depth^2/(fx*fy), obliquity-corrected; sigma 25% "
                                    "for 2D segmentation boundary uncertainty").to_dict(),
            "n_views": c["n_views"], "source_frames": c["frames"][:5],
            "detector": "classical-cv heuristic (no trained model)",
            "concealed_flag": {"flagged": bool(fired),
                               "rules": [{"id": r, "rule": RULES[r]} for r in fired],
                               "rule": "; ".join(f"{r}: {RULES[r]}" for r in fired) or "none fired"},
        }
        if c["cls"] == "crack":
            region["length_m"] = from_sigma(c["length"], 0.2 * c["length"], "m",
                                            "pixel length x depth/fx, obliquity-corrected; sigma 20%").to_dict()
        by_room.setdefault(rid, []).append(region)
    return by_room
