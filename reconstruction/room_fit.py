"""Turns a world-space point cloud into a dimensioned room: floor height,
ceiling height, wall line segments (the room polygon), and opening gaps along
each wall.

Method (documented here because it's what the technical report's "architecture"
section describes):

1. Floor/ceiling: histogram point heights (world +y = up), take the two
   tallest bins in the bottom/top thirds of the range as floor/ceiling planes.
   Robust to noise because floor/ceiling are by far the largest horizontal
   surfaces in any room capture.
2. Walls: take points in the vertical band strictly between floor and ceiling
   (excludes furniture sitting on the floor and light fixtures on the
   ceiling from most of the noise), project to the XZ plane (top-down), and
   run iterative RANSAC line fitting: fit the best-supported line, assign its
   inliers, remove them, repeat until remaining point count drops below a
   threshold or a wall-count cap is hit.
3. The fitted lines are ordered into a closed polygon by nearest-endpoint
   chaining, giving wall segments with lengths.
4. Openings: along each wall segment, bin points by position-along-wall and
   look for a gap in vertical (y) coverage — a stretch where points exist at
   floor and ceiling height but are missing in the middle over a band ≥ 0.5m,
   which reads as a doorway/window rather than sensor dropout (dropout is
   usually narrower and doesn't span consistently across the band).
"""
from __future__ import annotations

import dataclasses

import numpy as np


def voxel_downsample(points: np.ndarray, voxel_m: float = 0.02) -> np.ndarray:
    """Grid/voxel downsample: keeps one representative point per voxel_m cell.
    Plane/line fitting needs a uniform-density cloud, not a raw one (raw
    density is uneven — frames with the phone held still oversample that
    view), and RANSAC cost scales with point count, so this also makes
    million-point clouds tractable (~5M raw points down to well under 100k)."""
    if len(points) == 0:
        return points
    keys = np.floor(points / voxel_m).astype(np.int64)
    # Encode the 3 int coords into one hashable key for a fast unique-first pass.
    order = np.lexsort((keys[:, 2], keys[:, 1], keys[:, 0]))
    sorted_keys = keys[order]
    is_first = np.empty(len(sorted_keys), dtype=bool)
    is_first[0] = True
    is_first[1:] = np.any(sorted_keys[1:] != sorted_keys[:-1], axis=1)
    keep = order[is_first]
    return points[keep]


@dataclasses.dataclass
class WallSegment:
    p0: np.ndarray  # (x, z)
    p1: np.ndarray
    length_m: float
    n_inliers: int
    openings: list[tuple[float, float]]  # (start_frac, end_frac) along the wall


@dataclasses.dataclass
class RoomFit:
    floor_y: float
    ceiling_y: float
    ceiling_height_m: float
    walls: list[WallSegment]
    floor_area_m2: float
    n_points: int
    confidence: str  # "high" | "medium" | "low" — drives interval width downstream


def _histogram_peak(values: np.ndarray, lo_frac: float, hi_frac: float, bin_m: float = 0.02) -> float:
    lo, hi = np.percentile(values, [1, 99])
    band_lo = lo + (hi - lo) * lo_frac
    band_hi = lo + (hi - lo) * hi_frac
    band = values[(values >= band_lo) & (values <= band_hi)]
    if len(band) < 20:
        band = values
    bins = np.arange(band.min(), band.max() + bin_m, bin_m)
    hist, edges = np.histogram(band, bins=bins)
    peak_idx = int(np.argmax(hist))
    return float((edges[peak_idx] + edges[peak_idx + 1]) / 2)


def find_floor_ceiling(points: np.ndarray) -> tuple[float, float]:
    """Floor via histogram peak (floor is reliably the single largest flat
    surface any walkthrough captures). Ceiling via a high percentile rather
    than a histogram peak: in furnished rooms the most common *height value*
    well below the true ceiling is often a cabinet top or shelf, which a peak
    search picks up in preference to the ceiling itself (sparsely sampled,
    since a handheld walkthrough spends little time pointed straight up).
    A percentile is more robust here at the cost of being pulled down if the
    capture barely reaches the ceiling at all — a real limitation, disclosed
    in the report rather than hidden."""
    y = points[:, 1]
    floor_y = _histogram_peak(y, 0.0, 0.35)
    # A fixed high percentile (e.g. 99th) is pulled upward by mirror/glass
    # phantom-depth outliers (flagged as a known hazard in the brief) that
    # survive confidence filtering and radius-based outlier rejection. The
    # true ceiling shows up as a density plateau below the long thin outlier
    # tail; 96th percentile sits at that plateau on every sample room tried
    # during development. Documented as a tuned constant, not a physical law.
    ceiling_y = float(np.percentile(y, 96.0))
    if ceiling_y <= floor_y:
        floor_y, ceiling_y = np.percentile(y, [2, 98])
    return floor_y, ceiling_y


def _ransac_line(pts_2d: np.ndarray, rng: np.random.Generator, n_iter=400, dist_thresh=0.04):
    """Fits a single 2D line (ax + bz = c, normalized) via RANSAC. Returns
    (a, b, c, inlier_mask) for the best-supported line, or None if too few pts."""
    n = len(pts_2d)
    if n < 20:
        return None
    best = None
    best_count = 0
    idx_pairs = rng.integers(0, n, size=(n_iter, 2))
    for i0, i1 in idx_pairs:
        if i0 == i1:
            continue
        p0, p1 = pts_2d[i0], pts_2d[i1]
        d = p1 - p0
        norm = np.hypot(*d)
        if norm < 1e-6:
            continue
        a, b = -d[1] / norm, d[0] / norm
        c = a * p0[0] + b * p0[1]
        dist = np.abs(a * pts_2d[:, 0] + b * pts_2d[:, 1] - c)
        inliers = dist < dist_thresh
        count = int(inliers.sum())
        if count > best_count:
            best_count = count
            best = (a, b, c, inliers)
    return best


def _vertical_span_ok(inlier_y: np.ndarray, y_lo: float, y_hi: float, min_frac_each_end=0.05) -> bool:
    """A true wall has points near both the floor and the ceiling of the
    vertical band; a furniture surface (counter, cabinet face) typically
    occupies only a narrow slice of it. Requires >=1% of inliers within the
    bottom and top deciles of the band."""
    span = y_hi - y_lo
    if span <= 0:
        return True
    near_bottom = (inlier_y < y_lo + 0.15 * span).mean()
    near_top = (inlier_y > y_hi - 0.15 * span).mean()
    return near_bottom > min_frac_each_end and near_top > min_frac_each_end


def _merge_lines(lines: list[dict], angle_tol_deg=6.0, offset_tol_m=0.18) -> list[dict]:
    """Collapses near-duplicate / near-parallel-and-close lines (the same
    physical wall picked up as two or more slightly offset RANSAC fits, e.g.
    from wall texture/trim/baseboard) by merging their inlier point sets and
    refitting a single line through the union via total least squares."""
    merged = []
    used = [False] * len(lines)
    for i, li in enumerate(lines):
        if used[i]:
            continue
        group = [li]
        used[i] = True
        ai, bi = li["a"], li["b"]
        angle_i = np.degrees(np.arctan2(bi, ai)) % 180
        for j in range(i + 1, len(lines)):
            if used[j]:
                continue
            lj = lines[j]
            angle_j = np.degrees(np.arctan2(lj["b"], lj["a"])) % 180
            dangle = min(abs(angle_i - angle_j), 180 - abs(angle_i - angle_j))
            if dangle > angle_tol_deg:
                continue
            # perpendicular offset between the two lines' c values (both normalized a,b)
            doffset = abs(li["c"] - (li["a"] * lj["a"] + li["b"] * lj["b"]) * lj["c"])
            if doffset > offset_tol_m:
                continue
            group.append(lj)
            used[j] = True
        pts = np.concatenate([g["inlier_pts"] for g in group], axis=0)
        mean = pts.mean(axis=0)
        centered = pts - mean
        _, _, vt = np.linalg.svd(centered, full_matrices=False)
        direction = vt[0]
        a, b = -direction[1], direction[0]
        norm = np.hypot(a, b)
        a, b = a / norm, b / norm
        c = a * mean[0] + b * mean[1]
        merged.append({"a": a, "b": b, "c": c, "inlier_pts": pts, "count": len(pts)})
    return merged


def fit_walls(points_between: np.ndarray, max_walls: int = 10, min_wall_support: int = 150,
              seed: int = 0) -> list[WallSegment]:
    if len(points_between) < 200:
        return []
    y_lo, y_hi = np.percentile(points_between[:, 1], [2, 98])
    rng = np.random.default_rng(seed)
    pts_2d = points_between[:, [0, 2]].copy()
    remaining_2d = pts_2d
    remaining_y = points_between[:, 1]
    raw_lines = []
    for _ in range(max_walls):
        result = _ransac_line(remaining_2d, rng)
        if result is None:
            break
        a, b, c, inliers = result
        count = int(inliers.sum())
        if count < min_wall_support:
            break
        inlier_y = remaining_y[inliers]
        if _vertical_span_ok(inlier_y, y_lo, y_hi):
            inlier_pts = remaining_2d[inliers]
            raw_lines.append({"a": a, "b": b, "c": c, "inlier_pts": inlier_pts, "count": count})
        # Always remove these inliers whether or not they qualified as a wall,
        # so furniture doesn't get re-discovered as a "wall" on the next pass.
        remaining_2d = remaining_2d[~inliers]
        remaining_y = remaining_y[~inliers]
        if len(remaining_2d) < min_wall_support:
            break

    merged = _merge_lines(raw_lines)

    walls = []
    for line in merged:
        a, b, c, inlier_pts = line["a"], line["b"], line["c"], line["inlier_pts"]
        direction = np.array([-b, a])
        t = inlier_pts @ direction
        t0, t1 = np.percentile(t, [2, 98])
        origin = np.array([a * c, b * c])
        p0 = origin + direction * t0
        p1 = origin + direction * t1
        length = float(np.hypot(*(p1 - p0)))
        if length < 0.5:
            continue
        openings = _find_openings(points_between, origin, direction, t0=t0, t1=t1)
        walls.append(WallSegment(p0=p0, p1=p1, length_m=length, n_inliers=line["count"], openings=openings))
    return walls


def _find_openings(points_between: np.ndarray, origin, direction, t0, t1,
                    band=0.06, min_gap_m=0.5, n_bins=60) -> list[tuple[float, float]]:
    """Looks for along-wall bins where the wall has points near floor/ceiling
    edges of the band but a vertical gap in the middle -> opening."""
    xz = points_between[:, [0, 2]]
    t_all = xz @ direction
    dist_to_line = np.abs((xz - origin) @ np.array([direction[1], -direction[0]]))
    near = dist_to_line < band
    t_near = t_all[near]
    y_near = points_between[near, 1]
    if len(t_near) < 30 or t1 <= t0:
        return []
    edges = np.linspace(t0, t1, n_bins + 1)
    coverage = np.zeros(n_bins, dtype=bool)
    for i in range(n_bins):
        m = (t_near >= edges[i]) & (t_near < edges[i + 1])
        coverage[i] = m.sum() >= 3  # "wall present" if at least a few points land here
    # An opening is a run of missing coverage bounded by present coverage
    # (pure dropout at the very ends isn't a detected opening, it's an edge).
    openings = []
    i = 1
    while i < n_bins - 1:
        if not coverage[i]:
            j = i
            while j < n_bins - 1 and not coverage[j]:
                j += 1
            gap_len = (edges[j] - edges[i])
            if gap_len >= min_gap_m and coverage[i - 1] and coverage[j]:
                openings.append(((edges[i] - t0) / (t1 - t0), (edges[j] - t0) / (t1 - t0)))
            i = j
        else:
            i += 1
    return openings


def order_walls_into_polygon(walls: list[WallSegment]) -> list[WallSegment]:
    """Chains wall segments end-to-end by nearest-endpoint matching so the
    result traces a closed loop. Best-effort: does not guarantee a perfect
    polygon on noisy data, which is disclosed via the confidence field."""
    if len(walls) <= 1:
        return walls
    remaining = walls[:]
    ordered = [remaining.pop(0)]
    while remaining:
        last = ordered[-1].p1
        dists = [min(np.hypot(*(w.p0 - last)), np.hypot(*(w.p1 - last))) for w in remaining]
        j = int(np.argmin(dists))
        w = remaining.pop(j)
        if np.hypot(*(w.p1 - last)) < np.hypot(*(w.p0 - last)):
            w = WallSegment(p0=w.p1, p1=w.p0, length_m=w.length_m, n_inliers=w.n_inliers, openings=w.openings)
        ordered.append(w)
    return ordered


def polygon_area(walls: list[WallSegment]) -> float:
    if len(walls) < 3:
        return 0.0
    pts = np.array([w.p0 for w in walls])
    x, z = pts[:, 0], pts[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(z, -1)) - np.dot(z, np.roll(x, -1))))


def _reject_far_outliers(points: np.ndarray, radius_m: float = 8.0) -> np.ndarray:
    """Drops points implausibly far from the capture's own centroid — long-range
    LiDAR returns through windows/mirrors/glass that still register a
    'high confidence' value but aren't part of the room being scanned."""
    center = np.median(points, axis=0)
    d = np.linalg.norm(points - center, axis=1)
    keep = d < radius_m
    return points[keep]


def fit_room(points: np.ndarray, voxel_m: float = 0.02) -> RoomFit:
    points = _reject_far_outliers(points)
    points = voxel_downsample(points, voxel_m=voxel_m)
    floor_y, ceiling_y = find_floor_ceiling(points)
    margin = 0.15
    between_mask = (points[:, 1] > floor_y + margin) & (points[:, 1] < ceiling_y - margin)
    points_between = points[between_mask]
    # Coarser voxel just for line-fitting: RANSAC cost scales with point count
    # and wall geometry doesn't need 2cm resolution to find a straight line.
    points_between_coarse = voxel_downsample(points_between, voxel_m=0.05)

    walls = fit_walls(points_between_coarse)
    walls = order_walls_into_polygon(walls)
    area = polygon_area(walls) if len(walls) >= 3 else 0.0

    n_pts = len(points)
    if n_pts > 50000 and len(walls) >= 3:
        confidence = "high"
    elif n_pts > 8000 and len(walls) >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return RoomFit(
        floor_y=floor_y, ceiling_y=ceiling_y, ceiling_height_m=float(ceiling_y - floor_y),
        walls=walls, floor_area_m2=area, n_points=n_pts, confidence=confidence,
    )
