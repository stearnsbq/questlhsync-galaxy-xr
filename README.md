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

Existing live trial profiles can still be built using the
[measured-profile instructions](docs/measured-profile.md). Factory replay output
is not a replacement for a live profile yet.

## Factory calibration

On the supported firmware, boot logs confirm the runtime loads per-device factory
calibration from `/mnt/vendor/efs/device_profile.textproto`. The profile under
`/vendor/etc/calibration_service/` is an average-device fallback. Extract the
factory source without modifying the headset:

```sh
python read_factory_calibration.py --serial ADB_TRANSPORT
python inspect_factory_profile.py build/factory-calibration/factory-device-profile.textproto --output build/factory-calibration/inventory.json
```

The factory tracking models include fisheye spline coefficients, distortion offsets
and curved-window refraction. These cannot be copied into the existing KB4/Fisheye62
coefficient fields. Experimental factory-ray conversion now acquires alignment in
saved seated, standing and recentering recordings with the existing solver.
Automatic startup calibration and live factory-ray conversion are not implemented;
the working module still uses its measured profile. See
[factory calibration investigation](docs/factory-calibration.md) for reproducible
commands, model assumptions and remaining work.
Keep the extracted file private and under the ignored `build/` directory.

Factory analysis dependencies:

```sh
python -m pip install -r requirements-factory.txt
```

- `read_factory_calibration.py`: retrieve the firmware-pinned factory source.
- `inspect_factory_profile.py`: inventory the four tracking camera models.
- `factory_camera_model.py`: spline, distortion-offset and cover-glass ray model.
- `prepare_factory_replay.py`: convert dashboard recordings for offline replay.
- `evaluate_factory_calibration.py`: validate fixed factory geometry against saved
  checkerboard observations; this does not fit a replacement camera calibration.

Use the QuestLHSync dashboard's **Record session** for recordings that include
controller positions and clock round trips. Generated profiles, recordings,
images and vendor libraries stay in ignored local directories. The former manual
calibration and standalone recording tools are recoverable from Git history at
`ac53e6b`.

## Repository layout

- `module/`, `src/`, `vendor/questlhsync/`: KernelSU service and native camera backend.
- `build_module.py`: guarded diagnostic or existing measured-profile builds.
- `docs/`: factory model validation and live-trial compatibility instructions.
- `integration/`: the separate upstream PC compatibility patch and PR description.
- `build/`: ignored local artifacts and private investigation data.

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
