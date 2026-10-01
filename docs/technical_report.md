# Cozmo AI — Technical Report

Status is reported as-is; `docs/compliance_matrix.md` is the per-requirement
table. Numbers below are measured on the three sample LiDAR captures; gate
numbers against tape/laser are pending (sheets in `benchmark/ground_truth/`).

## 1. Architecture

```
StrayScanner export ──> capture/loader.py  (poses, per-frame intrinsics, RGB size from video header)
                   └──> reconstruction/backproject.py  depth(mm)+confidence -> world points
                              (OpenCV camera convention; world +y up)
                   └──> reconstruction/drift.py   plane-anchored yaw correction, kept only if it
                              tightens registration ("auto")
                   └──> reconstruction/layout.py
                         floor plane -> plan orientation (projection sharpness)
                         -> 2D free-space ray carving -> watershed room split at doorways
                         -> rectilinear room polygons, every wall re-fit to raw points (1 cm)
                         -> doorways measured jamb-to-jamb at room cuts; see-through openings
                         -> per-room ceiling (or "not observed" + lower bound)
                   └──> damage/detect.py   2D candidates -> lifted through depth -> assigned to
                              wall/floor/ceiling -> metric extent -> multi-view de-dup -> rules
                   └──> cli/run.py  -> plan.json (schema) + plan.png (stitched, dimensioned)
```

One continuous walk can cover a whole property: rooms, doors and adjacency
come out of the same command, already in one plan frame.

## 2. Tiers and devices

LiDAR tier: StrayScanner on any iPhone Pro with LiDAR (Route 2; the sample
data was already in its export format, and a custom iOS app was not worth
it in 24 h).

Photo and video tiers (any iPhone 15+, stock Camera) use **per-room pivot
scans** (turn on the spot in each room). Two dead ends first, both measured:
(1) Depth Anything V2's "metric" output alone is 18-30 % off in scale and
varies +-25 % per frame (vs LiDAR on our frames); its shape after per-frame
rescale is good (~9-10 % abs-rel on upright frames - and frames must be
rotated upright, which my first attempt got backwards). (2) Feature-based
PnP tracking was accurate when it worked (0.4 deg/step) but plain white
walls and ceilings give 24-73 keypoints per frame, so a free walk could not
be tracked through blank-wall moments.
What works without texture is room geometry: per-frame surface normals
give gravity and the yaw relative to the room's walls directly, so a pivot
scan registers itself; scale comes from the chest-height camera over the
floor. Measured on natural pivots inside the LiDAR walks: room area error
RMS 22 % (+-11 % per length). That does not meet the 8 %/3 % tier gates;
intervals are set from the measured error (+-22 %/length at 95 %) so the
tiers stay calibrated rather than confidently wrong. Video pivots are found
from the net signed heading change (an ordinary walk yields none, instead
of 14 phantom pivots with a peak-to-peak rule). Rooms from separate
pivots are placed by doorway matching with overlap rejection.

## 3. The bug that mattered, and what it taught

The first pipeline produced impossible geometry (floor above the camera,
1.5-1.9 m ceilings, smeared walls). I spent hours treating downstream
symptoms (RANSAC tuning, polygon ordering, a "drift" hypothesis) before an
upstream physical check exposed the cause: the back-projection applied
ARKit's camera convention to poses StrayScanner had already converted to
OpenCV's. Fixing one sign tightened registration 2.6-5.6x and put the floor
at 1.40-1.46 m below the camera on all captures (`docs/fix_loop.md`).
Lesson, now built into `benchmark/fix_loop.py`: check the cheapest physical
invariant first.

## 4. Drift handling

Rectilinear walls give an absolute heading reference: per 8 s chunk, the
residual angle between the chunk's wall directions and the plan axes is
estimated, smoothed, and the trajectory re-integrated with corrected yaw.
Measured: ARKit is already good to ~1 deg RMS here. The correction tightens
registration on 2 of 3 captures (-0.6 %, -1.8 %; the second removes a real
-3 to -4 deg offset in the first 40 s) and loosens it on the 162 s walk
(+17 %), so the default keeps it only when registration improves.
Ablation (footprint with/without): `benchmark/results/drift_*/ablation.json`;
footprint changes +1.2 % / +2.1 % / (rejected). Which arm is closer to the
truth is decided by the laser footprint.

## 5. Error budget (model; to be calibrated)

| term | 1-sigma | source |
|---|---|---|
| wall plane position | robust scatter / sqrt(n), typically < 1 mm | surface points within +-2.5 cm of the peak |
| per-surface LiDAR bias | 4 mm | Apple LiDAR literature, conservative |
| scale (pose + intrinsics) | 0.3 % of length | — |
| unobserved boundary | 3 cm | no wall evidence |
| door jamb (refined / fallback) | 4 mm / 11.5 mm | point percentile / 2 cm bin |

Wall length = quadrature of its two bounding perpendicular planes + scale
term (~6-14 mm at 95 % for observed walls). Ceiling = floor and ceiling
plane fits (~6 mm). Calibration = fraction of laser values inside the 95 %
interval (`benchmark/ground_truth.py score`); if it is well under 95 %, the
inflation factor in `confidence.py` is raised and reported.

## 6. Results so far (no ground truth)

| capture | duration | rooms | doors measured | ceilings observed | runtime |
|---|---|---|---|---|---|
| c00a170fe1 | 28 s | 3 | 1 | 0/3 | 46 s |
| 1a8384c3f6 | 87 s | 5 | 3 | 0/5 | 23 s |
| c7d28f72c6 | 162 s | 6 | 4 | 6/6 (2.28-3.08 m) | 36 s |

## 7. Known failure modes

See `docs/known_limitations.md` (ordered by impact): photo/video accuracy
(+-11 %/length) short of their gates; no ground truth yet; ceiling only measurable if the user tilts up; tall
furniture read as wall; open door leaf can shave a few cm off a door width,
closed doors missed, mirrors may appear as openings; damage detector is a
heuristic; yaw-only drift correction.
