# Benchmark — measured home

Regenerate: `python -m benchmark.run_all --capture-dir <dir> --sheet <sheet.json> --out <this dir>`

## Per capture

| capture | tier | rooms found | walls measured | wall err median | within tier tol | openings ≤2 cm (missed/phantom) | ceiling | footprint err | 95% CI coverage | runtime |
|---|---|---|---|---|---|---|---|---|---|---|
| spectacular_1 | video | 2 | 8 | 20.4% | 12.5% | 0/2 (1/0) | room_2: 11.0 cm; room_1: 32.5 cm | 17.8% | 9/11 | 120.26 s |
| spectacular_2 | video | 2 | 8 | 7.0% | 25.0% | 0/3 (2/1) | room_1: 10.0 cm; room_2: 17.4 cm | 8.3% | 9/10 | 124.82 s |
| spectacular_3 | video | 2 | 8 | 35.5% | 12.5% | 0/2 (1/0) | room_1: 14.0 cm; room_2: 19.5 cm | -5.2% | 7/11 | 155.01 s |

Wall error is relative (|pred − tape| / tape). Tier tolerance: video 3 %, photo 8 %. Openings: a missed and a phantom opening each count as a miss. Footprint: sum of matched rooms vs the same rooms built from tape lengths.

## Repeatability — video (3 runs)

Walls within max(1 cm, 0.5 %) across all runs: **0/8**

| room | wall | lengths (m) | spread | pass |
|---|---|---|---|---|
| room1 | A | 2.262, 2.995, 3.252 | 0.990 | no |
| room1 | B | 2.375, 6.830, 2.507 | 4.455 | no |
| room1 | C | 2.591, 3.022, 3.034 | 0.443 | no |
| room1 | D | 4.425, 5.952, 5.648 | 1.526 | no |
| room2 | A | 3.019, 2.944, 1.638 | 1.381 | no |
| room2 | B | 3.090, 2.106, 2.353 | 0.984 | no |
| room2 | C | 2.186, 2.317, 1.795 | 0.522 | no |
| room2 | D | 3.743, 2.718, 1.880 | 1.863 | no |

| room | ceiling heights (m) | spread | ≤1 cm |
|---|---|---|---|
| room1 | 2.735, 2.945, 2.985 | 0.250 | no |
| room2 | 2.916, 2.765, 2.396 | 0.520 | no |

## Drift on/off (video tier)

| capture | footprint OFF | footprint ON | tape footprint | auto chose | registration OFF→ON |
|---|---|---|---|---|---|
| spectacular_1 | 34.64 | 34.49 | 29.26 | on | 162545 → 162100 |
| spectacular_2 | 31.68 | 31.53 | 29.26 | off | 109961 → 110142 |
| spectacular_3 | 27.73 | 32.38 | 29.26 | off | 167449 → 168355 |
