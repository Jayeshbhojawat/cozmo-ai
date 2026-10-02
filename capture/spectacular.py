"""Video tier input: a Spectacular Rec recording (free App Store app; works on
any iPhone, no LiDAR needed): data.mov + data.jsonl (accelerometer,
gyroscope, magnetometer, per-frame timestamps) + calibration.json.

The phone's metric camera path is computed from video + motion sensors with
the Spectacular AI SDK (pip `spectacularAI`, free for non-commercial use,
disclosed in the report): visual-inertial odometry, so scale comes from the
accelerometer in real metres, and tracking survives blank walls because the
motion sensors bridge them. Because the poses are computed FROM the video
frames, image and pose are in sync by construction (unlike the StrayScanner
RGB stream, where we measured a timing mismatch).

Output is a `Capture` with the same Frame objects the LiDAR tier uses
(OpenCV camera convention, world +y up), so the rest of the pipeline is
shared. Poses are cached to <recording>/poses_cache.json (deterministic
replay); `--recompute` regenerates them live.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from capture.loader import Capture, Frame

# Spectacular AI world is z-up; ours is y-up: (x, y, z)_sai -> (x, z, -y)
W_SAI_TO_OURS = np.array([[1.0, 0, 0], [0, 0, 1.0], [0, -1.0, 0]])


def _run_vio(folder: Path) -> list[dict]:
    try:
        import spectacularAI
    except ImportError:
        raise SystemExit(
            "Camera poses for this recording are not computed yet and the Spectacular AI SDK is not "
            "installed here (it has no macOS build). On a Mac run:\n"
            "    scripts/run_video_mac.sh <recording> <out_dir>\n"
            "or first:  docker run --rm --platform linux/amd64 -v <recording>:/rec cozmo poses --input /rec")
    out = []

    def on_output(o):
        try:
            M = np.array(o.getCameraPose(0).getCameraToWorldMatrix())
        except Exception:
            return
        out.append({"t": float(o.pose.time), "M": M.tolist(), "tracking": "TRACKING" in str(o.status)})

    replay = spectacularAI.Replay(str(folder))
    replay.setOutputCallback(on_output)
    replay.runReplay()
    return out


def load_spectacular(folder, recompute: bool = False) -> Capture:
    folder = Path(folder)
    cal = json.loads((folder / "calibration.json").read_text())["cameras"][0]
    cache = folder / "poses_cache.json"
    if cache.exists() and not recompute:
        vio = json.loads(cache.read_text())
    else:
        vio = _run_vio(folder)
        try:
            cache.write_text(json.dumps(vio))
        except OSError:
            pass                      # read-only input folder: run live every time
    # frame number -> frame time, from the log
    frame_times = {}
    with open(folder / "data.jsonl") as f:
        for line in f:
            d = json.loads(line)
            if "frames" in d:
                frame_times[int(d["number"])] = float(d["time"])
    vt = np.array([v["t"] for v in vio])
    frames = []
    for num in sorted(frame_times):
        t = frame_times[num]
        j = int(np.argmin(np.abs(vt - t)))
        if abs(vt[j] - t) > 0.02 or not vio[j]["tracking"]:
            continue
        M = np.array(vio[j]["M"])
        R = W_SAI_TO_OURS @ M[:3, :3]
        p = W_SAI_TO_OURS @ M[:3, 3]
        q = Rotation.from_matrix(R).as_quat()            # x, y, z, w
        frames.append(Frame(index=num, timestamp=t, position=p, quaternion=q,
                            fx=cal["focalLengthX"], fy=cal["focalLengthY"],
                            cx=cal["principalPointX"], cy=cal["principalPointY"]))
    cap = Capture(root=folder, frames=frames, camera_matrix=None, has_depth=False,
                  rgb_shape=(int(cal["imageHeight"]), int(cal["imageWidth"])))
    return cap
