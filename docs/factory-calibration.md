# Factory model and validation tools

The current private trial uses the runtime-selected factory profile from
`/mnt/vendor/efs/device_profile.textproto`. Never silently substitute the nominal
profile under `/vendor/etc/calibration_service/`. Firmware and QVR library
versions are pinned by the module guards.

For installation and measured results, see [factory trial setup](live-factory-trial.md).
All extracted profiles, vendor libraries, head transforms and captures belong in
ignored local directories.

## Camera model

The four buffers are `tracking:0`, `tracking:1`, `ctrl-tracking:0` and
`ctrl-tracking:1`, each 640 by 640 pixels. Their factory models combine:

1. A `fisheye_spline3` radial cubic Hermite gain with knots at 0, 30, 60 and
   90 degrees. Six coefficients hold the three nonzero-knot value/slope pairs.
2. Numerical radial inversion and a distortion offset in undistorted x/z, y/z.
3. Air/glass/air refraction through spherical surfaces at radius minus/plus
   half the cover-window thickness.
4. A central projection onto a plane one metre along the negated, normalized
   sphere-centre axis, represented by a 1,000-entry cosine-indexed correction table.

Both factory radius limits are enforced. `factory_projection_rays` implements
this central model. `factory_rays` retains physical exit origins/directions and
alternative window hypotheses for developer comparisons. Far-field direction
alone is not the current factory projection.

The map stores virtual equidistant pixels with focal lengths 200 and principal
point (320,320). Bilinear interpolation rejects invalid cells conservatively.
The detector and protocol use pixel centres at `n + 0.5`: subtract the half pixel
before lookup and restore it on output, since the PC removes it when making rays.

This is an independent implementation inferred from the pinned firmware.
Bitwise parity with the native calibration service is not claimed. Full-area
native comparisons, including rejection boundaries, remain useful validation.

## Coordinate frames

The supported convention is
`IMUFromCamera = [transpose(R(quaternion)), stored_position]`.
A successful runtime `FRAME_IMU_0_t_SENSOR_THIRD_EYE` log supplies the head
axis-angle rotation and translation, giving
`HeadFromCamera = inverse(IMUFromHead) * IMUFromCamera`.

Do not add the system third-eye Z-offset property again. The recorded comparison
favoured the logged transform without that additional offset. No user's head
transform is embedded in source. A stable runtime API and verification across
startup/IPD states are still required for automatic preparation.

## Timestamp contract

QVR sensor stamps use BOOTTIME; daemon clock replies use CLOCK_MONOTONIC. The
reader brackets a fresh clock-offset sample for every frame, with at most 0.1 ms
midpoint uncertainty. It rejects invalid, future, stale or non-increasing converted
stamps instead of substituting delivery times. Recomputing the offset handles
accumulated suspend time.

Calibration kind `galaxy_xr_sensor` selects the existing PC sensor-time path,
without subtracting estimated polling lag. Automatic pose-timing learning remains
unchanged. Legacy `galaxy_xr` profiles retain delivery timestamps and their
existing behavior. Keep their saved timing in separate PC profiles.

## Developer comparisons

Install `requirements-factory.txt` and generate an inventory using the README
commands. To compare fixed factory geometry against an existing checkerboard
capture containing `metadata.json` and `calibration/detections.json`:

```sh
python evaluate_factory_calibration.py build/factory-calibration/inventory.json build/checkerboard-session --window native --output build/factory-comparison.json
```

This fits board poses, not replacement camera calibration. The 29-view check
reported a median angular pixel-equivalent RMS of 0.708. That metric is unit-ray
chord error scaled by focal length, not literal reprojection error or absolute
tracking accuracy.

For **legacy raw-pixel** recordings only:

```sh
python prepare_factory_replay.py recordings/raw-session.txt --inventory build/factory-calibration/inventory.json --head-origin-log build/head-origin.log --window native --output-dir build/factory-replay
qlhs_replay build/factory-replay/replay.txt --calib build/factory-replay/calibration.json --dir build/factory-replay/fresh-state --pings --learn --learn-grid
```

Pixel remapping preserves the original timestamps, brightness, blob sizes and
peaks. It cannot reconstruct discarded sensor timestamps; its calibration keeps
legacy `galaxy_xr` timing. Never label an arrival-only recording as sensor-stamped,
remap an already-converted factory recording, or install offline replay calibration
with a raw-pixel reader. Virtual image bounds also do not exactly represent
physical sensor visibility.

## Remaining work

- Read the head-origin transform through a stable runtime API.
- Replace private host preparation with automatic on-device factory preparation.
- Compare the full model against native service output across the sensor area.
- Expand live, restart/recenter, exposure and additional-headset validation.

Earlier hypotheses, firmware investigation notes and regression results remain
in Git history through `c7df3a5`. Removed manual calibration tools are recoverable
at `ac53e6b`; they are not part of the current setup workflow.
