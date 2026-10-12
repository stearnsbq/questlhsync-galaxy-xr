# QuestLHSync for Galaxy XR

Experimental KernelSU module that connects Samsung Galaxy XR tracking cameras to
[QuestLHSync](https://github.com/CreoleVR/QuestLHSync) for Lighthouse alignment
with Virtual Desktop and SteamVR.

The module uses four outward-facing tracking cameras and prepares calibration
from the headset's factory data automatically at startup. No manual camera
calibration is required.

## Requirements

- Samsung Galaxy XR (SM-I610), firmware `I610UEU2AZF3`.
- KernelSU.
- Virtual Desktop and SteamVR.
- A QuestLHSync PC build with Galaxy XR support.

Firmware and camera-library compatibility are checked before startup. Other
firmware versions are currently unsupported. Face, eye, depth and color
passthrough cameras are not used for alignment.

## Installation

Download the module ZIP from [Releases](https://github.com/stearnsbq/questlhsync-galaxy-xr/releases),
install it through KernelSU Manager, and reboot. Use the module's Action button
if the service does not start automatically.

The module prepares calibration on the headset before starting the camera
service. The compatible QuestLHSync PC driver must be installed separately.

## Building

Requires Python 3, Zig 0.16.0, and Clang/LLD. Build with Android NDK arm64 API 29
link libraries:

```sh
python build_module.py --bionic-dir /path/to/ndk/toolchains/llvm/prebuilt/HOST/sysroot/usr/lib/aarch64-linux-android/29
```

Alternatively, use `--serial ADB_TRANSPORT` to obtain link libraries from a
connected supported headset. Output ZIPs are written to `build/`. Add
`--diagnostic` to build without automatic calibration or alignment.

GitHub Actions builds the module on pushes, pull requests and manual runs.
Version-tag builds publish prereleases. To publish an existing tag manually,
run the workflow with `release_tag` set to that tag; leave it blank for a build
only. Releases include a ZIP and SHA256 checksum.

## Service

The service uses TCP port 47280 and UDP port 47281 for discovery. It sends
tracking observations rather than camera images. The LAN service is
unauthenticated and should be used on a trusted network.

Logs are available at `/dev/questlhsync-gxr/service.log`. Disabling or removing
the module stops the service. Calibration is generated locally and is not
included in distributed packages.

## License

MIT licensed. Includes code from QuestLHSync by CreoleVR; see
[vendor provenance](vendor/questlhsync/README.md).
