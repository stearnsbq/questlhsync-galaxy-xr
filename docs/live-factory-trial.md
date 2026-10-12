# Private factory trial (0.3.2)

This workflow uses per-device factory optics and QVR sensor timestamps with the
Galaxy XR PC compatibility patch. It is validated on one SM-I610 running
`I610UEU2AZF3`. Automatic head-origin lookup and generic deployment are not yet
implemented. Keep the previous working module and PC settings for rollback.

## Prepare

From the repository root, install `requirements-factory.txt`, extract the factory
source and inventory it as shown in the [README](../README.md#factory-tools).
Save a successful runtime `FRAME_IMU_0_t_SENSOR_THIRD_EYE` transform under
`build/head-origin.log`. A nominal offset is not a substitute for that transform.

```sh
python prepare_factory_trial.py --serial ADB_TRANSPORT --inventory build/factory-calibration/inventory.json --head-origin-log build/head-origin.log --output-dir build/factory-trial
python build_module.py --serial ADB_TRANSPORT --factory-trial build/factory-trial
```

If bionic link inputs are already available, replace `--serial ADB_TRANSPORT` in
the build command with `--bionic-dir build/bionic`.

Output: `build/QuestLHSync-GXR-0.3.2-factory-trial.zip`. It contains private,
device-bound calibration and must not be published as a generic release.
`--factory-trial` and legacy `--profile` builds are mutually exclusive; a build
without either remains diagnostic.

Regenerate older bundles. Current manifests require:

- `projection_model: window-plane-1m-lut1000`
- `frame_timestamp: sensor-boottime-to-monotonic`
- `pixel_centres: wire-half-pixel`

The preparer checks firmware, QVR library and the current factory source, then
binds the bundle to the hardware serial hash. Startup verifies the packaged
hashes, factory source and serial before capture. Missing calibration fails
closed; there is no fallback to guessed optics.

## Install

Install the private module ZIP through KernelSU Manager and reboot, or use a
reviewed deployment while its service is stopped. Preserve a working rollback.

The PC must support calibration kind `galaxy_xr_sensor`. Close SteamVR before
replacing its DLL. The optional installer can select an isolated profile:

```powershell
.\integration\install-pc-trial.ps1 -Driver PATH_TO_DLL -ExpectedSha256 REVIEWED_SHA256 -BackupDirectory build/pc-backup -Profile galaxy-xr-sensor-trial
```

Do not reuse saved delivery-time estimates from an older trial. The installer
backs up the existing DLL and QuestLHSync settings. With the same backup directory,
`-Rollback` restores them; reinstall the corresponding headset module as well.
The installer defaults to the older `galaxy-xr-factory-trial` profile when
`-Profile` is omitted, so supply the sensor profile explicitly.

## Verify and record

The connection must identify `gxr/factory-trial.json`; camera diagnostics must
show `mode=factory-trial` and `clock=sensor-monotonic`. `map_rejected` counts
blobs outside valid map cells. The existing exposure limit remains 3 ms; longer
exposures can produce gaps in selected alignment frames while cameras keep running.

Use the dashboard's **Record session** command. Save the exact bundled
`calibration.json` alongside each recording. These pixels are already mapped;
**do not run factory recordings through `prepare_factory_replay.py`**.

For a cold-start replay, use a new, empty state directory and no timing override:

```sh
qlhs_replay recordings/session.txt --calib build/factory-trial/calibration.json --dir build/replay-fresh-state --pings --learn --learn-grid
```

## Validation

The 0.3.2 PC driver, dashboard, installer and module built successfully. The
installed DLL and all 19 module files matched the reviewed artifacts.

- Fresh live profile: acquired about 20 seconds after connection and learned
  timing one second later, without saved stations or timing.
- Subsequent 90.47-second recording: 7,356 frames (1,839 per camera), no error
  records or jump events, and all 18 sampled statuses locked. Final stop support
  was 3,372/2,873; residuals ranged from 0.277 to 0.341 degrees.
- Round trip: median 4.00 ms, sampled maximum 15.79 ms.
- Empty-state replay: acquired at 8 seconds, learned timing from the original
  18 ms default, and ended at 2,851/2,343 support with 0.288-degree median residual.
  Logging the unchanged jump detector confirmed zero replay jump events.
- Native map: 50,785 of 53,023 raw blobs accepted; maximum analytical discrepancy
  below 0.071 pixels including wire rounding.
- Compatibility: legacy delivery-timestamp replay decisions were unchanged;
  the older PC build rejected the sensor-stamped calibration kind.

These are fit and stability checks on one headset, not independent absolute
tracking-accuracy measurements. Additional-device, restart and recenter coverage,
and automatic factory preparation remain requirements for a generic release.
Earlier trial results are preserved in Git history through `c7df3a5`.
