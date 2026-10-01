from benchmark.gates import (
    opening_width_gate, ceiling_height_gate, repeatability_gate,
    drift_ablation_gate, photo_tier_stitch_gate,
)


def test_opening_width_gate_passes_when_within_tolerance():
    pred = [{"position_m": 1.0, "width_m": 0.81}, {"position_m": 3.0, "width_m": 1.20}]
    gt = [{"position_m": 1.02, "width_m": 0.80}, {"position_m": 3.0, "width_m": 1.21}]
    r = opening_width_gate(pred, gt)
    assert r.passed
    assert r.pass_rate == 1.0


def test_opening_width_gate_counts_missed_and_phantom():
    pred = [{"position_m": 1.0, "width_m": 0.81}, {"position_m": 9.0, "width_m": 0.5}]  # phantom
    gt = [{"position_m": 1.0, "width_m": 0.81}, {"position_m": 3.0, "width_m": 1.2}]  # one missed
    r = opening_width_gate(pred, gt)
    assert not r.passed
    # 1 correct out of (2 ground truth + 1 phantom): phantoms count as misses
    assert abs(r.pass_rate - 1 / 3) < 1e-9


def test_ceiling_height_gate_flags_unrepeatable():
    r = ceiling_height_gate(2.40, 2.405, repeat_predictions_m=[2.40, 2.43])
    assert not r.passed  # spread 3cm > 1cm repeat tolerance
    assert "unrepeatable" in r.detail


def test_ceiling_height_gate_flags_repeatable_but_biased():
    r = ceiling_height_gate(2.50, 2.40, repeat_predictions_m=[2.50, 2.505])
    assert not r.passed  # 10cm error > 1.5cm gate, even though repeatable
    assert "repeatable-but-biased" in r.detail


def test_repeatability_gate():
    r = repeatability_gate([3.0, 4.0, 3.0, 4.0], [3.005, 4.03, 3.001, 3.995])
    assert not r.passed  # second wall off by 3cm > max(1cm, 0.5%*4=2cm)


def test_drift_ablation_gate_detects_improvement():
    r = drift_ablation_gate(footprint_with_correction_m2=24.8, footprint_without_correction_m2=19.2,
                             ground_truth_footprint_m2=25.0)
    assert r.passed


def test_photo_tier_stitch_gate():
    r = photo_tier_stitch_gate(predicted_footprint_m2=23.5, ground_truth_footprint_m2=25.0,
                                rooms_placed=3, rooms_expected=3, no_overlaps=True)
    assert r.passed  # 6% error, under 8% tolerance

    r2 = photo_tier_stitch_gate(predicted_footprint_m2=23.5, ground_truth_footprint_m2=25.0,
                                 rooms_placed=2, rooms_expected=3, no_overlaps=True)
    assert not r2.passed  # a room failed to place


def test_phantom_openings_are_penalised():
    gt = [{"position_m": 1.0, "width_m": 0.80}]
    pred = [{"position_m": 1.0, "width_m": 0.80}, {"position_m": 5.0, "width_m": 0.9}]
    r = opening_width_gate(pred, gt)
    assert r.pass_rate == 0.5 and not r.passed


def test_match_walls_independent_of_order():
    import numpy as np
    from benchmark.gates import match_walls
    a = np.array([[0, 0], [4, 0], [4, 3], [0, 3]], float)
    b = np.roll(a + [0.1, -0.05], 1, axis=0)
    pairs = match_walls(a, b)
    assert all(p2 is not None and abs(p1 - p2) < 1e-3 for p1, p2 in pairs)
