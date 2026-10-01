"""Placing separately-captured rooms into one plan, and correcting drift
between repeated captures.

A single continuous LiDAR walkthrough does not need this module: every room
comes out of `reconstruction/layout.py` already in one shared plan frame,
with adjacency from the doorway cuts. This module is for the cases where
rooms do NOT share a pose frame:
  * photo tier (one folder of stills per room), and
  * the repeatability / drift ablation (the same room captured twice).

Bugs fixed in this version (found in review, each now covered by a test in
tests/test_stitch.py):
  * wall-to-wall alignment translated by a.p0 - R b.p0; facing walls run in
    opposite directions, so that placed the neighbour diagonally, touching
    only at a corner. Now aligns wall midpoints.
  * repeated-room alignment paired walls by list index, but wall order is
    not stable between captures. Now uses ICP over points sampled along the
    walls (correspondence-free).
  * the "footprint" used for the drift ablation was a sum of per-room areas,
    which a rigid transform cannot change, so the ablation would always show
    no difference. Now it is the area of the union of the placed polygons
    (overlaps counted once), and overlap area is reported separately.
"""
from __future__ import annotations

import numpy as np
from matplotlib.path import Path as MplPath
from scipy.spatial import cKDTree


def transform(T: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, float)
    return pts @ T[:2, :2].T + T[:2, 2]


def _T(theta, t):
    c, s = np.cos(theta), np.sin(theta)
    T = np.eye(3)
    T[:2, :2] = [[c, -s], [s, c]]
    T[:2, 2] = t
    return T


def align_shared_wall(a0, a1, b0, b1) -> np.ndarray:
    """Transform for room B such that its wall (b0->b1) lies on room A's wall
    (a0->a1), facing it (directions opposite, midpoints coincident). Works
    when the two rooms measured the shared wall with different lengths."""
    a0, a1, b0, b1 = map(lambda p: np.asarray(p, float), (a0, a1, b0, b1))
    da, db = a1 - a0, b1 - b0
    theta = np.arctan2(da[1], da[0]) - np.arctan2(db[1], db[0]) + np.pi
    R = _T(theta, [0, 0])[:2, :2]
    t = (a0 + a1) / 2 - R @ ((b0 + b1) / 2)
    return _T(theta, t)


def place_by_adjacency(polygons: dict, anchor: str, hints: list) -> dict:
    """polygons: {room_id: (N,2) polygon in its own frame}.
    hints: [(room_a, wall_idx_a, room_b, wall_idx_b)] where wall k of a room
    is polygon[k] -> polygon[k+1]. BFS from the anchor room. Returns
    {room_id: 3x3 transform}; rooms unreachable from the anchor are omitted
    (reported as unplaced rather than dropped somewhere arbitrary)."""
    placed = {anchor: np.eye(3)}
    adj = {}
    for a, ia, b, ib in hints:
        adj.setdefault(a, []).append((ia, b, ib))
        adj.setdefault(b, []).append((ib, a, ia))
    frontier = [anchor]
    while frontier:
        a = frontier.pop()
        Pa = transform(placed[a], polygons[a])
        for ia, b, ib in adj.get(a, []):
            if b in placed:
                continue
            Pb = np.asarray(polygons[b], float)
            nA, nB = len(Pa), len(Pb)
            placed[b] = align_shared_wall(Pa[ia], Pa[(ia + 1) % nA], Pb[ib], Pb[(ib + 1) % nB])
            frontier.append(b)
    return placed


def _sample_boundary(P, step=0.05):
    P = np.asarray(P, float)
    out = []
    for k in range(len(P)):
        a, b = P[k], P[(k + 1) % len(P)]
        n = max(int(np.linalg.norm(b - a) / step), 1)
        out.append(a + (b - a) * (np.arange(n)[:, None] / n))
    return np.vstack(out)


def icp_2d(src_pts, dst_pts, iters=40, max_dist=0.5) -> np.ndarray:
    """Rigid 2D ICP, src -> dst. Returns 3x3 transform."""
    tree = cKDTree(dst_pts)
    T = np.eye(3)
    cur = np.asarray(src_pts, float).copy()
    # initialise with centroid alignment
    T0 = _T(0.0, dst_pts.mean(0) - cur.mean(0))
    cur = transform(T0, cur)
    T = T0 @ T
    for _ in range(iters):
        d, idx = tree.query(cur)
        m = d < max_dist
        if m.sum() < 3:
            break
        A, B = cur[m], dst_pts[idx[m]]
        ma, mb = A.mean(0), B.mean(0)
        H = (A - ma).T @ (B - mb)
        U, _, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T
        if np.linalg.det(R) < 0:
            Vt[-1] *= -1
            R = Vt.T @ U.T
        step = np.eye(3)
        step[:2, :2] = R
        step[:2, 2] = mb - R @ ma
        cur = transform(step, cur)
        T = step @ T
        if np.linalg.norm(step[:2, 2]) < 1e-5 and abs(np.arctan2(R[1, 0], R[0, 0])) < 1e-6:
            break
    return T


def align_repeat(poly_first, poly_second) -> np.ndarray:
    """Plane-anchored drift correction between two captures of the same room:
    align the second pass's walls onto the first pass's walls (ICP over wall
    samples, no index correspondence assumed)."""
    # dense target (1cm) so point-to-point matches are not biased by sample spacing
    return icp_2d(_sample_boundary(poly_second, 0.05), _sample_boundary(poly_first, 0.01))


def raster_union_overlap(polygons: list, res=0.02):
    """(union_area, overlap_area) of placed polygons via rasterisation."""
    allp = np.vstack(polygons)
    lo, hi = allp.min(0) - res, allp.max(0) + res
    xs = np.arange(lo[0], hi[0], res) + res / 2
    ys = np.arange(lo[1], hi[1], res) + res / 2
    gx, gy = np.meshgrid(xs, ys)
    pts = np.stack([gx.ravel(), gy.ravel()], 1)
    count = np.zeros(len(pts), np.int16)
    for P in polygons:
        count += MplPath(P).contains_points(pts)
    cell = res * res
    return float((count >= 1).sum() * cell), float((count >= 2).sum() * cell)
