#!/usr/bin/env bash
# Video tier on an Apple-Silicon Mac, one command:
#   scripts/run_video_mac.sh <spectacular_recording_folder> <out_dir>
# Step 1 (poses) runs in Docker (x86 emulation; the Spectacular AI SDK has no
# macOS build). Step 2 (depth, layout, damage, plan) runs natively, which is
# several times faster than running everything under emulation.
set -euo pipefail
REC="$(cd "$1" && pwd)"; OUT="$2"
IMAGE="${COZMO_IMAGE:-cozmo}"
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. The video tier's pose step needs it on a Mac (the Spectacular AI"
  echo "SDK has no macOS build). Install Docker Desktop for Apple chip (docker.com, or"
  echo "'brew install --cask docker'), open it once, then re-run this script."
  echo "LiDAR and photo tiers run without Docker: python -m cli.run capture --tier lidar|photo ..."
  exit 2
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but not running: open Docker Desktop, wait for the whale icon, re-run."
  exit 2
fi
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker build --platform linux/amd64 -t "$IMAGE" "$(dirname "$0")/.."
fi
docker run --rm --platform linux/amd64 -v "$REC:/rec" "$IMAGE" poses --input /rec
python -m cli.run capture --input "$REC" --tier video --out "$OUT"
