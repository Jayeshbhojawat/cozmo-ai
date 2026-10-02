"""Whole-capture layout analysis: one continuous capture (possibly spanning a
whole apartment) -> rooms, each with a rectilinear dimensioned polygon,
openings, ceiling height, floor area, plus room adjacency.

Replaces the earlier single-polygon RANSAC fitter (`room_fit.py`), which
assumed one capture == one room. With the camera-convention bug fixed (see
`backproject.py`), the sample captures turned out to be clean multi-room
walkthroughs, so the model had to change, not just the tuning.

Pipeline:
 1. Floor height: sharpest low horizontal peak in point heights.
 2. Plan orientation: rotation angle that makes wall points project most
    sharply onto the two plan axes ("projection sharpness" search) - rooms
    are rectilinear, so the plan frame is axis-aligned with the walls.
 3. Free-space carving: 2D rays from each frame's camera position to its
    depth points (stopped 10cm short of the hit) mark traversed cells free.
    This captures room interiors including floor under low furniture,
    and connects rooms only through real openings (rays pass through doors).
 4. Room segmentation: distance transform of the interior; seeds where the
    clearance exceeds a doorway half-width; marker watershed splits rooms at
    doorway constrictions; neighbours sharing >1.3m of boundary are merged
    (open plan, not a door).
 5. Per room: rectilinear polygon from the room mask, then every wall line is
    re-fit against the raw points (1cm histogram peak + median) to get
    cm-level wall positions independent of the 5cm grid.
 6. Openings: along each wall, 2cm bins classify the wall surface as
    present/absent at low and mid heights and look for "see-through"
    evidence beyond the wall plane (points past it). Door = no wall at low
    and mid heights + see-through; window = wall below, gap at mid height +
    see-through. Gaps without see-through are occlusion, not openings.
    Widths are refined to the actual jamb points, not bin edges.
 7. Ceiling per room: horizontal peak above 1.9m with enough area support.
    If the capture never saw the ceiling, it says so (lower bound + flag)
    instead of reporting the top of a cabinet as the ceiling.

Uncertainty (all 1-sigma, model-based until calibrated against ground truth):
 - wall line position: robust std of its surface points / sqrt(n), plus a
   per-surface LiDAR bias term;
 - wall length / opening width: quadrature of the two bounding edges, plus a
   0.3%-of-length scale term (pose/intrinsics scale error);
 - area: first-order propagation of every edge's position sigma.
"""
from __future__ import annotations

import dataclasses

import cv2
import os

import numpy as np
from scipy import ndimage as ndi
from skimage.segmentation import watershed

RES = 0.05                 # plan grid resolution (m)
SURFACE_BIAS_SIGMA = 0.004  # per-surface LiDAR bias (m), 1-sigma
SCALE_SIGMA_FRAC = 0.003    # pose/intrinsic scale error, fraction of length
DOOR_HALF_WIDTH = 0.42      # clearance (m) below which interior is "doorway"
MERGE_SHARED_M = 1.3        # rooms sharing more boundary than this are one room
MIN_ROOM_AREA = 1.0
MIN_WALL_SUPPORT = 40       # surface points needed to call a wall "observed"
UNOBSERVED_SIGMA = 0.03     # position sigma for a boundary with no wall evidence


@dataclasses.dataclass
class Opening:
    start_m: float
    end_m: float
    width_m: float
    width_sigma_m: float
    kind: str              # "door" | "window" | "opening_unconfirmed"
    leads_to: str | None


@dataclasses.dataclass
class Wall:
    wall_id: str
    p0: np.ndarray
    p1: np.ndarray
    length_m: float
    length_sigma_m: float
    line_sigma_m: float
    n_support: int
    openings: list[Opening]
    observed: bool = True


@dataclasses.dataclass
class Room:
    room_id: str
    polygon: np.ndarray
    walls: list[Wall]
    floor_y: float
    ceiling_height_m: float
    ceiling_sigma_m: float
    ceiling_observed: bool
    floor_area_m2: float
    area_sigma_m2: float
    visited: bool
    wall_coverage: float = 1.0
    partial: bool = False


@dataclasses.dataclass
class Layout:
    rooms: list[Room]
    adjacency: list[tuple[str, str]]
    theta_rad: float
    origin: np.ndarray
    floor_y: float
    diagnostics: dict


# ---------------------------------------------------------------- helpers

def _rot(theta):
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, s], [-s, c]])


def find_floor_y(points: np.ndarray) -> float:
    y = points[:, 1]
    lo, mid = np.percentile(y, [0.5, 50])
    band = y[(y >= lo - 0.05) & (y <= mid)]
    hist, edges = np.histogram(band, bins=np.arange(band.min(), band.max() + 0.01, 0.01))
    peak = (edges[np.argmax(hist)] + edges[np.argmax(hist) + 1]) / 2
    near = band[np.abs(band - peak) < 0.02]
    return float(np.median(near))


def dominant_angle(xz: np.ndarray) -> float:
    rng = np.random.default_rng(0)
    if len(xz) > 150_000:
        xz = xz[rng.choice(len(xz), 150_000, replace=False)]

    def score(th):
        u, v = (xz @ _rot(th).T).T
        hu = np.bincount(((u - u.min()) / 0.02).astype(np.int64)).astype(float)
        hv = np.bincount(((v - v.min()) / 0.02).astype(np.int64)).astype(float)
        return (hu ** 2).sum() + (hv ** 2).sum()

    coarse = np.radians(np.arange(0, 90, 1.0))
    best = coarse[int(np.argmax([score(t) for t in coarse]))]
    fine = best + np.radians(np.arange(-1.0, 1.0, 0.05))
    return float(fine[int(np.argmax([score(t) for t in fine]))]) % (np.pi / 2)


# ------------------------------------------------------------ main entry

def find_floor_y_handheld(points: np.ndarray, camera_y: float, below=(0.9, 1.9)) -> tuple[float, str]:
    """Floor for captures WITHOUT direct depth (learned depth): the phone is
    hand-held, so the floor lies 0.9-1.9 m below the camera path. Only that
    window is searched. A clear horizontal peak there is the floor; if none
    (the phone rarely looked down and the floor is hidden by furniture), the
    floor is the window's lower edge (1st percentile of the points in it),
    reported as estimated. Without the window, the global histogram picked
    a bed / counter top 0.5-0.7 m below the camera on the measured home."""
    y = points[:, 1]
    w = y[(y > camera_y - below[1]) & (y < camera_y - below[0])]
    if len(w) < 200:
        return camera_y - 1.45, "prior_only"
    hist, edges = np.histogram(w, bins=np.arange(w.min(), w.max() + 0.02, 0.02))
    k = int(np.argmax(hist))
    if hist[k] > 3.0 * np.median(hist) and k < len(hist) * 0.5:
        return float((edges[k] + edges[k + 1]) / 2), "peak"
    return float(np.percentile(w, 1.0)), "lower_edge"


def analyze(frame_clouds: list[tuple[np.ndarray, np.ndarray]], trajectory_xz: np.ndarray,
            camera_y: float | None = None, occupancy_ratio: float | None = None,
            door_half_width: float | None = None, min_feature_m: float | None = None) -> Layout:
    """frame_clouds: list of (camera_position_xyz, world_points) per frame.
    camera_y: median camera height for hand-held captures without direct
    depth; switches the floor search to find_floor_y_handheld.
    occupancy_ratio: for noisy (learned) depth. A cell is an obstacle only
    if its wall-band hits are at least this fraction of the camera rays that
    PASS THROUGH it (a real wall stops rays; a stray point in open space is
    passed through many times). None = LiDAR behaviour (>= 2 hits).
    min_feature_m: for noisy depth. Outline notches and wall pieces smaller
    than this are treated as noise: the room mask is closed/opened at this
    size before tracing, and wall pieces shorter than it are merged away.
    None = LiDAR behaviour (10 cm stubs only)."""
    all_pts = np.concatenate([p for _, p in frame_clouds])
    keys = np.floor(all_pts / 0.02).astype(np.int64)
    _, keep = np.unique(keys, axis=0, return_index=True)
    pts = all_pts[keep]                       # 2cm-deduplicated cloud

    floor_method = "histogram"
    if camera_y is not None and os.environ.get("COZMO_VIDEO_FLOOR", "handheld") == "handheld":
        floor_y, floor_method = find_floor_y_handheld(pts, camera_y)
    else:
        floor_y = find_floor_y(pts)
    h = pts[:, 1] - floor_y
    band = (h > 0.3) & (h < 1.9)
    theta = dominant_angle(pts[band][:, [0, 2]])
    R = _rot(theta)

    uv = pts[:, [0, 2]] @ R.T
    origin = uv.min(axis=0) - 0.5
    uv = uv - origin
    traj_uv = trajectory_xz @ R.T - origin
    shape = (int(np.ceil(uv[:, 0].max() / RES)) + 10, int(np.ceil(uv[:, 1].max() / RES)) + 10)

    def cells(p):
        return np.clip((p[:, 0] / RES).astype(np.int64), 0, shape[0] - 1), \
               np.clip((p[:, 1] / RES).astype(np.int64), 0, shape[1] - 1)

    # Tall obstacles (walls, tall furniture): points at 1.2-1.9m above floor.
    tall = (h > 1.2) & (h < 1.9)
    iu, iv = cells(uv[tall])
    obstacle = np.zeros(shape, np.int32)
    np.add.at(obstacle, (iu, iv), 1)
    hits = obstacle

    # Free-space carving with 2D rays.
    free = np.zeros(shape[0] * shape[1], np.int32)
    step = RES * 0.5
    for cam, fp in frame_clouds:
        fh = fp[:, 1] - floor_y
        fp = fp[(fh > 0.05) & (fh < 2.2)]
        if len(fp) == 0:
            continue
        c = (cam[[0, 2]] @ R.T) - origin
        p = (fp[:, [0, 2]] @ R.T) - origin
        d = p - c
        L = np.linalg.norm(d, axis=1)
        n = np.maximum(((L - 0.10) / step).astype(np.int64), 0)
        tot = int(n.sum())
        if tot == 0:
            continue
        idx = np.repeat(np.arange(len(p)), n)
        k = np.arange(tot) - np.repeat(np.cumsum(n) - n, n)
        t = (k * step) / np.maximum(L[idx], 1e-6)
        s = c + d[idx] * t[:, None]
        a, b = cells(s)
        free += np.bincount(a * shape[1] + b, minlength=shape[0] * shape[1])
    passes = free.reshape(shape)
    if occupancy_ratio is None:
        obstacle = hits >= 2
    else:
        obstacle = (hits >= 2) & (hits >= occupancy_ratio * passes)
    free = passes >= 2

    # Close small ray-sampling gaps in free space FIRST, then re-impose the
    # obstacles: closing after masking would also erase one-cell-thick
    # interior walls and fuse neighbouring rooms into one region (a bug in
    # the first version of this module: a whole apartment came out as one
    # 67 m2 "room").
    free = ndi.binary_closing(free, structure=np.ones((3, 3)), iterations=1)
    interior = free & ~obstacle
    interior = ndi.binary_opening(interior, structure=np.ones((3, 3)), iterations=1)
    lab, n_comp = ndi.label(interior)
    if n_comp:
        sizes = ndi.sum(interior, lab, range(1, n_comp + 1))
        interior = lab == (int(np.argmax(sizes)) + 1)   # keep the walked-through component
    interior = ndi.binary_fill_holes(interior)

    # Room segmentation.
    dt = ndi.distance_transform_edt(interior) * RES
    seeds, n_seeds = ndi.label(dt > (door_half_width or DOOR_HALF_WIDTH))
    if n_seeds:
        seed_area = ndi.sum(np.ones(shape), seeds, range(1, n_seeds + 1)) * RES * RES
        for i, a in enumerate(seed_area, start=1):
            if a < 0.25:
                seeds[seeds == i] = 0
    labels = watershed(-dt, seeds, mask=interior)
    labels = _merge_open_plan(labels)

    # Room-level analysis.
    rel_h = h
    rooms: list[Room] = []
    room_labels = [l for l in np.unique(labels) if l != 0]
    areas = {l: (labels == l).sum() * RES * RES for l in room_labels}
    room_labels = [l for l in sorted(room_labels, key=lambda l: -areas[l]) if areas[l] >= MIN_ROOM_AREA]
    label_to_id = {l: f"room_{i + 1}" for i, l in enumerate(room_labels)}
    pt_iu, pt_iv = cells(uv)
    pt_label = labels[pt_iu, pt_iv]
    traj_iu, traj_iv = cells(traj_uv)
    visited_labels = set(np.unique(labels[traj_iu, traj_iv]).tolist())

    for l in room_labels:
        rid = label_to_id[l]
        mask = ndi.binary_fill_holes(labels == l)
        room = _analyze_room(rid, mask, uv, rel_h, floor_y, pt_label, l, labels, label_to_id,
                             visited=l in visited_labels, min_feature_m=min_feature_m)
        if room is not None:
            rooms.append(room)

    adjacency = _adjacency(labels, label_to_id)
    by_id = {r.room_id: r for r in rooms}
    for ra, rb, centre, cut_dir, left, right, sigma in _doorways(labels, label_to_id, uv, rel_h):
        for rid, other in ((ra, rb), (rb, ra)):
            if rid in by_id:
                _attach_doorway(by_id[rid], other, centre, cut_dir, left, right, sigma)
    return Layout(rooms=rooms, adjacency=adjacency, theta_rad=theta, origin=origin, floor_y=floor_y,
                  diagnostics={"grid_shape": shape, "n_points": int(len(pts)), "floor_method": floor_method,
                               "interior_m2": float(interior.sum() * RES * RES),
                               "labels": labels, "obstacle": obstacle})


def _merge_open_plan(labels: np.ndarray) -> np.ndarray:
    labels = labels.copy()
    changed = True
    while changed:
        changed = False
        ids = [l for l in np.unique(labels) if l != 0]
        for a in ids:
            ma = labels == a
            ring = ndi.binary_dilation(ma) & ~ma
            neigh, counts = np.unique(labels[ring], return_counts=True)
            for b, cnt in zip(neigh, counts):
                if b == 0 or b == a:
                    continue
                if cnt * RES > MERGE_SHARED_M:
                    labels[labels == b] = a
                    changed = True
                    break
            if changed:
                break
    return labels


def _doorways(labels, label_to_id, uv, rel_h):
    """Room-to-room doorways measured where the segmentation cut two rooms
    apart. The watershed cut sits inside the doorway, so the door is not a
    gap *in* a wall edge but the boundary itself; measure it directly as the
    clear distance between the jamb surfaces on either side of the cut."""
    found = []
    ids = list(label_to_id)
    jamb_pts = uv[(rel_h > 0.3) & (rel_h < 1.9)]
    for i, a in enumerate(ids):
        ma = labels == a
        for b in ids[i + 1:]:
            mb = labels == b
            cut = ma & ndi.binary_dilation(mb)          # a-cells touching b
            if cut.sum() * RES < 0.3:
                continue
            ci, cj = np.nonzero(cut)
            cells = np.stack([(ci + 0.5) * RES, (cj + 0.5) * RES], axis=1)
            centre = cells.mean(axis=0)
            # cut runs along the axis with more spread; passage crosses it
            along = 0 if np.ptp(cells[:, 0]) >= np.ptp(cells[:, 1]) else 1
            across = 1 - along
            near = np.abs(jamb_pts[:, across] - centre[across]) < 0.12
            off = jamb_pts[near, along] - centre[along]
            off = off[np.abs(off) < 1.5]
            lft, rgt = off[off < 0], off[off > 0]
            if len(lft) < 5 or len(rgt) < 5:
                continue
            left = float(np.percentile(lft, 98))
            right = float(np.percentile(rgt, 2))
            width = right - left
            if not (0.45 <= width <= 2.2):
                continue
            sigma = float(np.sqrt(2 * 0.004 ** 2 + (SCALE_SIGMA_FRAC * width) ** 2))
            cut_dir = np.zeros(2)
            cut_dir[along] = 1.0
            found.append((label_to_id[a], label_to_id[b], centre, cut_dir,
                          centre[along] + left, centre[along] + right, sigma))
    return found


def _attach_doorway(room, other_id, centre, cut_dir, left, right, sigma):
    """Put the doorway on this room's wall that is parallel to the cut and
    closest to it; replace any overlapping see-through opening there."""
    along = int(np.argmax(cut_dir))
    across = 1 - along
    best, best_d = None, 0.6
    for w in room.walls:
        d = w.p1 - w.p0
        if w.length_m < 1e-6 or abs(d[along]) < abs(d[across]):
            continue
        dist = abs(w.p0[across] - centre[across])
        lo, hi = sorted([w.p0[along], w.p1[along]])
        if dist < best_d and lo - 0.2 <= centre[along] <= hi + 0.2:
            best, best_d = w, dist
    if best is None:
        return
    sgn = 1.0 if best.p1[along] >= best.p0[along] else -1.0
    s0 = (left - best.p0[along]) * sgn
    s1 = (right - best.p0[along]) * sgn
    start, end = sorted([s0, s1])
    best.openings = [o for o in best.openings if o.end_m < start or o.start_m > end]
    best.openings.append(Opening(start_m=float(start), end_m=float(end), width_m=float(right - left),
                                 width_sigma_m=sigma, kind="door", leads_to=other_id))


def _adjacency(labels, label_to_id):
    pairs = set()
    for a, ida in label_to_id.items():
        ring = ndi.binary_dilation(labels == a, iterations=2) & (labels != a)
        neigh, counts = np.unique(labels[ring], return_counts=True)
        for b, cnt in zip(neigh, counts):
            if b in label_to_id and cnt * RES >= 0.3:
                pairs.add(tuple(sorted((ida, label_to_id[b]))))
    return sorted(pairs)


# ---------------------------------------------------- rectilinear polygon

def _rectilinear_edges(mask: np.ndarray):
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None
    cnt = max(cnts, key=cv2.contourArea)
    approx = cv2.approxPolyDP(cnt, 2.0, True)[:, 0, :].astype(float)
    # contour points are (col, row) = (iv, iu) -> plan (u, v) of cell centres
    P = np.stack([(approx[:, 1] + 0.5) * RES, (approx[:, 0] + 0.5) * RES], axis=1)
    edges = []
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        du, dv = b - a
        L = float(np.hypot(du, dv))
        if L < 1e-6:
            continue
        if abs(du) >= abs(dv):
            edges.append(["U", (a[1] + b[1]) / 2, L])   # runs along u, at v = const
        else:
            edges.append(["V", (a[0] + b[0]) / 2, L])   # runs along v, at u = const

    def merge_same(es):
        out = []
        for e in es:
            if out and out[-1][0] == e[0]:
                o = out[-1]
                tot = o[2] + e[2]
                out[-1] = [o[0], (o[1] * o[2] + e[1] * e[2]) / tot, tot]
            else:
                out.append(list(e))
        if len(out) > 1 and out[0][0] == out[-1][0]:
            o, e = out[-1], out[0]
            tot = o[2] + e[2]
            out[0] = [e[0], (o[1] * o[2] + e[1] * e[2]) / tot, tot]
            out.pop()
        return out

    edges = merge_same(edges)
    while len(edges) > 4:
        lengths = [e[2] for e in edges]
        k = int(np.argmin(lengths))
        if lengths[k] >= 0.25:
            break
        edges.pop(k)
        edges = merge_same(edges)
    if len(edges) < 4 or len(edges) % 2:
        return None
    return edges


def _corners(edges):
    pts = []
    n = len(edges)
    for k in range(n):
        e, f = edges[k - 1], edges[k]   # corner between previous edge and this one
        if e[0] == "U" and f[0] == "V":
            pts.append([f[1], e[1]])
        elif e[0] == "V" and f[0] == "U":
            pts.append([e[1], f[1]])
        else:
            return None
    return np.array(pts)


def _signed_area(P):
    x, y = P[:, 0], P[:, 1]
    return 0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


# ------------------------------------------------------------ room level

def _analyze_room(rid, mask, uv, rel_h, floor_y, pt_label, label, labels, label_to_id, visited,
                  min_feature_m=None):
    if min_feature_m:
        k = max(1, int(round(min_feature_m / RES)))
        st = np.ones((k, k), bool)
        sm = ndi.binary_opening(ndi.binary_closing(mask, structure=st), structure=st)
        if sm.sum() > 0.7 * mask.sum():          # never let smoothing eat the room
            mask = sm
    edges = _rectilinear_edges(mask)
    if edges is None:
        return None
    P = _corners(edges)
    if P is None:
        return None
    ccw = _signed_area(P) > 0

    # Points near this room (mask dilated by 0.4m) for wall refinement.
    near_mask = ndi.binary_dilation(mask, iterations=int(0.4 / RES))
    iu = np.clip((uv[:, 0] / RES).astype(np.int64), 0, mask.shape[0] - 1)
    iv = np.clip((uv[:, 1] / RES).astype(np.int64), 0, mask.shape[1] - 1)
    sel = near_mask[iu, iv]
    ruv, rh = uv[sel], rel_h[sel]

    # Refine each edge's coordinate against the raw points. Edges become
    # [orient, coord, grid_len, sigma, support].
    n = len(edges)
    for k in range(n):
        a, b = P[k], P[(k + 1) % n]
        orient, coord = edges[k][0], edges[k][1]
        along_axis = 0 if orient == "U" else 1
        norm_axis = 1 - along_axis
        lo, hi = sorted([a[along_axis], b[along_axis]])
        out_sign = _out_sign(a, b, ccw, norm_axis)
        m = (ruv[:, along_axis] > lo + 0.10) & (ruv[:, along_axis] < hi - 0.10) & (rh > 0.2) & (rh < 2.0)
        s = (ruv[m, norm_axis] - coord) * out_sign
        s = s[(s > -0.20) & (s < 0.40)]
        if len(s) < MIN_WALL_SUPPORT:
            edges[k] = [orient, coord, edges[k][2], UNOBSERVED_SIGMA, int(len(s))]
            continue
        hist, ed = np.histogram(s, bins=np.arange(-0.20, 0.41, 0.01))
        peak = (ed[np.argmax(hist)] + ed[np.argmax(hist) + 1]) / 2
        surf = s[np.abs(s - peak) < 0.025]
        ref = float(np.median(surf))
        mad = float(np.median(np.abs(surf - ref))) * 1.4826
        sigma = float(np.sqrt((mad / np.sqrt(max(len(surf), 1))) ** 2 + SURFACE_BIAS_SIGMA ** 2))
        edges[k] = [orient, coord + ref * out_sign, edges[k][2], sigma, int(len(surf))]

    # Refinement can leave stub edges (a few cm) where two refined lines
    # almost meet; drop them and merge the now-adjacent parallel neighbours.
    edges = _drop_stub_edges(edges, min_len=max(0.10, min_feature_m or 0.0))
    if edges is None:
        return None
    P = _corners(edges)
    n = len(edges)
    lengths = [float(np.linalg.norm(P[(k + 1) % n] - P[k])) for k in range(n)]
    sigmas = [e[3] for e in edges]
    area = abs(_signed_area(P))
    area_sigma = float(np.sqrt(sum((lengths[k] * sigmas[k]) ** 2 for k in range(n))))

    walls = []
    for k in range(n):
        a, b = P[k], P[(k + 1) % n]
        L = lengths[k]
        s_prev, s_next = sigmas[k - 1], sigmas[(k + 1) % n]   # perpendicular neighbours bound the length
        L_sigma = float(np.sqrt(s_prev ** 2 + s_next ** 2 + (SCALE_SIGMA_FRAC * L) ** 2))
        openings = _find_openings(a, b, edges[k], ccw, ruv, rh, labels, label, label_to_id, sigmas[k])
        walls.append(Wall(wall_id=f"{rid}_w{k}", p0=a, p1=b, length_m=L, length_sigma_m=L_sigma,
                          line_sigma_m=sigmas[k], n_support=edges[k][4], openings=openings,
                          observed=edges[k][4] >= MIN_WALL_SUPPORT))
    perim = sum(lengths)
    coverage = sum(w.length_m for w in walls if w.observed) / perim if perim else 0.0

    ceiling_h, ceiling_sigma, observed, floor_local = _ceiling(mask, near_mask, uv, rel_h)
    return Room(room_id=rid, polygon=P, walls=walls, floor_y=floor_y + floor_local,
                ceiling_height_m=ceiling_h, ceiling_sigma_m=ceiling_sigma, ceiling_observed=observed,
                floor_area_m2=float(area), area_sigma_m2=area_sigma, visited=visited,
                wall_coverage=float(coverage),
                partial=(not visited) or coverage < 0.6)


def _out_sign(a, b, ccw, norm_axis):
    direction = b - a
    left = np.array([-direction[1], direction[0]])   # interior is on the left of a CCW polygon
    outward = -left if ccw else left
    return float(np.sign(outward[norm_axis]) or 1.0)


def _drop_stub_edges(edges, min_len):
    for _ in range(50):
        P = _corners(edges)
        if P is None:
            return None
        n = len(edges)
        lengths = [float(np.linalg.norm(P[(k + 1) % n] - P[k])) for k in range(n)]
        k = int(np.argmin(lengths))
        if lengths[k] >= min_len or n <= 4:
            return edges
        edges = edges[:k] + edges[k + 1:]
        merged = []
        for e in edges:
            if merged and merged[-1][0] == e[0]:
                merged[-1] = _merge_edge(merged[-1], e)
            else:
                merged.append(e)
        if len(merged) > 1 and merged[0][0] == merged[-1][0]:
            merged[0] = _merge_edge(merged[-1], merged[0])
            merged.pop()
        edges = merged
        if len(edges) < 4 or len(edges) % 2:
            return None
    return edges


def _merge_edge(e, f):
    # Two parallel lines collapsing into one: keep the better-supported
    # line's position (support-weighted), sigma of the better one.
    we, wf = max(e[4], 1), max(f[4], 1)
    coord = (e[1] * we + f[1] * wf) / (we + wf)
    best = e if e[4] >= f[4] else f
    return [e[0], coord, e[2] + f[2], best[3], e[4] + f[4]]


def _find_openings(a, b, edge, ccw, ruv, rh, labels, label, label_to_id, line_sigma):
    orient, coord = edge[0], edge[1]
    along_axis = 0 if orient == "U" else 1
    norm_axis = 1 - along_axis
    direction = b - a
    L = float(np.linalg.norm(direction))
    if L < 0.6:
        return []
    unit = direction / L
    left = np.array([-direction[1], direction[0]])
    outward = -left if ccw else left
    out_sign = np.sign(outward[norm_axis]) or 1.0

    t = (ruv - a) @ unit                         # position along wall from p0
    s = (ruv[:, norm_axis] - coord) * out_sign   # signed distance outward
    on_wall = np.abs(s) < 0.05
    beyond = (s > 0.25) & (s < 4.0) & (rh > 0.3) & (rh < 1.9)
    in_span = (t > 0.05) & (t < L - 0.05)

    bins = np.arange(0.05, L - 0.05 + 1e-9, 0.02)
    if len(bins) < 3:
        return []
    nb = len(bins) - 1

    def occupancy(m):
        idx = np.clip(((t[m] - 0.05) / 0.02).astype(np.int64), 0, nb - 1)
        occ = np.zeros(nb, bool)
        occ[idx] = True
        return occ

    low = occupancy(on_wall & in_span & (rh > 0.15) & (rh < 0.7))
    mid = occupancy(on_wall & in_span & (rh > 0.9) & (rh < 1.7))
    see = occupancy(beyond & in_span)
    # Small sensor dropouts (<6cm) should not split a wall or an opening.
    low = ndi.binary_closing(low, structure=np.ones(3))
    mid = ndi.binary_closing(mid, structure=np.ones(3))
    see_smooth = ndi.binary_dilation(see, structure=np.ones(7))

    openings = []
    gap = ~mid
    lab, n = ndi.label(gap)
    for i in range(1, n + 1):
        idx = np.where(lab == i)[0]
        run_len = len(idx) * 0.02
        if run_len < 0.40:
            continue
        see_frac = see_smooth[idx].mean()
        low_frac = low[idx].mean()
        if see_frac < 0.3:
            continue           # wall not observed here (occluded), not an opening
        if low_frac < 0.3 and run_len >= 0.55:
            kind = "door"
        elif low_frac >= 0.6:
            kind = "window"
        else:
            continue
        # Refine to jamb points: last wall point before / first after the gap.
        start = 0.05 + idx[0] * 0.02
        end = 0.05 + (idx[-1] + 1) * 0.02
        jm = on_wall & (rh > 0.3) & (rh < 1.8)
        left_pts = t[jm & (t > start - 0.15) & (t <= start + 0.01)]
        right_pts = t[jm & (t >= end - 0.01) & (t < end + 0.15)]
        refined = len(left_pts) >= 3 and len(right_pts) >= 3
        if refined:
            start = float(np.percentile(left_pts, 98))
            end = float(np.percentile(right_pts, 2))
        width = end - start
        w_sigma = float(np.sqrt(2 * (0.004 if refined else 0.0115) ** 2 + (SCALE_SIGMA_FRAC * width) ** 2))
        # What is on the other side? A visited room -> confirmed door.
        mid_t = (start + end) / 2
        probe = a + unit * mid_t + outward / (np.linalg.norm(outward) + 1e-9) * 0.5
        pi = int(np.clip(probe[0] / RES, 0, labels.shape[0] - 1))
        pj = int(np.clip(probe[1] / RES, 0, labels.shape[1] - 1))
        other = labels[pi, pj]
        leads_to = label_to_id.get(other) if other not in (0, label) else None
        if kind == "door" and leads_to is None:
            kind = "opening_unconfirmed"   # could be exterior door, mirror or glass
        openings.append(Opening(start_m=start, end_m=end, width_m=width, width_sigma_m=w_sigma,
                                kind=kind, leads_to=leads_to))
    return openings


def _ceiling(mask, near_mask, uv, rel_h):
    iu = np.clip((uv[:, 0] / RES).astype(np.int64), 0, mask.shape[0] - 1)
    iv = np.clip((uv[:, 1] / RES).astype(np.int64), 0, mask.shape[1] - 1)
    inside = mask[iu, iv]
    hh = rel_h[inside]
    floor_pts = hh[np.abs(hh) < 0.05]
    floor_local = float(np.median(floor_pts)) if len(floor_pts) > 50 else 0.0
    hh = hh - floor_local
    up = hh > 1.9
    if up.sum() > 50:
        hist, ed = np.histogram(hh[up], bins=np.arange(1.9, hh[up].max() + 0.02, 0.01))
        if len(hist):
            peak = (ed[np.argmax(hist)] + ed[np.argmax(hist) + 1]) / 2
            sel = np.abs(hh - peak) < 0.015
            cells_cnt = len(np.unique(iu[inside][sel] * 100000 + iv[inside][sel]))
            if cells_cnt * RES * RES >= 0.3:
                vals = hh[sel]
                c = float(np.median(vals))
                mad = float(np.median(np.abs(vals - c))) * 1.4826
                sigma = float(np.sqrt((mad / np.sqrt(len(vals))) ** 2 + 2 * SURFACE_BIAS_SIGMA ** 2))
                return c, sigma, True, floor_local
    # Ceiling never observed: report the highest wall surface observed around
    # the room as a lower bound (the room's own interior mask excludes walls).
    near = near_mask[iu, iv]
    hn = rel_h[near] - floor_local
    lower = float(np.percentile(hn, 99.5)) if len(hn) else 0.0
    return lower, float("nan"), False, floor_local
