# Compliance Matrix

Status key: ✅ done & tested · 🟡 working but not yet accurate/complete · ⬜ not started

| # | Requirement | File path / artifact | Status |
|---|---|---|---|
| 1 | Route 2 capture protocol (one-pager) | `docs/capture_protocol.md` | ✅ |
| 2 | Device matrix | `docs/device_matrix.md` | ✅ |
| 3 | Photo tier: 2-8 stills/room → stitched plan | `reconstruction/sfm.py` + `cli/run.py` | 🟡 SfM scaffold has a known scale-drift bug (`docs/known_limitations.md`); not wired into CLI yet |
| 4 | Video tier: handheld walkthrough → plan | `reconstruction/sfm.py` | 🟡 same scale-drift bug as photo tier |
| 5 | LiDAR tier: depth/pose/intrinsics → plan | `capture/loader.py`, `reconstruction/backproject.py`, `reconstruction/room_fit.py` | 🟡 runs end-to-end on real data; wall-polygon accuracy is the open fix-loop item |
| 6 | Dimensioned per-room plan (walls, ceiling height, floor area, openings) | `reconstruction/room_fit.py`, `cli/run.py` output | 🟡 produced for every LiDAR-tier run; floor-area accuracy not yet validated against ground truth |
| 7 | Stitched multi-room plan, correct adjacency | `stitching/stitch.py` | 🟡 implemented (continuous-capture + adjacency-hint placement), tested only on synthetic rooms — no real multi-room capture received yet |
| 8 | Per-surface damage regions, class + metric extent | `damage/detect.py` | 🟡 heuristic (water-stain/crack via classical CV, not a trained model); noisy on real furnished scenes, documented |
| 9 | Concealed-damage flags with rule that fired | `damage/detect.py` (`CONCEALED_RULE`) | ✅ rule implemented and recorded verbatim in output |
| 10 | Scope line items keyed to surfaces | `cli/run.py` (`_scope_from_damage`) | ✅ derived directly from damage regions |
| 11 | Confidence interval on every measurement | `reconstruction/confidence.py` | ✅ every length/height/area in the output JSON carries one |
| 12 | One command per capture | `cli/run.py` (`python -m cli.run capture ...`) | ✅ |
| 13 | JSON to published schema | `schema/capture_schema.json`, validated in `cli/run.py` output | ✅ schema-validated in testing |
| 14 | Rendered plan | `reconstruction/render.py` | ✅ per-room PNG; stitched-plan renderer implemented, untested on real multi-room data |
| 15 | Device matrix with honest accuracy per tier | `docs/device_matrix.md` | ✅ |
| 16 | Benchmark set (multi-room 3+, furnished+damage, repeat capture, all 3 tiers, ground truth) | `benchmark/` | ⬜ needs real captures beyond the 3 single-room samples provided — see note below |
| 17 | Opening-width gate | `benchmark/gates.py` | ⬜ depends on #16 ground truth |
| 18 | Ceiling-height + repeatability gate | `benchmark/gates.py` | ⬜ depends on #16 ground truth |
| 19 | Drift accountability + on/off ablation | `stitching/stitch.py` (`correct_drift_repeated_rooms`) | 🟡 mechanism implemented; ablation report depends on #16 |
| 20 | Photo-tier whole-property stitch gate | `benchmark/gates.py` | ⬜ depends on #3 and #16 |
| 21 | Head-to-head vs. consumer app (2 rooms, LiDAR tier) | `benchmark/head_to_head.md` | ⬜ not started |
| 22 | Fix loop: declaration + root cause + shipped fix + before/after | `docs/fix_loop.md` | ⬜ candidate identified (wall-polygon accuracy), formal declaration not yet written pending ground truth |
| 23 | Process evidence (incremental git history) | this repo's `git log` | ✅ ongoing, 9 commits as of this snapshot, each a real working increment |
| 24 | Technical report, max 6 pages | `docs/technical_report.md` | 🟡 outline in progress |
| 25 | Reproduction bundle | `README.md` + `requirements.txt` | 🟡 install/run documented; full regeneration from raw inputs not yet scripted end-to-end |
| 26 | Raw benchmark data | delivered separately (sample data excluded from git; see `.gitignore`) | 🟡 only 3 single-room samples so far, not yet the full required benchmark composition |

## What's blocking the most score right now

The single biggest gap is **#16: the benchmark set doesn't yet meet the
required composition** (multi-room 3+ rooms, a furnished room with staged
damage across 2+ damage classes, a repeat capture of one room, all of the
above at all 3 tiers, plus laser/tape ground truth). Everything from gates
(#17-20) through the formal fix-loop declaration (#22) depends on having
that data and those measurements. The three sample folders provided so far
are three separate, ordinary single rooms — useful for building and testing
the pipeline (which is what they were used for), but not sufficient to
satisfy the benchmark requirement on their own.
