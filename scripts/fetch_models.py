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
import shutil
import ssl
import subprocess
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


def download(url, out):
    """python.org Python on macOS ships without CA certificates
    (CERTIFICATE_VERIFY_FAILED). Try certifi's bundle, then the system
    default, then curl (which uses the macOS keychain). TLS verification is
    never disabled; the sha256 check below also guards the file."""
    contexts = []
    try:
        import certifi
        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except ImportError:
        pass
    contexts.append(ssl.create_default_context())
    last = None
    for ctx in contexts:
        try:
            with urllib.request.urlopen(url, context=ctx) as r, open(out, "wb") as f:
                shutil.copyfileobj(r, f)
            return
        except Exception as e:  # noqa: BLE001 - try the next trust store
            last = e
    if shutil.which("curl"):
        subprocess.run(["curl", "-fL", "--retry", "3", "-o", str(out), url], check=True)
        return
    raise SystemExit(f"download failed ({last}). On macOS run "
                     "'/Applications/Python 3.x/Install Certificates.command' or 'pip install certifi'.")


def main():
    DEST.mkdir(exist_ok=True)
    for name, (url, digest) in MODELS.items():
        out = DEST / name
        if out.exists() and sha256(out) == digest:
            print(f"ok      {name}")
            continue
        print(f"fetch   {name} <- {url}")
        download(url, out)
        got = sha256(out)
        if got != digest:
            out.unlink()
            sys.exit(f"checksum mismatch for {name}: {got}")
        print(f"ok      {name}")


if __name__ == "__main__":
    main()
