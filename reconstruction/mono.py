"""Monocular reconstruction for the video and photo tiers.

Per frame: learned depth (shape only) -> floor plane by RANSAC in the lower
part of the upright image -> metric scale from camera height above the
floor (protocol: phone at chest height; measured 1.40/1.40/1.46 m on our
three LiDAR walks) -> gravity from the floor normal.
Between frames: ORB matches + previous frame's metric depth -> PnP (metric
pose, robust to turning on the spot, no essential-matrix degeneracy).
The resulting per-frame world point clouds go into the SAME
`layout.analyze` the LiDAR tier uses.
"""
from __future__ import annotations

import dataclasses

import cv2
import numpy as np

from reconstruction.mono_depth import predict_depth

CAMERA_HEIGHT_M = 1.42          # protocol chest height; LiDAR walks: 1.40, 1.40, 1.46
CAMERA_HEIGHT_SIGMA_M = 0.04
WORK_W = 256                    # working width for depth -> points (upright frame)


@dataclasses.dataclass
class FloorFit:
    normal: np.ndarray   # unit, camera coords, pointing from floor to camera ("up")
    height: float        # camera-to-floor distance in model units
    inlier_frac: float


def backproject(depth, K):
    h, w = depth.shape
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    z = depth
    return np.stack([(xs - K[0, 2]) / K[0, 0] * z, (ys - K[1, 2]) / K[1, 1] * z, z], axis=-1)


def fit_floor(depth, K, rng=None, iters=200):
    """RANSAC plane in the lower 45% of an upright image. Accept planes whose
    up-normal is within 30 deg of image-up (camera -y) and which lie below
    the camera. Returns FloorFit or None."""
    rng = rng or np.random.default_rng(0)
    h, w = depth.shape
    P = backproject(depth, K)[int(h * 0.55):].reshape(-1, 3)
    P = P[(P[:, 2] > 0.3) & (P[:, 2] < 8.0)]
    if len(P) < 200:
        return None
    if len(P) > 4000:
        P = P[rng.choice(len(P), 4000, replace=False)]
    best = None
    for _ in range(iters):
        a, b, c = P[rng.choice(len(P), 3, replace=False)]
        n = np.cross(b - a, c - a)
        nn = np.linalg.norm(n)
        if nn < 1e-9:
            continue
        n /= nn
        d = n @ a
        if d > 0:                 # orient so the camera (origin) is on the + side: n.x - d > 0 at x=0
            n, d = -n, -d
        if n @ np.array([0, -1.0, 0]) < np.cos(np.radians(30)):
            continue              # not a floor (normal must point up in the image)
        dist = np.abs(P @ n - d)
        inl = dist < 0.03 * np.maximum(P[:, 2], 1.0)
        if best is None or inl.sum() > best[2].sum():
            best = (n, d, inl)
    if best is None or best[2].mean() < 0.25:
        return None
    n, d, inl = best
    below = (P @ n - d) < -0.05 * np.maximum(P[:, 2], 1.0)
    if below.mean() > 0.05:
        return None               # real points below the plane: it is a counter/table top, not the floor
    if not (1.0 <= abs(d) * MODEL_SCALE_PRIOR <= 1.9):
        return None               # implausible camera height even allowing for model scale error
    Q = P[inl]                     # least-squares refit on inliers
    c = Q.mean(0)
    _, _, vt = np.linalg.svd(Q - c)
    n = vt[2] if vt[2] @ np.array([0, -1.0, 0]) > 0 else -vt[2]
    return FloorFit(normal=n, height=float(abs(n @ c)), inlier_frac=float(inl.mean()))


ALLOW_NEW_SEGMENTS = False   # a guessed pose corrupts geometry; unknown beats wrong
REJECT = {"few_matches": 0, "pnp_fail": 0, "inlier_ratio": 0, "motion": 0}
MODEL_SCALE_PRIOR = 0.72        # LiDAR/model depth ratio, upright frames, 3 captures: 0.70/0.71/0.76
ROTATIONS = {"none": 0, "cw": 3, "ccw": 1, "180": 2}


def _K_for(shape, fx=None):
    """Intrinsics for an upright frame. Default focal: iPhone main camera,
    0.83 x long side for 4:3 frames (ARKit/StrayScanner 1920x1440:
    fx=1598-1601 -> 0.83), 0.72 x long side for 16:9 video (sensor width
    kept, height cropped). Override with fx (pixels at this resolution)."""
    h, w = shape[:2]
    long_side = max(h, w)
    aspect = long_side / min(h, w)
    f = fx if fx else (0.72 if aspect > 1.5 else 0.83) * long_side
    return np.array([[f, 0, w / 2.0], [0, f, h / 2.0], [0, 0, 1.0]])


def read_video_frames(path, fps=3.0, max_frames=360, rotate="none"):
    vc = cv2.VideoCapture(str(path))
    src_fps = vc.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(vc.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(src_fps / fps)))
    if n // step > max_frames:
        step = int(np.ceil(n / max_frames))
    frames, idx = [], 0
    k = ROTATIONS[rotate]
    while True:
        ok = vc.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, img = vc.retrieve()
            if ok:
                frames.append((idx / src_fps, np.ascontiguousarray(np.rot90(img, k)) if k else img))
        idx += 1
    vc.release()
    return frames


def _sample_depth(depth, uv):
    h, w = depth.shape
    x = np.clip(uv[:, 0], 0, w - 1.001)
    y = np.clip(uv[:, 1], 0, h - 1.001)
    x0, y0 = x.astype(int), y.astype(int)
    ax, ay = x - x0, y - y0
    d = (depth[y0, x0] * (1 - ax) * (1 - ay) + depth[y0, x0 + 1] * ax * (1 - ay)
         + depth[y0 + 1, x0] * (1 - ax) * ay + depth[y0 + 1, x0 + 1] * ax * ay)
    return d


def track(images, fx=None, log=None):
    """images: list of upright BGR frames. Returns dict with per-frame raw
    depth (work res), K (work res), cam-to-world poses (chain scale), chain
    scale c_k, floor fits."""
    work = []
    for img in images:
        h, w = img.shape[:2]
        s = WORK_W / w
        small = cv2.resize(img, (WORK_W, int(round(h * s))), interpolation=cv2.INTER_AREA)
        work.append(small)
    K_full = _K_for(images[0].shape, fx)
    s = WORK_W / images[0].shape[1]
    K = K_full.copy()
    K[:2] *= s
    feat_scale = 3                                    # ORB on 3x work res (~768 px wide)
    Kf = K.copy()
    Kf[:2] *= feat_scale
    orb = cv2.ORB_create(nfeatures=2500, fastThreshold=12)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)

    depths, kps, floors = [], [], []
    for i, (img, small) in enumerate(zip(images, work)):
        depths.append(predict_depth(small))
        g = cv2.cvtColor(cv2.resize(img, (WORK_W * feat_scale, small.shape[0] * feat_scale)), cv2.COLOR_BGR2GRAY)
        kp, des = orb.detectAndCompute(g, None)
        kps.append((np.float32([k.pt for k in kp]) if kp else np.zeros((0, 2), np.float32), des))
        floors.append(fit_floor(depths[-1], K))
        if log and i % 25 == 0:
            log(f"  depth+features {i}/{len(images)}")

    n = len(images)
    T = [np.eye(4)]                 # cam-to-world, chain scale
    c = [1.0]                       # chain scale per frame (multiplies raw depth)
    valid = [True]
    lost = relocalised = segments = 0
    for k in range(1, n):
        ok = False
        history = [j for j in range(k - 1, -1, -1) if valid[j]]
        recent = history[:8]                                        # last 8 VALID frames (~2 s)
        older = history[8::4][:8] if k % 2 == 0 else []            # relocalisation candidates (every 2nd frame)
        if len(kps[k][0]) < 200:
            recent, older = [], []                                  # blank wall / blur: cannot localise
        for j in recent + older:
            back = min(k - j, 3)
            (pj, dj), (pk, dk) = kps[j], kps[k]
            if dj is None or dk is None or len(pj) < 30 or len(pk) < 30:
                continue
            m = [a for a, b in (x for x in bf.knnMatch(dj, dk, k=2) if len(x) == 2) if a.distance < 0.8 * b.distance]
            if len(m) < 30:
                REJECT["few_matches"] += 1
                continue
            uj = pj[[x.queryIdx for x in m]] / feat_scale
            uk = pk[[x.trainIdx for x in m]]
            z = _sample_depth(depths[j], uj) * c[j]
            good = (z > 0.2) & (z < 8)
            if good.sum() < 25:
                continue
            Xc = np.stack([(uj[:, 0] - K[0, 2]) / K[0, 0] * z, (uj[:, 1] - K[1, 2]) / K[1, 1] * z, z], 1)[good]
            Xw = Xc @ T[j][:3, :3].T + T[j][:3, 3]
            ok_p, rvec, tvec, inl = cv2.solvePnPRansac(Xw.astype(np.float64), uk[good].astype(np.float64), Kf, None,
                                                       reprojectionError=6.0, iterationsCount=300,
                                                       flags=cv2.SOLVEPNP_EPNP)
            if not ok_p or inl is None or len(inl) < 20:
                REJECT["pnp_fail"] += 1
                continue
            if len(inl) < 0.3 * good.sum():
                REJECT["inlier_ratio"] += 1
                continue
            inl = inl.ravel()
            rvec, tvec = cv2.solvePnPRefineLM(Xw[inl], uk[good][inl].astype(np.float64), Kf, None, rvec, tvec)
            if j in older:
                relocalised += 1
            R, _ = cv2.Rodrigues(rvec)
            Tk = np.eye(4)
            Tk[:3, :3] = R.T
            Tk[:3, 3] = (-R.T @ tvec).ravel()
            dR = T[j][:3, :3].T @ Tk[:3, :3]
            ang = np.degrees(np.arccos(np.clip((np.trace(dR) - 1) / 2, -1, 1)))
            step = np.linalg.norm(Tk[:3, 3] - T[j][:3, 3]) / max(c[j], 1e-6) * MODEL_SCALE_PRIOR
            if ang > 35 * back or step > 1.0 * back:
                REJECT["motion"] += 1
                continue                  # physically implausible for a handheld walk at this frame rate
            # chain scale for frame k: depth of the inlier 3D points as seen from k vs raw model depth at k
            zc = (Xw[inl] @ R.T + tvec.ravel())[:, 2]
            raw = _sample_depth(depths[k], uk[good][inl] / feat_scale)
            ratio = zc / np.maximum(raw, 1e-3)
            T.append(Tk)
            c.append(float(np.median(ratio)))
            valid.append(True)
            ok = True
            break
        if not ok:
            # Lost (blank wall, blur). Never track FROM this frame and keep it
            # out of the cloud; later frames re-localise against older valid ones.
            lost += 1
            T.append(T[history[0]].copy() if history else T[-1].copy())
            c.append(c[history[0]] if history else c[-1])
            # If several frames in a row are lost and the frame itself has
            # texture, start a new segment from the last valid pose (an
            # unconnected piece; counted and reported, not hidden).
            run = 0
            for jj in range(k, -1, -1):
                if jj < len(valid) and valid[jj]:
                    break
                run += 1
            if ALLOW_NEW_SEGMENTS and run >= 6 and len(kps[k][0]) > 300:
                valid.append(True)
                segments += 1
            else:
                valid.append(False)
    return {"depths": depths, "K": K, "T": T, "c": np.array(c), "floors": floors, "lost": lost,
            "valid": np.array(valid), "relocalised": relocalised, "new_segments": segments}


def metric_scale(tr, smooth=31):
    """Per-frame metric scale = chain scale x smooth correction, where the
    correction comes from absolute observations: camera height above the
    floor (when the floor is in view) and, weakly, the model's own scale."""
    c = tr["c"]
    n = len(c)
    obs, w = np.full(n, np.nan), np.zeros(n)
    for i, f in enumerate(tr["floors"]):
        if f is not None and tr["valid"][i]:
            obs[i] = np.log(CAMERA_HEIGHT_M / f.height) - np.log(c[i])
            w[i] = 1.0
    prior = np.log(MODEL_SCALE_PRIOR) - np.log(c)
    o = obs[np.isfinite(obs)]
    if len(o) >= 5:
        delta = np.full(n, np.median(o))
        source = "floor"
    else:
        delta = np.full(n, np.median(prior))
        source = "model_prior"
    return c * np.exp(delta), {"n_floor_frames": int(len(o)), "scale_source": source}


def to_world_clouds(tr, scale, stride=4, max_depth=6.0):
    """Per-frame world clouds with positions rescaled consistently, then a
    global rotation so the mean floor normal is +y (gravity)."""
    K, T, depths = tr["K"], tr["T"], tr["depths"]
    n = len(T)
    chain = tr["c"]
    # rescale trajectory increments by the smooth correction factor
    corr = scale / chain                      # uniform when the global-scale path is used
    pos = [T[k][:3, 3] * corr[k] for k in range(n)]
    ups = []
    for k, f in enumerate(tr["floors"]):
        if f is not None and tr["valid"][k]:
            ups.append(T[k][:3, :3] @ f.normal)
    if ups:
        up = np.median(np.array(ups), axis=0)
    else:
        up = T[0][:3, :3] @ np.array([0, -1.0, 0])     # image-up of the first frame
    up /= np.linalg.norm(up)
    # rotation taking 'up' to +y
    y = np.array([0, 1.0, 0])
    v = np.cross(up, y)
    s, cth = np.linalg.norm(v), up @ y
    if s < 1e-9:
        G = np.eye(3)
    else:
        vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        G = np.eye(3) + vx + vx @ vx * ((1 - cth) / s ** 2)
    clouds = []
    h, w = depths[0].shape
    ys, xs = np.mgrid[0:h:stride, 0:w:stride].astype(np.float32)
    for k in range(n):
        if not tr["valid"][k]:
            continue
        d = depths[k][::stride, ::stride] * scale[k]
        gy, gx = np.gradient(np.log(np.maximum(depths[k], 1e-3)))
        edge = (np.hypot(gx, gy)[::stride, ::stride] > 0.08)          # flying pixels at depth edges
        m = (d > 0.3) & (d < max_depth) & ~edge
        P = np.stack([(xs[m] - K[0, 2]) / K[0, 0] * d[m], (ys[m] - K[1, 2]) / K[1, 1] * d[m], d[m]], 1)
        Pw = P @ T[k][:3, :3].T + pos[k]
        clouds.append((G @ pos[k], Pw @ G.T))
    return clouds


def video_to_clouds(video_path, rotate="none", fps=3.0, max_frames=360, fx=None, log=print):
    frames = read_video_frames(video_path, fps=fps, max_frames=max_frames, rotate=rotate)
    if len(frames) < 5:
        raise SystemExit(f"Could not read enough frames from {video_path}")
    log(f"  {len(frames)} frames @ ~{fps} fps")
    tr = track([f for _, f in frames], fx=fx, log=log)
    scale, srep = metric_scale(tr)
    clouds = to_world_clouds(tr, scale)
    stats = {"frames": len(frames), "tracking_lost": tr["lost"], **srep,
             "median_scale": float(np.median(scale))}
    return clouds, stats
