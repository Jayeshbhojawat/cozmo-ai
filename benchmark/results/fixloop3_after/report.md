# Benchmark — measured home

Regenerate: `python -m benchmark.run_all --capture-dir <dir> --sheet <sheet.json> --out <this dir>`

## Per capture

| capture | tier | rooms found | walls measured | wall err median | within tier tol | openings ≤2 cm (missed/phantom) | ceiling | footprint err | 95% CI coverage | runtime |
|---|---|---|---|---|---|---|---|---|---|---|
| spectacular_1 | video | 2 | 8 | 5.1% | 25.0% | 0/2 (2/0) | room_1: 8.0 cm; room_2: 14.4 cm | 14.6% | 9/10 | 119.35 s |
| spectacular_2 | video | 2 | 8 | 20.7% | 25.0% | 0/3 (1/1) | room_1: 10.0 cm; room_2: 17.4 cm | -4.9% | 11/11 | 124.87 s |
| spectacular_3 | video | 2 | 8 | 18.7% | 0.0% | 0/3 (1/1) | room_1: 14.0 cm; room_2: 19.5 cm | -3.7% | 11/11 | 155.6 s |

Wall error is relative (|pred − tape| / tape). Tier tolerance: video 3 %, photo 8 %. Openings: a missed and a phantom opening each count as a miss. Footprint: sum of matched rooms vs the same rooms built from tape lengths.

## Repeatability — video (3 runs)

Walls within max(1 cm, 0.5 %) across all runs: **0/8**

| room | wall | lengths (m) | spread | pass |
|---|---|---|---|---|
| room1 | A | 2.953, 2.539, 2.369 | 0.584 | no |
| room1 | B | 6.412, 11.173, 8.706 | 4.762 | no |
| room1 | C | 2.953, 5.228, 2.955 | 2.275 | no |
| room1 | D | 6.412, 5.946, 5.751 | 0.660 | no |
| room2 | A | 7.445, 2.980, 2.885 | 4.561 | no |
| room2 | B | 3.091, 2.528, 2.609 | 0.563 | no |
| room2 | C | 2.830, 2.980, 2.587 | 0.394 | no |
| room2 | D | 4.615, 2.528, 5.196 | 2.668 | no |

| room | ceiling heights (m) | spread | ≤1 cm |
|---|---|---|---|
| room1 | 2.925, 2.945, 2.985 | 0.060 | no |
| room2 | 2.735, 2.765, 2.396 | 0.369 | no |

## Drift on/off (video tier)

| capture | footprint OFF | footprint ON | tape footprint | auto chose | registration OFF→ON |
|---|---|---|---|---|---|
| spectacular_1 | 33.27 | 33.54 | 29.26 | on | 162545 → 162100 |
| spectacular_2 | 27.84 | 28.34 | 29.26 | off | 109961 → 110142 |
| spectacular_3 | 28.17 | 30.07 | 29.26 | off | 167449 → 168355 |
