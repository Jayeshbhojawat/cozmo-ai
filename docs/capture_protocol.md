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
   the LiDAR tier — any iPhone 15 or newer for photo/video tiers). A
   non-Pro iPhone 15 has no LiDAR, so StrayScanner refuses to run on it:
   use the video tier (Spectacular Rec) or photo tier on that phone.
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

## Photo tier (any iPhone, stock Camera app)

For each room, in the order you walk through the home:

1. Make a folder named with a number and the room, e.g. `01_hall`,
   `02_kitchen`, `03_bedroom` (the number is the walking order).
2. Stand near the middle of the room, phone upright (portrait), at chest
   height, pointing straight ahead (not at the floor or ceiling).
3. Take a photo, then turn on the spot about a quarter of the way left and
   take the next one, until you are back where you started: **6 to 8
   photos per room, each overlapping the previous one by about a third**.
   Keep your feet in the same place; only turn.
4. Make sure every doorway of the room appears in at least one photo,
   with both sides of its frame visible.
5. Put that room's photos in its folder. Put all room folders in one
   parent folder, then run:
   `python -m cli.run capture --input <parent folder> --tier photo --out outputs/<name>`

## Video tier (any iPhone 15 or newer) — recommended: Spectacular Rec

**App:** "Spectacular Rec" (free, App Store, by Spectacular AI). It records
normal video **plus the phone's motion sensors**, which lets the pipeline
compute where the phone was at every frame in real metres. No LiDAR needed.

1. Install Spectacular Rec, open it, allow camera + motion access.
2. Stand in the first room, phone upright (portrait) at chest height. Tap record.
3. **Hold still for 2 seconds** (the motion sensors settle), then walk the
   room slowly (~0.3 m/s), pointing at every wall, corner and doorway for
   about 2 seconds each. Tilt up to the ceiling once in the middle of the room.
4. Walk slowly through the doorway into the next room and repeat. One
   continuous recording for the whole home. Avoid fast spins.
5. Stop. In the app's recordings list, share the recording folder (it holds
   `data.mov`, `data.jsonl`, `calibration.json`, `metadata.json`) to the
   computer, then run:
   `python -m cli.run capture --input <recording folder> --tier video --out outputs/<name>`
   (on Apple Silicon Macs use the Docker command in the README: the
   motion-tracking library ships Linux/Windows x86 builds only.)

**Fallback (no app install possible): stock Camera app, Video mode.**
In the middle of every room stop and turn slowly on the spot through one
full circle (10-15 s); walk to the next room and repeat; one clip. Run the
same command with the video file as `--input`. This path has no motion
sensors, so it estimates scale from camera height and is much less accurate.

## If this page is ambiguous

Whatever a literal, first-time follower does under these five sections — install,
walk, avoid, hand-off, tiers — is treated as correct capture. Any looseness here
(how fast is "normal pace", how close a pass counts as a "connector") is expected
to show up as wider confidence intervals at the LiDAR tier and is accepted as
such, per the widening-intervals contract in Part 1.
