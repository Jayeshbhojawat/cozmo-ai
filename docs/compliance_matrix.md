# Compliance Matrix

✅ done and tested on real captures · 🟡 implemented, not yet scored against ground truth · ❌ missing

| # | Requirement | Where | Status |
|---|---|---|---|
| 1 | Capture route (Route 2 one-page protocol) | `docs/capture_protocol.md` | ✅ |
| 2 | Device matrix | `docs/device_matrix.md` | ✅ |
| 3 | LiDAR tier: depth + poses + intrinsics -> plan | `capture/`, `reconstruction/backproject.py`, `reconstruction/layout.py` | ✅ runs on all 3 captures (23-46 s) |
| 4 | Video tier | `reconstruction/monotier.py` (pivot detection), `pivot.py`, `mono_depth.py` | 🟡 runs end to end; measured accuracy +-11 %/length RMS (gate 3 %: not met) |
| 5 | Photo tier incl. whole-property stitch from per-room folders | `reconstruction/monotier.py` (doorway-matching placement), `pivot.py` | 🟡 runs end to end (10 s for 2 rooms); same accuracy; stitching tested on synthetic rooms only |
| 6 | Per-room plan: walls, ceiling height, floor area, openings | `reconstruction/layout.py` | 🟡 all produced; ceiling reported as "not observed" when the capture never saw it |
| 7 | Stitched multi-room plan with correct adjacency | `layout.py` (rooms, doorway cuts, adjacency) | 🟡 3/5/6 rooms recovered with door-based adjacency; adjacency not yet checked against the real floor plans |
| 8 | Per-surface damage regions, class + metric extent | `damage/detect.py` | 🟡 lifted through depth onto the actual wall/floor/ceiling; heuristic detector, unvalidated on real damage |
| 9 | Concealed-damage flags with the rule that fired | `damage/detect.py` (`RULES`) | ✅ rule id + text in output |
| 10 | Scope line items keyed to surfaces | `cli/run.py` (`_scope`) | ✅ |
| 11 | Confidence interval on every measurement | `reconstruction/confidence.py`, `layout.py` | 🟡 95% CI everywhere; model-based until calibrated |
| 12 | One command per capture | `python -m cli.run capture ...` | ✅ |
| 13 | JSON to published schema | `schema/capture_schema.json`, `tests/test_pipeline_outputs.py` | ✅ every output validated in tests |
| 14 | Rendered plan | `reconstruction/render.py`; `benchmark/results/plans/*.png` | ✅ |
| 15 | Benchmark: multi-room capture (3+ rooms + connector) | `1a8384c3f6` (5 rooms), `c7d28f72c6` (6 rooms) | ✅ captured |
| 16 | Benchmark: furnished room with staged damage, 2 classes | — | ❌ needs a capture |
| 17 | Benchmark: same rooms at all 3 tiers | — | ❌ needs protocol photo folders + a protocol video of the LiDAR-captured home |
| 18 | Benchmark: one room captured twice (repeatability) | — | ❌ needs a capture |
| 19 | Laser/tape ground truth on everything | `benchmark/ground_truth/*.json` (pre-filled sheets), `benchmark/ground_truth.py score` | ❌ sheets ready, measurements not taken |
| 20 | Opening-width gate (missed/phantom count) | `benchmark/gates.py`, `benchmark/ground_truth.py` | 🟡 scorer done + tested; needs #19 |
| 21 | Ceiling + repeatability gates | same | 🟡 needs #18, #19 |
| 22 | Drift accountability + on/off ablation | `reconstruction/drift.py`, `benchmark/drift_ablation.py`, `benchmark/results/drift_*` | ✅ ablation on all 3 captures; footprint error vs truth needs #19 |
| 23 | Photo-tier whole-property stitch gate | `benchmark/gates.py` | ❌ needs #17 + #19 |
| 24 | Head-to-head vs consumer app (2 rooms, LiDAR) | — | ❌ needs a free-tier Polycam/magicplan export of 2 rooms |
| 25 | Fix loop: declaration, root cause, shipped fix, before/after | `docs/fix_loop.md`, `benchmark/fix_loop.py`, `benchmark/results/fix_loop/` | 🟡 regenerable before/after on 3 captures; gate number needs #19 |
| 26 | Process evidence | `git log` | ✅ |
| 27 | Technical report <= 6 pages | `docs/technical_report.md` | 🟡 |
| 28 | Reproduction bundle | `README.md`, `requirements.txt`, scripts above | 🟡 raw captures shipped separately (too large for git) |
| 29 | Mirrors, glass, wet-look, low light covered | `known_limitations.md` #5, layout opening rules | 🟡 handled for openings; not stress-tested |

## What needs a person with a phone and a laser

Everything ❌ in rows 16-19 and 24 is data collection, not code: one
furnished room with staged damage (e.g. a tea stain + a pencil "crack" on
paper taped to the wall), one room captured twice, photo folders for the
multi-room walk, a free Polycam/magicplan scan of 2 rooms, and filling the
measuring sheets in `benchmark/ground_truth/`.
