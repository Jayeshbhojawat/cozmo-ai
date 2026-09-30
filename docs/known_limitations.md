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
