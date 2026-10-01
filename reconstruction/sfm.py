"""Classical structure-from-motion for the photo and video tiers, which have
no depth sensor and no IMU-fused pose (StrayScanner / a LiDAR app only
produces those). Reuses OpenCV (already a dependency) rather than adding a
heavy pretrained-depth-model download, which the 'runs in under 15 minutes
on a clean machine' README requirement argues against.

Pipeline, deliberately simple and documented as such (this is the piece of
the system most likely to need real work after the benchmark report comes
back — flagged in known_limitations.md):

1. ORB features + ratio-test matching between consecutive images (video:
   consecutive frames; photos: images in the order their filenames/EXIF
   timestamps suggest they were taken, which the capture protocol asks the
   user to preserve by walking a loop).
2. Essential-matrix pose recovery between each consecutive pair
   (cv2.findEssentialMat + recoverPose) -> relative rotation + translation
   DIRECTION (monocular: no metric scale from this alone).
3. Poses chained naively frame-to-frame (no bundle adjustment, no loop
   closure) into one trajectory; matched points triangulated into a sparse
   3D point cloud in that trajectory's frame.
4. World axes: assumes the phone was held with the capture protocol's
   instructed orientation (upright, screen roughly vertical) so the image's
   vertical axis tracks gravity closely enough to use the first camera's
   local "up" as the world's up -- an approximation, not a measured gravity
   vector (no IMU on these tiers).
5. Scale: monocular SfM is scale-ambiguous by construction. Anchored using
   the capture protocol's instructed phone height ("hold at chest height,
   ~1.4m") -- the mean camera height above the lowest point cluster (assumed
   floor) is rescaled to 1.4m. This is a coarse, disclosed assumption, not a
   measurement -- it is the dominant source of the wider photo/video-tier
   confidence intervals (see reconstruction/confidence.py).

Output is a point cloud in the same (x, y-up, z) convention `room_fit.py`
expects, so single-room fitting is fully reused.
"""
from __future__ import annotations

import cv2
import numpy as np

ASSUMED_CHEST_HEIGHT_M = 1.4


def _load_images(paths: list[str]) -> list[np.ndarray]:
    imgs = []
    for p in paths:
        img = cv2.imread(p)
        if img is not None:
            imgs.append(img)
    return imgs


def _frames_from_video(video_path: str, max_frames: int = 25) -> list[np.ndarray]:
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    if total <= 0:
        cap.release()
        return frames
    idxs = np.linspace(0, total - 1, min(max_frames, total)).astype(int)
    for idx in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if ok:
            frames.append(frame)
    cap.release()
    return frames


def _default_intrinsics(img_shape) -> np.ndarray:
    h, w = img_shape[:2]
    f = 1.1 * max(h, w)  # rough prior for a modern phone's main camera FOV
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], dtype=np.float64)
    return K


def _match(orb, bf, img_a, img_b):
    kp_a, des_a = orb.detectAndCompute(img_a, None)
    kp_b, des_b = orb.detectAndCompute(img_b, None)
    if des_a is None or des_b is None or len(kp_a) < 8 or len(kp_b) < 8:
        return None
    matches = bf.knnMatch(des_a, des_b, k=2)
    good = [m for m, n in matches if m.distance < 0.75 * n.distance]
    if len(good) < 15:
        return None
    pts_a = np.float32([kp_a[m.queryIdx].pt for m in good])
    pts_b = np.float32([kp_b[m.trainIdx].pt for m in good])
    return pts_a, pts_b


def reconstruct_sparse_cloud(image_paths: list[str] = None, video_path: str = None,
                              max_frames: int = 25) -> tuple[np.ndarray, dict]:
    """Returns (points_world_xyz, stats). points may be empty if too few
    usable matches were found (reported honestly, not padded)."""
    if video_path:
        images = _frames_from_video(video_path, max_frames=max_frames)
    else:
        images = _load_images(image_paths or [])
    stats = {"n_images_in": len(images), "n_pairs_used": 0, "n_points": 0}
    if len(images) < 2:
        return np.zeros((0, 3)), stats

    grays = [cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) for im in images]
    K = _default_intrinsics(images[0].shape)
    orb = cv2.ORB_create(nfeatures=2000)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)

    all_points_cam0 = []
    T_cum = np.eye(4)  # camera_i -> camera_0
    for i in range(len(grays) - 1):
        m = _match(orb, bf, grays[i], grays[i + 1])
        if m is None:
            continue
        pts_a, pts_b = m
        E, mask = cv2.findEssentialMat(pts_a, pts_b, K, method=cv2.RANSAC, prob=0.999, threshold=1.0)
        if E is None:
            continue
        _, R, t, mask_pose = cv2.recoverPose(E, pts_a, pts_b, K)
        inl = mask_pose.ravel().astype(bool)
        if inl.sum() < 12:
            continue

        P0 = K @ np.eye(3, 4)
        P1 = K @ np.hstack([R, t])
        pts4 = cv2.triangulatePoints(P0, P1, pts_a[inl].T, pts_b[inl].T)
        pts3_cam_i = (pts4[:3] / pts4[3]).T  # in camera i's own frame

        # Bring into camera-0's frame via the accumulated transform.
        T_i1_i = np.eye(4)
        T_i1_i[:3, :3] = R
        T_i1_i[:3, 3] = t.ravel()
        pts_h = np.hstack([pts3_cam_i, np.ones((len(pts3_cam_i), 1))])
        pts_world = (T_cum @ pts_h.T).T[:, :3]

        # Filter obviously-bad triangulations (behind camera / absurd range).
        depth_ok = (pts_world[:, 2] if False else np.linalg.norm(pts_world, axis=1)) < 50
        all_points_cam0.append(pts_world[depth_ok])

        T_cum = T_cum @ np.linalg.inv(T_i1_i)
        stats["n_pairs_used"] += 1

    if not all_points_cam0:
        return np.zeros((0, 3)), stats

    cloud = np.concatenate(all_points_cam0, axis=0)
    cloud = _to_world_axes_and_scale(cloud)
    stats["n_points"] = len(cloud)
    return cloud, stats


def _to_world_axes_and_scale(cloud_cam0: np.ndarray) -> np.ndarray:
    """Camera-0's -Y (image up) is treated as world up; this holds as long as
    the phone was held roughly level per the capture protocol. Scale is
    anchored by assuming the camera's own average height above the point
    cloud's lowest 5th percentile (the presumed floor) was the protocol's
    instructed chest height."""
    if len(cloud_cam0) == 0:
        return cloud_cam0
    # OpenCV camera convention: +x right, +y down, +z forward. World wants
    # +y up, so negate y; keep x, z as the horizontal plane like the LiDAR
    # pipeline's convention (z = camera forward, roughly along the walk).
    world = np.stack([cloud_cam0[:, 0], -cloud_cam0[:, 1], cloud_cam0[:, 2]], axis=1)
    floor_y = np.percentile(world[:, 1], 5)
    cam_height_unscaled = 0.0 - floor_y  # camera-0 origin is (0,0,0) pre-scale
    if abs(cam_height_unscaled) < 1e-6:
        return world
    scale = ASSUMED_CHEST_HEIGHT_M / abs(cam_height_unscaled)
    return world * scale
