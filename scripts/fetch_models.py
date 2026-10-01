#!/usr/bin/env python3
"""Fetch pretrained weights (not stored in git, per the brief).

    python scripts/fetch_models.py

Model (disclosed): Depth Anything V2, ViT-S, metric fine-tune on Hypersim
("indoor"), ONNX export by fabio-sim/Depth-Anything-ONNX (release v2.0.0).
Upstream: Yang et al., "Depth Anything V2", 2024. Apache-2.0 (ViT-S).
Used only by the photo and video tiers, and only for depth *shape*: metric
scale comes from the floor plane / camera height, not from the model
(measured on our LiDAR captures: raw model scale is off by 18-25% and varies
+-25% frame to frame, while per-frame-rescaled shape error is ~11%).
"""
import hashlib
import sys
import urllib.request
from pathlib import Path

MODELS = {
    "da2_vits_indoor.onnx": (
        "https://github.com/fabio-sim/Depth-Anything-ONNX/releases/download/v2.0.0/"
        "depth_anything_v2_vits_indoor_dynamic.onnx",
        "2e25a3f332b34d885a1b3059cab471f7916a36099325810821b2d6e0471f74ad",
    ),
}
DEST = Path(__file__).resolve().parents[1] / "models"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    DEST.mkdir(exist_ok=True)
    for name, (url, digest) in MODELS.items():
        out = DEST / name
        if out.exists() and sha256(out) == digest:
            print(f"ok      {name}")
            continue
        print(f"fetch   {name} <- {url}")
        urllib.request.urlretrieve(url, out)
        got = sha256(out)
        if got != digest:
            out.unlink()
            sys.exit(f"checksum mismatch for {name}: {got}")
        print(f"ok      {name}")


if __name__ == "__main__":
    main()
