# Design decisions — defense sheet

For the live defense (tools closed). Each entry: what was chosen, what was
rejected, the evidence, and the honest weak spot. Read top to bottom once;
the numbers in **bold** are the ones worth remembering.

---

## 1. Route 2: a stock capture app instead of a custom iOS app
**Chose:** StrayScanner (LiDAR tier), Spectacular Rec (video tier), the
stock Camera app (photo tier and fallback video).
**Rejected:** writing a custom ARKit app.
**Why:** 24 hours. A custom app means Xcode, signing, TestFlight and a
device to test on; none of that improves the measurements. The sample data
was already in StrayScanner's export format, so the pipeline could be built
and tested from hour one.
**Weak spot:** StrayScanner refuses to run on non-Pro iPhones (no LiDAR).
That is why the video tier moved to Spectacular Rec.

## 2. One command per capture, one pipeline shared by the tiers
`python -m cli.run capture --input X --tier lidar|video|photo --out Y`.
Every tier ends as "3D points in a world where +y is up", then the same
layout code finds floor, walls, rooms, doors and ceilings. Only the way the
points are produced differs:
- LiDAR: phone depth map + phone pose.
- Video (Spectacular Rec): learned depth + phone pose from video and
  motion sensors.
- Photo / fallback video: learned depth + orientation from the room's own
  walls, scale from camera height.
**Why:** one layout implementation to debug and benchmark, not three.

## 3. The bug that mattered: the camera convention (fix loop)
**What happened:** the first version put the floor *above* the camera
(**-0.15 to -0.24 m**) and found 0-1 rooms per capture. StrayScanner's
poses are already in the OpenCV convention (x right, y down, z forward); I
applied ARKit's convention on top, flipping every point through the camera.
**Fix:** one sign. After it: floor **1.40-1.46 m** below the camera
(chest height), registration **2.6-5.6x** tighter, rooms 1→3, 0→5, 0→6.
**What I got wrong first:** I blamed polygon ordering, then "heading drift"
(wall angles smeared over 25-36°). Both were symptoms. The post-mortem is
kept in `docs/fix_loop.md` on purpose.
**Lesson:** check the cheapest physical fact first ("is the floor below
the camera?"). That check is now in `benchmark/fix_loop.py`, and the bug is
reproducible with `COZMO_CAMERA_CONVENTION=arkit`.

## 4. How rooms are found (layout)
1. **Floor** = the biggest peak in the height histogram of points.
2. **Plan orientation** = the angle at which wall points line up most
   sharply when projected (most homes are rectilinear).
3. **Free space** = 2D grid (**5 cm** cells); rays from the camera to each
   wall point mark the cells in between as empty.
4. **Rooms** = the free space split at narrow necks (doorways) with a
   watershed. Rooms sharing a long open boundary (> **1.3 m**) are merged
   (open-plan).
5. **Walls** = each room outline simplified to straight, right-angled
   segments, then each segment moved to the *measured* wall position (1 cm
   histogram of the real points, median).
**Rejected:** RANSAC line fitting per wall (first version) — it fragmented
on furniture and was unstable on short walls.
**Weak spot:** a tall wardrobe against a wall reads as the wall.

## 5. Doors and openings
Doors are measured where two rooms meet: jamb to jamb, using surfaces
0.3-1.9 m high within 12 cm of the cut. Openings where you can see
"through" a wall into unvisited space are labelled `opening_unconfirmed`,
not door — a mirror can do that too.
**Weak spot:** closed doors are invisible (nothing to see through), and an
open door leaf can be taken for the jamb (width a few cm short).

## 6. Ceiling: report "not observed" instead of guessing
In 2 of the 3 samples nobody tilted the phone up; there are **no points
above ~2 m**. The pipeline then reports a *lower bound* (H ≥ x) and says
"ceiling not observed", rather than inventing 2.4 m. The protocol now has a
mandatory tilt-up.
**Why:** a wrong number with a tight interval is worse than an honest gap.

## 7. 95% interval on every number
- LiDAR: from a model — scatter of the points on each wall, plus **4 mm**
  per-surface LiDAR bias, plus **0.3%** scale, plus 3 cm for walls never
  seen. Walls come out around **±6-14 mm**.
- Photo/video: **±22% per length** (±44% area), set from *measured* error
  of those tiers against LiDAR (room area error RMS **22%** on 5 rooms).
- Calibration check: the share of tape values that fall inside the
  interval should be about 95%. If it is lower, the intervals are widened
  by a single factor (`LIDAR_SIGMA_INFLATION`) and the report says so.

## 8. Drift: correct only when it provably helps (ablation)
**Method:** walls are straight and at right angles, so they give an
absolute heading reference. Per 8 s chunk, the angle between the chunk's
walls and the plan axes is the heading error; it is smoothed and removed.
**Accept rule (`--drift auto`):** keep the correction only if wall points
register more tightly with it (fewer 5 cm voxels).
**Results:** accepted on 2 of 3 captures (footprint +1.2%, +2.1%); rejected
on the 162 s walk (it made registration 17% worse).
**Why not always on:** "poses as-is" fails the brief, but so does a
correction that makes things worse. The ablation shows both arms.
**Weak spot:** heading only; it does not fix position drift.

## 9. Video tier: phone motion tracking (Spectacular Rec)
**Problem:** a plain video has no scale and no camera path. My own
feature tracker (ORB + PnP) got **0.4°** per step but got lost on blank
walls (only **24-73** keypoints per frame) and never recovered.
**Chose:** Spectacular Rec records video *and* the accelerometer/gyro. The
Spectacular AI SDK turns that into a metric camera path (the accelerometer
gives real metres; the gyro bridges blank walls). Disclosed: free for
non-commercial use.
**Depth per frame:** Depth Anything V2 (small, indoor, ONNX). Its scale is
wrong by ~25-30%, so each frame's scale is fixed by triangulating points
against neighbouring frames whose poses are known.
**Why not StrayScanner's video + poses:** measured a timing mismatch
between its RGB and poses (2-4 px reprojection, scale biased 12-18%);
Spectacular's poses are computed *from* the frames, so in sync
(0.24-0.69 px).
**Weak spot:** no Apple Silicon build of the SDK → Docker on Mac.

## 10. Photo tier and fallback video: turn on the spot
**Why turning, not walking:** without motion sensors there is no reliable
camera path, but if the feet stay put the camera only rotates. Rotation is
recovered from the room's own walls (surface normals), scale from camera
height (chest ≈ **1.42 m**).
**Rooms stitched** by matching door widths between rooms and placing them
on opposite sides of a 15 cm wall, rejecting overlaps.
**Honest number:** ±11% per length RMS — **does not meet** the 8% / 3%
gates. Kept because the brief requires the tier, and the intervals say so.

## 11. Damage detection
Classical computer vision: dark, low-saturation blobs (stains) and thin
dark meandering lines (cracks), placed on a wall/floor/ceiling through
depth so each region has a real size in m². Must be seen in **≥ 2 views**;
straight lines and skirting boards are filtered.
False-alarm funnel on the clean samples: **40→6, 33→1, 63→2**.
Rules: stain at wall base (WS-BASE), on ceiling (WS-CEIL), long crack
(CR-LONG), crack at a door/window corner (CR-OPEN) → scope items.
**Weak spot:** not validated on real damage.

## 12. Testing and honesty
- 21 unit tests, including tests for the gate logic itself (a phantom door
  counts as a miss).
- Ground-truth sheets + scorer: `benchmark/ground_truth.py`.
- Every limit is listed in `docs/known_limitations.md`, ranked by impact.
- Head-to-head: no Pro phone and magicplan's scan did not work on the
  iPhone 15 → compared against tape only, stated openly.

---

## 13. What the tape said (measured home, iPhone 15)
2 rooms (3.05 × 6.25 m, 3.05 × 3.35 m), one 92 cm door. **Video (3 walks):**
2/2 rooms every time, footprint **−5 … +18 %**, but walls **7-36 %** off
(gate 3 %), doors **0 %** within 2 cm, ceilings **10-33 cm** off, **0/8**
walls repeatable. **Photo:** room 2 area **+6 %**, room 1 only partly
built. Say it plainly: the learned-depth tiers find the rooms but do not
measure them to spec.

## 14. Fix loop 2: the layout broke on learned depth
Before: 1/2/0 rooms, camera "0.5 m above the floor" (impossible). I looked
at the raw points from above (`benchmark/debug_topdown.py`): both rooms were
clearly there, so the data was fine and the layout was wrong. Three LiDAR
assumptions broke:
1. floor = biggest flat surface → it was the bed. Fix: search only
   0.9-1.9 m below the camera path.
2. a cell with 2 points = wall → learned depth sprinkles points everywhere.
   Fix: a cell is wall only if it stops rays (hits ≥ 5 % of rays through it).
3. smeared door jambs → door looked too wide to split rooms. Fix: 1.4 m
   doorway threshold for video.
After: 2/2/2 rooms, footprint 34.5/31.7/27.7 m² vs 29.3.
**Honest caveat:** I chose 0.05 and 1.4 m on the same home I scored.

## 15. A fix I rejected because the tape said no
Per-frame scale refinement made walls 10 % *sharper* but wall error
*worse* and split one walk into 3 rooms. Sharper is not more accurate; I
let the measurement decide and did not ship it.

## 16. Intervals: widened when the tape proved them wrong
At ±22 % only 18 of 32 video tape values were inside the "95 %" interval.
I reset the width to the measured 95th-percentile error (±58 % video,
±45 % photo) and found door widths were wrongly using the LiDAR ±1 cm.
Coverage now 25/32. The rest are walls broken into fragments — a shape
failure, not something a wider interval should hide.

## 17. Fix loop 3 — the one to defend (docs/fix_declaration.md)
**Order, provable from git:** declaration with prediction committed
(`3f602b9`) → fix shipped (`a997d09`) → measured (`8feb70c`).
**Gate:** video walls ±3 %, 4/24 walls within. **Hypothesis:** smeared
depth makes notches; notches split real walls into pieces.
**Discipline:** developed on walk 1 only; walks 2-3 held out.
**Prediction:** 5-8/16 held-out walls within 3 %. **Measured:** 2/16 —
wrong. **Why:** the real problem on walks 2-3 was room 1 merged with the
passage; and the old fragmented outline had *flattered* the score because
the matcher could pick lucky pieces. Say this plainly: the held-out split
is what caught it.

## 18. Path doorways — the post-mortem's next fix
A door is where *you walked through* a narrow gap. Along the camera path I
measure free-space width straight across the walking direction (left +
right, not distance to the nearest wall — that would fire every time you
walk near a wall). A dip below 1.3 m with ≥ 0.5 m wider on both sides = a
doorway; the cut is that cross-section. Result: walk 1 median wall error
**2.9 %**, 4/8 walls within 3 %; overall 6/24 (from 4/24). Gate still fails.
Weak spot: needs the capturer to walk through each door (the protocol says so).

## 19. Mac walk-in plan
Only the pose step needs the x86 SDK → Docker for that step only
(`scripts/run_video_mac.sh`), everything else native. LiDAR and photo tiers
are native. Caches make the benchmark replay deterministic; the live path
ignores them when they are absent.

## More likely questions
- *Why didn't you hit 3 %?* Each frame's depth scale is uncertain by about
  ±18 %; on blank walls nothing pins it down. Walls smear over ~30 cm.
- *What would you do next?* Tell the user to stay 1-2 m from walls; fit wall
  planes across frames and solve each frame's scale against them; use a
  multi-view depth model; with a Pro phone, LiDAR.
- *Why trust anything here?* Every number regenerates with one command, the
  before arm of each fix is switchable, and the failures are in the report.

## Likely questions, short answers (original)
- *Why is LiDAR the most accurate?* It measures distance directly; the
  others estimate it from images.
- *What would you do with one more week?* A small custom ARKit capture app
  (depth + pose on Pro, pose on non-Pro), a learned multi-view depth model
  for photos, and calibrate all intervals on 10+ measured rooms.
- *Where does it fail?* Ceiling not filmed; tall furniture; closed doors;
  mirrors; photo/video scale.
- *How do you know the intervals are right?* Only from the tape
  comparison — coverage is reported per tier, and if it is low the
  intervals are widened and that is written down.
- *What did AI tools do?* Wrote much of the code with me; the decisions,
  the protocol, the captures and the debugging direction are mine to
  defend — this sheet is that defense.
