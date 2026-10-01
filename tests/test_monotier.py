import numpy as np

from reconstruction.layout import Opening, Room, Wall
from reconstruction.monotier import find_pivots, place_rooms


def test_find_pivots_detects_full_turn_only():
    t = np.arange(0, 40, 0.5)
    yaw = np.zeros_like(t)
    yaw[(t >= 10) & (t < 20)] = np.radians(np.linspace(0, 330, ((t >= 10) & (t < 20)).sum()))
    yaw[t >= 20] = np.radians(330)
    segs = find_pivots(yaw, t)
    assert len(segs) == 1
    a, b = segs[0]
    assert 9.5 <= t[a] <= 11 and t[b] <= 20


def _box(name, w, h, door_wall=None, door=(0.5, 1.3)):
    P = np.array([[0, 0], [w, 0], [w, h], [0, h]], float)
    walls = []
    for k in range(4):
        a, b = P[k], P[(k + 1) % 4]
        ops = [Opening(door[0], door[1], door[1] - door[0], 0.01, "opening_unconfirmed", None)] if k == door_wall else []
        walls.append(Wall(f"{name}_w{k}", a, b, float(np.linalg.norm(b - a)), 0.01, 0.005, 100, ops))
    return Room(name, P, walls, 0.0, 2.6, 0.01, True, w * h, 0.1, True)


def test_rooms_with_matching_doors_are_connected_without_overlap():
    a = _box("a", 4, 3, door_wall=1)      # door on x=4 wall
    b = _box("b", 3, 3, door_wall=3)      # door on x=0 wall
    placed, adj, rep = place_rooms([a, b])
    assert adj == [("a", "b")]
    pb = placed[1].polygon
    assert pb[:, 0].min() >= 4.0 - 1e-6   # B is beyond A's door wall (plus wall thickness)


def test_room_without_openings_is_reported_unconnected():
    a = _box("a", 4, 3, door_wall=1)
    b = _box("b", 3, 3)
    placed, adj, rep = place_rooms([a, b])
    assert adj == [] and rep[0]["connected_to"] is None
