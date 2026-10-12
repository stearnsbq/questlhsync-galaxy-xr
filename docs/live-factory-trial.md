# Private live factory trial (0.3.0)

This trial converts blob coordinates inside the Galaxy XR reader. It uses the
factory spline, distortion offset, cover-window midpoint model and validity
radii to build a 640x640 lookup map for each of four cameras. The PC receives
virtual equidistant pixels with a matching calibration through the existing
Galaxy XR compatibility patch. The alignment solver is unchanged.

This is **not a generic calibrated release**. Preparation requires ADB root,
the current factory profile inventory and a saved successful runtime head-origin
transform. Automatic head-origin lookup is still missing. The model has a known
late support-collapse case in recorded-data validation; see
[the investigation](factory-calibration.md). Keep a measured-profile rollback.

## Prepare and build

Install `requirements-factory.txt` and regenerate the factory inventory as shown
in the README. Then, from the repository root:

```sh
python prepare_factory_trial.py --serial ADB_TRANSPORT --inventory build/factory-calibration/inventory.json --head-origin-log build/head-origin.log --output-dir build/factory-trial
python build_module.py --bionic-dir build/bionic --factory-trial build/factory-trial
```

Output: `build/QuestLHSync-GXR-0.3.0-factory-trial.zip`. This ZIP contains private,
device-bound derived calibration. Do not publish it as a generic release.
`--factory-trial` and the existing measured `--profile` option are mutually
exclusive. A build without either option remains diagnostic.

The preparer verifies firmware, QVR library and the current factory-source hash,
then binds the bundle to the headset serial hash. The launcher checks the bundle
manifest and current source/serial before capture. The native reader rejects a
bad map header, wrong dimensions, truncated/trailing data and invalid coordinates.
No missing-data fallback to guessed optics is provided.

Maps use little-endian float pairs and bilinear interpolation. Invalid corners
reject the blob conservatively. The existing 3 ms exposure limit, detector,
timestamps, blob size and peak brightness remain unchanged. No exposure control
or vendor service changes are made.

## Install and check

Install the private ZIP through KernelSU Manager and reboot, or use a reviewed
development deployment while the service is stopped. Preserve the measured ZIP
and a backup of the installed module before replacing it.

Close SteamVR before updating the PC compatibility DLL. The optional
`integration/install-pc-trial.ps1` accepts `-Driver`, `-ExpectedSha256` and
`-BackupDirectory`; it saves the old DLL and QuestLHSync settings, then selects
the separate `galaxy-xr-factory-trial` profile. With the same backup directory,
`-Rollback` restores the old DLL and driver settings. It does not restore the
headset module; reinstall the measured-profile ZIP as well. No other SteamVR
settings are intentionally changed.

On connection, the calibration record must name `gxr/factory-trial.json` and
camera diagnostics must show `mode=factory-trial`. `map_rejected` counts rejected
blob coordinates per camera. Use the dashboard's recording function to collect
poses, station/controller observations and already-converted camera blobs.
**Do not run those factory recordings through `prepare_factory_replay.py` again:**
their coordinates are already converted. Replay them directly with the exact
bundled `calibration.json`.

The first native implementation was checked against 53,023 raw blobs from the
90-second regression recording. It accepted 50,802, with at most 0.071 pixels
error versus the Python model including tenths-of-a-pixel wire rounding. It
rejected 103 additional boundary blobs compared with direct conversion. The
native-map replay reproduced the known late regression, so numerical parity
does not establish tracking reliability. A headset protocol check confirmed
factory calibration and converted frames from all four cameras without errors.

## First live alignment check

After installing the 0.3.0 trial and the clean PC compatibility build, the driver
acquired alignment in the separate factory profile. A subsequent 90.5-second
recording contained 18,692 converted frames across all four cameras and no error
records. All 18 five-second status samples remained locked; median angular
residuals ranged from 0.289 to 0.314 degrees. Median round trip was 3.97 ms, with
one sampled peak of 9.45 ms. Ending station support was 2,752/4,480.

This recording began after live acquisition. Replaying it from fresh state with
recorded pings initially selected a mirrored solution at 21 seconds, corrected
it at 42 seconds, and ended with both stations supported. It does not establish
repeatable startup acquisition or absolute positional accuracy. The earlier
regression recording remains unresolved even though this live check was stable.
