"""Debug view of a posed-video reconstruction: top-down density of the raw
world points in the wall band (1.0-1.9 m above the floor), with the camera
path. Needs a run made with COZMO_DUMP_CLOUDS=1 (writes clouds_debug.npz).

    python -m benchmark.debug_topdown <out_dir> [<out_dir> ...] --png out.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def floor_height(y):
    h, e = np.histogram(y, bins=np.arange(y.min(), y.max() + 0.02, 0.02))
    low = e[:-1] < np.percentile(y, 40)
    return float(e[:-1][low][np.argmax(h[low])] + 0.01)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--png", required=True)
    a = ap.parse_args()
    fig, axs = plt.subplots(1, len(a.dirs), figsize=(7 * len(a.dirs), 7), squeeze=False)
    for ax, d in zip(axs[0], a.dirs):
        z = np.load(Path(d) / "clouds_debug.npz")
        P, path = z["pts"], z["path"]
        fy = floor_height(P[:, 1])
        cam_h = float(np.median(path[:, 1]) - fy)
        cy = float(np.median(path[:, 1]))
        band = P[(P[:, 1] > cy - 0.5) & (P[:, 1] < cy + 0.3)]          # wall band around camera height
        H, xe, ze = np.histogram2d(band[:, 0], band[:, 2], bins=[np.arange(-15, 15, 0.05)] * 2)
        ax.imshow(np.log1p(H.T), origin="lower", extent=[xe[0], xe[-1], ze[0], ze[-1]], cmap="magma")
        ax.plot(path[:, 0], path[:, 2], "c-", lw=0.8)
        ax.plot(path[0, 0], path[0, 2], "go")
        lo, hi = path[:, [0, 2]].min(0) - 2.5, path[:, [0, 2]].max(0) + 2.5
        ax.set_xlim(lo[0], hi[0])
        ax.set_ylim(lo[1], hi[1])
        ax.set_title(f"{Path(d).name}: camera {cam_h:.2f} m above floor, {len(P)} pts")
        ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(a.png, dpi=90)


if __name__ == "__main__":
    main()
