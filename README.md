# QuestLHSync for Galaxy XR

Experimental KernelSU camera backend for Samsung Galaxy XR (SM-I610), used with
[QuestLHSync](https://github.com/CreoleVR/QuestLHSync) and Virtual Desktop.
It supplies blob observations from four outward-facing tracking cameras. PC
changes are limited to headset compatibility; the original solver is unchanged.

## Current status

Version 0.4.0 prepares factory calibration automatically on the headset. It reads
this device's factory camera profile and queries the runtime head-origin transform,
then generates all four maps locally. Sensor timestamps use CLOCK_MONOTONIC and
the protocol's half-pixel coordinate convention. No manual calibration is needed.

This is an experimental prerelease validated on one SM-I610 running
`I610UEU2AZF3`. Firmware, QVR libraries and the calibration client are pinned.
Face, eye, depth and color passthrough cameras are not alignment inputs.

## Install

Download the `automatic.zip` and `SHA256SUMS` from the private GitHub release.
Install the ZIP through KernelSU Manager and reboot. If late root loading prevents
automatic startup, use the module Action button. Factory preparation takes a few
seconds and runs before alignment starts. An unavailable calibration service is
retried; unsupported or invalid calibration stops setup with a log message.

Use Virtual Desktop/SteamVR with the QuestLHSync PC compatibility build supporting
**`galaxy_xr_sensor`**, and a separate profile such as `galaxy-xr-sensor-trial`.
Older PC builds reject this calibration kind. The module does not install the PC
patch. Other headset support and the original solver are unchanged.

Calibration is regenerated in private RAM storage on each service start. No
headset calibration or proprietary library is included in the release ZIP.

## Build

Install Python 3, Zig 0.16.0 and Clang/LLD. With a supported headset connected over
ADB and KernelSU root available through `su`:

```sh
python build_module.py --serial ADB_TRANSPORT
```

Output: `build/QuestLHSync-GXR-0.4.0-automatic.zip`.
The build validates firmware and QVR hashes and saves local bionic link inputs
under `build/bionic`. These vendor libraries are never packaged. Offline builds
can use `--bionic-dir build/bionic`, or point it at the Android NDK's
`toolchains/llvm/prebuilt/HOST/sysroot/usr/lib/aarch64-linux-android/29` directory.
Add `--diagnostic` for a module with alignment and automatic setup disabled.

## GitHub Actions

The `Build module` workflow runs on pushes, pull requests and manual dispatch.
The `QuestLHSync-GXR` artifact contains the automatic ZIP and its SHA256 checksum.
It uses Zig 0.16.0 and Android NDK r27d's API 29 link stubs, without a headset.
Pushing a matching version tag (for example `v0.4.0`) publishes the verified
artifact as a prerelease in the private repository. Tags must match both the
builder and module metadata; calibration data is never uploaded.

## Repository layout

- `module/`, `src/`, `vendor/questlhsync/`: KernelSU service and native backend.
- `build_module.py`: automatic, diagnostic, factory-trial and legacy measured-profile packaging.
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
