# Cozmo AI — Technical Report

Phone capture → dimensioned, stitched floor plan with damage, scope and a
95 % interval on every number. This report states what was built, what was
measured against tape, and where it fails. Per-requirement status:
`docs/compliance_matrix.md`; ranked failures: `docs/known_limitations.md`;
design choices with evidence: `docs/design_decisions.md`.

**Headline.** The LiDAR tier recovers multi-room plans with doors and
ceilings on all three sample walkthroughs, but has no tape ground truth
(no Pro iPhone was available to capture a measured home). The video and
photo tiers were scored on a tape-measured 2-room home captured with a
non-Pro iPhone 15: they recover the rooms and the footprint to within
−5 … +18 % (video) but **miss every per-wall, door and ceiling gate**; their
95 % intervals were re-calibrated on that home to stay honest.

## 1. Architecture

```
capture/            StrayScanner export (LiDAR) | Spectacular Rec recording (video+IMU) | photos / clip
  └─ world points   LiDAR depth      | learned depth, scaled per frame | learned depth, pivot scans
     (OpenCV camera convention, world +y up, metric)
reconstruction/drift.py    plane-anchored heading correction, kept only if walls register tighter
reconstruction/layout.py   floor → plan orientation → ray-carved free space → watershed at
                           doorways → rectilinear rooms, walls re-fit to points → doors
                           jamb-to-jamb → per-room ceiling or "not observed" + lower bound
damage/detect.py           2D stain/crack candidates → lifted through depth onto a wall/floor/
                           ceiling → metric extent → ≥2 views → concealed-damage rules → scope
cli/run.py                 one command per capture → plan.json (schema) + plan.png
benchmark/                 tape sheet → automatic wall matching → gates, repeatability,
                           drift on/off, calibration → report.md (one command)
```

Every tier ends in the same representation (metric points, y up), so one
layout, damage and scoring implementation serves all three.

## 2. Tiers and devices

| tier | device | capture | where scale comes from |
|---|---|---|---|
| LiDAR | iPhone Pro (LiDAR) | StrayScanner, one walk | LiDAR depth + ARKit poses |
| Video | any iPhone 15+ (tested: non-Pro 15) | Spectacular Rec, one walk | visual-inertial poses (Spectacular AI SDK); Depth Anything V2 depth scaled per frame by triangulation against neighbouring posed frames |
| Video fallback | any iPhone | stock Camera clip, full turn on the spot per room | depth model + camera height prior |
| Photo | any iPhone | stock Camera, 8 stills turning on the spot per room, one folder per room | depth model + camera height prior; rooms joined by door matching |

Why Spectacular Rec: StrayScanner refuses non-LiDAR phones; my own feature
tracker reached 0.4°/step but lost track on blank walls (24-73 keypoints
per frame). Recording the IMU with the video gives metric poses that survive
blank walls. Its poses are computed from the frames, so image and pose are
in sync (0.24-0.69 px reprojection, vs 2-4 px for StrayScanner RGB).

## 3. Results on the tape-measured home

Home: room 1 3.05 × 6.25 m (bed + kitchen), room 2 3.05 × 3.35 m, one
92 cm door, ceilings 2.84 / 2.59 m, no windows. Tape readings were taken to
0.5 ft for walls (±7.6 cm, i.e. ±1.2-2.5 %) and 1 in for ceilings; this
limits how finely the gates can be scored and is stated in the sheet.
Regenerate: `python -m benchmark.run_all --capture-dir <dir> --sheet
benchmark/ground_truth/home/sheet.json --out benchmark/results/home`.

| capture | rooms (truth 2) | wall error median | walls within tier tol | door ≤2 cm | ceiling error | footprint error | 95 % coverage |
|---|---|---|---|---|---|---|---|
| video walk 1 | 2 | 20 % | 1/8 | 0/2 | 11, 33 cm | +18 % | 9/11 |
| video walk 2 | 2 | 7 % | 2/8 | 0/3 | 10, 17 cm | +8 % | 9/10 |
| video walk 3 | 2 | 36 % | 1/8 | 0/2 | 14, 20 cm | −5 % | 7/11 |
| video fallback (clip) | 1 | 10 % | 2/4 | 0/1 | not seen | — (1 room) | 4/6 |
| photo | 2 | 28 % | 1/8 | 0/2 | 13 cm / not seen | room 2 +6 %, room 1 partial | 8/10 |

Gates: video walls ±3 % — **fail**; photo walls ±8 % — **fail**; doors 2 cm
on ≥85 % — **fail** (0 %); ceiling 1.5 cm — **fail** (10-33 cm); photo
stitch footprint ±8 % — **fail** (room 1 only partly reconstructed from one
standing point in a 6.25 m room).

**Repeatability (3 video walks):** 0/8 walls within max(1 cm, 0.5 %);
ceiling spread 25 / 52 cm. The tier is not repeatable at the brief's level.

**Drift on/off (every video walk carries both arms):** footprint off / on
vs tape 29.26 m²: 34.64 / 34.49, 31.68 / 31.53, 27.73 / 32.38. The `auto`
rule (keep the correction only if walls register tighter) chose on, off,
off; on walk 3 it avoided a +11 % error (picked −5 %), on walk 2 it kept
the slightly worse arm (0.15 m² difference). Poses as-is are never used
unaudited.

**Time per capture** (2-CPU cloud box, no GPU): Spectacular walk of
100-150 s → ~2.5 min poses + ~5-8 min depth on first run, ~70 s when the
depth cache exists; photo tier 21 s for 16 photos; LiDAR 23-93 s.

**Head-to-head vs Polycam / magicplan:** not run. Polycam's room mode
needs LiDAR; magicplan's scan did not work on the available iPhone 15.
Reported as a gap rather than omitted.

## 4. LiDAR tier on the sample walks (no ground truth)

| capture | rooms | doors linking rooms | footprint | ceilings |
|---|---|---|---|---|
| c00a170fe1 | 3 | 2 | 19.8 m² | not filmed → lower bound only |
| 1a8384c3f6 | 5 | 4 | 67.7 m² | not filmed → lower bound only |
| c7d28f72c6 | 6 | 5 | 69.2 m² | 2.28-3.08 m |

Model intervals: walls ±6-14 mm, doors ±8-12 mm, ceilings ±6 mm. These
are **not validated**: no measured home exists for this tier.

## 5. Fix loops (`docs/fix_loop.md`)

**Fix loop 1 — camera convention (LiDAR).** Floor detected 0.15-0.24 m
*above* the camera; 0-1 rooms per capture. Root cause: StrayScanner poses
are already in the OpenCV convention; I applied ARKit's on top, mirroring
every point. One sign fixed it: floor 1.40-1.46 m below the camera,
registration 2.6-5.6× tighter, rooms 1→3, 0→5, 0→6. I first blamed polygon
ordering and heading drift; that post-mortem is kept. Regenerable via
`COZMO_CAMERA_CONVENTION=arkit`.

**Fix loop 2 — video layout on the measured home (has a gate number).**
Before: 1/2/0 rooms, footprint 9.1/37.1/0 m² (truth 29.3), camera
0.73/−0.08/0.59 m above the "floor", ceiling error 56 cm. Root causes, found
on the raw points: the floor histogram picked the bed/counter; ≥2-point
"wall" cells shredded free space under learned-depth scatter; smeared jambs
made the door look wider than the doorway threshold. Shipped: floor
searched 0.9-1.9 m below the camera path, occupancy ratio 0.05, doorway
1.4 m (video only; LiDAR output verified unchanged). After: 2/2/2 rooms,
footprint 34.5/31.7/27.7 m². **Tuned on the scored home — disclosed.**
Tried and not shipped: per-frame scale refinement (sharper walls, worse
wall error on the tape).

## 6. Confidence intervals and calibration

LiDAR: per-wall model (point scatter, 4 mm per-surface bias, 0.3 % scale,
3 cm for unobserved boundaries). Learned-depth tiers: a relative half-width
per tier taken from measured error. At the first setting (±22 % per length,
from pivot scans vs LiDAR) only 18/32 posed-video and 4/10 photo tape values
fell inside — over-confident. Re-set to the 95th-percentile wall error on
the home: **±58 % posed video, ±45 % photo**; door widths on these tiers had
wrongly inherited the LiDAR ±1 cm jamb sigma and now use the tier error.
Coverage after: 25/32, 8/10, 4/6. The remaining misses are walls broken
into fragments (a 6.25 m wall drawn as 2.4 m), a structural failure no
interval width fixes honestly. Same-home calibration: disclosed.

## 7. Why the learned-depth tiers fall short, and what would fix it

The fused points show both rooms clearly, but each wall is smeared over
~0.3 m: the per-frame depth scale from triangulation spreads p10-p90
0.51-0.74, and blank walls (most of this home) give the triangulation
nothing to hold. The layout then breaks long walls into fragments.
Next steps, in order of expected gain: (1) a protocol change — stay 1-2 m
from walls, which this capture did not (frames full of blank wall);
(2) plane-based fusion: fit wall planes across frames, then solve per-frame
scale against the planes rather than against sparse features; (3) a
multi-view depth model instead of single-image depth; (4) a custom ARKit
capture app so a Pro phone can feed LiDAR and a non-Pro phone at least
ARKit poses.

## 8. Damage

Classical CV (stains: dark, low-saturation blobs; cracks: thin, meandering
dark lines), lifted onto a building surface through depth, metric extent,
seen in ≥2 views, straight-line and skirting filters, rules WS-BASE,
WS-CEIL, CR-LONG, CR-OPEN → scope items. Runs on the LiDAR and posed-video
tiers (not photo). Sample walks without damage: false-alarm funnel
40→6, 33→1, 63→2. **Not validated on staged damage** (none was staged in
the measured home); the video walks report 9/5/3 regions, presumed false
alarms.

## 9. Disclosures

Depth Anything V2 ViT-S metric-indoor (ONNX, fetched by
`scripts/fetch_models.py`, checksum-verified); Spectacular AI SDK (PyPI,
free for non-commercial use; Linux/Windows x86-64 only, so a Dockerfile is
provided for Apple-Silicon Macs); StrayScanner and Spectacular Rec as stock
capture apps. AI coding assistants were used throughout; design decisions,
captures and measurements are the author's (`docs/design_decisions.md`,
commit history).
