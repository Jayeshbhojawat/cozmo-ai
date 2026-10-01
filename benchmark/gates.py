"""Gate definitions from Part 2, implemented so they can be run the moment
ground-truth measurements exist. Each gate function takes predictions +
ground truth and returns a GateResult; nothing here is specific to any one
room, so the same functions run across the whole benchmark set once it's
captured (see docs/compliance_matrix.md #16 for what's still missing).
"""
from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class GateResult:
    name: str
    passed: bool
    detail: str
    pass_rate: float | None = None  # for gates scored as a percentage


def opening_width_gate(predicted_openings: list[dict], ground_truth_openings: list[dict],
                        match_radius_m: float = 0.3, tol_m: float = 0.02) -> GateResult:
    """predicted/ground_truth openings: [{"position_m": float_along_wall,
    "width_m": float}]. A missed opening (no prediction within match_radius_m
    of a ground-truth one) and a phantom opening (no ground truth within
    match_radius_m of a prediction) both count as misses, per the brief."""
    total = len(ground_truth_openings)
    matched_gt = set()
    pairs = []
    for pred in predicted_openings:
        best_j, best_d = None, match_radius_m
        for j, gt in enumerate(ground_truth_openings):
            if j in matched_gt:
                continue
            d = abs(pred["position_m"] - gt["position_m"])
            if d < best_d:
                best_j, best_d = j, d
        if best_j is not None:
            matched_gt.add(best_j)
            pairs.append((pred, ground_truth_openings[best_j]))
    n_phantom = len(predicted_openings) - len(pairs)
    n_missed = total - len(pairs)
    n_correct_width = sum(1 for p, g in pairs if abs(p["width_m"] - g["width_m"]) <= tol_m)
    # Brief: "a missed opening and a phantom opening each count as a miss" ->
    # phantoms must enter the denominator, otherwise over-detection is free.
    denom = max(total + n_phantom, 1)
    pass_rate = n_correct_width / denom
    passed = pass_rate >= 0.85
    detail = (f"{n_correct_width}/{total + n_phantom} scored openings within {tol_m*100:.0f}cm "
              f"({n_missed} missed, {n_phantom} phantom)")
    return GateResult("opening_widths", passed, detail, pass_rate)


def ceiling_height_gate(predicted_m: float, ground_truth_m: float,
                         repeat_predictions_m: list[float] | None = None,
                         tol_m: float = 0.015, repeat_tol_m: float = 0.01) -> GateResult:
    err = abs(predicted_m - ground_truth_m)
    passed = err <= tol_m
    detail = f"|{predicted_m:.3f} - {ground_truth_m:.3f}| = {err*100:.1f}cm (gate: <={tol_m*100:.1f}cm)"
    if repeat_predictions_m and len(repeat_predictions_m) > 1:
        spread = max(repeat_predictions_m) - min(repeat_predictions_m)
        repeat_ok = spread <= repeat_tol_m
        passed = passed and repeat_ok
        bias_note = "repeatable-but-biased" if repeat_ok and err > tol_m else (
            "unrepeatable" if not repeat_ok else "repeatable and within tolerance")
        detail += f"; repeat spread {spread*100:.1f}cm (gate: <={repeat_tol_m*100:.1f}cm) -> {bias_note}"
    return GateResult("ceiling_height", passed, detail)


def match_walls(poly_first, poly_second):
    """Pairs walls of two captures of the same room without assuming the same
    wall order: align pass 2 onto pass 1 (ICP), then match each wall to the
    parallel wall with the nearest midpoint. Returns [(len1, len2)]; walls
    with no counterpart within 0.3m are returned as (len1, None)."""
    import numpy as np
    from stitching.stitch import align_repeat, transform
    P1 = np.asarray(poly_first, float)
    P2 = transform(align_repeat(P1, poly_second), poly_second)
    def walls(P):
        out = []
        for k in range(len(P)):
            a, b = P[k], P[(k + 1) % len(P)]
            d = b - a
            out.append(((a + b) / 2, d / (np.linalg.norm(d) + 1e-12), float(np.linalg.norm(d))))
        return out
    w2 = walls(P2)
    pairs = []
    for m1, d1, l1 in walls(P1):
        best, bd = None, 0.3
        for m2, d2, l2 in w2:
            if abs(abs(d1 @ d2) - 1) < 0.02 and np.linalg.norm(m1 - m2) < bd:
                best, bd = l2, float(np.linalg.norm(m1 - m2))
        pairs.append((l1, best))
    return pairs


def repeatability_gate(wall_lengths_pass1: list[float], wall_lengths_pass2: list[float],
                        abs_tol_m: float = 0.01, rel_tol: float = 0.005) -> GateResult:
    """Lengths must already be paired wall-by-wall (use match_walls() on the
    two room polygons; list order of two captures is not a correspondence)."""
    if len(wall_lengths_pass1) != len(wall_lengths_pass2) or not wall_lengths_pass1:
        return GateResult("repeatability", False, "wall count mismatch between passes -- cannot compare")
    if any(b is None for b in wall_lengths_pass2):
        n_missing = sum(b is None for b in wall_lengths_pass2)
        return GateResult("repeatability", False, f"{n_missing} wall(s) have no counterpart in the repeat capture")
    diffs = [abs(a - b) for a, b in zip(wall_lengths_pass1, wall_lengths_pass2)]
    tols = [max(abs_tol_m, rel_tol * a) for a in wall_lengths_pass1]
    n_ok = sum(1 for d, t in zip(diffs, tols) if d <= t)
    passed = n_ok == len(diffs)
    detail = f"{n_ok}/{len(diffs)} walls agree within max(1cm, 0.5%)"
    return GateResult("repeatability", passed, detail, n_ok / len(diffs))


def drift_ablation_gate(footprint_with_correction_m2: float, footprint_without_correction_m2: float,
                         ground_truth_footprint_m2: float) -> GateResult:
    err_with = abs(footprint_with_correction_m2 - ground_truth_footprint_m2)
    err_without = abs(footprint_without_correction_m2 - ground_truth_footprint_m2)
    improved = err_with < err_without
    detail = (f"with-correction error {err_with:.2f}m2 vs without-correction error "
              f"{err_without:.2f}m2 (ground truth {ground_truth_footprint_m2:.2f}m2)")
    return GateResult("drift_accountability", improved, detail)


def photo_tier_stitch_gate(predicted_footprint_m2: float, ground_truth_footprint_m2: float,
                            rooms_placed: int, rooms_expected: int,
                            no_overlaps: bool, tol_frac: float = 0.08) -> GateResult:
    err_frac = abs(predicted_footprint_m2 - ground_truth_footprint_m2) / max(ground_truth_footprint_m2, 1e-6)
    all_placed = rooms_placed == rooms_expected
    passed = (err_frac <= tol_frac) and all_placed and no_overlaps
    detail = (f"footprint error {err_frac*100:.1f}% (gate <={tol_frac*100:.0f}%), "
              f"{rooms_placed}/{rooms_expected} rooms placed, overlaps={'none' if no_overlaps else 'FOUND'}")
    return GateResult("photo_tier_whole_property_stitch", passed, detail)
