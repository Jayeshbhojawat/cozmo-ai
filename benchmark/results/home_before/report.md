# Benchmark — measured home

Regenerate: `python -m benchmark.run_all --capture-dir <dir> --sheet <sheet.json> --out <this dir>`

## Per capture

| capture | tier | rooms found | walls measured | wall err median | within tier tol | openings ≤2 cm (missed/phantom) | ceiling | footprint err | 95% CI coverage | runtime |
|---|---|---|---|---|---|---|---|---|---|---|
| spectacular_1 | video | 1 | 4 | 24.2% | 0.0% | 0/1 (0/0) | room_1: 55.7 cm | -10.5% | 2/6 | 101.81 s |
| spectacular_2 | video | 2 | 8 | 25.4% | 0.0% | 0/3 (2/1) | room_1: not seen; room_2: 7.4 cm | 26.8% | 5/10 | 139.88 s |
| spectacular_3 | video | 0 | 0 | — | — | — | — | — | 0/0 | 115.94 s |

Wall error is relative (|pred − tape| / tape). Tier tolerance: video 3 %, photo 8 %. Openings: a missed and a phantom opening each count as a miss. Footprint: sum of matched rooms vs the same rooms built from tape lengths.

## Repeatability — video (3 runs)

Walls within max(1 cm, 0.5 %) across all runs: **0/0**

| room | wall | lengths (m) | spread | pass |
|---|---|---|---|---|
| room1 | A | 2.241 | — | no |
| room1 | B | 7.442 | — | no |
| room1 | C | 2.456 | — | no |
| room1 | D | 2.588 | — | no |
| room2 | A | 2.631, 2.702 | 0.070 | no |
| room2 | B | 3.068, 2.071 | 0.998 | no |
| room2 | C | 1.992, 1.637 | 0.354 | no |
| room2 | D | 1.974, 4.170 | 2.196 | no |

| room | ceiling heights (m) | spread | ≤1 cm |
|---|---|---|---|
| room2 | 2.034, 2.665 | 0.631 | no |

## Drift on/off (video tier)

| capture | footprint OFF | footprint ON | tape footprint | auto chose | registration OFF→ON |
|---|---|---|---|---|---|
| spectacular_1 | 9.15 | 9.14 | 10.22 | on | 162545 → 162100 |
| spectacular_2 | 37.12 | 36.43 | 29.26 | off | 109961 → 110142 |
| spectacular_3 | 0.00 | 0.00 | 0.00 | off | 167449 → 168355 |
