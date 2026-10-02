# Compliance Matrix

✅ done and tested on real captures · 🟡 implemented, not yet scored against ground truth · ❌ missing

| # | Requirement | Where | Status |
|---|---|---|---|
| 1 | Capture route (Route 2 one-page protocol) | `docs/capture_protocol.md` | ✅ |
| 2 | Device matrix | `docs/device_matrix.md` | ✅ |
| 3 | LiDAR tier: depth + poses + intrinsics -> plan | `capture/`, `reconstruction/backproject.py`, `reconstruction/layout.py` | ✅ runs on all 3 captures (23-46 s) |
| 4 | Video tier | primary: Spectacular Rec (`capture/spectacular.py`, `reconstruction/video_posed.py`); fallback: pivot clip (`monotier.py`) | 🟡 scored on the tape-measured home: 2/2 rooms on all 3 walks, footprint −5…+18 %, walls 7-36 % median error — **gate ±3 % not met** |
| 5 | Photo tier incl. whole-property stitch from per-room folders | `reconstruction/monotier.py` (HEIC supported) | 🟡 scored on the home: room 2 area +6 %, room 1 only partly reconstructed; walls 28 % median — **gate ±8 % not met** |
| 6 | Per-room plan: walls, ceiling height, floor area, openings | `reconstruction/layout.py` | 🟡 all produced; ceiling reported as "not observed" when the capture never saw it |
| 7 | Stitched multi-room plan with correct adjacency | `layout.py` (rooms, doorway cuts, adjacency) | 🟡 3/5/6 rooms recovered with door-based adjacency; adjacency not yet checked against the real floor plans |
| 8 | Per-surface damage regions, class + metric extent | `damage/detect.py` | 🟡 LiDAR and posed-video tiers (photo tier: none yet); lifted through depth onto the actual wall/floor/ceiling; heuristic detector, unvalidated on real damage |
| 9 | Concealed-damage flags with the rule that fired | `damage/detect.py` (`RULES`) | ✅ rule id + text in output |
| 10 | Scope line items keyed to surfaces | `cli/run.py` (`_scope`) | ✅ |
| 11 | Confidence interval on every measurement | `reconstruction/confidence.py` | 🟡 LiDAR: model-based, unvalidated. Video/photo: calibrated on tape (±58 % / ±45 % per length); coverage 25/32, 8/10, 4/6 |
| 12 | One command per capture | `python -m cli.run capture ...` | ✅ |
| 13 | JSON to published schema | `schema/capture_schema.json`, `tests/test_pipeline_outputs.py` | ✅ every output validated in tests |
| 14 | Rendered plan | `reconstruction/render.py`; `benchmark/results/plans/*.png` | ✅ |
| 15 | Benchmark: multi-room capture (3+ rooms + connector) | `1a8384c3f6` (5 rooms), `c7d28f72c6` (6 rooms) | ✅ captured |
| 16 | Benchmark: furnished room with staged damage, 2 classes | — | ❌ needs a capture |
| 17 | Benchmark: same rooms at all 3 tiers | `benchmark/run_all.py`, `benchmark/results/home/` | 🟡 video (3 walks) + fallback clip + photos of the same 2 measured rooms; LiDAR tier impossible (no Pro phone) |
| 18 | Benchmark: one room captured twice (repeatability) | `benchmark/results/home/report.md` | 🟡 measured: 3 walks, **0/8 walls** within max(1 cm, 0.5 %), ceiling spread 25/52 cm — fails |
| 19 | Laser/tape ground truth on everything | `benchmark/ground_truth/home/` (raw + converted sheet), `benchmark/sheet.py` | 🟡 2 rooms, walls to 0.5 ft, ceilings to 1 in, door; no LiDAR-tier ground truth |
| 20 | Opening-width gate (missed/phantom count) | `benchmark/ground_truth.py` | 🟡 scored: **0 %** of doors within 2 cm on video/photo (gate 85 %) — fails |
| 21 | Ceiling + repeatability gates | same | 🟡 scored: ceilings 10-33 cm off (gate 1.5 cm), repeat spread 25-52 cm — fail |
| 22 | Drift accountability + on/off ablation | `reconstruction/drift.py`; every video run carries both arms | ✅ ablation on 3 LiDAR samples + 3 tape-scored walks (auto avoided a +11 % error on walk 3) |
| 23 | Photo-tier whole-property stitch gate | `benchmark/results/home/` | 🟡 scored: footprint −33 % (room 1 partial) — fails |
| 24 | Head-to-head vs consumer app (2 rooms) | `docs/known_limitations.md` #9 | ❌ not possible on the available device: Polycam room mode needs LiDAR, magicplan scan failed on the iPhone 15; compared against tape only |
| 25 | Fix loop: declaration, root cause, shipped fix, before/after | `docs/fix_loop.md` (loop 2 has tape numbers), `benchmark/results/home_before` | ✅ regenerable before/after on measured ground truth; a tried-and-rejected fix also recorded |
| 26 | Process evidence | `git log`, pushed to GitHub as work progresses | ✅ |
| 27 | Technical report <= 6 pages | `docs/technical_report.md` | ✅ |
| 28 | Reproduction bundle | `README.md`, `requirements.txt`, scripts above | 🟡 raw captures shipped separately (too large for git) |
| 30 | Live defense preparation | `docs/design_decisions.md` | ✅ |
| 29 | Mirrors, glass, wet-look, low light covered | `known_limitations.md` #5, layout opening rules | 🟡 handled for openings; not stress-tested |

## Still open

LiDAR-tier accuracy against tape (needs a Pro phone), staged damage
(none was staged in the measured home), head-to-head against a commercial
app (none ran on the available iPhone 15), and the per-wall / door /
ceiling gates on the learned-depth tiers (measured and failing).
