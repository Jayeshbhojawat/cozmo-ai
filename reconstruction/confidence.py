"""Confidence-interval policy: every measurement in the output JSON carries an
interval, and intervals widen honestly as sensor data thins, per Part 1's
"same output contract from each [tier], intervals widen honestly" rule.

These half-widths are starting points tuned to the gate targets in Part 2
(LiDAR: openings <=2cm/85%, ceiling <=1.5cm/room), not measured error yet —
the benchmark report (once ground truth is collected) replaces these with
measured, tier-specific calibration curves. Using gate targets as the prior
means a tier that can't plausibly meet its gate says so up front instead of
reporting a falsely tight interval ("confident garbage on thin input caps
your score" — Part 2).
"""
from __future__ import annotations

import dataclasses

TIER_BASE_HALF_WIDTH_M = {
    "lidar": 0.010,   # 1.0cm — inside the <=1.5cm ceiling-height gate
    "video": 0.03,    # ~3% of a typical 1m reference wall segment
    "photo": 0.08,    # ~8% of a typical 1m reference wall segment, per Part 2's photo-tier gate
}

# Multiplicative penalty applied when a measurement's local point support is
# below this many inlier points (thin data even within a "high confidence"
# LiDAR capture -> honestly wider interval rather than a flat per-tier number).
LOW_SUPPORT_INLIERS = 500
LOW_SUPPORT_MULTIPLIER = 2.5

UNTRUSTED_MULTIPLIER = 8.0  # for anything flagged n_inliers == 0 (degenerate geometry)


@dataclasses.dataclass
class Measurement:
    value: float
    unit: str
    ci_low: float
    ci_high: float
    basis: str  # short human-readable reason for the interval width chosen


def interval_for_length(value_m: float, tier: str, n_inliers: int) -> Measurement:
    base = TIER_BASE_HALF_WIDTH_M[tier]
    mult = 1.0
    basis = f"{tier} tier base interval"
    if n_inliers == 0:
        mult = UNTRUSTED_MULTIPLIER
        basis = "degenerate geometry (near-parallel adjacent walls) — flagged untrusted"
    elif tier == "lidar" and n_inliers < LOW_SUPPORT_INLIERS:
        mult = LOW_SUPPORT_MULTIPLIER
        basis = f"{tier} tier, thin support ({n_inliers} inlier points)"
    half_width = base * mult
    # Photo/video half-widths in Part 2 are stated as a percentage of wall
    # length, not an absolute; apply that once value is known, floor at the
    # LiDAR-scale absolute minimum so short walls don't get a near-zero CI.
    if tier in ("video", "photo"):
        half_width = max(base * abs(value_m), 0.01)
        if n_inliers == 0:
            half_width *= UNTRUSTED_MULTIPLIER
    return Measurement(value=value_m, unit="m", ci_low=value_m - half_width,
                        ci_high=value_m + half_width, basis=basis)


def interval_for_height(value_m: float, tier: str, n_room_samples: int = 1) -> Measurement:
    base = TIER_BASE_HALF_WIDTH_M[tier]
    half_width = base if tier == "lidar" else base * abs(value_m)
    basis = f"{tier} tier base interval"
    if n_room_samples > 1:
        # Repeatability gate context: spread across repeat captures, if known,
        # would replace this basis string with the measured spread.
        basis += f" ({n_room_samples} repeat captures available for spread check)"
    return Measurement(value=value_m, unit="m", ci_low=value_m - half_width,
                        ci_high=value_m + half_width, basis=basis)


def interval_for_area(value_m2: float, tier: str, wall_measurements: list[Measurement]) -> Measurement:
    # Propagate wall-length relative uncertainty into area (first-order): area
    # relative error ~= 2x average wall relative error for a simple polygon.
    if not wall_measurements or value_m2 <= 0:
        rel = TIER_BASE_HALF_WIDTH_M[tier] if tier != "lidar" else 0.02
    else:
        rels = [abs(m.ci_high - m.ci_low) / 2 / max(abs(m.value), 1e-3) for m in wall_measurements]
        rel = 2 * (sum(rels) / len(rels))
    half_width = value_m2 * rel
    return Measurement(value=value_m2, unit="m2", ci_low=max(0.0, value_m2 - half_width),
                        ci_high=value_m2 + half_width,
                        basis=f"propagated from {len(wall_measurements)} wall-length intervals")
