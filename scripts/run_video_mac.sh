#!/usr/bin/env bash
# Video tier on an Apple-Silicon Mac, one command:
#   scripts/run_video_mac.sh <spectacular_recording_folder> <out_dir>
# Step 1 (poses) runs in Docker (x86 emulation; the Spectacular AI SDK has no
# macOS build). Step 2 (depth, layout, damage, plan) runs natively, which is
# several times faster than running everything under emulation.
set -euo pipefail
REC="$(cd "$1" && pwd)"; OUT="$2"
IMAGE="${COZMO_IMAGE:-cozmo}"
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker build --platform linux/amd64 -t "$IMAGE" "$(dirname "$0")/.."
fi
docker run --rm --platform linux/amd64 -v "$REC:/rec" "$IMAGE" poses --input /rec
python -m cli.run capture --input "$REC" --tier video --out "$OUT"
