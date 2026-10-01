from benchmark.ground_truth import template, score


def _m(v, hw):
    return {"value": v, "unit": "m", "ci_low": v - hw, "ci_high": v + hw, "basis": "t"}


PLAN = {
    "capture_id": "t",
    "stitched_plan": {"footprint_m2": _m(12.0, 0.1)},
    "rooms": [{
        "room_id": "room_1", "ceiling_observed": True, "ceiling_height_m": _m(2.70, 0.01),
        "walls": [{"wall_id": "room_1_w0", "observed": True, "length_m": _m(4.00, 0.01),
                   "openings": [{"opening_id": "room_1_w0_o0", "kind": "door", "width_m": _m(0.80, 0.01)},
                                {"opening_id": "room_1_w0_o1", "kind": "window", "width_m": _m(1.20, 0.01)}]}],
    }],
}


def test_template_has_every_measurable_item():
    t = template(PLAN)
    r = t["rooms"][0]
    assert r["walls"][0]["measured"] is None and len(r["openings"]) == 2


def test_score_counts_phantoms_and_missed_and_calibration():
    gt = template(PLAN)
    r = gt["rooms"][0]
    r["walls"][0]["measured"] = 4.03                 # outside the +-1cm CI
    r["ceiling_height_m"]["measured"] = 2.705        # inside, error 0.5cm
    r["openings"][0]["measured"] = 0.81              # within 2cm
    r["openings"][1]["exists"] = False               # phantom
    r["missed_openings"] = [{"near_wall_id": "room_1_w0", "kind": "door", "measured": 0.7}]
    s = score(PLAN, gt)
    g = s["gates"]["opening_widths"]
    assert g["scored"] == 3 and g["within_2cm"] == 1 and not g["passed"]
    assert s["gates"]["ceiling_height"]["passed"]
    assert s["calibration_95ci_coverage"] == {"inside": 2, "total": 3, "rate": 0.667}
