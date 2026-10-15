Configurable exposure cutoff for Samsung Galaxy XR (SM-I610), firmware I610UEU2AZF3.

Adds an offline KernelSU WebUI with a persistent 1–5 ms exposure cutoff and
Save & apply to restart capture. Automatic factory calibration now defaults to
5 ms. The cutoff filters frames rather than changing camera exposure. Legacy
calibration bundles keep their existing limits.

A live 5 ms trial maintained approximately 240 usable frames per second across
four cameras and 0.28–0.32 degree alignment error during the observed locked
portion. This is limited testing on one headset, not a guarantee for every setup.

Fixes rejection of valid camera timestamps when BOOTTIME and MONOTONIC have
little or no accumulated suspend offset. Clock failures now include the reason
and sampled values for diagnosis. Future, stale and non-increasing timestamps
remain rejected.

Install the `automatic.zip` in KernelSU Manager and reboot. If late root loading
prevents startup, use the module Action button. Setup reads this headset's factory
camera profile and queries its runtime head-origin transform, then generates the
four tracking-camera maps locally. No checkerboard, Python, ADB preparation, or
calibration from another headset is needed by the installer.

Requires Virtual Desktop/SteamVR and the QuestLHSync PC compatibility build that
supports Galaxy XR. The module does not install the PC driver.

The archive includes no vendor libraries, recordings, or per-device calibration.
Generated calibration stays in private RAM storage and is refreshed each service
start. Setup refuses unsupported firmware, calibration clients, and invalid
factory data; unavailable runtime calibration is retried before serving alignment.

Experimental prerelease for the supported firmware. Face, eye, depth, and color
passthrough cameras are not alignment inputs.
Logs are in `/dev/questlhsync-gxr/service.log`. Disable the module and reboot to
stop it. `SHA256SUMS` accompanies the installable archive.
