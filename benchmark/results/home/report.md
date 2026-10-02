# Benchmark — measured home

Regenerate: `python -m benchmark.run_all --capture-dir <dir> --sheet <sheet.json> --out <this dir>`

## Per capture

| capture | tier | rooms found | walls measured | wall err median | within tier tol | openings ≤2 cm (missed/phantom) | ceiling | footprint err | 95% CI coverage | runtime |
|---|---|---|---|---|---|---|---|---|---|---|
| camera_video | video | 1 | 4 | 9.5% | 50.0% | 0/1 (0/0) | room_1: not seen | 45.7% | 4/6 | 217.89 s |
| spectacular_1 | video | 3 | 8 | 2.9% | 50.0% | 0/3 (2/1) | room_1: 8.0 cm; room_2: 14.5 cm | -4.1% | 10/10 | 87.37 s |
| spectacular_2 | video | 3 | 8 | 20.6% | 25.0% | 0/3 (1/1) | room_1: 10.0 cm; room_2: 17.4 cm | -6.9% | 11/11 | 89.81 s |
| spectacular_3 | video | 4 | 8 | 10.6% | 0.0% | 0/2 (0/0) | room_1: 17.0 cm; room_2: 9.3 cm | -16.1% | 11/12 | 105.55 s |
| photos | photo | 2 | 8 | 28.3% | 12.5% | 0/2 (2/0) | 01_room1: 13.0 cm; 02_room2: not seen | -32.8% | 8/10 | 30.92 s |

Wall error is relative (|pred − tape| / tape). Tier tolerance: video 3 %, photo 8 %. Openings: a missed and a phantom opening each count as a miss. Footprint: sum of matched rooms vs the same rooms built from tape lengths.

## Repeatability — video (3 runs)

Walls within max(1 cm, 0.5 %) across all runs: **0/8**

| room | wall | lengths (m) | spread | pass |
|---|---|---|---|---|
| room1 | A | 2.953, 4.362, 2.525 | 1.837 | no |
| room1 | B | 6.412, 5.949, 6.818 | 0.868 | no |
| room1 | C | 2.953, 2.539, 1.308 | 1.645 | no |
| room1 | D | 6.412, 10.311, 5.958 | 4.354 | no |
| room2 | A | 3.006, 2.980, 2.844 | 0.161 | no |
| room2 | B | 3.043, 2.529, 2.948 | 0.515 | no |
| room2 | C | 3.006, 2.980, 2.844 | 0.161 | no |
| room2 | D | 3.043, 2.529, 2.948 | 0.515 | no |

| room | ceiling heights (m) | spread | ≤1 cm |
|---|---|---|---|
| room1 | 2.925, 2.945, 3.015 | 0.090 | no |
| room2 | 2.736, 2.765, 2.684 | 0.081 | no |

## Drift on/off (video tier)

| capture | footprint OFF | footprint ON | tape footprint | auto chose | registration OFF→ON |
|---|---|---|---|---|---|
| spectacular_1 | 32.98 | 33.68 | 29.26 | on | 162545 → 162100 |
| spectacular_2 | 28.22 | 28.77 | 29.26 | off | 109961 → 110142 |
| spectacular_3 | 30.23 | 31.45 | 29.26 | off | 167449 → 168355 |
