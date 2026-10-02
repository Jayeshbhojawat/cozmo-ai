"""Capture-quality report for every tier: low light, motion blur and (LiDAR)
unreliable depth, which is how mirrors, glass and wet/glossy surfaces show up
in practice. Written into plan.json as "capture_quality" with plain-language
warnings, so a bad capture is flagged instead of silently producing a
confident-looking plan.

Thresholds (8-bit, images resized to 480 px wide):
  low light  - median luminance < 60, or > 25 % of pixels below 30
  blur       - variance of the Laplacian < 60 (sharp indoor frames: 150-1500)
  LiDAR      - share of depth pixels ARKit marks low confidence (0); glass and
               mirrors return depth of what is behind/reflected, which ARKit
               mostly marks low-confidence; dark or glossy floors likewise.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

DARK_MEDIAN, DARK_PIXEL, DARK_FRAC = 60, 30, 0.25
BLUR_VAR = 60.0


def frame_stats(bgr) -> dict:
    h, w = bgr.shape[:2]
    small = cv2.resize(bgr, (480, int(round(h * 480 / w))), interpolation=cv2.INTER_AREA)
    g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    med = float(np.median(g))
    dark_frac = float((g < DARK_PIXEL).mean())
    sharp = float(cv2.Laplacian(g, cv2.CV_64F).var())
    return {"luma_median": med, "dark_frac": dark_frac, "sharpness": sharp,
            "low_light": med < DARK_MEDIAN or dark_frac > DARK_FRAC, "blurred": sharp < BLUR_VAR}


def summarize(stats: list[dict], extra: dict | None = None) -> dict:
    if not stats:
        return {"frames_checked": 0, "warnings": ["no frames could be read"]}
    n = len(stats)
    low = sum(s["low_light"] for s in stats) / n
    blur = sum(s["blurred"] for s in stats) / n
    out = {"frames_checked": n, "low_light_frac": round(low, 3), "blurred_frac": round(blur, 3),
           "luma_median": round(float(np.median([s["luma_median"] for s in stats])), 1),
           "sharpness_median": round(float(np.median([s["sharpness"] for s in stats])), 1), "warnings": []}
    if low > 0.2:
        out["warnings"].append(f"{low:.0%} of frames are low-light: depth and tracking degrade; "
                               "turn lights on and re-capture if the plan looks wrong")
    if blur > 0.2:
        out["warnings"].append(f"{blur:.0%} of frames are motion-blurred: move the phone more slowly")
    if extra:
        out.update({k: v for k, v in extra.items() if k != "warnings"})
        out["warnings"] += extra.get("warnings", [])
    return out


def assess_video(video_path, n: int = 40) -> dict:
    vc = cv2.VideoCapture(str(video_path))
    total = int(vc.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    stats = []
    for i in np.linspace(0, max(total - 1, 0), min(n, max(total, 1))).astype(int):
        vc.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, img = vc.read()
        if ok:
            stats.append(frame_stats(img))
    vc.release()
    return summarize(stats)


def assess_images(images) -> dict:
    return summarize([frame_stats(im) for im in images])


def assess_photo_folders(folder) -> dict:
    from reconstruction.monotier import IMG_EXT, _read_image
    folder = Path(folder)
    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMG_EXT)
    stats = []
    for p in files:
        im = _read_image(p)
        if im is not None:
            stats.append(frame_stats(im))
    return summarize(stats)


def assess_lidar(cap, n: int = 40) -> dict:
    """Video stats plus the share of LiDAR depth ARKit marks low-confidence."""
    video = Path(cap.root) / "rgb.mp4"
    base = assess_video(video, n) if video.exists() else summarize([])
    fracs = []
    frames = [f for f in cap.frames if cap.depth_path(f.index).exists()]
    for f in [frames[i] for i in np.linspace(0, len(frames) - 1, min(n, len(frames))).astype(int)] if frames else []:
        p = cap.confidence_path(f.index)
        if p.exists():
            c = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
            if c is not None:
                fracs.append(float((c == 0).mean()))
    if fracs:
        lc = float(np.median(fracs))
        base["lidar_low_confidence_frac"] = round(lc, 3)
        if lc > 0.25:
            base["warnings"].append(f"{lc:.0%} of LiDAR depth is low-confidence (typical of glass, "
                                    "mirrors, dark or glossy surfaces): those points are excluded; "
                                    "walls seen only through them are reported unobserved")
    return base
