# Known limitations (live)

Ordered by impact on the score. Each says what is wrong, the evidence, and
what would fix it.

## 1. Photo and video tiers: working, but not accurate enough for their gates
Built on per-room pivot scans (`reconstruction/pivot.py`): learned depth
(Depth Anything V2 ViT-S, metric-indoor ONNX, fetched by script) for shape,
room orientation from surface normals (no texture needed), scale from the
chest-height camera. Measured against LiDAR on 5 pivot reconstructions:
room-area error -2, +30, -28, +32, -3.5 % (RMS 22 %). The brief's gates are
+-8 % (photo) and +-3 % (video): **not met**. Intervals are widened to the
measured error so they stay calibrated.
Why feature tracking was abandoned: plain walls/ceilings/mirrors give
24-73 ORB keypoints per frame; a free-walk PnP tracker reached 0.4 deg
per-step rotation accuracy but could not relocalise after blank-wall
moments (ATE ~1 m). Kept in `reconstruction/mono.py` (history) as evidence.
Known failure cases: tiny rooms with mirrors (phantom depth), pivots done
in a doorway (free space leaks into the next room), pivots short of a full
turn (unseen walls). Room placement uses doorway matching; rooms with no
detected opening are placed apart and reported unconnected.
Not yet tested on real protocol captures (none exist yet): the numbers
above come from natural pivots (~230 deg) inside the LiDAR walks.
Video pivot detection on that non-protocol walk (threshold lowered to 200
deg for the test): 3 windows found; one was a real turn and reconstructed
the bathroom at 2.05 x 2.23 m vs LiDAR 2.01 x 2.17 m (+2-3 %); the other two
were 28-30 s of slow heading drift accumulating, which produced garbage
rooms. Pivot windows are now capped at 20 s (protocol: a full circle in
10-15 s). At the protocol threshold (270 deg) the same walk yields 0
pivots and a clear protocol error instead of phantom rooms.

## 1b. Posed video tier (Spectacular Rec): new, unscored
Metric poses from video + motion sensors (works on non-Pro iPhones);
learned depth scaled per frame by triangulation against neighbouring posed
frames (reprojection < 2 px, parallax > 2 deg). First iPhone 15 recording
(corridor + bathroom + bedroom, not a protocol walk): 2 rooms + a door,
ceiling not seen; the corridor and bedroom merged into one L-shaped room.
No damage detection on this tier yet. Runtime ~4.5 min on CPU (depth model
over 250 frames). Needs a protocol recording + tape measurements to score.

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

## 9. Head-to-head vs a commercial app not possible on the available phone
The only capture device available is a non-Pro iPhone 15. Polycam's room
mode needs LiDAR, and magicplan's scan did not work on this phone when
tried (2026-10-02). The head-to-head therefore compares our output against
tape-measure ground truth only; the commercial-app column is reported as
"could not run on this device" rather than omitted.
