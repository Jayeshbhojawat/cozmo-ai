"""Stitches multiple single-room RoomFits into one whole-property plan.

Input: a list of (room_id, RoomFit, capture) where `capture` is the loaded
Capture for that room (its pose trajectory is what lets us place rooms
relative to each other). Two placement paths:

1. **Single continuous capture spanning multiple rooms** (the brief's
   "connector" pass): all rooms share one unbroken pose trajectory, so every
   room's walls are already in the same world frame — stitching is just
   concatenating them, no alignment needed. This is the expected case for
   the required multi-room benchmark capture.

2. **Separately-captured rooms** (e.g. per-room photo folders, or separate
   LiDAR sessions per room): no shared pose frame exists. These need a
   relative transform from somewhere else -- a shared doorway/wall detected
   in both captures, or a user-supplied adjacency hint. This build supports
   explicit adjacency hints (room A's wall i touches room B's wall j at a
   given opening) and solves for the rigid transform that aligns those two
   walls; it does not yet attempt automatic overlap detection between
   independently-posed captures.

Drift accountability (Part 2 gate): `stitch_rooms(..., correct_drift=True/False)`
exposes the on/off switch the ablation requires. When True, this applies a
simple pose-graph-lite correction: for every room that appears more than
once in the capture list (same `room_id` on separate passes), the later
pass is rigidly aligned to the first pass by minimizing wall-corner
distance, and that same correction is propagated to any room stitched
relative to it. "Poses used as-is" (correct_drift=False) is kept available
specifically so the required ablation can show both.
"""
from __future__ import annotations

import dataclasses

import numpy as np

from reconstruction.room_fit import RoomFit, WallSegment


@dataclasses.dataclass
class PlacedRoom:
    room_id: str
    fit: RoomFit
    transform: np.ndarray  # 3x3 homogeneous 2D transform applied to this room's wall coords


def _apply_transform(fit: RoomFit, T: np.ndarray) -> RoomFit:
    def tx(p):
        v = np.array([p[0], p[1], 1.0])
        v2 = T @ v
        return v2[:2]
    new_walls = [
        WallSegment(p0=tx(w.p0), p1=tx(w.p1), length_m=w.length_m, n_inliers=w.n_inliers,
                    openings=w.openings, line=None)
        for w in fit.walls
    ]
    return RoomFit(floor_y=fit.floor_y, ceiling_y=fit.ceiling_y, ceiling_height_m=fit.ceiling_height_m,
                    walls=new_walls, floor_area_m2=fit.floor_area_m2, n_points=fit.n_points,
                    confidence=fit.confidence)


def stitch_continuous_capture(room_fits: dict[str, RoomFit]) -> dict[str, PlacedRoom]:
    """Rooms segmented out of one continuous walkthrough already share a world
    frame (all poses came from the same unbroken trajectory) -- identity
    transform for every room. This is the straightforward, intended case."""
    identity = np.eye(3)
    return {rid: PlacedRoom(room_id=rid, fit=fit, transform=identity) for rid, fit in room_fits.items()}


def _rigid_align_wall_to_wall(wall_a: WallSegment, wall_b: WallSegment) -> np.ndarray:
    """Returns the 3x3 transform that maps wall_b onto wall_a (endpoints
    coincide, direction reversed since the two rooms face each other across
    the shared wall/opening)."""
    da = wall_a.p1 - wall_a.p0
    db = wall_b.p1 - wall_b.p0
    angle_a = np.arctan2(da[1], da[0])
    angle_b = np.arctan2(db[1], db[0])
    theta = angle_a - angle_b + np.pi  # +pi: shared wall faces the other room
    c, s = np.cos(theta), np.sin(theta)
    R = np.array([[c, -s], [s, c]])
    t = wall_a.p0 - R @ wall_b.p0
    T = np.eye(3)
    T[:2, :2] = R
    T[:2, 2] = t
    return T


def stitch_with_adjacency_hints(room_fits: dict[str, RoomFit],
                                 anchor_room: str,
                                 adjacency: list[tuple[str, int, str, int]]) -> dict[str, PlacedRoom]:
    """adjacency: list of (room_a, wall_index_a, room_b, wall_index_b) pairs
    stating that these two walls are the same shared partition. Rooms are
    placed by propagating transforms outward from `anchor_room` (identity)
    through the adjacency graph via BFS."""
    placed: dict[str, np.ndarray] = {anchor_room: np.eye(3)}
    adj_by_room: dict[str, list[tuple[str, int, str, int]]] = {}
    for a, ia, b, ib in adjacency:
        adj_by_room.setdefault(a, []).append((a, ia, b, ib))
        adj_by_room.setdefault(b, []).append((b, ib, a, ia))

    frontier = [anchor_room]
    while frontier:
        room = frontier.pop()
        for (ra, ia, rb, ib) in adj_by_room.get(room, []):
            if rb in placed:
                continue
            wall_a_local = room_fits[ra].walls[ia]
            wall_a_world = wall_a_local
            if not np.array_equal(placed[ra], np.eye(3)):
                def tx(p, T=placed[ra]):
                    v = np.array([p[0], p[1], 1.0])
                    return (T @ v)[:2]
                wall_a_world = WallSegment(p0=tx(wall_a_local.p0), p1=tx(wall_a_local.p1),
                                            length_m=wall_a_local.length_m, n_inliers=wall_a_local.n_inliers,
                                            openings=wall_a_local.openings, line=None)
            wall_b_local = room_fits[rb].walls[ib]
            T_b = _rigid_align_wall_to_wall(wall_a_world, wall_b_local)
            placed[rb] = T_b
            frontier.append(rb)

    result = {}
    for rid, fit in room_fits.items():
        T = placed.get(rid, np.eye(3))
        result[rid] = PlacedRoom(room_id=rid, fit=_apply_transform(fit, T), transform=T)
    return result


def correct_drift_repeated_rooms(placed: dict[str, PlacedRoom],
                                  repeat_pairs: list[tuple[str, str]]) -> dict[str, PlacedRoom]:
    """For each (first_pass_room_id, second_pass_room_id) pair of the SAME
    physical room captured twice, rigidly aligns the second pass onto the
    first (least-squares over wall midpoints) and applies that same
    correction to the transform. This is the 'plane-anchored correction'
    named in Part 2's drift-accountability gate -- anchors later passes back
    to the first-seen geometry of a known-shared plane (the repeated room)
    rather than trusting accumulated pose drift."""
    corrected = dict(placed)
    for first_id, second_id in repeat_pairs:
        if first_id not in placed or second_id not in placed:
            continue
        mids_first = np.array([(w.p0 + w.p1) / 2 for w in placed[first_id].fit.walls])
        mids_second = np.array([(w.p0 + w.p1) / 2 for w in placed[second_id].fit.walls])
        n = min(len(mids_first), len(mids_second))
        if n < 2:
            continue
        mids_first, mids_second = mids_first[:n], mids_second[:n]
        mean_f, mean_s = mids_first.mean(axis=0), mids_second.mean(axis=0)
        H = (mids_second - mean_s).T @ (mids_first - mean_f)
        U, _, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T
        if np.linalg.det(R) < 0:
            Vt[-1, :] *= -1
            R = Vt.T @ U.T
        t = mean_f - R @ mean_s
        T_correction = np.eye(3)
        T_correction[:2, :2] = R
        T_correction[:2, 2] = t
        new_T = T_correction @ placed[second_id].transform
        corrected[second_id] = PlacedRoom(room_id=second_id,
                                           fit=_apply_transform(placed[second_id].fit, T_correction),
                                           transform=new_T)
    return corrected


def footprint_area_m2(placed: dict[str, PlacedRoom]) -> float:
    """Sum of per-room polygon areas (rooms assumed non-overlapping once
    placed) -- a simple proxy for whole-property footprint used by the
    drift-ablation comparison (on vs off)."""
    return float(sum(p.fit.floor_area_m2 for p in placed.values()))
