"""Confidence-interval policy. Every number in the output JSON carries a 95%
interval and a `basis` string saying where its width came from.

LiDAR tier: intervals come from the measurement model in `layout.py`
(robust scatter of the surface points behind each wall line, a per-surface
LiDAR bias term and a scale term), propagated to lengths, widths and areas.
That is a *model*, not yet a calibration: `benchmark/calibrate.py`
compares those intervals with tape/laser ground truth and reports coverage
(fraction of true values inside the stated 95% interval); if coverage is
low the inflation factor below is raised, and the report says so.

Photo/video tiers: no depth sensor, metric scale comes from an assumption
(camera height), so intervals are tier priors proportional to length,
matching Part 2's tier tolerances (photo +-8%, video +-3%) rather than
pretending to the LiDAR model's precision.
"""
from __future__ import annotations

import dataclasses
import math

Z95 = 1.96
# Multiplier applied to model sigmas until ground-truth calibration says
# otherwise (1.0 = trust the model as-is). Set by benchmark/calibrate.py.
LIDAR_SIGMA_INFLATION = 1.0

# Photo/video (pivot-scan) tiers: measured, not assumed. Five pivot
# reconstructions vs the LiDAR plan of the same rooms gave room-area errors
# of -2, +30, -28, +32, -3.5 % (RMS 22 %, i.e. ~11 % per length). The 95 %
# half-width per length is set to 2 x 11 % ~= 22 %; the brief's tier
# tolerances (photo 8 %, video 3 %) are therefore NOT met yet, and the
# intervals say so instead of pretending.
TIER_REL_HALF_WIDTH = {"video": 0.22, "photo": 0.22}


@dataclasses.dataclass
class Measurement:
    value: float
    unit: str
    ci_low: float
    ci_high: float
    basis: str

    def to_dict(self, nd=4):
        return {"value": round(self.value, nd), "unit": self.unit, "ci_low": round(self.ci_low, nd),
                "ci_high": round(self.ci_high, nd), "basis": self.basis}


def from_sigma(value: float, sigma: float, unit: str, basis: str, floor_at_zero=True) -> Measurement:
    hw = Z95 * sigma * LIDAR_SIGMA_INFLATION
    lo = value - hw
    if floor_at_zero:
        lo = max(0.0, lo)
    return Measurement(value, unit, lo, value + hw, basis)


def tier_prior(value: float, tier: str, unit: str = "m", power: int = 1) -> Measurement:
    """power=2 for areas (relative error doubles to first order)."""
    rel = TIER_REL_HALF_WIDTH[tier] * power
    hw = abs(value) * rel
    return Measurement(value, unit, max(0.0, value - hw), value + hw,
                       f"{tier}-tier interval +-{rel*100:.0f}% from measured pivot-scan error vs LiDAR "
                       f"(5 rooms, area RMS 22%); monocular depth, scale from camera height")


def lower_bound(value: float, upper: float, unit: str, basis: str) -> Measurement:
    return Measurement(value, unit, value, upper, basis)


def is_nan(x) -> bool:
    return isinstance(x, float) and math.isnan(x)
