# Cozmo AI — Technical Report

*24-hour build. Status is reported honestly throughout; `docs/compliance_matrix.md`
is the authoritative per-requirement status table this report summarizes.*

## 1. Architecture

One pipeline, three entry points (tiers), one shared core:

```
capture/loader.py        parse odometry.csv + camera_matrix.csv -> per-frame
                          pose (position + quaternion) + intrinsics (fx,fy,cx,cy)

[LiDAR tier]                              [Photo/video tier]
reconstruction/backproject.py             reconstruction/sfm.py
  depth(mm,16-bit) + confidence(0/1/2)      ORB features -> essential matrix
  -> per-frame world-space point cloud,     -> triangulation -> sparse
  confidence-filtered                       world-space point cloud
        \                                  /
         \                                /
          v                              v
            reconstruction/room_fit.py
            (shared single-room fitter: floor/ceiling height via
             histogram+percentile, walls via iterative RANSAC + Manhattan-
             direction snap + line-intersection polygon, openings via
             along-wall vertical-coverage gaps)
                          |
          +---------------+----------------+
          |                                |
stitching/stitch.py                damage/detect.py
(multi-room placement,             (heuristic per-surface
 drift correction)                  damage + concealed flags)
          |                                |
          +---------------+----------------+
                          v
          reconstruction/confidence.py (CI on every measurement)
                          v
          cli/run.py -> schema/capture_schema.json + rendered PNG
```

The design goal was one fitter (`room_fit.py`) shared across all three
tiers: LiDAR and SfM both produce a world-space point cloud (x, y-up, z);
everything downstream of that point cloud — floor/ceiling, wall RANSAC,
Manhattan snapping, opening detection, polygon construction — is tier-
agnostic. Only the *path to a point cloud* differs by tier.

## 2. Tier design and device matrix

See `docs/device_matrix.md` for the full table. Summary: LiDAR tier uses
StrayScanner (Route 2 — see `docs/capture_protocol.md` for why Route 2 was
chosen: the provided sample data was already in StrayScanner's export
format, and a 24-hour budget doesn't afford building and distributing a
custom iOS app). Photo and video tiers use the stock Camera app and reuse
the LiDAR tier's room fitter via classical SfM instead of depth sensing.

**Status, honestly:** LiDAR tier is implemented and tested end-to-end on
real captures. Photo/video tiers are scaffolded but blocked on a scale-
chaining bug in the SfM module (Section 5).

## 3. Drift handling

Two separate drift problems showed up, at two different scales:

**Within a single room's walk** (seconds-to-tens-of-seconds scale):
uncorrected VIO heading drift smears wall angles continuously across the
capture rather than jumping between a few fixed values — diagnosed directly
by dumping raw RANSAC wall-line angles pre-correction (`docs/known_limitations.md`),
which showed a 25-36° continuous band on one sample room rather than two
clusters ~90° apart. The shipped mitigation (`_snap_to_manhattan_directions`
in `reconstruction/room_fit.py`) assumes a small number of discrete
direction clusters and, as the fix-loop before/after shows
(`docs/fix_loop.md`), both helps (one room's self-intersecting polygon
resolved) and over-merges (two rooms lost real wall identity) depending on
how well that assumption holds. The architecturally correct fix — a joint
least-squares fit solving for a smooth rotation-drift model rather than
discrete clusters — is scoped but not yet implemented.

**Across a multi-room capture** (the required ablation): `stitching/stitch.py`
implements `correct_drift_repeated_rooms`, a plane-anchored correction —
when the same physical room is captured twice (the repeatability-gate
requirement), the second pass is rigidly aligned to the first via a
least-squares fit over wall midpoints (Kabsch/SVD), and that correction
propagates to anything stitched relative to the second pass. This is
implemented and unit-tested on synthetic rooms (`stitching/stitch.py`'s
module docstring documents the method); the required on/off ablation
against real ground truth is not yet run because the benchmark set
(`docs/compliance_matrix.md` #16) doesn't yet include a real repeat capture.
"Poses used as-is" is explicitly *not* what happens here — both the
`correct_drift_repeated_rooms` path and a no-op identity path are available,
which is what the ablation needs to compare.

## 4. Error budget and calibration analysis

`reconstruction/confidence.py` is the single place every confidence
interval is computed. Policy: LiDAR-tier base interval (1.0cm) is set just
inside the ceiling-height gate (1.5cm), not derived from a measured error
distribution — honestly, this is a *prior*, not a calibration, because no
ground truth has been collected yet (`docs/compliance_matrix.md` #16 again
is the blocker). Two things do adjust the interval based on real signal
already: (1) walls with fewer than 500 RANSAC inlier points get a 2.5x
wider interval (thin support, independent of tier), and (2) walls flagged
`trusted: false` by the degenerate-corner guard get an 8x wider interval
rather than a tight one around a number known to be unreliable. Photo/video
tier intervals scale with wall length at the tier's stated percentage (8%
photo, 3% video, per Part 2), which is itself a prior pending calibration.

**What real calibration requires and doesn't exist yet:** laser/tape ground
truth across the benchmark set, binned by tier and by inlier-support bucket,
to replace the prior above with a measured curve. This is the single
highest-value next step for the whole report's credibility, ahead of
further algorithm work — Part 2 is explicit that "confident garbage on thin
input caps your score," and right now these intervals are honest priors,
not measured calibration.

## 5. The fix-loop story

Full declaration in `docs/fix_loop.md`; summary here. The worst
self-diagnosed problem (no ground truth yet, so this is an internal-
consistency diagnosis, not a gate failure against real measurements): wall
polygons were self-intersecting, producing areas absurdly small relative to
their own wall lengths (8 walls of 11-13m enclosing 12m²). Root cause:
nearest-endpoint polygon chaining on noisy RANSAC segments doesn't guarantee
a simple polygon. Fix: angle-sort walls around the point cloud centroid
(guaranteed non-self-intersecting, since a room is star-shaped around its
own interior) and set corners via exact line-line intersection instead of
raw noisy endpoints, with a guard that flags (rather than silently emits) a
degenerate near-parallel corner. Measured result across all 3 sample rooms:
one clear improvement, two regressions from a side effect (the Manhattan
snap bundled into the same fix over-merged walls on rooms where wall-angle
drift was continuous rather than discrete). Reported as "meaningful
movement short of the gate," per Part 4's own scoring language, with the
regression's root cause traced further (Section 3) rather than hidden.

A second, real SfM bug was found and documented but *not* shipped as the
formal fix-loop entry (`docs/known_limitations.md`): monocular pose chaining
in `reconstruction/sfm.py` uses `cv2.recoverPose`'s unit-norm translations
directly, which drifts scale catastrophically when chained across frames
(a y-range of -28m to +79m on an 8-second test clip). Root cause is
identified (needs shared-track depth-ratio scale propagation between
consecutive pairs, the standard incremental-SfM fix) but not implemented —
deliberately deprioritized against breadth (benchmark harness, compliance
matrix, this report) given the 24-hour budget, per the scoring weights
(compliance 10% + fix loop 25% + benchmark accuracy 15% + head-to-head 10%
= 60%, versus one more tier's accuracy).

## 6. Known failure modes

In priority order (highest-impact first), all also in
`docs/known_limitations.md`:

1. **Wall-polygon geometry** is not yet reliable across all room shapes —
   works better on rooms with a genuine, strong bimodal wall-angle
   distribution; degrades on rooms with continuous angle drift or weak
   support for one wall direction (e.g. a narrow/galley-shaped capture that
   barely turns).
2. **Photo/video tiers are non-functional** pending the SfM scale-chaining
   fix described above. Nothing downstream of point-cloud generation needs
   to change once that's fixed — `room_fit.py` already accepts a point
   cloud from either source.
3. **Damage detection is a classical-CV heuristic**, not a trained model:
   HSV-threshold blob detection for water stains, Canny-edge aspect-ratio
   filtering for cracks. Functional and produces classed, metric-scale
   (if roughly so) regions with concealed-damage flags, but noisy on
   cluttered real scenes (dark cabinet shadows read as water-stain
   candidates on the sample kitchen capture) — the extent numbers carry
   deliberately wide confidence intervals to reflect this rather than
   claiming false precision.
4. **No measured calibration** — every confidence interval in the system is
   currently a documented prior, pending the benchmark set and ground
   truth described in `docs/compliance_matrix.md` #16.
5. **Depth/RGB intrinsic scale factor** (`ASSUMED_RGB_SHAPE` in
   `reconstruction/backproject.py`) is a documented constant (1920x1440),
   not read per-device — correct for the sample captures, unverified
   against the walk-in test device.
6. **Mirrors/glass**: handled today by a single radius-based 3D outlier
   filter. Functional (it's part of what unblocked plausible ceiling-height
   numbers — see `room_fit.py`'s `_reject_far_outliers`), but a real
   mirror/glass-aware filter (view-consistency across frames) would be more
   robust than a fixed radius cutoff.

## 7. What's not in this build yet

Per `docs/compliance_matrix.md`: the required benchmark set (multi-room 3+
rooms with a connector, a furnished room with staged damage across 2+
classes, a repeat capture, all at all 3 tiers, with laser/tape ground
truth), the head-to-head comparison against a consumer app, and the formal
(ground-truth-backed) versions of the gates in `benchmark/gates.py` — that
module's gate *logic* is implemented and unit-tested
(`tests/test_gates.py`), but has nothing real to score against yet.
