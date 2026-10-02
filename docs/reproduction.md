# Reproduction bundle

Everything needed to regenerate every reported number from raw inputs.

## Raw data (shipped next to the repo, not in git)

```
data/samples_full/<id>/          3 StrayScanner LiDAR walks (sample data)
data/raw/home/
  spectacular_1..3/              Spectacular Rec exports: data.mov, data.jsonl (IMU + frame
                                 times), calibration.json, metadata.json
                                 + caches: poses_cache.json, depth_cache_250.npz, scale_pairs_250.npz
  camera_video.MOV               stock-Camera clip (fallback video tier)
  photos/01_room1, 02_room2      8 HEIC stills per room (photo tier)
benchmark/ground_truth/home/     tape sheet as written (measurements_raw.txt) + converted sheet.json
```

## Two paths

**Cached replay (fast, deterministic).** With the caches present, the video
tier skips pose solving and the depth network; two runs give byte-identical
rooms and walls (checked). Every number in `benchmark/results/home/report.md`:

```bash
python -m benchmark.run_all --capture-dir data/raw/home \
    --sheet benchmark/ground_truth/home/sheet.json --out benchmark/results/home
```

**Live / cold path (what the walk-in test runs).** Delete the caches, or
copy only `data.mov data.jsonl calibration.json metadata.json` into a fresh
folder, then:

```bash
python -m cli.run capture --input <recording> --tier video --out <out>   # Linux/Windows x86-64
scripts/run_video_mac.sh <recording> <out>                               # Apple-Silicon Mac
```

`--recompute-poses` forces the pose solve even when a cache exists.

## Fix-loop arms

```bash
# fix loop 3 (docs/fix_declaration.md), as declared (path doorways came later, so off in both arms)
COZMO_VIDEO_PATH_DOORS=0 COZMO_VIDEO_MIN_FEATURE=0 python -m benchmark.run_all \
    --capture-dir <dir with spectacular_1..3> --sheet benchmark/ground_truth/home/sheet.json \
    --out benchmark/results/fixloop3_before
COZMO_VIDEO_PATH_DOORS=0 python -m benchmark.run_all ... --out benchmark/results/fixloop3_after
# fix loop 2: before = LiDAR floor + layout on video
COZMO_VIDEO_LAYOUT=lidar COZMO_VIDEO_FLOOR=histogram python -m benchmark.run_all ... --out benchmark/results/home_before
# fix loop 1 (LiDAR camera convention)
python -m benchmark.fix_loop --captures data/samples_full/* --out benchmark/results/fix_loop
```

Readable diffs: `git log --oneline -- reconstruction/layout.py cli/run.py`;
the declaration, fix and measurement are separate commits in that order.

## Known non-determinism

Only the cached replay has been checked for determinism (identical output
on repeated runs). The cold path (pose solve, ORB matching, depth network)
has not been checked across machines; its numbers may differ slightly from
the cached ones.

## Walk-in rehearsal on the presenter's Mac (2026-10-02)

MacBook Pro (Apple Silicon), python.org Python 3.14, clean venv:
`pip install -r requirements.txt` OK. Model download failed twice on that
network (missing CA certificates, then GitHub's file server resetting the
connection); fixed in `scripts/fetch_models.py` (certifi → system → curl),
and the model was installed from a checksum-verified copy. **Bring the model
pre-installed to the walk-in** so the live run never depends on the venue's
network. Photo tier on the measured home: **8.9 s**, rooms 8.82 / 10.86 m²,
identical to the cloud run (cross-machine reproduction of the photo tier).
Video tier on the same Mac: blocked at first, in this order — Docker Desktop
not installed (script now says so); apt "Hash Sum mismatch" on that network
over plain HTTP (Dockerfile now uses HTTPS sources); then "ffmpeg must be
installed" after I had wrongly dropped ffmpeg (restored). After those fixes,
**cold run of walk 1 (no caches): poses 104 s in Docker emulation + 58 s
native (depth 52 s, layout 3 s, damage 3 s) ≈ 2.7 min**, 3 spaces (2 rooms +
passage), footprint 33.28 m² vs 33.0 m² from the cached cloud run (~1 %
cross-machine difference on the cold path). LiDAR and photo tiers need no
Docker.
