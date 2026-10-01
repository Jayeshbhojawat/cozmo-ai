# LiDAR-tier plans of the three sample captures (regenerable)

`python -m cli.run capture --input data/samples_full/<id> --tier lidar --out outputs/<id>`

| capture | rooms | adjacencies | footprint m2 (95%) | ceiling | damage regions | runtime |
|---|---|---|---|---|---|---|
| c00a170fe1 | 3 | 2 | 19.80 [19.70-19.91] | not observed (lower bound only) | 6 | 93 s |
| 1a8384c3f6 | 5 | 4 | 67.73 [67.47-68.00] | not observed (lower bound only) | 1 | 69 s |
| c7d28f72c6 | 6 | 5 | 69.16 [68.96-69.37] | observed, 2.28-3.08 m | 2 | 90 s |

No tape/laser ground truth exists for these homes, so these show the pipeline
runs end to end; they are not accuracy evidence. Damage regions on these
captures are presumed false positives (no staged damage).
Runtimes measured with the three captures processed in parallel on one CPU box.
