# QuestLHSync for Galaxy XR

Experimental KernelSU camera backend for Samsung Galaxy XR (SM-I610), used with
[QuestLHSync](https://github.com/CreoleVR/QuestLHSync) and Virtual Desktop.
It supplies blob observations from four outward-facing tracking cameras. PC
changes are limited to headset compatibility; the original solver is unchanged.

## Current status

Version 0.3.2 uses per-device factory optics, sensor timestamps converted to
CLOCK_MONOTONIC, and the protocol's half-pixel coordinate convention. Fresh-profile
live startup and empty-state replay passed timing learning without jump resets
on one headset running `I610UEU2AZF3`.

This is a private trial, not a generic calibrated release. Preparation still
requires a saved runtime head-origin transform. Firmware and QVR libraries are
pinned. Face, eye, depth and color passthrough cameras are not alignment inputs.

## Build and install

Install Python 3, Zig (tested with 0.16.0), Clang/LLD and ADB. Connect the supported
headset with KernelSU root available through `su`.

For a **diagnostic-only** module (no calibration or alignment frames):

```sh
python build_module.py --serial ADB_TRANSPORT
```

The build validates firmware and QVR hashes and saves local bionic link inputs
under `build/bionic`. These vendor libraries are never packaged. Subsequent
offline builds can use `--bionic-dir build/bionic`.

Output: `build/QuestLHSync-GXR-0.3.2-diagnostic.zip`. Install through KernelSU
Manager and reboot. If late root loading prevents automatic startup, use the
module Action button.

Alignment requires the PC patch supporting **`galaxy_xr_sensor`** and a separate profile
such as `galaxy-xr-sensor-trial`. Older PC builds reject the new calibration kind.
Existing measured profiles remain supported through `build_module.py --profile` for legacy rollback.

## Factory trial

```sh
python -m pip install -r requirements-factory.txt
python read_factory_calibration.py --serial ADB_TRANSPORT
python inspect_factory_profile.py build/factory-calibration/factory-device-profile.textproto --output build/factory-calibration/inventory.json
```

The source is `/mnt/vendor/efs/device_profile.textproto`; the profile under
`/vendor/etc/calibration_service/` is a nominal fallback and must not replace it.
Keep extracted profiles, head transforms, recordings, images, maps and vendor
libraries in ignored local directories. Device-bound trial ZIPs are private.

Save a successful runtime `FRAME_IMU_0_t_SENSOR_THIRD_EYE` transform in
`build/head-origin.log`, then prepare and build the factory trial:

```sh
python prepare_factory_trial.py --serial ADB_TRANSPORT --inventory build/factory-calibration/inventory.json --head-origin-log build/head-origin.log --output-dir build/factory-trial
python build_module.py --serial ADB_TRANSPORT --factory-trial build/factory-trial
```

Install `build/QuestLHSync-GXR-0.3.2-factory-trial.zip` through KernelSU Manager.
Regenerate bundles from older versions rather than reusing their timing metadata.

| Tool | Purpose |
| --- | --- |
| `read_factory_calibration.py` | Read the firmware-pinned factory source. |
| `inspect_factory_profile.py` | Extract four camera models and their validity limits. |
| `prepare_factory_trial.py` | Build a guarded private factory-map bundle. |
| `factory_camera_model.py` | Shared spline and curved-window model. |
| `prepare_factory_replay.py` | Remap raw-pixel recordings for offline investigation. |
| `evaluate_factory_calibration.py` | Compare fixed factory geometry with saved checkerboard observations. |

Record sessions through the QuestLHSync dashboard to include poses, controllers
and clock round trips. Factory recordings already contain mapped pixels: replay
them directly with their exact bundled calibration. The offline converter cannot
recover sensor timestamps from older delivery-timestamp recordings.

Earlier model notes, experiments and removed manual-calibration tools are
retained in Git history.

## Repository layout

- `module/`, `src/`, `vendor/questlhsync/`: KernelSU service and native backend.
- `build_module.py`: diagnostic, factory-trial and legacy measured-profile packaging.
- `build/`: ignored generated artifacts and private investigation data.

The PC compatibility patch is maintained in the separate QuestLHSync checkout
and targets QuestLHSync 1.14 (`faf2287`).

## Runtime

Firmware and library guards run before camera access. The reader copies and
releases QVR buffers before analysis. It does not change exposure settings,
camera configuration, SELinux policy or vendor overlays. The daemon uses static
musl; the camera reader runs separately with Android bionic.

TCP 47280 serves clients and UDP 47281 provides discovery. As upstream, the LAN
service is unauthenticated and sends blob metadata rather than images. Clients
must send regular `P` heartbeats. Capture stops after the last client's idle
grace period. Do not run two daemons on the same ports.

Logs: `/dev/questlhsync-gxr/service.log`. The random discovery UUID persists in
`/data/adb/questlhsync-gxr/id`; it is not the hardware serial. Disabling/removing
the module stops its service; uninstall retains the UUID.

## Attribution

MIT licensed. The vendored daemon/interface and adapted detector originate from
QuestLHSync 1.14 by CreoleVR; see [vendor provenance](vendor/questlhsync/README.md).
No proprietary libraries, firmware or personal calibration data are distributed.
