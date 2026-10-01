"""Video tier with the phone's own motion tracking (poses), no depth sensor.

Every iPhone 15 runs Apple's motion tracking (camera + motion sensors) and
reports where the camera is in real metres for every frame, with or without
LiDAR. A free App Store logger records it next to the video (capture
protocol). That changes the video problem completely:

  * scale is known from the phone's own movement - no guessing from
    camera height;
  * tracking through blank walls is the phone's job (the motion sensor
    bridges featureless moments) - the failure that sank our image-only
    tracker;
  * the only thing missing compared with LiDAR is depth.

Depth: a pretrained monocular model gives each frame's SHAPE (measured on
our LiDAR captures: ~9-10% shape error after per-frame rescale, but raw
scale off by 18-30% and unstable). Each frame's SCALE is then measured by
triangulation: ORB points matched between this frame and a nearby frame
taken from a known, different position (the phone's poses give the
baseline in metres) -> true distance of those points -> median ratio to the
model's depth at the same pixels. Frames where too few points triangulate
borrow the scale of their neighbours.

The resulting per-frame clouds go through exactly the same pipeline as the
LiDAR tier (drift audit, layout, rooms, doors, ceilings).
"""
from __future__ import annotations

import cv2
import numpy as np

from reconstruction.mono_depth import predict_depth

DEPTH_W, DEPTH_H = 256, 192      # same working size as the LiDAR depth maps
FEAT_W = 960                      # ORB at half of 1920


def _upright_k(R_cw):
    """Number of 90-deg CCW rotations (np.rot90 k) that make the image
    upright, from gravity in camera coords (OpenCV: x right, y down)."""
    up = R_cw.T @ np.array([0.0, 1.0, 0.0])          # world up in camera coords
    ang = np.degrees(np.arctan2(up[1], up[0]))       # image-plane direction of 'up'
    # want 'up' to point to image -y (angle -90); rot90 CCW by k*90 rotates directions by -k*90 in image coords
    return int(np.round(((ang + 90) % 360) / 90)) % 4


def depth_for_frame(img, R_cw):
    """Model depth at DEPTH_W x DEPTH_H in the frame's own (sensor) orientation,
    predicted on the upright-rotated image (orientation matters: measured)."""
    k = _upright_k(R_cw)
    up = np.ascontiguousarray(np.rot90(img, k)) if k else img
    h, w = up.shape[:2]
    small = cv2.resize(up, (256, int(round(h * 256 / w))) if w <= h else (int(round(w * 256 / h)), 256),
                       interpolation=cv2.INTER_AREA)
    d = predict_depth(small)
    d = np.ascontiguousarray(np.rot90(d, -k)) if k else d
    return cv2.resize(d, (DEPTH_W, DEPTH_H), interpolation=cv2.INTER_LINEAR)


def _proj(frame, rgb_shape, scale_to_w):
    """3x4 projection (world -> pixels at FEAT_W) for a capture Frame."""
    s = scale_to_w / rgb_shape[1]
    K = np.array([[frame.fx * s, 0, frame.cx * s], [0, frame.fy * s, frame.cy * s], [0, 0, 1.0]])
    T = frame.pose_matrix()                           # cam -> world
    Rw = T[:3, :3].T
    tw = -Rw @ T[:3, 3]
    return K, K @ np.hstack([Rw, tw[:, None]]), Rw, tw


def triangulated_scale(fa, fb, ga, gb, da, rgb_shape, orb, bf, min_pts=15):
    """Metric scale of frame a's model depth (da) from matches with frame b,
    using the known poses. Returns (scale, n_points) or (None, n)."""
    ka, desa = orb.detectAndCompute(ga, None)
    kb, desb = orb.detectAndCompute(gb, None)
    if desa is None or desb is None or len(ka) < 30 or len(kb) < 30:
        return None, 0
    m = [x for x, y in (p for p in bf.knnMatch(desa, desb, k=2) if len(p) == 2) if x.distance < 0.75 * y.distance]
    if len(m) < min_pts:
        return None, len(m)
    pa = np.float32([ka[x.queryIdx].pt for x in m])
    pb = np.float32([kb[x.trainIdx].pt for x in m])
    Ka, Pa, Ra, ta = _proj(fa, rgb_shape, FEAT_W)
    Kb, Pb, Rb, tb = _proj(fb, rgb_shape, FEAT_W)
    X = cv2.triangulatePoints(Pa, Pb, pa.T.astype(np.float64), pb.T.astype(np.float64))
    X = (X[:3] / X[3]).T
    za = X @ Ra[2] + ta[2]
    zb = X @ Rb[2] + tb[2]
    # reprojection error in both views
    def reproj(P, p):
        x = np.hstack([X, np.ones((len(X), 1))]) @ P.T
        return np.linalg.norm(x[:, :2] / x[:, 2:3] - p, axis=1)
    ok = (za > 0.2) & (zb > 0.2) & (za < 8) & (reproj(Pa, pa) < 2.0) & (reproj(Pb, pb) < 2.0)
    # enough parallax: angle between the two viewing rays > 2 deg
    ca, cb = fa.position, fb.position
    ra = X - ca
    rb = X - cb
    cosang = (ra * rb).sum(1) / (np.linalg.norm(ra, axis=1) * np.linalg.norm(rb, axis=1) + 1e-9)
    ok &= cosang < np.cos(np.radians(2.0))
    if ok.sum() < min_pts:
        return None, int(ok.sum())
    # model depth at the same pixels (da is DEPTH_W x DEPTH_H, sensor orientation)
    s = DEPTH_W / FEAT_W
    u = np.clip((pa[ok, 0] * s).astype(int), 0, DEPTH_W - 1)
    v = np.clip((pa[ok, 1] * s).astype(int), 0, DEPTH_H - 1)
    r = za[ok] / np.maximum(da[v, u], 1e-3)
    return float(np.median(r)), int(ok.sum())


def video_frame_clouds(cap, video_path, max_frames=300, stride=4, max_depth=5.0, log=None):
    """Per-frame world clouds for the posed video tier. `cap` supplies poses
    and intrinsics per frame (odometry.csv from the logger); depth comes from
    the model, never from a LiDAR file. Returns (frame_clouds, used_frames, stats)."""
    n = len(cap.frames)
    step = max(1, n // max_frames)
    idx = list(range(0, n, step))
    vc = cv2.VideoCapture(str(video_path))
    imgs, grays = {}, {}
    want = set(idx)
    i = 0
    while True:
        ok = vc.grab()
        if not ok:
            break
        if i in want:
            ok, img = vc.retrieve()
            if ok:
                imgs[i] = img
                g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                grays[i] = cv2.resize(g, (FEAT_W, int(round(g.shape[0] * FEAT_W / g.shape[1]))))
        i += 1
    vc.release()
    idx = [k for k in idx if k in imgs]
    orb = cv2.ORB_create(nfeatures=3000, fastThreshold=10)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    depths, scales, npts = {}, {}, {}
    for c, k in enumerate(idx):
        fa = cap.frames[k]
        depths[k] = depth_for_frame(imgs[k], fa.rotation_matrix())
        best = (None, 0)
        # partners: nearby frames with a useful baseline (>= 12 cm)
        for off in (3, 5, 8, -3, -5, -8, 12, -12):
            j = c + off
            if not (0 <= j < len(idx)):
                continue
            fb = cap.frames[idx[j]]
            if np.linalg.norm(fb.position - fa.position) < 0.12:
                continue
            sc, m = triangulated_scale(fa, fb, grays[k], grays[idx[j]], depths[k], cap.rgb_shape, orb, bf)
            if sc is not None and m > best[1]:
                best = (sc, m)
            if best[1] >= 60:
                break
        scales[k], npts[k] = best
        if log and c % 40 == 0:
            log(f"  posed video: {c}/{len(idx)} frames")
    # smooth / fill scales over time (model scale drifts slowly frame to frame)
    sv = np.array([scales[k] if scales[k] is not None else np.nan for k in idx], float)
    good = np.isfinite(sv)
    if good.sum() < 3:
        raise SystemExit("Too few frames could be scaled by triangulation (is the video too static or blurred?)")
    filled = np.interp(np.arange(len(idx)), np.where(good)[0], sv[good])
    smooth = np.array([np.median(filled[max(0, a - 3):a + 4]) for a in range(len(idx))])

    clouds, used = [], []
    ys, xs = np.mgrid[0:DEPTH_H:stride, 0:DEPTH_W:stride].astype(np.float32)
    for a, k in enumerate(idx):
        f = cap.frames[k]
        d = depths[k][::stride, ::stride] * smooth[a]
        gy, gx = np.gradient(np.log(np.maximum(depths[k], 1e-3)))
        edge = np.hypot(gx, gy)[::stride, ::stride] > 0.08
        m = (d > 0.3) & (d < max_depth) & ~edge
        sx, sy = DEPTH_W / cap.rgb_shape[1], DEPTH_H / cap.rgb_shape[0]
        fx, fy, cx, cy = f.fx * sx, f.fy * sy, f.cx * sx, f.cy * sy
        P = np.stack([(xs[m] - cx) / fx * d[m], (ys[m] - cy) / fy * d[m], d[m]], 1)
        T = f.pose_matrix()
        clouds.append((f.position, P @ T[:3, :3].T + T[:3, 3]))
        used.append(f)
        if keep_depth is not None:
            dfull = depths[k] * smooth[a]
            gyf, gxf = np.gradient(np.log(np.maximum(depths[k], 1e-3)))
            keep_depth[k] = (dfull.astype(np.float32),
                             (dfull > 0.3) & (dfull < max_depth) & (np.hypot(gxf, gyf) < 0.08))
    stats = {"frames": len(idx), "frames_scaled_directly": int(good.sum()),
             "median_triangulated_points": float(np.median([npts[k] for k in idx])),
             "scale_median": float(np.median(smooth)), "scale_iqr": [float(np.percentile(smooth, 25)),
                                                                     float(np.percentile(smooth, 75))]}
    return clouds, used, stats


# ---------------------------------------------------------------------------
# Scale by multi-view agreement (replaces feature triangulation as the
# primary method). Measured on our captures: feature triangulation with the
# phone's poses came out 12-18 % short of LiDAR on most frames (image
# frames not perfectly in sync with poses; small baselines), while LiDAR +
# poses agree tightly. Agreement of whole depth maps across frames does not
# need texture: at the right scale the same wall seen from different
# positions lands in the same place.

def _keys(P, vox):
    k = np.floor(P / vox).astype(np.int64)
    return (k[:, 0] * 73856093) ^ (k[:, 1] * 19349663) ^ (k[:, 2] * 83492791)


def _fuse(frames, scales, vox, max_depth):
    W = []
    for (T, P), s in zip(frames, scales):
        Q = P * s
        Q = Q[(Q[:, 2] > 0.3) & (Q[:, 2] < max_depth)]
        W.append(Q @ T[:3, :3].T + T[:3, 3])
    return np.concatenate(W)


def global_scale(frames, lo=0.4, hi=1.2, steps=33, max_depth=5.0, ref_vox=0.05):
    """One scale for all frames: the one minimising size-normalised
    occupancy (cell size grows with the trial scale, so only disagreement
    between frames changes the count)."""
    best = None
    for lam in np.linspace(lo, hi, steps):
        W = _fuse(frames, [lam] * len(frames), ref_vox * lam, max_depth)
        occ = len(np.unique(_keys(W, ref_vox * lam)))
        if best is None or occ < best[1]:
            best = (lam, occ)
    return best[0]


def refine_frame_scales(frames, lam, rounds=2, span=0.2, steps=21, max_depth=5.0, vox=0.05):
    """Per-frame scale refinement: each frame's scale is chosen (within
    +-span of the current value) to maximise how many of its points land in
    cells occupied by the OTHER frames' fused points."""
    scales = np.full(len(frames), lam, float)
    for _ in range(rounds):
        W = _fuse(frames, scales, vox, max_depth)
        counts = {}
        allk = _keys(W, vox)
        uk, cnt = np.unique(allk, return_counts=True)
        new = scales.copy()
        for i, (T, P) in enumerate(frames):
            best = (scales[i], -1)
            for s in scales[i] * np.linspace(1 - span, 1 + span, steps):
                Q = P * s
                Q = Q[(Q[:, 2] > 0.3) & (Q[:, 2] < max_depth)]
                if len(Q) == 0:
                    continue
                k = _keys(Q @ T[:3, :3].T + T[:3, 3], vox)
                pos = np.searchsorted(uk, k)
                pos = np.clip(pos, 0, len(uk) - 1)
                hit = (uk[pos] == k) & (cnt[pos] > 1)          # occupied by others too
                score = hit.mean()
                if score > best[1]:
                    best = (s, score)
            new[i] = best[0]
        # keep refinements smooth in time (model scale drifts slowly)
        scales = np.array([np.median(new[max(0, j - 2):j + 3]) for j in range(len(new))])
    return scales


def video_frame_clouds_v2(cap, video_path, max_frames=300, stride=4, max_depth=5.0, log=None):
    """Posed video tier: model depth per frame, scale from multi-view
    agreement (global sweep, then per-frame refinement)."""
    n = len(cap.frames)
    step = max(1, n // max_frames)
    want = set(range(0, n, step))
    vc = cv2.VideoCapture(str(video_path))
    frames, used, i = [], [], 0
    ys, xs = np.mgrid[0:DEPTH_H:stride, 0:DEPTH_W:stride].astype(np.float32)
    sx, sy = DEPTH_W / cap.rgb_shape[1], DEPTH_H / cap.rgb_shape[0]
    while True:
        ok = vc.grab()
        if not ok:
            break
        if i in want and i < n:
            ok, img = vc.retrieve()
            if ok:
                f = cap.frames[i]
                d = depth_for_frame(img, f.rotation_matrix())
                gy, gx = np.gradient(np.log(np.maximum(d, 1e-3)))
                m = np.hypot(gx, gy)[::stride, ::stride] < 0.08
                dd = d[::stride, ::stride]
                fx, fy, cx, cy = f.fx * sx, f.fy * sy, f.cx * sx, f.cy * sy
                P = np.stack([(xs[m] - cx) / fx * dd[m], (ys[m] - cy) / fy * dd[m], dd[m]], 1)
                frames.append((f.pose_matrix(), P))
                used.append(f)
                if log and len(used) % 50 == 0:
                    log(f"  posed video: depth {len(used)} frames")
        i += 1
    vc.release()
    lam = global_scale(frames, max_depth=max_depth)
    scales = refine_frame_scales(frames, lam, max_depth=max_depth)
    clouds = []
    for (T, P), s, f in zip(frames, scales, used):
        Q = P * s
        Q = Q[(Q[:, 2] > 0.3) & (Q[:, 2] < max_depth)]
        clouds.append((f.position, Q @ T[:3, :3].T + T[:3, 3]))
    stats = {"frames": len(used), "global_scale": float(lam), "scale_median": float(np.median(scales)),
             "scale_p10_p90": [float(np.percentile(scales, 10)), float(np.percentile(scales, 90))]}
    return clouds, used, stats


def posed_clouds(cap, video_path, max_frames=300, stride=4, max_depth=5.0, log=None, keep_depth=None):
    """Generic posed-video path (frames looked up by video frame number, so it
    works for any pose source: StrayScanner odometry or Spectacular AI VIO).
    Per-frame scale from triangulation against nearby frames using the known
    poses; frames without enough triangulated points borrow neighbours' scale.
    Returns (frame_clouds, used_frames, stats). If keep_depth is a dict, it
    is filled with {frame_index: (metric_depth, valid_mask)} at DEPTH_W x
    DEPTH_H (used by the damage detector to lift 2D candidates to 3D)."""
    by_idx = {f.index: f for f in cap.frames}
    nums = sorted(by_idx)
    step = max(1, len(nums) // max_frames)
    want = nums[::step]
    want_set = set(want)
    vc = cv2.VideoCapture(str(video_path))
    imgs, grays, i = {}, {}, 0
    while True:
        ok = vc.grab()
        if not ok:
            break
        if i in want_set:
            ok, img = vc.retrieve()
            if ok:
                imgs[i] = img
                g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                grays[i] = cv2.resize(g, (FEAT_W, int(round(g.shape[0] * FEAT_W / g.shape[1]))))
        i += 1
    vc.release()
    seq = [k for k in want if k in imgs]
    orb = cv2.ORB_create(nfeatures=3000, fastThreshold=10)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    depths, sc, npts = {}, [], []
    for c, k in enumerate(seq):
        fa = by_idx[k]
        depths[k] = depth_for_frame(imgs[k], fa.rotation_matrix())
        best = (None, 0)
        for off in (3, -3, 5, -5, 8, -8, 12, -12):
            j = c + off
            if not (0 <= j < len(seq)):
                continue
            fb = by_idx[seq[j]]
            if np.linalg.norm(fb.position - fa.position) < 0.10:
                continue
            s, m = triangulated_scale(fa, fb, grays[k], grays[seq[j]], depths[k], cap.rgb_shape, orb, bf)
            if s is not None and m > best[1]:
                best = (s, m)
            if best[1] >= 80:
                break
        sc.append(best[0] if best[0] is not None else np.nan)
        npts.append(best[1])
        if log and c % 50 == 0:
            log(f"  posed video: {c}/{len(seq)} frames")
    sv = np.array(sc, float)
    good = np.isfinite(sv)
    if good.sum() < 3:
        raise SystemExit("Too few frames could be scaled by triangulation (video too static, blurred or textureless).")
    filled = np.interp(np.arange(len(seq)), np.where(good)[0], sv[good])
    smooth = np.array([np.median(filled[max(0, a - 4):a + 5]) for a in range(len(seq))])
    ys, xs = np.mgrid[0:DEPTH_H:stride, 0:DEPTH_W:stride].astype(np.float32)
    sx, sy = DEPTH_W / cap.rgb_shape[1], DEPTH_H / cap.rgb_shape[0]
    clouds, used = [], []
    for a, k in enumerate(seq):
        f = by_idx[k]
        d = depths[k][::stride, ::stride] * smooth[a]
        gy, gx = np.gradient(np.log(np.maximum(depths[k], 1e-3)))
        m = (d > 0.3) & (d < max_depth) & (np.hypot(gx, gy)[::stride, ::stride] < 0.08)
        fx, fy, cx, cy = f.fx * sx, f.fy * sy, f.cx * sx, f.cy * sy
        P = np.stack([(xs[m] - cx) / fx * d[m], (ys[m] - cy) / fy * d[m], d[m]], 1)
        T = f.pose_matrix()
        clouds.append((f.position, P @ T[:3, :3].T + T[:3, 3]))
        used.append(f)
        if keep_depth is not None:
            dfull = depths[k] * smooth[a]
            gyf, gxf = np.gradient(np.log(np.maximum(depths[k], 1e-3)))
            keep_depth[k] = (dfull.astype(np.float32),
                             (dfull > 0.3) & (dfull < max_depth) & (np.hypot(gxf, gyf) < 0.08))
    stats = {"frames": len(seq), "frames_scaled_directly": int(good.sum()),
             "median_triangulated_points": float(np.median(npts)),
             "scale_median": float(np.median(smooth)),
             "scale_p10_p90": [float(np.percentile(smooth, 10)), float(np.percentile(smooth, 90))]}
    return clouds, used, stats
