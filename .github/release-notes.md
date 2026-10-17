Galaxy XR 0.5.2 for Samsung Galaxy XR (SM-I610), firmware I610UEU2AZF3.

Adds an **Exit settings** button to close the module's configuration page using
KernelSU's native WebUI exit action. The button remains available if settings
fail to load. Managers without the exit API show a reminder to use system Back.
Exiting does not save pending slider changes; use **Save & apply** first.

Includes the exposure and diagnostic improvements from 0.5.1 described below.

Expands the offline KernelSU WebUI exposure cutoff from 1–5 ms to 1–10 ms,
in 0.1 ms steps. Automatic factory calibration now defaults to 10 ms, allowing
observations when camera exposure stays above the previous 5 ms limit.
The cutoff filters captured frames; it does not change camera exposure.
Longer exposures may reduce accuracy during motion.

Existing saved cutoffs are preserved during an update. To adopt 10 ms, open
the module WebUI, choose **Use default**, then **Save & apply**. Legacy calibration
bundles retain their own limits.

Adds per-camera cutoff, rejected-exposure, observation-frame, empty-frame and
accepted-frame-age diagnostics to distinguish exposure rejection from missing
detections. These counters do not certify an alignment lock. Exposure parsing
also rejects malformed and out-of-range values without integer overflow.

The wider cutoff has automated policy coverage; this release does not claim
new headset accuracy or tracking validation at 10 ms.

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
