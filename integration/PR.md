# Support Galaxy XR calibration and sensor timestamps

An external Galaxy XR backend supplies four tracking-camera streams whose factory
optics need separate horizontal/vertical focal lengths and whose sensor timestamps
are already in the daemon clock. Interpret its `PinholeXY` calibration and
`galaxy_xr_sensor` kind using the existing sensor-timestamp path. Keep legacy
`galaxy_xr` delivery-timestamp support. Older drivers reject the distinct
calibration root instead of silently misinterpreting it.

An optional `driver_questlhsync.profile` isolates stored geometry and learned
timing between headsets and timestamp modes. Missing or invalid names preserve
the existing directory. The selected directory is logged.

The patch targets QuestLHSync 1.14 (`faf2287985e0ccdfd1fb0e4254ad4d8800c78cdb`)
and contains only `src/driver/driver_main.cpp`, `src/driver/sync.cpp`, and
`docs/galaxy-xr.md`. KernelSU packaging, the camera reader and factory preparation
remain separate. Solver code, thresholds, station identity, acquisition cadence,
the dashboard and existing-headset behavior are unchanged.

Validation:

- Windows driver, dashboard, installer and replay tools build with Visual Studio 2022.
- Fresh-profile live startup acquired and learned timing without saved state.
- A 90-second sensor-timestamp recording stayed locked in all 18 sampled statuses
  with no jump events. Empty-state replay also had no jump events and ended with
  support for both stations (2,851/2,343; 0.288-degree median residual).
- Legacy delivery-timestamp replay decisions match the earlier build; older
  compatibility drivers reject the new sensor calibration kind.
- The bundled patch applies to the pinned upstream base and reproduces the
  compatibility branch's three changed files. `git diff --check` passes.

Hardware validation covers one headset and firmware version. Factory preparation
still needs a runtime head-origin transform; this PC patch is not a generic module
release. Angular residuals measure fit, not independent tracking accuracy. The
module remains private during preparation; this PR has not been submitted upstream.
