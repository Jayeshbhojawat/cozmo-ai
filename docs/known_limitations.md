# Known limitations (live)

Ordered by impact on the score. Each says what is wrong, the evidence, and
what would fix it.

## 1. Photo and video tiers do not exist yet
`--tier video|photo` exits with a message. `reconstruction/sfm.py` holds a
classical SfM prototype with a known bug (unit-norm translations chained
without scale propagation -> scale explodes). Plan: ORB/essential-matrix
poses with shared-track scale propagation + a small monocular depth model
(MiDaS small; weights fetchable from GitHub releases by script) aligned per
frame to the SfM points, metric scale from the floor-plane camera height,
then the existing `layout.analyze` unchanged. The rgb.mp4 in every LiDAR
capture is a real iPhone walkthrough video, so the video tier can be scored
against the LiDAR result of the same walk.

## 2. No ground truth yet -> no scored gates, no calibration
All intervals are model-based (surface-point scatter + 4 mm per-surface
bias + 0.3% scale). They have not been checked against tape/laser.
`benchmark/ground_truth/*.json` are pre-filled measuring sheets; scoring
reports gate pass/fail and 95%-interval coverage. If coverage is well
below 95%, raise `LIDAR_SIGMA_INFLATION` in `reconstruction/confidence.py`
and say so in the report.

## 3. Ceiling never seen in 2 of 3 captures
Even at low LiDAR confidence there are no points above ~2.0 m in
`c00a170fe1` / `1a8384c3f6`: the phone never tilted up. The pipeline now
reports "not observed" + a lower bound (no fabricated value). The capture
protocol has been made explicit about the tilt-up pass.

## 4. Tall furniture can be read as wall
Wall detection uses points 1.2-1.9 m above the floor. A fridge or wardrobe
against a wall produces a notch in the room polygon (its front face reads
as the wall). Distinguishing furniture from wall needs the ceiling
(walls reach it, furniture doesn't) — available only when the ceiling was
captured.

## 5. Door width ambiguity
Doorways are measured jamb-to-jamb at the room cut, using surfaces 0.3-1.9 m
high within 12 cm of the cut. An open door leaf at the hinge side can be
taken as the jamb (width under-read by the leaf thickness, ~3-4 cm). Closed
doors are not detected (no see-through). Mirrors can appear as openings
(reflections land "behind" the wall); unconfirmed openings into unvisited
space are labelled `opening_unconfirmed`, not `door`.

## 6. Damage detection is a heuristic
Classical CV (dark low-saturation blobs, thin meandering dark lines), with
surface assignment through depth, metric extent, multi-view de-dup and
straight-line / skirting filters. False-positive funnel on the sample
captures (no staged damage): 40->6, 33->1, 63->2 regions. Not validated on
real damage until the furnished staged-damage room is captured.

## 7. Drift correction
Yaw only (plane-anchored); does not correct translational odometry drift.
ARKit poses were already good to ~1 deg on the samples; `auto` mode keeps
the correction only when it tightens registration (applied on 2 of 3).

## 8. (fixed) RGB resolution for depth intrinsics
Now read from the video header (fallback: 2x principal point). Was a hard-coded
1920x1440 assumption; a device recording another RGB size would have
scaled every dimension.
