# Fix Loop (Part 4)

## Post-mortem of the first declaration (kept on purpose)

The first version of this file (commit `6d4217c`) declared polygon
self-intersection as the worst gate, blamed it on nearest-endpoint wall
chaining, and later on "continuous VIO heading drift". **Both root-cause
hypotheses were wrong.** The shipped fix (angle-sorted polygon + Manhattan
snap) improved one room and regressed two, and the "drift smear" evidence
(wall angles spread over 25-36 deg) was a symptom of the real bug below,
not drift. Measured ARKit heading drift on these captures turned out to be
~1 deg RMS (see `reconstruction/drift.py` and the drift ablation).

What went wrong in the process: every check was downstream (walls,
polygons, areas). The first upstream physical check — "is the floor below
the camera?" — would have caught it in minutes. That check is now part of
the fix-loop script.

## 1. Worst-performing gate, with the failing number

**Ceiling height** (gate: <= 1.5 cm per room). Before the fix the pipeline
reported ceilings of **1.47-1.94 m** (e.g. 1.935 m for `c00a170fe1`), and
in every capture the detected **floor was 0.15-0.24 m above the camera**,
which is physically impossible for a phone held at chest height. Every
ceiling-height result failed, by tens of cm, before ground truth was even
needed, and the same defect broke walls, rooms and openings (0-1 rooms
recovered per capture, 0 doors).

## 2. Root cause and evidence

**Root cause:** wrong camera coordinate convention in back-projection.
StrayScanner writes `odometry.csv` poses already in the OpenCV camera
convention (+x right, +y down, +z forward), as its reference viewer
StrayVisualizer does. `reconstruction/backproject.py` additionally applied
ARKit's native convention (+y up, -z forward), flipping y and z a second
time: every depth point was mirrored through the camera before being placed
in the world.

**Evidence** (`benchmark/fix_loop.py`, all 3 captures, the only difference
between arms is that sign):

| capture | floor below camera | wall-band occupied 5cm voxels | rooms | doors measured |
|---|---|---|---|---|
| c00a170fe1 | -0.17 m -> **+1.40 m** | 194,844 -> **34,969** (5.6x tighter) | 1 -> 3 | 0 -> 1 |
| 1a8384c3f6 | -0.24 m -> **+1.40 m** | 204,002 -> **78,733** (2.6x) | 0 -> 5 | 0 -> 3 |
| c7d28f72c6 | -0.15 m -> **+1.46 m** | 321,716 -> **122,425** (2.6x) | 0 -> 6 | 0 -> 4 |

Two independent physical checks agree: the floor lands at the protocol's
chest height, and the same wall seen from different frames falls in the
same voxels (2.6-5.6x fewer occupied voxels).

## 3. Fix shipped and predicted number

**Fix:** one convention change in `reconstruction/backproject.py`
(`y_cam = (v - cy)/fy * d`, `z_cam = d`). The before-arm is kept behind
`COZMO_CAMERA_CONVENTION=arkit` purely so the before run stays regenerable.
Because the corrected cloud showed the sample captures are multi-room
walkthroughs, the single-room fitter was then replaced by
`reconstruction/layout.py` (rooms, doors, per-room ceilings) — that is new
capability built on top of the fix, not part of the fix itself, and the
before/after above isolates the fix alone (both arms run the new layout code).

**Predicted after the fix:** ceiling height within the 1.5 cm gate on rooms
where the ceiling was actually observed.

**Measured so far:** ceilings are now observed and measured in 6 of 6 rooms
of `c7d28f72c6` (2.28-3.08 m, model sigma ~0.6 cm). The other two captures
never pointed at the ceiling; the pipeline now reports "ceiling not
observed" with a lower bound instead of a fake value. **The gate itself can
only be scored once laser ground truth exists** — `benchmark/ground_truth/`
has pre-filled measuring sheets for every room; scoring is one command
(`python -m benchmark.ground_truth score ...`). This file gets the measured
gate numbers when that is done; if the prediction is wrong, it says so here.

## Regenerate

```bash
python -m benchmark.fix_loop --captures data/samples_full/* --out benchmark/results/fix_loop
git show cdcbdda..d05d3c1 -- reconstruction/backproject.py   # readable diff of the fix + the before switch
```
