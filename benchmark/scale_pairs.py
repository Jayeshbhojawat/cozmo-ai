"""Collect (model depth, triangulated metric depth) pairs per frame for a
posed-video capture, reusing the cached model depth. Lets depth-calibration
models (scale only / scale + shift / inverse-depth affine) be compared in
seconds instead of re-running the depth network.

    python -m benchmark.scale_pairs data/raw/home/spectacular_2
    -> <capture>/scale_pairs_250.npz : seq, frame, pred, tri, depth_frac
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

from capture.spectacular import load_spectacular
from reconstruction.video_posed import DEPTH_H, DEPTH_W, FEAT_W, _proj


def pairs_for(fa, fb, ga, gb, da, rgb_shape, orb, bf, cache_kp):
    def kp(key, g):
        if key not in cache_kp:
            cache_kp[key] = orb.detectAndCompute(g, None)
        return cache_kp[key]
    ka, desa = kp(fa.index, ga)
    kb, desb = kp(fb.index, gb)
    if desa is None or desb is None or len(ka) < 30 or len(kb) < 30:
        return None
    m = [x for x, y in (p for p in bf.knnMatch(desa, desb, k=2) if len(p) == 2) if x.distance < 0.75 * y.distance]
    if len(m) < 15:
        return None
    pa = np.float32([ka[x.queryIdx].pt for x in m])
    pb = np.float32([kb[x.trainIdx].pt for x in m])
    _, Pa, Ra, ta = _proj(fa, rgb_shape, FEAT_W)
    _, Pb, Rb, tb = _proj(fb, rgb_shape, FEAT_W)
    X = cv2.triangulatePoints(Pa, Pb, pa.T.astype(np.float64), pb.T.astype(np.float64))
    X = (X[:3] / X[3]).T
    za, zb = X @ Ra[2] + ta[2], X @ Rb[2] + tb[2]

    def reproj(P, p):
        x = np.hstack([X, np.ones((len(X), 1))]) @ P.T
        return np.linalg.norm(x[:, :2] / x[:, 2:3] - p, axis=1)
    ok = (za > 0.2) & (zb > 0.2) & (za < 8) & (reproj(Pa, pa) < 2.0) & (reproj(Pb, pb) < 2.0)
    ra, rb = X - fa.position, X - fb.position
    cosang = (ra * rb).sum(1) / (np.linalg.norm(ra, axis=1) * np.linalg.norm(rb, axis=1) + 1e-9)
    ok &= cosang < np.cos(np.radians(2.0))
    if ok.sum() < 15:
        return None
    s = DEPTH_W / FEAT_W
    u = np.clip((pa[ok, 0] * s).astype(int), 0, DEPTH_W - 1)
    v = np.clip((pa[ok, 1] * s).astype(int), 0, DEPTH_H - 1)
    return da[v, u], za[ok]


def main(cdir):
    cdir = Path(cdir)
    cap = load_spectacular(cdir)
    z = np.load(cdir / "depth_cache_250.npz")
    seq = [int(k) for k in z["seq"]]
    by = {f.index: f for f in cap.frames}
    want = set(seq)
    vc = cv2.VideoCapture(str(cdir / "data.mov"))
    grays, i = {}, 0
    while want:
        if not vc.grab():
            break
        if i in want:
            ok, img = vc.retrieve()
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            grays[i] = cv2.resize(g, (FEAT_W, int(round(g.shape[0] * FEAT_W / g.shape[1]))))
            want.discard(i)
        i += 1
    orb = cv2.ORB_create(nfeatures=3000, fastThreshold=10)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    kp = {}
    F, PR, TR = [], [], []
    for c, k in enumerate(seq):
        fa = by[k]
        best = None
        for off in (3, -3, 5, -5, 8, -8, 12, -12):
            j = c + off
            if not (0 <= j < len(seq)):
                continue
            fb = by[seq[j]]
            if np.linalg.norm(fb.position - fa.position) < 0.10:
                continue
            r = pairs_for(fa, fb, grays[k], grays[seq[j]], z["depth"][c].astype(np.float32), cap.rgb_shape, orb, bf, kp)
            if r is not None and (best is None or len(r[0]) > len(best[0])):
                best = r
            if best is not None and len(best[0]) >= 80:
                break
        if best is not None:
            F.append(np.full(len(best[0]), c))
            PR.append(best[0])
            TR.append(best[1])
    np.savez_compressed(cdir / "scale_pairs_250.npz", seq=np.array(seq), frame=np.concatenate(F),
                        pred=np.concatenate(PR), tri=np.concatenate(TR))
    print(cdir.name, "frames with pairs", len(F), "pairs", sum(len(x) for x in PR))


if __name__ == "__main__":
    main(sys.argv[1])
