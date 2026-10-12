# Factory calibration investigation

Status: experimental offline conversion, validated on recordings from one Galaxy
XR running `I610UEU2AZF3`. This does not enable a calibration-free live module.
Keep extracted profiles, libraries, runtime logs and generated outputs under
ignored `build/`; none is a distributable calibration asset.

## Model and coordinate frames

Use the runtime-selected `/mnt/vendor/efs/device_profile.textproto`, extracted
with `read_factory_calibration.py`. The vendor-directory profile is a nominal
fallback and must not silently replace a missing factory profile.

The four logical buffers are tracking:0, tracking:1, ctrl-tracking:0 and
ctrl-tracking:1. The observed factory entries use fisheye_spline3, a distortion
offset and a curved cover window. The Python model implements:

1. A radial cubic Hermite gain with knots at 0, 30, 60 and 90 degrees. Gain
   correction and slope start at zero; the six stored coefficients are the
   remaining three value/slope pairs. The distorted radius is angle times gain.
2. Numerical radial inversion followed by an offset in undistorted x/z, y/z.
3. Two spherical intersections and air/glass/air Snell refraction. The `mid`
   candidate uses inner/outer radii equal to radius minus/plus half thickness.
   `inner` and `outer` retain earlier hypotheses for comparison; `none` disables
   the window explicitly.

This is an independently implemented experimental model inferred by inspecting
the locally installed firmware. It is not yet verified numerically against the
native runtime's lookup-table output. Useful function addresses in the pinned
`libperception_calibration_host_plugin.so` are `0xc1d6a8` (radial evaluator),
`0xc26d40` (combined unprojection) and `0xfd5a18` (sphere refraction, including
radius minus/plus half thickness). That library's SHA256 is
`6ba0b15f762a6d398cde102c0b527e01f06cbce0a26a9d3307a5e465fa2ef517`.
Addresses apply only to this exact binary; no vendor binary is distributed.

The best factory extrinsic convention in the checkerboard comparison is
`IMUFromCamera = [transpose(R(quaternion)), stored_position]`. Among four
tested conventions, this yields a median per-view RMS ray discrepancy of
0.49 pixel equivalents across 29 synchronized views without the window. Other
conventions yield 26–105. This metric is unit-ray chord error times mean focal
length, not image reprojection error or an independent accuracy measurement.
With the `mid` window enabled and physical exit points retained, the same winning
convention gives 0.74 median and 0.90 maximum per-view RMS pixel equivalents.

For the current offline experiment, a successful runtime
`FRAME_IMU_0_t_SENSOR_THIRD_EYE` log provides an axis-angle rotation and translation.
Then `HeadFromCamera = inverse(IMUFromHead) * IMUFromCamera`.
Do not add the system third-eye Z-offset property again: the logged transform
already performed better without that additional offset in the recorded
checkerboard comparison. This remains an inferred convention requiring a stable
runtime API and verification across headset startup/IPD states. No user's head
transform is embedded in source.

## Reproduce the offline comparison

Install `requirements-factory.txt`, then extract/inventory the factory file
as described in the README. The optional checkerboard comparison consumes saved
validation data: `metadata.json` with grid width and frame timestamps, and
`calibration/detections.json` with detected 9x6 corner coordinates. The former
capture/fitting tools are available in Git history at `ac53e6b`; they are no longer
part of the module's supported workflow. Existing private captures remain usable:

```sh
python evaluate_factory_calibration.py build/factory-calibration/inventory.json build/checkerboard-session --window mid --output build/factory-comparison.json
```

Record a full session through QuestLHSync's dashboard, including controller
positions and clock round trips. Save the successful runtime transform log to a
private local file. To convert a recording:

```sh
python prepare_factory_replay.py recordings/session.txt --inventory build/factory-calibration/inventory.json --head-origin-log build/head-origin.log --window mid --output-dir build/factory-replay
qlhs_replay build/factory-replay/replay.txt --calib build/factory-replay/calibration.json --dir build/factory-replay/fresh-state --expo 0.045
```

Use a new state directory for each comparison. These commands reproduce the
fixed 45 ms timing comparison below, using the replay tool's default arrival
clock. They do not validate automatic live timing; `--expo` is a replay parameter,
not a change to the installed driver.

The converter preserves non-frame records and frame timestamps, brightness,
blob sizes and peaks. It remaps raw pixel coordinates to a virtual equidistant
camera (focal length 200, principal point 320,320). Its calibration only makes
sense with its **remapped recording**. Installing it with the raw-pixel reader
would produce incorrect rays. Invalid/out-of-domain rays are counted and omitted.
Window exit positions are discarded in this far-field replay, and virtual image
bounds do not exactly reproduce physical sensor visibility.

## Recorded results

The original solver, acquisition thresholds and station-identity logic were
unchanged. All captures came from the same headset and room. Residuals describe
the solver fit, not absolute tracking accuracy.

| Capture/model | Acquisition | Later median residual | Later station support |
| --- | --- | --- | --- |
| Seated, measured profile | 32 s | 0.313 degrees at 50 s | 306 / 312 |
| Seated, factory without window | 32 s | 0.329 degrees at 50 s | 7 / 73 |
| Seated, factory window `inner` | 28 s | 0.330 degrees at 50 s | 412 / 381 |
| Seated, factory window `outer` | 28 s | 0.333 degrees at 50 s | 423 / 374 |
| Seated, factory window `mid` | 28 s | 0.334 degrees at 50 s | 410 / 391 |
| Standing, factory window `inner` | 26 s | 0.319 degrees at 60 s | 1243 / 151 |
| Recentered, factory window `inner` | 36 s, then 57 s | 0.296 degrees at 70 s | 357 / 677 |

The recentered recording has pose breaks at approximately 28 and 50 seconds.
The standing audit lacks controller trajectories, so it is a weaker identity
check than the dashboard recordings. Seated conversion retained 23,426 blobs
and rejected eight out-of-domain blobs. Small differences between window radius
hypotheses cannot establish the correct model by replay performance alone.

### Fresh 90-second validation capture

A subsequent 90.5-second dashboard recording included 16,135 frames from all four
cameras, controller positions, stations and clock round trips. The installed
measured-profile module acquired within the first ten seconds of sampled status
and remained locked. This was a live baseline capture, not live factory alignment.

With fresh replay state and fixed 45 ms timing, both measured and factory `mid`
calibration acquired at 11 seconds and confirmed station ordering at 22 seconds.
At 80 seconds the factory replay had 471/480 station support and a 0.344-degree
median residual. At 90 seconds support fell to 16/51 and its estimate shifted by
approximately 7.5 cm and 1.4 degrees relative to its 80-second estimate. The
measured replay retained 339/389 support at 90 seconds. A second comparison using
recorded pings and learned timing also reproduced the factory support collapse
(18/54 at 90 seconds); the issue is not resolved by using automatic timing.

Frame gaps coincided with exposure exceeding the existing 3 ms selection limit.
During the longest approximately 4.7-second gap, camera frame counters continued
at about 60 Hz while short-exposure counters stopped, with diagnostic exposure
values around 3.4–3.8 ms. The source cameras were still running. The module's
exposure filter withheld alignment frames as designed. Whether this interruption
triggers the factory fit instability is not yet established.

The extracted factory profile was unchanged. The replay still uses the previously
observed head-origin transform; it has not been read through a current runtime
API. This new capture is a regression case to retain when validating the model;
the earlier successful captures alone are not sufficient for release.

## Remaining integration work

- Obtain the current head-origin transform reliably through the calibration
  service. Boot logs rotate and cannot be the production dependency. A device
  configuration's nominal head offset also is not the measured runtime transform.
- Confirm native curved-window lookup semantics and compare rays over the full
  usable sensor area, including rejection boundaries.
- Implement guarded on-device factory parsing and ray conversion, validating
  firmware, source, camera order and frame transforms before emitting alignment
  observations. Missing/invalid calibration must leave alignment disabled.
- Validate live operation, exposure selection, timing, restart/recenter behavior
  and additional headsets before distributing a generic release.

The default module build and upstream PC compatibility patch remain unchanged.
