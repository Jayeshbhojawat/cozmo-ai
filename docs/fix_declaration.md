# Fix declaration (Part 4) — written before the fix is shipped

Committed before the shipped run on the held-out walks. The git timestamps
of this file, the fix commit and the measurement commit show the order.

## 1. Worst-performing gate, with the failing number

**Video-tier wall length, gate ±3 %** (benchmark/results/home, tape-measured
2-room home, 3 Spectacular Rec walks on a non-Pro iPhone 15).

Failing number: **4 of 24 walls (17 %) within ±3 %**; median wall error
20.4 % / 7.0 % / 35.5 % on walks 1 / 2 / 3.

It is the worst gate relative to its tolerance among those our benchmark
scores on all three walks, and it drives the others (footprint, door
placement, repeatability: 0/8 walls repeatable).

## 2. Root-cause hypothesis and evidence

**Hypothesis: the error is mostly outline fragmentation, not wrong wall
positions.** Learned depth smears each wall over ~0.3 m (doubled wall
lines in the top-down view, `benchmark/debug_topdown.py`). The free-space
boundary then has notches of that size; each notch splits a real wall into
pieces. The tape has one length per wall, so a 6.25 m wall drawn as
2.4 + 0.5 + 3.0 m scores as a 60 % error, and the extra pieces also make the
sheet-to-plan matcher pair the wrong rooms.

Evidence:
- Walk 1 (development walk) at the current setting: room 1 drawn with 8
  walls (6.44, 2.69, 2.28, 0.89, 3.16, 0.56, 0.99, 3.02 m) for a rectangular
  6.25 × 3.05 m room, and the matcher paired it with the wrong tape room.
- Ruled out first: depth-dependent bias of the learned depth. Within a
  frame the triangulated/model ratio is flat with distance (±1 % from 1.25
  to 4 m, 50-66 k point pairs per walk, `benchmark/scale_pairs.py`), so a
  scale-plus-offset depth model would not change wall positions.
- Ruled out by the tape earlier: per-frame scale refinement (sharper walls,
  worse wall error; `docs/fix_loop.md`).

## 3. The fix to ship

For learned-depth tiers only (LiDAR unchanged): treat outline features
smaller than a minimum size as noise. The room mask is closed then opened
at that size before tracing, and wall pieces shorter than it are merged
into their neighbours (`min_feature_m` in `reconstruction/layout.py`).
Size chosen on **walk 1 only**: 0.8 m (≈ 2.5 × the measured wall smear; on
walk 1 it turns room 1 into 6.46 × 2.91 m vs tape 6.25 × 3.05 m).
**Walks 2 and 3 are held out**: they were not looked at with this setting.

## 4. Predicted number after the fix (held-out walks 2 and 3)

- Walls within ±3 %: from 3/16 now on walks 2-3 to **5-8 of 16**.
- Median wall error: from 7.0 % / 35.5 % to **≤ 10 % on both**.
- **The ±3 % gate will still fail.** Remaining error after de-fragmenting is
  the overall size bias (room 1 on walk 1: +3 % length, −5 % width), which
  this fix does not touch. Room 2 is merged with the passage between the
  rooms on walk 1 and may stay merged; walls of a merged room will miss.

If the measured result is outside these ranges in either direction, the
post-mortem goes in `docs/fix_loop.md` under this declaration.
