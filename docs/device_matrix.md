# Device Matrix

| Tier   | Minimum hardware              | Capture tool          | Sensors used                                   | Honest accuracy target (this submission) |
|--------|--------------------------------|------------------------|-------------------------------------------------|-------------------------------------------|
| Photos | iPhone 15 or newer (any model) | Native Camera app      | RGB only, no depth/pose                          | Wall lengths within ±8%, calibrated intervals; footprint within ±8% on the stitched multi-room plan |
| Video  | iPhone 15 or newer (any model) | Native Camera app (video) | RGB video only, no depth/pose                 | Wall lengths within ±3%, calibrated intervals |
| LiDAR  | iPhone 12 Pro/Pro Max or newer ("Pro" line, any generation) | StrayScanner (App Store) | LiDAR depth (256x192, mm), per-pixel ARKit confidence (0/1/2), 6-DoF pose + per-frame intrinsics, raw IMU | Openings ≤2cm on ≥85% detected; ceiling height ≤1.5cm/room, ≤1cm repeat spread |

Non-Pro iPhones (15/16/17 base, non-Pro) cannot run the LiDAR tier — StrayScanner
requires the LiDAR scanner hardware only present on Pro-class devices. They fall
back to photo or video tier automatically; the pipeline's tier selection is by
which input files are present, not by device model string, so this is enforced
by what the phone is physically able to produce rather than by a check in code.
