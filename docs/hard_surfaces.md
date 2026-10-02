# Mirrors, glass, wet-look surfaces and low light

What each does to each tier, what the pipeline does about it, and what is
and is not verified. Every run writes `capture_quality` into plan.json
(`capture/quality.py`) with plain-language warnings.

| condition | effect | LiDAR tier | video / photo tiers | verified? |
|---|---|---|---|---|
| **Mirror** | depth "through" the wall (the reflected room) | ARKit marks most of it low-confidence → excluded (`min_confidence=1`); what survives lands behind the wall, so free-space carving sees a hole: reported as `opening_unconfirmed`, never as a door | learned depth reads the mirror as a surface or a hole depending on content; same `opening_unconfirmed` rule | partly: on the mirror-heavy sample walk the learned depth's shape error vs LiDAR was 21-23 % (7-10 % elsewhere), which is why learned depth is never trusted where LiDAR exists. Not measured against tape. |
| **Glass (window, glass door)** | LiDAR passes through or reflects; learned depth sees the scene outside | low-confidence share reported (`lidar_low_confidence_frac`), warning above 25 %; a wall seen only through glass stays "unobserved" (dashed in the plan, wider interval) | windows found as wall gaps with sill/head; glass doors may read as openings | not tape-verified (the measured home has barred vents, no glass panes facing the capture) |
| **Wet-look / glossy floor or tiles** | specular highlights; LiDAR dropouts at grazing angles | floor plane from the robust histogram peak, not single points; low-confidence share reported | floor found from the camera-height window (0.9-1.9 m below the path), not from the glossy surface | partly: the measured home has a tiled floor; a floor was found on all 3 walks (camera 1.72-1.81 m above it, likely 10-20 cm too low — see report) |
| **Low light** | noisy RGB, fewer features, worse learned depth | depth is active (works in the dark); RGB-only damage detection degrades | tracking keeps going on the IMU; triangulated scale gets fewer points (frames borrow neighbours' scale); `low_light_frac` warning above 20 % of frames | warning thresholds checked on the home captures (5 % / 0 % low-light frames → no warning) and on the sample walks; no deliberately dark capture yet |
| **Motion blur** | features and damage cues smear | depth unaffected | fewer triangulated points, blurry damage cues; `blurred_frac` warning | flagged on sample c00a170fe1 (38 % blurred frames) |

Protocol (docs/capture_protocol.md) tells the capturer to keep lights on,
not to dwell on mirrors or glass, and to move slowly; the quality report is
what tells them, after the fact, that they did not.
