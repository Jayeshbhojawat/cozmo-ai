# Compliance Matrix

✅ done and tested on real captures · 🟡 implemented, not yet scored against ground truth · ❌ missing

| # | Requirement | Where | Status |
|---|---|---|---|
| 1 | Capture route (Route 2 one-page protocol) | `docs/capture_protocol.md` | ✅ |
| 2 | Device matrix | `docs/device_matrix.md` | ✅ |
| 3 | LiDAR tier: depth + poses + intrinsics -> plan | `capture/`, `reconstruction/backproject.py`, `reconstruction/layout.py` | ✅ runs on all 3 captures (23-46 s) |
| 4 | Video tier | primary: `capture/spectacular.py` + `reconstruction/video_posed.py` (Spectacular Rec: phone motion tracking + learned depth scaled by triangulation); fallback: `monotier.py` pivot scans | 🟡 primary runs end to end on a non-Pro iPhone 15 (2 rooms + door, ~4 min CPU), incl. damage and its own drift on/off; accuracy to be scored on the measured home. Fallback measured +-11 %/length RMS (gate 3 %: not met) |
| 5 | Photo tier incl. whole-property stitch from per-room folders | `reconstruction/monotier.py` (doorway-matching placement), `pivot.py` | 🟡 runs end to end (10 s for 2 rooms); same accuracy; stitching tested on synthetic rooms only |
| 6 | Per-room plan: walls, ceiling height, floor area, openings | `reconstruction/layout.py` | 🟡 all produced; ceiling reported as "not observed" when the capture never saw it |
| 7 | Stitched multi-room plan with correct adjacency | `layout.py` (rooms, doorway cuts, adjacency) | 🟡 3/5/6 rooms recovered with door-based adjacency; adjacency not yet checked against the real floor plans |
| 8 | Per-surface damage regions, class + metric extent | `damage/detect.py` | 🟡 LiDAR and posed-video tiers (photo tier: none yet); lifted through depth onto the actual wall/floor/ceiling; heuristic detector, unvalidated on real damage |
| 9 | Concealed-damage flags with the rule that fired | `damage/detect.py` (`RULES`) | ✅ rule id + text in output |
| 10 | Scope line items keyed to surfaces | `cli/run.py` (`_scope`) | ✅ |
| 11 | Confidence interval on every measurement | `reconstruction/confidence.py`, `layout.py` | 🟡 95% CI everywhere; model-based until calibrated |
| 12 | One command per capture | `python -m cli.run capture ...` | ✅ |
| 13 | JSON to published schema | `schema/capture_schema.json`, `tests/test_pipeline_outputs.py` | ✅ every output validated in tests |
| 14 | Rendered plan | `reconstruction/render.py`; `benchmark/results/plans/*.png` | ✅ |
| 15 | Benchmark: multi-room capture (3+ rooms + connector) | `1a8384c3f6` (5 rooms), `c7d28f72c6` (6 rooms) | ✅ captured |
| 16 | Benchmark: furnished room with staged damage, 2 classes | — | ❌ needs a capture |
| 17 | Benchmark: same rooms at all 3 tiers | `benchmark/run_all.py` | 🟡 video + photo + fallback video of the same 2 measured rooms (capture pending); LiDAR tier impossible: no Pro phone available |
| 18 | Benchmark: one room captured twice (repeatability) | `benchmark/run_all.py` (keyed by tape-sheet wall letters) | 🟡 3 Spectacular walks of the same rooms planned; tooling verified on sample data |
| 19 | Laser/tape ground truth on everything | tape sheet (walls A, B, C... clockwise) -> `benchmark/sheet.py` maps it onto any plan automatically (360/360 rooms in stress test) -> `benchmark/ground_truth.py score` | ❌ measurements not taken yet |
| 20 | Opening-width gate (missed/phantom count) | `benchmark/gates.py`, `benchmark/ground_truth.py` | 🟡 scorer done + tested; needs #19 |
| 21 | Ceiling + repeatability gates | same | 🟡 needs #18, #19 |
| 22 | Drift accountability + on/off ablation | `reconstruction/drift.py`, `benchmark/drift_ablation.py`, `benchmark/results/drift_*` | ✅ ablation on all 3 captures; footprint error vs truth needs #19 |
| 23 | Photo-tier whole-property stitch gate | `benchmark/gates.py` | ❌ needs #17 + #19 |
| 24 | Head-to-head vs consumer app (2 rooms) | `docs/known_limitations.md` #9 | ❌ not possible on the available device: Polycam room mode needs LiDAR, magicplan scan failed on the iPhone 15; compared against tape only |
| 25 | Fix loop: declaration, root cause, shipped fix, before/after | `docs/fix_loop.md`, `benchmark/fix_loop.py`, `benchmark/results/fix_loop/` | 🟡 regenerable before/after on 3 captures; gate number needs #19 |
| 26 | Process evidence | `git log`, pushed to GitHub as work progresses | ✅ |
| 27 | Technical report <= 6 pages | `docs/technical_report.md` | 🟡 |
| 28 | Reproduction bundle | `README.md`, `requirements.txt`, scripts above | 🟡 raw captures shipped separately (too large for git) |
| 30 | Live defense preparation | `docs/design_decisions.md` | ✅ |
| 29 | Mirrors, glass, wet-look, low light covered | `known_limitations.md` #5, layout opening rules | 🟡 handled for openings; not stress-tested |

## What needs a person with a phone and a tape

The ❌ rows are data collection, not code. With a non-Pro iPhone 15:
2 measured rooms connected by a door, 3 Spectacular Rec walks, one photo
set, one stock-Camera clip, one staged-damage spot (tea stain + pencil
"crack" on paper taped to a wall), and the tape sheet. Then
`python -m benchmark.run_all --capture-dir <dir> --sheet <sheet.json> --out benchmark/results/home`
regenerates every benchmark number.
