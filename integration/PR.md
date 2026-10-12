# Add Galaxy XR camera calibration compatibility

Galaxy XR's measured tracking-camera calibration has separate horizontal and
vertical focal lengths. The current PC loader cannot consume that calibration
without losing information. This adds a distinct Galaxy XR calibration root and
the four-coefficient `PinholeXY` projection used by its external KernelSU backend.
Older PC drivers reject the distinct root instead of misreading its coefficients.

An optional `driver_questlhsync.profile` isolates the headset's stored geometry
and timing from an existing Quest or Steam Frame installation. Unset or invalid
profile names preserve the existing directory. The selected directory is logged.

The PR contains only two PC source changes and backend integration documentation.
The camera reader, KernelSU package, and calibration tools live separately. It
does not change acquisition cadence, solver thresholds, station identity logic,
the dashboard, or the existing headset protocols.

Validation:

- Windows driver, dashboard and installer build successfully with Visual Studio 2022.
- The existing Galaxy XR trial using this calibration format aligned live through
  Virtual Desktop; the user confirmed standing and seated operation.
- A fresh seated replay acquired at 32 seconds, retained support for both base
  stations, and reported good geometric conditioning by 50 seconds.
- `git diff --check` passes. No personal calibration or device identifiers included.

Limitations: hardware validation covers one Galaxy XR and one firmware version.
Calibration remains per-device and experimental. Replay angular residuals are
fit metrics, not independent controller-accuracy measurements. The external
module is private during preparation; this PR is not yet submitted upstream.
