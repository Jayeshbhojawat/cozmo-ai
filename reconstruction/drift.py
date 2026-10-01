"""Plane-anchored heading-drift correction (the 'drift accountability' row).

Visual-inertial odometry drifts mostly in yaw (heading) and translation;
gravity keeps roll/pitch observable. In a rectilinear home every wall is
parallel to one of two plan axes, so walls are an absolute heading
reference available everywhere along the walk:

 1. Split the trajectory into time chunks (~8s).
 2. For each chunk, estimate the dominant wall direction (mod 90 deg) from
    that chunk's own wall-band points, and its offset delta(t) from the
    whole-capture plan direction. Chunks with too few wall points get no
    vote (interpolated from neighbours).
 3. Smooth delta(t) (drift is slow) and interpolate it per frame.
 4. Re-integrate the trajectory with corrected heading:
        p'_t = p'_{t-1} + Rz(-delta_t) (p_t - p_{t-1})
    and move each frame's points with its corrected pose:
        X' = p'_t + Rz(-delta_t) (X - p_t)
    (rotation about the vertical axis only).

This corrects heading drift and the translation error that heading drift
induces through integration; it does not correct pure translational
(scale/odometry) drift - stated in the report as a limitation.
`benchmark/drift_ablation.py` runs the layout with this on and off.
"""
from __future__ import annotations

import numpy as np

from reconstruction.layout import dominant_angle, find_floor_y


def _wrap45(a):
    return (a + np.pi / 4) % (np.pi / 2) - np.pi / 4


def _Ry(delta):
    # rotation about world +y (up) acting on (x, z): consistent with plan angle convention
    c, s = np.cos(delta), np.sin(delta)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def estimate_heading_drift(frame_clouds, timestamps, chunk_s=8.0, min_pts=3000):
    allp = np.concatenate([p for _, p in frame_clouds])
    floor_y = find_floor_y(allp)
    def band(p):
        h = p[:, 1] - floor_y
        return p[(h > 0.3) & (h < 1.9)][:, [0, 2]]
    theta = dominant_angle(np.concatenate([band(p) for _, p in frame_clouds]))
    t = np.asarray(timestamps, float)
    edges = np.arange(t.min(), t.max() + chunk_s, chunk_s)
    centres, deltas, counts = [], [], []
    for a, b in zip(edges[:-1], edges[1:]):
        idx = np.where((t >= a) & (t < b))[0]
        if len(idx) == 0:
            continue
        pts = np.concatenate([band(frame_clouds[i][1]) for i in idx])
        centres.append((a + b) / 2)
        counts.append(len(pts))
        deltas.append(_wrap45(dominant_angle(pts) - theta) if len(pts) >= min_pts else np.nan)
    centres, deltas = np.array(centres), np.array(deltas)
    ok = ~np.isnan(deltas)
    if ok.sum() == 0:
        return np.zeros(len(t)), {"theta_deg": float(np.degrees(theta)), "chunks": []}
    # smooth: running median over 3 valid chunks
    d_ok = deltas[ok]
    sm = np.array([np.median(d_ok[max(0, i - 1):i + 2]) for i in range(len(d_ok))])
    per_frame = np.interp(t, centres[ok], sm)
    report = {"theta_deg": float(np.degrees(theta)),
              "chunks": [{"t_mid": float(c), "delta_deg": None if np.isnan(d) else float(np.degrees(d)),
                          "n_wall_pts": int(n)} for c, d, n in zip(centres, deltas, counts)],
              "max_abs_correction_deg": float(np.degrees(np.abs(per_frame).max()))}
    return per_frame, report


def apply_heading_correction(frame_clouds, deltas, mode="orientation"):
    """mode="orientation": rotate each frame's points about its own camera,
    keep the (already loop-closed) VIO positions. mode="reintegrate": also
    re-integrate positions with the corrected heading."""
    if mode == "orientation":
        return [(cam, (pts - cam) @ _Ry(d).T + cam) for (cam, pts), d in zip(frame_clouds, deltas)]
    out = []
    prev_p, prev_new = None, None
    for (cam, pts), d in zip(frame_clouds, deltas):
        R = _Ry(d)   # _Ry(a) rotates (x,z) by -a; chunk walls sit at theta+delta -> rotate by -delta
        if prev_p is None:
            new_cam = cam.copy()
        else:
            new_cam = prev_new + R @ (cam - prev_p)
        out.append((new_cam, (pts - cam) @ R.T + new_cam))
        prev_p, prev_new = cam, new_cam
    return out


def registration_score(frame_clouds) -> int:
    """Occupied 5cm voxels in the wall band. Lower = tighter = better
    registered (the same wall seen from different frames lands in the same
    voxels). Used as the acceptance test for any pose correction."""
    P = np.concatenate([p for _, p in frame_clouds])
    fl = find_floor_y(P)
    h = P[:, 1] - fl
    W = P[(h > 0.3) & (h < 1.9)]
    return int(len(np.unique(np.floor(W / 0.05).astype(np.int64), axis=0)))


def correct_drift(frame_clouds, timestamps, mode: str = "auto"):
    """mode: "off" (VIO poses, for the ablation), "on" (always apply the
    re-integrated heading correction), "auto" (apply it only if it improves
    the registration score; otherwise keep VIO poses and say why).
    Returns (frame_clouds, report)."""
    report = {"mode": mode}
    if mode == "off":
        report["applied"] = False
        return frame_clouds, report
    deltas, est = estimate_heading_drift(frame_clouds, timestamps)
    corrected = apply_heading_correction(frame_clouds, deltas, mode="reintegrate")
    s_raw, s_cor = registration_score(frame_clouds), registration_score(corrected)
    report.update(est)
    report.update({"registration_voxels_raw": s_raw, "registration_voxels_corrected": s_cor,
                   "registration_change_pct": round(100.0 * (s_cor - s_raw) / max(s_raw, 1), 2)})
    if mode == "on" or s_cor < s_raw:
        report["applied"] = True
        return corrected, report
    report["applied"] = False
    report["reason"] = ("correction rejected: it loosened wall registration, so the VIO poses "
                        "(already loop-closed by ARKit) were kept after audit")
    return frame_clouds, report
