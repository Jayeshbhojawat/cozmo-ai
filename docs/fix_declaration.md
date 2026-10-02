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

---

## 5. Measured result (after shipping) and post-mortem

Before / after, same depth cache, regenerable:
`COZMO_VIDEO_MIN_FEATURE=0 python -m benchmark.run_all ... --out benchmark/results/fixloop3_before`
and the same without the variable → `benchmark/results/fixloop3_after`.

| walk | median wall error | walls within ±3 % | footprint error | 95 % coverage |
|---|---|---|---|---|
| 1 (dev) | 20.4 % → **5.1 %** | 1/8 → 2/8 | +17.8 % → +14.6 % | 9/11 → 9/10 |
| 2 (held out) | 7.0 % → **20.7 %** | 2/8 → 2/8 | +8.3 % → −4.9 % | 9/10 → 11/11 |
| 3 (held out) | 35.5 % → **18.7 %** | 1/8 → 0/8 | −5.2 % → −3.7 % | 7/11 → 11/11 |

**Prediction: wrong.** Predicted 5-8 of 16 held-out walls within ±3 % and
median ≤ 10 % on both held-out walks; measured **2 of 16**, medians 20.7 %
and 18.7 %. The gate still fails (as predicted), but the size of the
improvement was over-predicted and walk 2 got worse.

**Why.** The hypothesis was half right. Fragmentation was real (room 2 on
walk 2 went from 6 pieces to a clean 2.98 × 2.53 m rectangle; room 1 on walk
1 from 8 pieces to 6.46 × 2.91 m). But on walks 2 and 3 the dominant error
is a **segmentation** error the development walk did not show: room 1 is
merged with the 1.2 m passage between the rooms, giving 11.17 m and 8.71 m
"walls" for a 6.25 m room. Before the fix that merged room was traced as 14
small pieces, and the sheet matcher could pick the pieces that happened to
lie near the tape lengths (3.00, 6.83, 3.02, 5.95 m on walk 2). **The
"before" numbers were flattered by that freedom**; after de-fragmenting,
the matcher has to use the real merged walls. One development walk was not
enough to see this; the held-out split is what exposed it.

**Kept shipped** because the footprint improved on all three walks
(|error| 17.8/8.3/5.2 % → 14.6/4.9/3.7 %), interval coverage went from
25/32 to 31/32, and outlines no longer carry noise-sized notches that
reward a lenient matcher. **Next fix:** separate narrow passages from rooms
(the 1.4 m doorway threshold, chosen to split the rooms, also swallows a
1.2 m passage); the evidence is the 11.17 m / 8.71 m merged walls above.

## 6. Follow-up shipped: the post-mortem's next fix

Doorways cut where the walking path squeezes through free space (width
across the walking direction has a local minimum < 1.3 m with ≥ 0.5 m more
on both sides). Not declared in advance like the fix above; reported here
with its measured effect (`benchmark/results/home`, switch
`COZMO_VIDEO_PATH_DOORS=0` for the run without it):

| walk | median wall error | walls within ±3 % | footprint error | 95 % coverage |
|---|---|---|---|---|
| 1 | 5.1 % → **2.9 %** | 2/8 → **4/8** | +14.6 % → −4.1 % | 9/10 → 10/10 |
| 2 | 20.7 % → 20.6 % | 2/8 → 2/8 | −4.9 % → −6.9 % | 11/11 → 11/11 |
| 3 | 18.7 % → **10.6 %** | 0/8 → 0/8 | −3.7 % → −16.1 % | 11/11 → 11/12 |

Across the three walks the ±3 % wall gate moves from 4/24 (first declared
baseline) to **6/24 walls**; **it still fails.** Walk 2 keeps room 1 and the
passage merged (its cut is not found). Walk 3's footprint gets worse because
the passage is now split off and the remaining room 1 is short. Room 2 is
2.5-2.95 m long on every walk vs 3.35 m on the tape: the tall wardrobe along
its wall reads as the wall (known limitation 4).
