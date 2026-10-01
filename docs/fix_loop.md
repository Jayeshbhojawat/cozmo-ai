# Fix Loop Declaration (Part 4)

**Status of this declaration: preliminary.** It's written against internal
self-consistency diagnostics (no laser/tape ground truth collected yet — see
`docs/compliance_matrix.md` #16). Once ground truth exists, this same gate
should be re-scored with real error numbers and this file updated or
superseded. What's below is a real before/after from actual commits in this
repo, not a hypothetical — the mechanism has genuinely run once already.

## 1. Worst-performing gate (self-diagnosed)

**Gate:** floor-area self-consistency — does the enclosed polygon area a
room's fitted walls form match what those same wall lengths imply?

**Failing number (before fix, commit `80c9872`):** on sample room
`c7d28f72c6`, 8 fitted walls with lengths all between 11.4m and 13.0m
(individually plausible, large RANSAC inlier support) enclosed a polygon
area of **12.01 m²**. 8 walls each 11-13m long enclosing barely more floor
area than a single 3.5m x 3.5m room is a contradiction internal to the
output itself, visible without any ground truth at all — a textbook sign of
a self-intersecting ("bowtie") polygon rather than a measurement error.

## 2. Root-cause hypothesis and evidence

**Hypothesis:** `order_walls_into_polygon` chained wall segments by nearest
endpoint distance. On noisy, RANSAC-fit wall segments whose raw endpoint
extents don't land exactly where two walls should meet, nearest-endpoint
chaining can connect segments out of their true spatial order, producing a
self-intersecting polygon. The shoelace area formula on a self-intersecting
polygon partially cancels positive and negative contributions, which
produces exactly the symptom observed: individually-plausible wall lengths,
implausibly small enclosed area.

**Evidence:** rendering the "before" polygon (`reconstruction/render.py` on
commit `80c9872`'s output) shows crossing wall segments rather than a simple
loop — visually confirming the self-intersection hypothesis, not just
inferring it from the area number.

## 3. Fix shipped and predicted number after

**Fix (commit `1ea93bd`):** replaced nearest-endpoint chaining with (a)
angle-sorting walls around the point cloud's centroid — a room is star-shaped
around its own interior, so this ordering is guaranteed non-self-intersecting
— and (b) setting each wall's endpoints to the exact line-line intersection
with its two angular neighbors, rather than trusting raw noisy segment
extents. A degenerate-corner guard was added for near-parallel adjacent
lines (falls back to the raw segment and flags it untrusted rather than
emitting a wild corner).

**Predicted number after fix:** a simple (non-self-intersecting) polygon
whose area is the same order of magnitude as wall-length-squared — i.e. no
more near-zero areas alongside 5m+ walls.

## Before / after (regenerable)

```bash
# Before:
git checkout 80c9872 -- reconstruction/room_fit.py
for room in c00a170fe1 1a8384c3f6 c7d28f72c6; do
  python -m cli.run capture --input data/samples_full/$room --tier lidar \
      --room-id r --out /tmp/before_$room --stride 4
done
# After:
git checkout HEAD -- reconstruction/room_fit.py
for room in c00a170fe1 1a8384c3f6 c7d28f72c6; do
  python -m cli.run capture --input data/samples_full/$room --tier lidar \
      --room-id r --out /tmp/after_$room --stride 4
done
```

**Actual result, all three sample rooms (measured, not predicted) — reported
honestly, including where it fell short:**

| room | before: area / n_walls | after: area / n_walls (untrusted flagged) |
|---|---|---|
| c7d28f72c6 | 12.01 m² / 8 walls, all 11.4-13.0m | **20.43 m² / 5 walls**, 2 flagged untrusted |
| c00a170fe1 | 1.33 m² / 5 walls, 5.6-6.1m | 0.0 m² / 2 walls, none flagged |
| 1a8384c3f6 | 1.37 m² / 6 walls, 9.6-10.9m | 0.78 m² / 4 walls, none flagged |

**This did not cleanly move the gate from fail to pass — it's mixed, and
here's why.** On the room that motivated the fix (`c7d28f72c6`), the
self-intersection is gone and area moved from a value absurdly small for
8 walls of 11-13m to one more consistent with a subset of those walls —
real progress, and the degenerate-corner guard correctly caught and flagged
the two walls it couldn't resolve, rather than emitting a bad number
silently (the specific failure mode targeted is fixed: no more near-zero
area hidden behind large, confidently-reported walls). On the other two
rooms, the Manhattan-direction snap this fix added (to correct per-wall
independent rotation from uncorrected pose drift) over-merged: it reduced 5
and 6 walls down to 2 and 4, losing real wall identity rather than fixing
their ordering. That's a different, newly-introduced failure mode, not the
one this declaration targeted, and it's the reason overall area didn't
improve on those rooms. `docs/known_limitations.md`'s planned next fix
(joint least-squares Manhattan fit, solved once across all walls rather
than snap-then-merge wall-by-wall) is aimed squarely at this regression.
