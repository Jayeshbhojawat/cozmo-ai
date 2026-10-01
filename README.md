# Cozmo AI — phone capture to dimensioned, stitched floor plan

A phone walkthrough in, a whole-property floor plan out: rooms, wall lengths,
ceiling heights, floor areas, doors and windows with widths, room adjacency,
per-surface damage with concealed-damage rules and scope items, a 95%
interval on every number, as JSON (`schema/capture_schema.json`) + PNG.

Live status: `docs/compliance_matrix.md`. Open problems: `docs/known_limitations.md`.
LiDAR tier works end to end; **photo and video tiers are not built yet.**

## Install (clean machine, ~3 min)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests -q          # output-contract tests run once outputs/ exists
```

CPU only; no model weights; no network at run time.

## Run on a capture (one command)

Capture with the one-page protocol (`docs/capture_protocol.md`, StrayScanner),
export the folder, then:

```bash
python -m cli.run capture --input path/to/capture_folder --tier lidar --out outputs/my_flat
```

-> `outputs/my_flat/plan.json`, `outputs/my_flat/plan.png`. One continuous
walk through several rooms yields every room plus the stitched plan.
Takes 20-50 s on a laptop. Options: `--drift auto|on|off`, `--no-damage`.

## Benchmark / reproduction

```bash
# Fix loop before/after (Part 4)
python -m benchmark.fix_loop --captures data/samples_full/* --out benchmark/results/fix_loop
# Drift ablation (footprint with/without correction)
python -m benchmark.drift_ablation --input data/samples_full/<capture> --out benchmark/results/drift_<capture>
# Ground truth: make a measuring sheet, fill it with tape/laser values, score the gates
python -m benchmark.ground_truth template --plan outputs/<cap>/plan.json --out benchmark/ground_truth/<cap>.json
python -m benchmark.ground_truth score    --plan outputs/<cap>/plan.json --gt benchmark/ground_truth/<cap>.json
```

Raw captures are not in git (size); they are shipped separately and go in
`data/samples_full/<capture_id>/`.

## Layout

```
capture/         StrayScanner export -> frames, poses, intrinsics
reconstruction/  backproject (depth -> points), drift (yaw correction),
                 layout (rooms, walls, doors, ceilings), confidence, render, sfm (WIP)
damage/          per-surface damage detection + concealed-damage rules
stitching/       placing separately captured rooms; repeat-capture alignment
benchmark/       gates, ground-truth sheets + scorer, fix-loop and drift-ablation runners
schema/          published output schema
docs/            protocol, device matrix, compliance matrix, report, fix loop, limitations
```
