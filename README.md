# Cozmo AI — Phone-Capture Floor Plan & Damage Pipeline

Status: **work in progress, 24-hour build.** See `docs/compliance_matrix.md`
for a live, honest per-requirement status and `docs/known_limitations.md`
for the specific open bugs and their root causes.

## What this is

Turns a phone capture (LiDAR, video, or photos — see `docs/device_matrix.md`)
of a room into a dimensioned floor plan, a stitched whole-property plan, and
per-surface damage regions, all with confidence intervals, via one command
per capture.

## Install (target: under 15 minutes on a clean machine)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

No GPU, no external API calls, no network access needed at run time (per the
brief's constraints — everything here is classical CV / numpy, no pretrained
model weights to fetch).

## Run it on a capture

LiDAR tier (StrayScanner export — `rgb.mp4`, `depth/`, `confidence/`,
`odometry.csv`, `imu.csv`, `camera_matrix.csv` in one folder):

```bash
python -m cli.run capture --input /path/to/capture_folder --tier lidar \
    --room-id living_room --out outputs/living_room
```

Produces `outputs/living_room/plan.json` (validates against
`schema/capture_schema.json`) and `outputs/living_room/plan.png`.

Photo/video tiers are scaffolded (`reconstruction/sfm.py`) but not yet wired
into the CLI — see `docs/known_limitations.md` for the specific blocking bug
(monocular scale-chaining drift).

## Capturing data

Follow `docs/capture_protocol.md` exactly — it's written to be followed
literally by a non-engineer, per the brief's Route 2 requirement.

## Repo layout

```
capture/        parses a capture folder into frames + poses
reconstruction/ depth backprojection, room fitting (walls/floor/ceiling),
                 SfM for photo/video tiers, confidence intervals, rendering
stitching/      multi-room placement + drift correction
damage/         per-surface damage detection
schema/         published JSON output schema
cli/            the one-command-per-capture entry point
benchmark/      gate definitions + (once ground truth exists) results
docs/           protocol, device matrix, compliance matrix, report,
                 known limitations, fix-loop declaration
```

## Running the tests

```bash
python -m pytest tests/ -v
```

## What's real vs. not yet

The LiDAR tier runs end-to-end on real captures: parses the sensor data,
builds a confidence-filtered point cloud, fits floor/ceiling/walls, detects
openings, renders a plan, runs heuristic damage detection, and writes
schema-valid JSON with a confidence interval on every number. Wall-polygon
accuracy is the known open item (`docs/known_limitations.md`) and the
current candidate for the formal Part 4 fix-loop entry. Photo/video tiers
and the full benchmark/gates/head-to-head/report deliverables are in
progress — `docs/compliance_matrix.md` is the source of truth for exactly
what's done.
