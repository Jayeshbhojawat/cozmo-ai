"""Renders the stitched whole-property plan (and per-room plans) as PNG:
walls drawn as thick lines with interior dimensions, doors as gaps with a
swing arc, windows as a thin double line, each room labelled with its name,
area and ceiling height. Unobserved (inferred) wall segments are dashed."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc, Polygon
import numpy as np

ROOM_FILL = ["#e8eef6", "#eef6e8", "#f6efe6", "#f2e8f6", "#e6f4f4", "#f6f3e2", "#ebe9f7"]


def _wall_segments(w):
    """Split a wall into solid pieces around its openings (along-wall metres)."""
    cuts = sorted((max(0.0, o.start_m), min(w.length_m, o.end_m)) for o in w.openings)
    pieces, t = [], 0.0
    for s, e in cuts:
        if s > t:
            pieces.append((t, s))
        t = max(t, e)
    if t < w.length_m:
        pieces.append((t, w.length_m))
    return pieces


def render_plan(layout, out_path: str, title: str = "Floor plan", room_ids=None):
    rooms = [r for r in layout.rooms if room_ids is None or r.room_id in room_ids]
    if not rooms:
        return None
    allp = np.vstack([r.polygon for r in rooms])
    span = np.ptp(allp, axis=0)
    fig, ax = plt.subplots(figsize=(max(6, span[0] * 1.1 + 2), max(6, span[1] * 1.1 + 2)))
    for i, r in enumerate(rooms):
        ax.add_patch(Polygon(r.polygon, closed=True, facecolor=ROOM_FILL[i % len(ROOM_FILL)],
                             edgecolor="none", alpha=0.9 if not r.partial else 0.45, zorder=1))
        centroid = r.polygon.mean(axis=0)
        ceil = f"H {r.ceiling_height_m:.2f} m" if r.ceiling_observed else f"H ≥ {r.ceiling_height_m:.2f} m (ceiling not seen)"
        tag = " (partially observed)" if r.partial else ""
        ax.text(centroid[0], centroid[1], f"{r.room_id}{tag}\n{r.floor_area_m2:.2f} m²\n{ceil}",
                ha="center", va="center", fontsize=8, zorder=6, color="#333")
        for w in r.walls:
            d = (w.p1 - w.p0) / max(w.length_m, 1e-9)
            style = "-" if w.observed else (0, (4, 3))
            for s, e in _wall_segments(w):
                q0, q1 = w.p0 + d * s, w.p0 + d * e
                ax.plot([q0[0], q1[0]], [q0[1], q1[1]], color="#222", lw=3.2, ls=style,
                        solid_capstyle="butt", zorder=3)
            for o in w.openings:
                if o.leads_to is not None and o.leads_to < r.room_id and \
                        any(x.room_id == o.leads_to for x in rooms):
                    continue        # shared door: drawn once, from the other room
                q0, q1 = w.p0 + d * o.start_m, w.p0 + d * o.end_m
                if o.kind == "window":
                    n = np.array([-d[1], d[0]]) * 0.04
                    for off in (n, -n):
                        ax.plot([q0[0] + off[0], q1[0] + off[0]], [q0[1] + off[1], q1[1] + off[1]],
                                color="#3b7dd8", lw=1.2, zorder=4)
                else:
                    ang = np.degrees(np.arctan2(d[1], d[0]))
                    ax.add_patch(Arc(q0, 2 * o.width_m, 2 * o.width_m, angle=ang, theta1=0, theta2=90,
                                     color="#c0392b" if o.kind == "door" else "#e67e22", lw=0.8, zorder=4))
                mid = (q0 + q1) / 2
                ax.text(mid[0], mid[1], f"{o.width_m:.2f}", fontsize=6, color="#c0392b",
                        ha="center", va="bottom", zorder=7)
            if w.length_m >= 0.3:
                mid = (w.p0 + w.p1) / 2
                n_in = np.array([-d[1], d[0]])
                # place the dimension just inside the room
                probe = mid + n_in * 0.18
                inside = Polygon(r.polygon).get_path().contains_point(probe)
                pos = mid + (n_in if inside else -n_in) * 0.18
                rot = np.degrees(np.arctan2(d[1], d[0]))
                rot = rot - 180 if rot > 90 else (rot + 180 if rot < -90 else rot)
                ax.text(pos[0], pos[1], f"{w.length_m:.2f}", fontsize=6.5, rotation=rot,
                        ha="center", va="center", color="#555" if w.observed else "#aaa", zorder=5)
    ax.set_aspect("equal")
    ax.set_title(title)
    ax.axis("off")
    pad = 0.6
    ax.set_xlim(allp[:, 0].min() - pad, allp[:, 0].max() + pad)
    ax.set_ylim(allp[:, 1].min() - pad, allp[:, 1].max() + pad)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path
