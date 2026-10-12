# Existing measured-profile builds

Place private profiles under the ignored `profiles/` directory:

```sh
python build_module.py --bionic-dir build/bionic --profile profiles/my-headset.json
```

`verified_profile()` in `build_module.py` defines the required v2 schema. It
requires four 640x640 camera calibrations, measured camera-to-HMD rigid transforms,
firmware and serial-hash binding, evidence records, and a positive exposure limit
no greater than 3000 microseconds. Evidence text is a measurement record, not an
automated guarantee of accuracy. No guessed/default alignment profile is supplied.

The resulting trial ZIP contains private calibration and device-binding data;
do not publish it as a general-purpose release.

On the PC, enable `driver_questlhsync.anyHmd`. The compatible PC patch also permits
`driver_questlhsync.profile` (for example `galaxy-xr`) to isolate this headset's
state. Use the dashboard's headset selection or an explicit host setting as needed.
Hold a Lighthouse controller and slowly view both stations. Recentring resets
the pose frame and requires reacquisition.


These instructions preserve the measured live baseline and rollback option while
automatic factory startup calibration is being implemented. Manual calibration generation tools have been
removed from the current tree; the last complete workflow is in Git history at
`ac53e6b`. Existing private v2 profiles remain supported.
