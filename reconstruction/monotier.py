"""Photo and video tiers: per-room pivot scans -> rooms -> one stitched plan.

Photo tier input: a folder with one sub-folder per room (2-8 stills each,
taken turning in place near the middle of the room; sub-folders named in
walking order, e.g. 01_hall, 02_kitchen).
Video tier input: one video file; pivot segments (full turns in place) are
found automatically and treated like photo folders, in order.

Each room is reconstructed on its own (reconstruction/pivot.py) and keeps
only the room the camera stood in. Rooms are then placed into one plan by
matching doorways: for each new room, every (its opening, placed opening)
pair of similar width is tried as a shared doorway (rotations by 90 deg,
door centres coincident, rooms on opposite sides of the wall), and the
placement with no overlap and the best wall agreement wins. A room with no
usable doorway is placed apart and reported as unconnected (never silently
attached somewhere arbitrary).
"""
from __future__ import annotations

import copy
import dataclasses
from pathlib import Path

import cv2
import numpy as np
from matplotlib.path import Path as MplPath

from reconstruction.layout import Layout, Opening, analyze
from reconstruction.mono import WORK_W
from reconstruction.pivot import pivot_room_clouds, frame_orientation, _yaw_of
from reconstruction.mono_depth import predict_depth
from stitching.stitch import raster_union_overlap

IMG_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif"}       # compared lower-case
WALL_THICKNESS_M = 0.15     # typical interior partition; doors sit in a wall this thick


def _read_image(path):
    """BGR image upright. OpenCV reads JPEG/PNG (and applies EXIF rotation);
    iPhone HEIC needs pillow-heif (iPhones save HEIC by default)."""
    img = cv2.imread(str(path))
    if img is not None:
        return img
    try:
        import pillow_heif
        from PIL import Image, ImageOps
        pillow_heif.register_heif_opener()
        im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def _exif_focal_px(path, width_px):
    try:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass
        from PIL import Image
        ex = Image.open(path).getexif()
        f35 = ex.get_ifd(0x8769).get(41989) or ex.get(41989)   # FocalLengthIn35mmFilm
        if f35:
            return float(f35) / 36.0 * width_px if width_px >= 1 else None
    except Exception:
        pass
    return None


def _K(shape, focal_full=None, full_long=None):
    h, w = shape[:2]
    long_side = max(h, w)
    if focal_full and full_long:
        f = focal_full * long_side / full_long
    else:
        f = (0.72 if long_side / min(h, w) > 1.5 else 0.83) * long_side
    return np.array([[f, 0, w / 2.0], [0, f, h / 2.0], [0, 0, 1.0]])


def _prep(img):
    h, w = img.shape[:2]
    s = WORK_W / w
    return cv2.resize(img, (WORK_W, int(round(h * s))), interpolation=cv2.INTER_AREA)


def reconstruct_room(images, K, name):
    clouds, st = pivot_room_clouds(images, K)
    if not clouds:
        return None, st
    L = analyze(clouds, np.zeros((1, 2)))
    cam = (np.zeros(2) @ np.eye(2)) - L.origin
    c = np.array([np.cos(L.theta_rad), np.sin(L.theta_rad)])
    R = np.array([[c[0], c[1]], [-c[1], c[0]]])
    cam = np.zeros(2) @ R.T - L.origin
    room = None
    for r in L.rooms:
        if MplPath(r.polygon).contains_point(cam):
            room = r
            break
    if room is None and L.rooms:
        room = min(L.rooms, key=lambda r: np.linalg.norm(r.polygon.mean(0) - cam))
    if room is None:
        return None, st
    room = copy.deepcopy(room)
    room.room_id = name
    for k, w in enumerate(room.walls):
        w.wall_id = f"{name}_w{k}"
        w.openings = [o for o in w.openings if o.kind != "door"] + [o for o in w.openings if o.kind == "door"]
        for o in w.openings:
            o.leads_to = None
    st["n_openings"] = sum(len(w.openings) for w in room.walls)
    return room, st


def _transform_room(room, T):
    r = copy.deepcopy(room)
    f = lambda p: T[:2, :2] @ p + T[:2, 2]
    r.polygon = np.array([f(p) for p in r.polygon])
    for w in r.walls:
        w.p0, w.p1 = f(w.p0), f(w.p1)
    return r


def _opening_segments(room):
    out = []
    for w in room.walls:
        d = (w.p1 - w.p0) / max(w.length_m, 1e-9)
        for o in w.openings:
            if o.kind == "window":
                continue
            out.append((w, o, w.p0 + d * o.start_m, w.p0 + d * o.end_m))
    return out


def _T(theta, t):
    c, s = np.cos(theta), np.sin(theta)
    T = np.eye(3)
    T[:2, :2] = [[c, -s], [s, c]]
    T[:2, 2] = t
    return T


def place_rooms(rooms):
    """Greedy doorway matching in walking order. Returns (placed rooms,
    adjacency [(a, b)], report)."""
    placed = [rooms[0]]
    adjacency, report = [], []
    for r in rooms[1:]:
        best = None
        for (wb, ob, b0, b1) in _opening_segments(r):
            for P in placed:
                for (wa, oa, a0, a1) in _opening_segments(P):
                    if abs(ob.width_m - oa.width_m) > 0.20:
                        continue
                    da, db = a1 - a0, b1 - b0
                    theta = np.arctan2(da[1], da[0]) - np.arctan2(db[1], db[0]) + np.pi
                    theta = np.round(theta / (np.pi / 2)) * (np.pi / 2)        # rooms are axis-aligned
                    Rm = _T(theta, [0, 0])[:2, :2]
                    # wall normal of A pointing out of A, to offset by the wall thickness
                    na = np.array([-da[1], da[0]]) / (np.linalg.norm(da) + 1e-9)
                    if MplPath(P.polygon).contains_point((a0 + a1) / 2 + na * 0.2):
                        na = -na
                    t = (a0 + a1) / 2 + na * WALL_THICKNESS_M - Rm @ ((b0 + b1) / 2)
                    T = _T(theta, t)
                    cand = _transform_room(r, T)
                    union, overlap = raster_union_overlap([p.polygon for p in placed] + [cand.polygon], res=0.05)
                    score = overlap + 0.5 * abs(ob.width_m - oa.width_m)
                    if best is None or score < best[0]:
                        best = (score, cand, P.room_id, oa, ob, overlap)
        if best is not None and best[5] < 0.3:
            _, cand, other, oa, ob, overlap = best
            oa.leads_to, ob.leads_to = cand.room_id, other
            oa.kind = ob.kind = "door"
            placed.append(cand)
            adjacency.append(tuple(sorted((other, cand.room_id))))
            report.append({"room": cand.room_id, "connected_to": other, "overlap_m2": round(overlap, 3)})
        else:
            # unconnected: place to the right of everything, flagged
            xmax = max(p.polygon[:, 0].max() for p in placed)
            dx = xmax + 1.0 - r.polygon[:, 0].min()
            placed.append(_transform_room(r, _T(0.0, [dx, 0.0])))
            report.append({"room": r.room_id, "connected_to": None,
                           "reason": "no doorway match without overlap" if best else "no openings detected"})
    return placed, adjacency, report


def _as_layout(rooms, adjacency, diagnostics):
    return Layout(rooms=rooms, adjacency=sorted(set(adjacency)), theta_rad=0.0, origin=np.zeros(2),
                  floor_y=0.0, diagnostics=diagnostics)


def photo_tier(folder: Path, log=print):
    folder = Path(folder)
    room_dirs = sorted([d for d in folder.iterdir() if d.is_dir()]) or [folder]
    rooms, stats = [], {}
    for d in room_dirs:
        files = sorted([p for p in d.iterdir() if p.suffix.lower() in IMG_EXT])
        imgs, K = [], None
        for p in files:
            img = _read_image(p)                           # upright (EXIF orientation applied)
            if img is None:
                continue
            if K is None:
                fpx = _exif_focal_px(p, max(img.shape[:2]))
                small = _prep(img)
                K = _K(small.shape, fpx, max(img.shape[:2]))
            imgs.append(_prep(img))
        if len(imgs) < 2:
            stats[d.name] = {"error": "fewer than 2 readable photos"}
            continue
        room, st = reconstruct_room(imgs, K, d.name)
        stats[d.name] = st
        log(f"  {d.name}: {len(imgs)} photos -> {'room ' + str(round(room.floor_area_m2, 2)) + ' m2' if room else 'no room'}")
        if room is not None:
            rooms.append(room)
    if not rooms:
        raise SystemExit("No room could be reconstructed from the photo folders.")
    placed, adjacency, rep = place_rooms(rooms)
    return _as_layout(placed, adjacency, {"per_room": stats, "placement": rep}), {"rooms_in": len(room_dirs),
                                                                                    "rooms_out": len(placed)}


def find_pivots(yaws, times, min_turn_deg=270, max_dur_s=20.0):
    """Segments where the heading turns >= min_turn NET in one direction
    within max_dur. Uses the signed net rotation, not the peak-to-peak
    range: orientation noise goes back and forth and cancels, a real turn
    on the spot accumulates. (Peak-to-peak found 14 phantom pivots in an
    ordinary walk.)"""
    segs, i, n = [], 0, len(yaws)
    while i < n:
        j, best = i, None
        while j < n and times[j] - times[i] <= max_dur_s:
            sweep = abs(np.degrees(yaws[j] - yaws[i]))
            if sweep >= min_turn_deg:
                best = j
                break
            j += 1
        if best is not None:
            # shrink from the left: keep only the minimal window that achieves
            # the turn (otherwise walking frames from elsewhere leak in)
            while i + 1 < best and abs(np.degrees(yaws[best] - yaws[i + 1])) >= min_turn_deg:
                i += 1
            segs.append((i, best))
            i = best + 1
        else:
            i += 1
    return segs


def video_tier(video: Path, rotate="none", fps=2.5, log=print):
    from reconstruction.mono import read_video_frames, ROTATIONS
    frames = read_video_frames(video, fps=fps, max_frames=400, rotate=rotate)
    imgs = [_prep(f) for _, f in frames]
    times = np.array([t for t, _ in frames])
    K = _K(imgs[0].shape)
    # heading track from per-frame room orientation, unwrapped by continuity
    yaws, prev = [], None
    for im in imgs:
        # orientation needs only coarse depth: 4x cheaper than the 392-px pass
        R, info = frame_orientation(predict_depth(im, short_side=224), K)
        if R is None or info.get("yaw_peak_frac", 0) < 0.25:
            yaws.append(np.nan)
            continue
        y = _yaw_of(R)
        if prev is not None:
            y = prev + ((y - prev + np.pi / 4) % (np.pi / 2) - np.pi / 4)   # continuity, mod 90 deg
        yaws.append(y)
        prev = y
    yaws = np.array(yaws)
    ok = ~np.isnan(yaws)
    import os
    segs = find_pivots(yaws[ok], times[ok], min_turn_deg=float(os.environ.get("COZMO_PIVOT_MIN_TURN", 270)))
    idx_ok = np.where(ok)[0]
    log(f"  {len(imgs)} frames, {len(segs)} pivot scan(s) found")
    rooms, stats = [], {}
    for k, (a, b) in enumerate(segs):
        sel = idx_ok[a:b + 1]
        room, st = reconstruct_room([imgs[i] for i in sel], K, f"room_{k + 1}")
        stats[f"room_{k + 1}"] = {**st, "t_start": float(times[sel[0]]), "t_end": float(times[sel[-1]])}
        if room is not None:
            rooms.append(room)
    if not rooms:
        raise SystemExit("No full-turn pivot scan found in the video (see capture protocol: turn a full "
                         "circle in the middle of each room).")
    placed, adjacency, rep = place_rooms(rooms)
    return _as_layout(placed, adjacency, {"per_room": stats, "placement": rep}), {"frames": len(imgs),
                                                                                    "pivots": len(segs)}
