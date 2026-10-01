"""Monocular depth (photo/video tiers): Depth Anything V2 ViT-S, metric
indoor fine-tune, ONNX on CPU. Only its depth SHAPE is trusted; callers
rescale every frame from the floor plane (see mono.py)."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

MODEL = Path(__file__).resolve().parents[1] / "models" / "da2_vits_indoor.onnx"
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
_SESSION = None


def _session():
    global _SESSION
    if _SESSION is None:
        if not MODEL.exists():
            raise SystemExit(f"Depth model missing: run `python scripts/fetch_models.py` (expects {MODEL})")
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        _SESSION = ort.InferenceSession(str(MODEL), opts, providers=["CPUExecutionProvider"])
    return _SESSION


def predict_depth(bgr: np.ndarray, short_side: int = 392) -> np.ndarray:
    """Depth (model units ~ metres, biased) at the input image's resolution
    divided down to the network size; returned resized to (h, w) of input."""
    h, w = bgr.shape[:2]
    s = short_side / min(h, w)
    W, H = int(np.ceil(w * s / 14) * 14), int(np.ceil(h * s / 14) * 14)
    x = cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), (W, H), interpolation=cv2.INTER_AREA)
    x = ((x.astype(np.float32) / 255.0 - MEAN) / STD).transpose(2, 0, 1)[None]
    d = _session().run(None, {"image": x})[0][0]
    return cv2.resize(d, (w, h), interpolation=cv2.INTER_LINEAR)
