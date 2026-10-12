# QuestLHSync for Galaxy XR

Experimental KernelSU camera backend for Samsung Galaxy XR (SM-I610), used with
[QuestLHSync](https://github.com/CreoleVR/QuestLHSync) and Virtual Desktop.
It serves observations from the four outward-facing tracking cameras over the
existing QuestLHSync protocol. The original PC alignment solver is unchanged.

## Status

Live alignment, including seated acquisition, has been confirmed on one headset
with measured per-device calibration. This is not a universal calibrated release.
Only firmware `I610UEU2AZF3` and the pinned QVR client library are supported.
Face, eye, depth and color passthrough cameras are not alignment inputs.

The default build is **diagnostic only**: it emits diagnostic records but no
calibration or alignment observations. Alignment requires a measured profile and
a PC driver that supports `kind: galaxy_xr`, `GxrCameraCalibration` and
`PinholeXY`. Older drivers reject this calibration format.

## Build

Install Python 3, Zig (tested with 0.16.0), Clang/LLD and ADB on the build host.
Connect the supported headset with KernelSU root available through `su`:

```sh
python build_module.py --serial ADB_TRANSPORT
```

The build checks firmware and QVR library hashes, then retrieves `libc.so` and
`libdl.so` from the device as local link inputs. Those libraries are not included
in the ZIP or this repository. For subsequent offline builds:

```sh
python build_module.py --bionic-dir build/bionic
```

The output is `build/QuestLHSync-GXR-0.2.0-diagnostic.zip`. Install it with
KernelSU Manager and reboot. The module Action button can start an already
installed service if this device's KernelSU setup did not start it during boot.
Automatic startup on custom late-loading root configurations remains limited.

## Alignment profile

Place private profiles under the ignored `profiles/` directory:

```sh
python build_module.py --bionic-dir build/bionic --profile profiles/my-headset.json
```

`verified_profile()` in `build_module.py` defines the required v2 schema. It
requires four 640x640 camera calibrations, measured camera-to-HMD rigid transforms,
firmware and serial-hash binding, evidence records, and a positive exposure limit
no greater than 3000 microseconds. Evidence text is a measurement record, not an
automated guarantee of accuracy. No guessed/default alignment profile is supplied.

The resulting trial ZIP contains private calibration and device-binding data;
do not publish it as a general-purpose release.

On the PC, enable `driver_questlhsync.anyHmd`. The compatible PC patch also permits
`driver_questlhsync.profile` (for example `galaxy-xr`) to isolate this headset's
state. Use the dashboard's headset selection or an explicit host setting as needed.
Hold a Lighthouse controller and slowly view both stations. Recentring resets
the pose frame and requires reacquisition.

## Calibration and diagnostics

Optional image-analysis dependencies:

```sh
python -m pip install -r requirements-calibration.txt
```

- `capture_calibration.py`: camera images and optional synchronized HMD poses.
- `fit_tracking_calibration.py`: checkerboard intrinsics and stereo validation.
- `fit_hand_eye.py`: measured camera-to-HMD candidate transforms.
- `capture_lighthouses.py`: offline blobs, HMD poses, stations and clock samples.
- `prepare_replay.py`: convert an audit for the upstream replay executable;
  `--max-exposure-us` and `--output-dir` support offline comparisons.
- `triangulate_spots.py`: source-ray consistency analysis, not station identity proof.
- `build_pose_recorder.cmd PATH_TO_QUESTLHSYNC`: build the Windows pose recorder
  using Visual Studio and OpenVR files from a QuestLHSync checkout. Run the
  resulting executable from `build/` while SteamVR is open.

Use each Python command's `--help` for arguments. Raw calibration observations,
images, libraries, profiles and recordings belong in ignored local directories.
The separate pose recorder does not record controller trajectories; use the
QuestLHSync dashboard's **Record session** for full live alignment diagnostics.

## Runtime

Firmware and library guards run before camera access. The reader copies and
releases QVR buffers before analysis and does not alter exposure settings, camera
configuration, SELinux policy or vendor overlays. The daemon is static musl;
the QVR reader runs as a separate Android bionic process.

TCP 47280 serves clients; UDP 47281 provides discovery. As upstream, the service
is unauthenticated on the LAN. It transmits blob metadata, not camera images.
Clients must send regular `P` heartbeat messages. Capture stops after the last
client's idle grace period. Do not run two daemons on the same ports.

Logs: `/dev/questlhsync-gxr/service.log`. The discovery UUID is randomly generated
and retained at `/data/adb/questlhsync-gxr/id`; it is not the hardware serial.
Disabling/removing the module stops the service, and uninstall retains this ID.

## Attribution

MIT licensed. The vendored daemon/interface and adapted blob detector originate
from QuestLHSync 1.14 by CreoleVR; see `LICENSE` and `vendor/questlhsync/README.md`.
No proprietary QVR libraries, extracted firmware or personal calibration data
are distributed. Changes to PC code are limited to headset compatibility;
acquisition thresholds, solver cadence and station-identity logic remain upstream.
