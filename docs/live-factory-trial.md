# Private live factory trial (0.3.2)

This trial converts blob coordinates inside the Galaxy XR reader. It uses the
factory spline, distortion offset, cover-window central projection and validity
radii to build a 640x640 lookup map for each of four cameras. The PC receives
virtual equidistant pixels with a matching calibration through the existing
Galaxy XR compatibility patch. The alignment solver is unchanged.

This is **not a generic calibrated release**. Preparation requires ADB root,
the current factory profile inventory and a saved successful runtime head-origin
transform. Automatic head-origin lookup is still missing. Version 0.3.1 fixes a
projection mismatch and avoids the earlier late support-collapse replay; see
[the investigation](factory-calibration.md). Keep a measured-profile rollback.

## Prepare and build

Install `requirements-factory.txt` and regenerate the factory inventory as shown
in the README. Then, from the repository root:

```sh
python prepare_factory_trial.py --serial ADB_TRANSPORT --inventory build/factory-calibration/inventory.json --head-origin-log build/head-origin.log --output-dir build/factory-trial
python build_module.py --bionic-dir build/bionic --factory-trial build/factory-trial
```

Output: `build/QuestLHSync-GXR-0.3.2-factory-trial.zip`. This ZIP contains private,
device-bound derived calibration. Do not publish it as a generic release.
`--factory-trial` and the existing measured `--profile` option are mutually
exclusive. A build without either option remains diagnostic.

The preparer verifies firmware, QVR library and the current factory-source hash,
then binds the bundle to the headset serial hash. The launcher checks the bundle
manifest and current source/serial before capture. The native reader rejects a
bad map header, wrong dimensions, truncated/trailing data and invalid coordinates.
No missing-data fallback to guessed optics is provided.

Regenerate bundles for 0.3.2: the builder rejects older bundles without
`projection_model: window-plane-1m-lut1000`. The midpoint glass surfaces feed
a central projection onto a plane one metre along the window axis, with the
firmware's 1,000-entry correction lookup. Using the outgoing physical direction
alone, as in 0.3.0, is a different camera model.

The manifest also requires `frame_timestamp: sensor-boottime-to-monotonic` and
`pixel_centres: wire-half-pixel`. The calibration kind is `galaxy_xr_sensor`,
which older PC compatibility drivers reject instead of misinterpreting timestamps.

Maps use little-endian float pairs and bilinear interpolation. Invalid corners
reject the blob conservatively. Detector coordinates have centres at `n + 0.5`;
conversion subtracts 0.5 before lookup and adds it back for the wire format.
The existing 3 ms exposure limit, detector, blob size and peak brightness remain
unchanged. No exposure control
or vendor service changes are made.

The factory reader converts QVR sensor BOOTTIME to CLOCK_MONOTONIC per frame,
bracketing the clock sample to limit uncertainty to 0.1 ms. Missing, future,
over-one-second-old or non-increasing converted timestamps stop capture. It never
silently substitutes delivery times. Recomputing the clock offset handles suspend.
The PC selects its existing sensor-timestamp path, without altering the solver
or timing estimator. Measured-profile and diagnostic modes retain delivery times.

## Install and check

Install the private ZIP through KernelSU Manager and reboot, or use a reviewed
development deployment while the service is stopped. Preserve the measured ZIP
and a backup of the installed module before replacing it.

Close SteamVR before updating the PC compatibility DLL. Version 0.3.2 requires
the PC compatibility build supporting `galaxy_xr_sensor`. The optional
`integration/install-pc-trial.ps1` accepts `-Driver`, `-ExpectedSha256` and
`-BackupDirectory`; it saves the old DLL and QuestLHSync settings, then selects
the separate `galaxy-xr-factory-trial` profile by default. Pass
`-Profile galaxy-xr-sensor-trial` for 0.3.2; do not inherit saved delivery-time
estimates. With the same backup directory,
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
repeatable startup acquisition or absolute positional accuracy. This is historical
0.3.0 evidence; it does not validate the updated 0.3.1 map.

## Projection correction validation

The 0.3.1 native-map replay of the failing raw recording ends at 1,302/1,118
station support and 0.331-degree median residual with recorded pings and learned
timing, without the late support collapse. It accepts the same 50,802 blobs as
the previous native map. Numerical agreement with the revised Python projection
is within 0.071 pixels including wire rounding.

The seated and recenter recordings retain their previous behavior; the seated
ping-based replay still has the existing unresolved station-mirror ambiguity.
Correcting the projection changes acquisition history in the failing capture,
so one successful replay is not proof that all jump events are eliminated.
No PC solver, acquisition threshold, exposure gate or timing behavior was changed.

## Live 0.3.1 check

A 90.49-second recording after deployment contained 9,068 converted frames
(2,267 per camera) and no error records. The driver had detected a real HMD pose
break after a 384-second pose gap before recording. It reacquired approximately
30 seconds into recording and stayed locked in all subsequent sampled statuses,
ending at 768/627 station support. Post-acquisition median residuals were
0.300-0.318 degrees; median round trip was 3.64 ms and the sampled maximum 4.11 ms.
Long exposures still caused intervals without selected alignment frames.

A replay with only the live session's previously learned 47.025 ms timing,
and otherwise fresh state, ends at 659/604 support without a jump. A fully fresh
replay starting at the upstream 18 ms default instead learns approximately 51 ms
at 65 seconds and triggers a support reset near 70 seconds, ending at 71/75.
This remains a cold-start timing limitation: the live pass and the corrected
original regression do not establish reliable startup without learned timing.
No timing override or upstream solver modification was introduced to conceal it.

## Sensor timestamp and pixel-centre correction (0.3.2)

Changing only the initial timing estimate did not resolve the retained cold-start
case and was not shipped. Investigation found that the backend was discarding
available sensor stamps, and its optical map was interpreting the detector's
`n + 0.5` coordinates as integer-centred pixels. Version 0.3.2 corrects both
backend contracts. The PC change only recognizes the sensor-stamped calibration
kind and selects the existing sensor-time path; no solver code, thresholds,
forced timing estimate or learned-timing override is changed.

A native clock probe on the headset, including its approximately 96-second
accumulated suspend offset, produced frames from all four cameras and closed
with zero errors. The revised C map accepted 50,785 of 53,023 raw blobs and
agreed with the corrected analytical coordinates within 0.071 pixels including
wire rounding. Legacy delivery-timestamp replay decisions were identical with
the old and new PC builds, and the older build rejected the new calibration kind.

The installed PC build used a new `galaxy-xr-sensor-trial` profile with no saved
timing or stations. It acquired approximately 20 seconds after connection and
learned timing one second later. A subsequent 90.47-second recording contained
7,356 converted frames, exactly 1,839 per camera, and no error records or live
jump events. All 18 status samples remained locked. Residuals ranged from
0.277 to 0.341 degrees; median round trip was 4.00 ms, with a 15.79 ms sampled
peak. Final stop status had 3,372/2,873 station support.

Replaying that recording from empty state and the unmodified 18 ms default
acquired at 8 seconds, learned 32.1 ms at 25 seconds, and ended at 2,851/2,343
support with 0.288-degree median residual. A diagnostic build that only logs
the existing jump decision confirmed zero replay jump events. No saved timing
was supplied to this check. The earlier arrival-only recordings cannot recreate
these sensor stamps; changing their calibration kind would be an invalid test.

These checks validate this headset and firmware through a fresh startup and
timing-learning transition. Automatic factory preparation and additional-device
coverage remain separate requirements for a generic release.
