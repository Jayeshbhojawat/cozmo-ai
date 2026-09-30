"""Renders a top-down dimensioned plan (single room or stitched multi-room)
as a PNG — the "rendered plan" required by the output contract."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reconstruction.room_fit import RoomFit


def render_room_plan(fit: RoomFit, out_path: str, room_id: str = "room"):
    fig, ax = plt.subplots(figsize=(6, 6))
    for i, w in enumerate(fit.walls):
        color = "#c0392b" if w.n_inliers == 0 else "#2c3e50"
        ax.plot([w.p0[0], w.p1[0]], [w.p0[1], w.p1[1]], color=color, linewidth=3)
        mid = (w.p0 + w.p1) / 2
        ax.annotate(f"{w.length_m:.2f}m", mid, fontsize=8, color=color)
        for (s, e) in w.openings:
            d = w.p1 - w.p0
            op0 = w.p0 + d * s
            op1 = w.p0 + d * e
            ax.plot([op0[0], op1[0]], [op0[1], op1[1]], color="white", linewidth=4, zorder=5)
            ax.plot([op0[0], op1[0]], [op0[1], op1[1]], color="#2980b9", linewidth=1.5,
                     linestyle="--", zorder=6)

    ax.set_title(f"{room_id} — ceiling {fit.ceiling_height_m:.2f}m, "
                 f"area {fit.floor_area_m2:.2f}m² ({fit.confidence} confidence)")
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("z (m)")
    ax.grid(True, linestyle=":", alpha=0.4)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def render_stitched_plan(room_fits: dict[str, tuple[RoomFit, "np.ndarray"]], out_path: str):
    """room_fits: {room_id: (RoomFit, 2x2 transform-to-world-plan offset+rotation applied already
    to wall coordinates, i.e. walls are expected pre-transformed into the shared plan frame)}."""
    fig, ax = plt.subplots(figsize=(9, 9))
    colors = ["#2c3e50", "#8e44ad", "#16a085", "#d35400", "#2980b9"]
    for idx, (room_id, (fit, _)) in enumerate(room_fits.items()):
        color = colors[idx % len(colors)]
        for w in fit.walls:
            ax.plot([w.p0[0], w.p1[0]], [w.p0[1], w.p1[1]], color=color, linewidth=3)
        if fit.walls:
            cx = sum((w.p0[0] + w.p1[0]) / 2 for w in fit.walls) / len(fit.walls)
            cz = sum((w.p0[1] + w.p1[1]) / 2 for w in fit.walls) / len(fit.walls)
            ax.annotate(room_id, (cx, cz), fontsize=10, color=color, weight="bold")
    ax.set_title("Stitched whole-property plan")
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("z (m)")
    ax.grid(True, linestyle=":", alpha=0.4)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path
