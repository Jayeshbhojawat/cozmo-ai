"""Loads a StrayScanner-format capture folder into memory.

Expected folder layout (LiDAR tier):
    <capture>/rgb.mp4
    <capture>/depth/000000.png ...      16-bit PNG, millimeters, 256x192
    <capture>/confidence/000000.png ... 8-bit PNG, values 0/1/2 (ARKit low/med/high)
    <capture>/odometry.csv              timestamp,frame,x,y,z,qx,qy,qz,qw,fx,fy,cx,cy,...
    <capture>/imu.csv                   timestamp,a_x,a_y,a_z,alpha_x,alpha_y,alpha_z
    <capture>/camera_matrix.csv         3x3 intrinsic matrix, comma-separated rows
"""
from __future__ import annotations

import csv
import dataclasses
from pathlib import Path

import numpy as np


@dataclasses.dataclass
class Frame:
    index: int
    timestamp: float
    position: np.ndarray       # (3,) world position, meters
    quaternion: np.ndarray     # (4,) x,y,z,w
    fx: float
    fy: float
    cx: float
    cy: float

    def rotation_matrix(self) -> np.ndarray:
        x, y, z, w = self.quaternion
        return np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ])

    def pose_matrix(self) -> np.ndarray:
        """4x4 camera-to-world transform."""
        T = np.eye(4)
        T[:3, :3] = self.rotation_matrix()
        T[:3, 3] = self.position
        return T


@dataclasses.dataclass
class Capture:
    root: Path
    frames: list[Frame]
    camera_matrix: np.ndarray  # overall 3x3 intrinsic (fallback / reference)
    has_depth: bool

    def depth_path(self, frame_index: int) -> Path:
        return self.root / "depth" / f"{frame_index:06d}.png"

    def confidence_path(self, frame_index: int) -> Path:
        return self.root / "confidence" / f"{frame_index:06d}.png"


def _read_camera_matrix(path: Path) -> np.ndarray:
    rows = []
    with open(path, newline="") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append([float(v) for v in line.split(",")])
    return np.array(rows)


def load_capture(root: str | Path) -> Capture:
    root = Path(root)
    odometry_path = root / "odometry.csv"
    camera_matrix_path = root / "camera_matrix.csv"

    frames: list[Frame] = []
    with open(odometry_path, newline="") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        for row in reader:
            idx = int(row["frame"])
            frames.append(Frame(
                index=idx,
                timestamp=float(row["timestamp"]),
                position=np.array([float(row["x"]), float(row["y"]), float(row["z"])]),
                quaternion=np.array([float(row["qx"]), float(row["qy"]), float(row["qz"]), float(row["qw"])]),
                fx=float(row["fx"]), fy=float(row["fy"]), cx=float(row["cx"]), cy=float(row["cy"]),
            ))
    frames.sort(key=lambda fr: fr.index)

    camera_matrix = _read_camera_matrix(camera_matrix_path) if camera_matrix_path.exists() else None
    has_depth = (root / "depth").is_dir() and any((root / "depth").iterdir())

    return Capture(root=root, frames=frames, camera_matrix=camera_matrix, has_depth=has_depth)
