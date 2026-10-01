# Known limitations (live notes, feeds the technical report + fix loop)

## Wall polygon geometry — current worst gate, fix-loop candidate

Floor/ceiling height and individual wall-line detection are working
end-to-end on real captures (see commit history). The remaining weak point is
turning the set of fitted wall *lines* into a correct, closed room polygon:

- **Symptom:** enclosed floor area comes out far smaller than wall lengths
  imply on 2 of 3 sample rooms, and occasionally a near-parallel pair of
  adjacent walls produces a corner far outside the room (now guarded: such
  walls fall back to their raw RANSAC extent and are flagged with
  `n_inliers=0` rather than emitting an impossible dimension).
- **Root-cause hypothesis:** uncorrected per-frame VIO pose drift over the
  20-40s walk rotates each wall's apparent angle slightly independently, so
  walls that are physically parallel/perpendicular in the real room don't
  fit as exactly parallel/perpendicular. A Manhattan-direction snap
  (implemented, `_snap_to_manhattan_directions`) corrects most of this but
  not all of it — some adjacent walls still end up snapped to directions
  that produce degenerate (near-parallel) corner intersections.
- **Planned fix (formal Part 4 declaration to follow once ground truth is in
  hand):** replace snap-then-intersect with a joint least-squares polygon
  fit — solve for one global rotation offset per detected room (not per
  wall) plus per-wall offsets simultaneously, constrained to the dominant
  Manhattan directions, minimizing total inlier-to-line distance across all
  walls at once rather than line-by-line. This is standard practice for
  indoor Manhattan-world reconstruction and should remove the per-wall
  independent-rotation error rather than patching around it wall-by-wall.
- **What this means for today's numbers:** wall-length and opening-position
  outputs for a given wall are individually reasonable (large inlier counts,
  plausible lengths within one room), but polygon-derived floor area is not
  yet trustworthy and confidence intervals downstream should treat it as
  such until the fix above ships.

## Photo/video tier SfM — not yet usable, root cause identified

`reconstruction/sfm.py` implements classical frame-to-frame structure-from-
motion (ORB + essential matrix + triangulation) so the photo/video tiers can
reuse the same `room_fit.py` single-room fitter the LiDAR tier uses. First
test run (8s trimmed video, 20 frames, 14 pairs matched, 1749 points
triangulated) produced a point cloud with a y-range of roughly -28m to +79m
— nonsensical for a single room.

**Root cause:** `cv2.recoverPose` returns a *unit-norm* translation for each
consecutive pair (monocular pose recovery has no absolute scale). Chaining
several such unit-scale hops end-to-end (`T_cum = T_cum @ inv(T_i1_i)`)
implicitly treats every pair's motion as the same physical distance, which
it isn't — inter-frame motion varies with how fast the phone was moving, so
the chained trajectory's scale drifts arbitrarily and compounds with every
hop. This is a known, textbook failure mode of naive monocular VO chaining;
the standard fix is to resolve each new pair's scale against points already
triangulated and tracked from the previous pair (shared-track depth-ratio
scale propagation), not to chain unit vectors directly.

**Status:** not fixed in this build — deliberately deprioritized in favor of
the benchmark harness, fix-loop, compliance matrix, and report, which cover
more of the scoring weight (60% combined) than deepening this one component
further would. Flagged here as the clear next engineering task, and as a
second, real candidate for the formal Part 4 fix-loop entry if the LiDAR
polygon-geometry fix lands cleanly and there's time for a second pass.

## Other open items

- Depth/RGB intrinsic scale factor (`ASSUMED_RGB_SHAPE` in
  `reconstruction/backproject.py`) is a documented assumption (1920x1440),
  not read from per-device metadata — fine for the sample captures (all the
  same resolution), needs validation against the walk-in test device before
  the defense.
- Mirror/glass/reflective-surface rejection is a single radius-based 3D
  outlier filter today; real properties with more aggressive reflections
  (the brief's stated hazard) may need a view-consistency check across
  multiple frames instead.
- No multi-room stitching or drift-accountability ablation yet (next).
