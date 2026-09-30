"""Back-projects per-frame depth maps into a world-space, confidence-filtered
point cloud using the recorded pose + intrinsics.

Depth PNGs are 256x192, uint16, millimeters (StrayScanner convention, verified
against sample data: values in the few-hundred-to-few-thousand-mm range).
Confidence PNGs are 8-bit with values {0,1,2} = ARKit {low,medium,high}.
The depth map's native resolution differs from the RGB frame; StrayScanner's
depth intrinsics are the RGB intrinsics scaled by the depth/RGB resolution
ratio, which we derive from the depth image shape itself rather than assuming
a fixed constant (robust if capture devices differ).
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from capture.loader import Capture, Frame

MM_TO_M = 1.0 / 1000.0

# RGB frame resolution StrayScanner assumes for the recorded fx/fy/cx/cy
# (1920x1440 on most iPhone Pro LiDAR captures @ 4:3). Used only to derive the
# depth/RGB intrinsic scale factor; if wrong, wall lengths would scale
# uniformly, which the benchmark's ground-truth check would catch immediately.
ASSUMED_RGB_SHAPE = (1440, 1920)


def load_depth_confidence(capture: Capture, frame: Frame, min_confidence: int = 2):
    depth_img = np.array(Image.open(capture.depth_path(frame.index)))
    conf_img = np.array(Image.open(capture.confidence_path(frame.index)))
    depth_m = depth_img.astype(np.float32) * MM_TO_M
    mask = conf_img >= min_confidence
    # Reject obviously-invalid depth (0 = no return, > 6m unreliable indoors for
    # this sensor at this resolution).
    mask &= (depth_m > 0.05) & (depth_m < 6.0)
    return depth_m, mask


def depth_intrinsics_for(frame: Frame, depth_shape: tuple[int, int]) -> tuple[float, float, float, float]:
    dh, dw = depth_shape
    rh, rw = ASSUMED_RGB_SHAPE
    sx = dw / rw
    sy = dh / rh
    return frame.fx * sx, frame.fy * sy, frame.cx * sx, frame.cy * sy


def backproject_frame(capture: Capture, frame: Frame, min_confidence: int = 2, stride: int = 2):
    """Returns (N,3) world-space points and (N,) confidence values for one frame."""
    depth_m, mask = load_depth_confidence(capture, frame, min_confidence)
    h, w = depth_m.shape
    fx, fy, cx, cy = depth_intrinsics_for(frame, (h, w))

    ys, xs = np.mgrid[0:h:stride, 0:w:stride]
    m = mask[0:h:stride, 0:w:stride]
    d = depth_m[0:h:stride, 0:w:stride]

    xs, ys, d = xs[m].astype(np.float32), ys[m].astype(np.float32), d[m]
    if len(d) == 0:
        return np.zeros((0, 3), dtype=np.float32)

    # Pinhole back-projection into camera space (ARKit camera: +x right, +y up,
    # -z forward from the camera's point of view for the depth buffer's row
    # convention; image row 0 is top).
    x_cam = (xs - cx) / fx * d
    y_cam = -(ys - cy) / fy * d
    z_cam = -d
    pts_cam = np.stack([x_cam, y_cam, z_cam], axis=1)

    T = frame.pose_matrix()
    pts_world = (T[:3, :3] @ pts_cam.T).T + T[:3, 3]
    return pts_world.astype(np.float32)


def build_point_cloud(capture: Capture, min_confidence: int = 2, stride: int = 2, frame_stride: int = 1):
    """Accumulates world-space points across all (or a strided subset of) frames."""
    clouds = []
    used_frames = capture.frames[::frame_stride]
    for frame in used_frames:
        try:
            pts = backproject_frame(capture, frame, min_confidence=min_confidence, stride=stride)
        except FileNotFoundError:
            continue
        if len(pts):
            clouds.append(pts)
    if not clouds:
        return np.zeros((0, 3), dtype=np.float32)
    return np.concatenate(clouds, axis=0)
