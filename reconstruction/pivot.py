"""Pivot-scan reconstruction for the photo and video tiers.

Protocol (docs/capture_protocol.md): in each room, stand near the middle and
turn slowly through a full circle (photo tier: 6-8 overlapping stills;
video tier: one clip that pauses to turn a full circle in every room).

Why not feature tracking: measured on our captures, plain painted walls,
ceilings, mirrors and glass give 24-73 ORB keypoints per frame (vs ~2500 on
textured views), so feature-based pose tracking breaks exactly in the rooms
we need to measure (see git history: reconstruction/mono.py tracker).

What is used instead - room geometry ("Manhattan frame"):
 1. Per frame: learned depth (shape) -> per-pixel surface normals.
 2. Gravity: normals of horizontal surfaces (floor/ceiling) if visible,
    otherwise the direction perpendicular to the wall normals; image-up as
    a weak prior to pick the sign.
 3. Yaw relative to the room: wall normals projected on the horizontal
    plane, histogram of their angle mod 90 deg -> dominant direction.
    The 90-deg ambiguity is resolved by continuity (the user turns one way
    in small steps).
 4. Translation: ~0 for a pivot (the phone moves ~0.2-0.3 m around the
    body; disclosed as an error term).
 5. Scale: camera height above the floor where the floor is visible
    (protocol chest height 1.42 m), else the model's measured scale prior.
 6. All frames' points, rotated into one gravity- and room-aligned frame,
    go to the same layout.analyze the LiDAR tier uses.
"""
from __future__ import annotations

import numpy as np

from reconstruction.mono import (CAMERA_HEIGHT_M, MODEL_SCALE_PRIOR, backproject, fit_floor,
                                 predict_depth)


def _normals(P):
    """Per-pixel normals from a (h, w, 3) point map via central differences."""
    dx = np.zeros_like(P)
    dy = np.zeros_like(P)
    dx[:, 1:-1] = P[:, 2:] - P[:, :-2]
    dy[1:-1] = P[2:] - P[:-2]
    n = np.cross(dx, dy)
    nn = np.linalg.norm(n, axis=-1, keepdims=True)
    n = n / np.maximum(nn, 1e-9)
    # orient towards the camera
    flip = (n * P).sum(-1) > 0
    n[flip] *= -1
    return n, nn[..., 0]


def frame_orientation(depth, K, prior_up=np.array([0, -1.0, 0])):
    """Returns (R_cw, info): rotation taking camera coords to a room frame
    with +y up and walls along x/z (yaw defined mod 90 deg)."""
    import cv2
    d = cv2.GaussianBlur(depth, (5, 5), 0)
    P = backproject(d, K)
    n, mag = _normals(P)
    h, w = d.shape
    valid = (P[..., 2] > 0.3) & (P[..., 2] < 6.0)
    valid[:3], valid[-3:], valid[:, :3], valid[:, -3:] = False, False, False, False
    # smooth regions only (normals at depth edges are garbage)
    gy, gx = np.gradient(np.log(np.maximum(d, 1e-3)))
    valid &= np.hypot(gx, gy) < 0.03
    N = n[valid]
    if len(N) < 200:
        return None, {"reason": "too few smooth surface pixels"}
    if len(N) > 20000:
        N = N[np.random.default_rng(0).choice(len(N), 20000, replace=False)]
    cos_up = N @ prior_up
    horiz = np.abs(cos_up) > np.cos(np.radians(25))        # floor / ceiling candidates
    if horiz.sum() > 300:
        H = N[horiz] * np.sign(cos_up[horiz])[:, None]      # flip ceilings to point up too
        up = H.mean(0)
        src = "horizontal surfaces"
    else:
        walls = np.abs(cos_up) < np.sin(np.radians(35))
        Wn = N[walls]
        if len(Wn) < 300:
            return None, {"reason": "no floor/ceiling and too little wall"}
        ev, evec = np.linalg.eigh(Wn.T @ Wn)
        up = evec[:, 0]                                      # least-represented direction among wall normals
        if up @ prior_up < 0:
            up = -up
        if up @ prior_up < np.cos(np.radians(40)):
            up = prior_up                                    # degenerate (one wall only): keep the prior
            src = "image-up prior"
        else:
            src = "wall normals"
    up /= np.linalg.norm(up)
    walls = np.abs(N @ up) < np.sin(np.radians(20))
    Wn = N[walls]
    if len(Wn) < 200:
        return None, {"reason": "no wall visible"}
    # horizontal basis
    e1 = np.cross(up, [0, 0, 1.0])
    if np.linalg.norm(e1) < 1e-3:
        e1 = np.cross(up, [1.0, 0, 0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(e1, up)
    ang = np.arctan2(Wn @ e2, Wn @ e1) % (np.pi / 2)
    hist, edges = np.histogram(ang, bins=90, range=(0, np.pi / 2))
    hist = np.convolve(np.r_[hist[-2:], hist, hist[:2]], np.ones(5) / 5, mode="same")[2:-2]
    k = int(np.argmax(hist))
    sel = np.abs(((ang - (edges[k] + edges[k + 1]) / 2) + np.pi / 4) % (np.pi / 2) - np.pi / 4) < np.radians(4)
    yaw = float(np.angle(np.mean(np.exp(4j * ang[sel]))) / 4) % (np.pi / 2)
    x_axis = np.cos(yaw) * e1 + np.sin(yaw) * e2             # a wall normal direction
    z_axis = np.cross(x_axis, up)
    R_cw = np.stack([x_axis, up, z_axis])                    # rows: room axes in camera coords
    return R_cw, {"gravity_from": src, "wall_px": int(len(Wn)), "yaw_peak_frac": float(sel.mean())}


def _yaw_of(R_cw):
    # camera forward (+z cam) expressed in room frame -> heading
    f = R_cw @ np.array([0, 0, 1.0])
    return np.arctan2(f[0], f[2])


def _rot_y(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def pivot_room_clouds(images, K, stride=4, max_depth=6.0, log=None):
    """images: upright BGR frames of ONE pivot scan, in capture order.
    Returns (frame_clouds, stats) in a room-aligned metric frame with the
    camera at (0, CAMERA_HEIGHT_M above floor, 0)."""
    import cv2
    rots, depths, floors, infos = [], [], [], []
    for img in images:
        d = predict_depth(img)
        depths.append(d)
        floors.append(fit_floor(d, K))
        R, info = frame_orientation(d, K)
        rots.append(R)
        infos.append(info)
    # resolve the 90-degree yaw ambiguity by continuity
    prev = None
    for i, R in enumerate(rots):
        if R is None:
            continue
        if prev is not None:
            best, best_d = R, 9.0
            for q in range(4):
                Rq = _rot_y(q * np.pi / 2) @ R
                dyaw = abs(np.angle(np.exp(1j * (_yaw_of(Rq) - _yaw_of(prev)))))
                if dyaw < best_d:
                    best, best_d = Rq, dyaw
            rots[i] = best
        prev = rots[i]
    # scale: camera height above the floor where visible, else model prior
    hs = [f.height for f, R in zip(floors, rots) if f is not None and R is not None]
    if len(hs) >= 2:
        scale = CAMERA_HEIGHT_M / float(np.median(hs))
        scale_src = f"floor ({len(hs)} frames)"
    else:
        scale = MODEL_SCALE_PRIOR
        scale_src = "model prior (floor not visible)"
    cam = np.array([0.0, CAMERA_HEIGHT_M, 0.0])
    clouds = []
    h, w = depths[0].shape
    ys, xs = np.mgrid[0:h:stride, 0:w:stride].astype(np.float32)
    for d, R in zip(depths, rots):
        if R is None:
            continue
        dd = d[::stride, ::stride] * scale
        gy, gx = np.gradient(np.log(np.maximum(d, 1e-3)))
        m = (dd > 0.3) & (dd < max_depth) & (np.hypot(gx, gy)[::stride, ::stride] < 0.08)
        Pc = np.stack([(xs[m] - K[0, 2]) / K[0, 0] * dd[m], (ys[m] - K[1, 2]) / K[1, 1] * dd[m], dd[m]], 1)
        Pr = Pc @ R.T                     # room frame, camera at origin
        Pr[:, 1] += CAMERA_HEIGHT_M        # floor at y=0 (approximately)
        clouds.append((cam.copy(), Pr))
    stats = {"frames": len(images), "oriented": int(sum(r is not None for r in rots)),
             "scale": float(scale), "scale_source": scale_src,
             "gravity_sources": sorted({i.get("gravity_from", "none") for i in infos})}
    return clouds, stats
