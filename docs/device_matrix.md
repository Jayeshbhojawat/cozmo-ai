# Device Matrix

| Tier | Hardware | Capture | Sensors used | Accuracy this build delivers (honest) |
|---|---|---|---|---|
| LiDAR | iPhone 12 Pro or newer, Pro models only (LiDAR) | StrayScanner (App Store, free), one continuous walk | LiDAR depth 256x192 mm + confidence, ARKit 6-DoF pose + per-frame intrinsics, RGB, IMU | Model 95% intervals: walls +-6-14 mm, doors +-8-12 mm, ceiling +-6 mm (only if the ceiling was filmed). **Not yet confirmed against tape/laser.** |
| Video (primary) | Any iPhone 15 or newer (tested on a non-Pro iPhone 15) | Spectacular Rec (App Store, free), one continuous walk | RGB + accelerometer/gyro; metric 6-DoF poses from visual-inertial odometry (Spectacular AI SDK, free non-commercial); depth shape from Depth Anything V2, its scale fixed per frame by triangulating against neighbouring posed frames | Pipeline runs end to end on an iPhone 15 recording (2 rooms + door, 4.5 min CPU). **Error not yet measured against tape/laser**; intervals held at +-22 %/length (provisional) until scored. |
| Video (fallback) | Any iPhone 15 or newer | Stock Camera (Video), one clip, full turn on the spot in every room | RGB only; depth from Depth Anything V2 (ViT-S, metric indoor) for shape; scale from camera height (1.42 m) | Measured on pivot scans vs LiDAR: room area error RMS 22 % (+-11 % per length). **Does not meet the brief's +-3 % video gate.** Intervals are +-22 %/length to stay calibrated. |
| Photo | Any iPhone 15 or newer | Stock Camera, 6-8 overlapping stills turning on the spot per room, one folder per room | RGB + EXIF focal length; same depth model and scale source | Same pipeline and same measured error as video (+-11 % per length RMS). **Does not meet the +-8 % photo gate yet.** |

Tier selection follows from the input given (`--tier`), so a non-Pro phone
simply cannot produce a LiDAR capture; it uses the photo or video tier.

Scale assumption for photo/video: the phone is held at chest height. On our
three LiDAR walks the measured camera height was 1.40, 1.40 and 1.46 m
(same person). A much taller or shorter person shifts every dimension
proportionally; this is the dominant systematic error of those tiers.
