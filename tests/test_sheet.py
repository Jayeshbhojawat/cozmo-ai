"""The sheet matcher must recover wall identities from a tape sheet that uses
its own labels: different start wall, opposite direction, stubs omitted,
1 cm reading noise."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from benchmark.sheet import to_ground_truth
from benchmark.ground_truth import score

PLAN = Path(__file__).resolve().parents[1] / "benchmark/results/plans/c7d28f72c6.json"


def _fake_sheet(plan, room_ids, rng, stub=0.30):
    rooms, truth = [], {}
    for k, rid in enumerate(room_ids):
        r = next(r for r in plan["rooms"] if r["room_id"] == rid)
        walls = r["walls"]
        n = len(walls)
        start, direction = rng.integers(n), (-1 if k % 2 else 1)
        order = [(start + direction * i) % n for i in range(n)]
        kept = [i for i in order if walls[i]["length_m"]["value"] >= stub]
        letters = {}
        wl = []
        for li, i in enumerate(kept):
            L = walls[i]["length_m"]["value"] * 100 + rng.normal(0, 1.0)
            wl.append([round(L, 1), round(L + rng.normal(0, 0.2), 1)])
            letters[chr(65 + li)] = walls[i]["wall_id"]
        ops = []
        for li, i in enumerate(kept):
            for o in walls[i]["openings"]:
                ops.append({"kind": o["kind"], "wall": chr(65 + li),
                            "width_cm": [round(o["width_m"]["value"] * 100 + 1.0, 1)]})
        rooms.append({"name": f"sheet_{rid}", "walls_cm": wl, "ceiling_cm": [[250.0]], "openings": ops})
        truth[rid] = letters
    rng.shuffle(rooms)
    return {"capture_id": "t", "rooms": rooms}, truth


@pytest.mark.skipif(not PLAN.exists(), reason="stored sample plan missing")
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_matcher_recovers_walls(seed):
    plan = json.loads(PLAN.read_text())
    rng = np.random.default_rng(seed)
    sheet, truth = _fake_sheet(plan, ["room_2", "room_5", "room_6"], rng)
    gt, rep = to_ground_truth(plan, sheet)
    for m in rep["room_matches"]:
        rid = m["sheet_room"].replace("sheet_", "")
        assert m["plan_room"] == rid
        assert m["walls"] == truth[rid]
    res = score(plan, gt)
    op = res["gates"]["opening_widths"]
    assert op["missed"] == 0 and op["phantom"] == 0
    assert op["within_2cm"] == op["scored"]          # widths were offset by 1 cm only


def test_missing_door_counts_as_miss():
    plan = json.loads(PLAN.read_text())
    rng = np.random.default_rng(5)
    sheet, _ = _fake_sheet(plan, ["room_5"], rng)
    sheet["rooms"][0]["openings"].append({"kind": "door", "wall": "A", "width_cm": [300.0]})
    gt, _ = to_ground_truth(plan, sheet)
    res = score(plan, gt)
    assert res["gates"]["opening_widths"]["missed"] == 1
