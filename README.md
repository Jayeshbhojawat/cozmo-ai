# Cozmo AI — phone capture to dimensioned, stitched floor plan

A phone walkthrough in, a whole-property floor plan out: rooms, wall lengths,
ceiling heights, floor areas, doors and windows with widths, room adjacency,
per-surface damage with concealed-damage rules and scope items, a 95%
interval on every number, as JSON (`schema/capture_schema.json`) + PNG.

Live status: `docs/compliance_matrix.md`. Open problems: `docs/known_limitations.md`.
All three tiers run end to end. LiDAR is the accurate one; photo and video
(pivot scans + learned depth) currently measure +-11 % per length (RMS vs
LiDAR), outside the brief's 8 % / 3 % gates; their intervals say so.

## Install (clean machine, ~3 min)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests -q          # output-contract tests run once outputs/ exists
```

CPU only; no network at run time. Photo/video tiers need one model file,
fetched once by script (checksum-verified, not in git):

```bash
python scripts/fetch_models.py      # Depth Anything V2 ViT-S metric-indoor, ONNX, ~99 MB
```

## Run on a capture (one command)

Capture with the one-page protocol (`docs/capture_protocol.md`, StrayScanner),
export the folder, then:

```bash
python -m cli.run capture --input path/to/capture_folder --tier lidar --out outputs/my_flat
```

-> `outputs/my_flat/plan.json`, `outputs/my_flat/plan.png`. One continuous
walk through several rooms yields every room plus the stitched plan.
Takes 20-50 s on a laptop. Options: `--drift auto|on|off`, `--no-damage`.

Photo tier (one sub-folder of 6-8 stills per room, taken turning on the spot):

```bash
python -m cli.run capture --input path/to/photo_folders --tier photo --out outputs/my_flat_photo
```

Video tier, recommended (Spectacular Rec recording folder: video + motion sensors,
any iPhone 15+; needs `pip install -r requirements-video.txt`, Linux/Windows x86_64):

```bash
python -m cli.run capture --input path/to/spectacular_recording --tier video --out outputs/my_flat_video
```

On an Apple Silicon Mac (no native build of the motion-tracking library), use Docker:

```bash
docker build --platform linux/amd64 -t cozmo .
docker run --rm --platform linux/amd64 -v "$PWD/data:/data" -v "$PWD/outputs:/outputs" cozmo \
    capture --input /data/my_recording --tier video --out /outputs/my_flat_video
```

Video tier fallback (stock Camera clip; turn a full circle in the middle of every room):

```bash
python -m cli.run capture --input path/to/walk.mov --tier video --out outputs/my_flat_video
# --rotate cw|ccw|180 only if the file lacks orientation metadata
```

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
capture/         StrayScanner export / Spectacular Rec recording -> frames, poses, intrinsics
reconstruction/  backproject (depth -> points), drift (yaw correction),
                 layout (rooms, walls, doors, ceilings), confidence, render, sfm (WIP)
damage/          per-surface damage detection + concealed-damage rules
stitching/       placing separately captured rooms; repeat-capture alignment
benchmark/       gates, ground-truth sheets + scorer, fix-loop and drift-ablation runners
schema/          published output schema
docs/            protocol, device matrix, compliance matrix, report, fix loop, limitations
```
