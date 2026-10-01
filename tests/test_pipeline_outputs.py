"""Contract tests: every plan.json the pipeline wrote under outputs/ (or the
paths in COZMO_TEST_OUTPUTS) must validate against the published schema and
satisfy basic physical invariants. Skipped when no outputs exist yet."""
import glob
import json
import math
import os

import jsonschema
import pytest

SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), "..", "schema", "capture_schema.json")))
paths = (os.environ.get("COZMO_TEST_OUTPUTS", "").split(os.pathsep) if os.environ.get("COZMO_TEST_OUTPUTS")
         else glob.glob(os.path.join(os.path.dirname(__file__), "..", "outputs", "*", "plan.json")))
paths = [p for p in paths if p and os.path.exists(p)]


@pytest.mark.skipif(not paths, reason="no pipeline outputs to check yet")
@pytest.mark.parametrize("path", paths)
def test_output_validates_and_is_physical(path):
    d = json.load(open(path))
    jsonschema.validate(d, SCHEMA)
    ids = {r["room_id"] for r in d["rooms"]}
    for r in d["rooms"]:
        for key in ("ceiling_height_m", "floor_area_m2"):
            m = r[key]
            assert m["ci_low"] <= m["value"] <= m["ci_high"], (r["room_id"], key)
        if r["ceiling_observed"]:
            assert 1.9 < r["ceiling_height_m"]["value"] < 4.5
        assert r["floor_area_m2"]["value"] > 0
        for w in r["walls"]:
            L = w["length_m"]
            assert L["ci_low"] <= L["value"] <= L["ci_high"]
            assert math.isclose(L["value"], math.dist(w["p0"], w["p1"]), abs_tol=1e-3)
            for o in w["openings"]:
                assert 0.3 < o["width_m"]["value"] < 2.5
                assert o["leads_to"] is None or o["leads_to"] in ids
    for a in d["stitched_plan"]["adjacency"]:
        assert set(a["rooms"]) <= ids
