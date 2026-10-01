import numpy as np

from stitching.stitch import (align_shared_wall, place_by_adjacency, align_repeat, transform,
                              raster_union_overlap, _T)


def box(w, h):
    return np.array([[0, 0], [w, 0], [w, h], [0, h]], float)   # CCW; wall k = P[k]->P[k+1]


def test_shared_wall_rooms_share_the_wall_not_a_corner():
    a, b = box(4, 3), box(3, 3)
    # a's wall 1 is x=4 (0..3); b's wall 3 is x=0 (3..0)
    T = place_by_adjacency({"a": a, "b": b}, "a", [("a", 1, "b", 3)])
    pb = transform(T["b"], b)
    assert np.allclose(sorted(pb[:, 0]), [4, 4, 7, 7], atol=1e-9)
    assert np.allclose(sorted(pb[:, 1]), [0, 0, 3, 3], atol=1e-9)   # same z-span as a: shared wall
    union, overlap = raster_union_overlap([a, pb])
    assert abs(union - 21.0) < 0.1 and overlap < 0.05


def test_shared_wall_with_different_measured_lengths_aligns_midpoints():
    T = align_shared_wall([4, 0], [4, 3], [0, 3.1], [0, -0.1])
    mid = transform(T, np.array([[0, 1.5]]))[0]
    assert np.allclose(mid, [4, 1.5], atol=1e-9)


def test_repeat_alignment_does_not_depend_on_wall_order():
    first = box(4, 3)
    drift = _T(np.radians(3.0), [0.25, -0.15])
    second = transform(np.linalg.inv(drift), np.roll(first, 2, axis=0))   # rotated start index
    T = align_repeat(first, second)
    back = transform(T, second)
    d = np.min(np.linalg.norm(back[:, None] - first[None], axis=2), axis=1)
    assert d.max() < 0.01


def test_union_footprint_changes_when_rooms_overlap():
    a, b = box(4, 3), box(4, 3) + [3.5, 0]   # 0.5m overlap
    union, overlap = raster_union_overlap([a, b])
    assert abs(overlap - 1.5) < 0.1
    assert abs(union - 22.5) < 0.1
