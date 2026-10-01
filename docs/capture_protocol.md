# Capture Protocol (Route 2 — Stock Capture Tool)

**Tool:** StrayScanner (free, App Store, by Stray Robots). LiDAR logging app for
iPhone 12 Pro and newer (any Pro-class device with a LiDAR scanner). Identified
from the raw export format of the sample data: `rgb.mp4`, `depth/*.png` (16-bit,
256x192, millimeters), `confidence/*.png` (8-bit, values 0/1/2 = ARKit low/medium
/high confidence), `odometry.csv` (per-frame pose + intrinsics), `imu.csv` (raw
accelerometer/gyro), `camera_matrix.csv` (intrinsic matrix). This is StrayScanner's
dataset export layout.

This one page is what a non-engineer follows, verbatim, for every room.

## What to install

1. Open the App Store on the iPhone (iPhone 12 Pro or newer, any "Pro" model, for
   the LiDAR tier — any iPhone 15 or newer for photo/video tiers).
2. Search **"Stray Scanner"**, install it (free). No account/login required.
3. Open the app once and grant camera access when prompted. Nothing else to
   configure.

## How to walk (LiDAR tier)

1. Stand in a corner of the room so you can see as much of the room as possible.
2. Tap the red record button. Hold the phone at chest height, screen facing you,
   roughly level (not pointed at the floor or ceiling).
3. Walk the full perimeter of the room at a normal, unhurried walking pace —
   about 0.3–0.5 m/s. Keep the phone moving smoothly; do not stop-and-go.
4. Point the phone at every wall for at least 2 continuous seconds, including
   corners, doorways, and windows.
5. **Ceiling pass (do not skip):** in the middle of every room, stop, tilt the
   phone up until the screen shows mostly ceiling, hold 2 seconds, tilt back
   down. Without this the app cannot see the ceiling and the plan will say
   "ceiling not observed" for that room.
6. If the room connects to another room through a doorway or open archway, walk
   through it slowly and keep recording into the next room before stopping — this
   is the "connector" pass the multi-room stitch needs. Do not stop and restart
   between connected rooms.
7. Aim to cover the full room in 20–45 seconds. Longer is fine; do not rush.
8. Tap the record button again to stop.

## What to avoid

- Do not walk backwards.
- Do not point the camera at a mirror or window with strong reflections for more
  than 1–2 seconds continuously — glass and mirrors return unreliable depth.
- Do not capture in direct low light (flashlight-only conditions); normal indoor
  lighting is fine.
- Do not cover the True Depth/rear camera cluster with a case or a finger.
- Do not use a tripod or gimbal — handheld only, per the spec.

## How to hand off files

1. In StrayScanner, open the capture you just recorded and tap **Export** (or
   **Share**) → **Save to Files**.
2. Save the exported folder into a single top-level directory named after the
   room, e.g. `living_room/`. It will contain `rgb.mp4`, `depth/`, `confidence/`,
   `odometry.csv`, `imu.csv`, `camera_matrix.csv`.
3. AirDrop or cable-transfer that folder to the machine running the pipeline, or
   drop it into the shared capture inbox folder.
4. Run: `python -m cli.run capture --input living_room/ --tier lidar --out outputs/living_room`
   (see README). One command per capture. A walk through several rooms in one
   recording gives the whole stitched plan from that one command.

## Photo tier (no LiDAR needed)

Use the iPhone's native Camera app. Take 2–8 stills per room, walking a loop and
photographing each wall roughly head-on, plus one photo into any doorway/opening.
Put each room's stills in their own folder (`kitchen/`, `hallway/`, ...). No app
install beyond the stock Camera app.

## Video tier (no LiDAR needed)

Use the iPhone's native Camera app in **Video** mode. Same walking instructions
as the LiDAR tier above (perimeter walk, 20–45 seconds, through connectors without
stopping), just without LiDAR depth recorded. Save as a single `.mov`/`.mp4` per
room (or one continuous clip for a multi-room walkthrough).

## If this page is ambiguous

Whatever a literal, first-time follower does under these five sections — install,
walk, avoid, hand-off, tiers — is treated as correct capture. Any looseness here
(how fast is "normal pace", how close a pass counts as a "connector") is expected
to show up as wider confidence intervals at the LiDAR tier and is accepted as
such, per the widening-intervals contract in Part 1.
