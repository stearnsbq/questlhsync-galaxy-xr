#!/system/bin/sh
# Foreground entry point: works for both module service and temporary ADB checks.
MODDIR=${0%/*}
. "$MODDIR/guard.sh"
gxr_guard || { echo 'Unsupported GXR firmware/QVR binaries' >&2; exit 2; }
export QLHS_FW=$(getprop ro.build.version.incremental)
export QLHS_CALIBRATED=0
unset QLHS_FACTORY_MAP
unset QLHS_SENSOR_TIME
if [ -f "$MODDIR/profile.sha256" ]; then
  (cd "$MODDIR" && sha256sum -c profile.sha256) >&2 || exit 2
  ACTUAL=$(getprop ro.serialno | tr -d '\r\n' | sha256sum | cut -d ' ' -f 1)
  [ "$ACTUAL" = "$(cat "$MODDIR/device.sha256")" ] || { echo 'Profile belongs to another headset' >&2; exit 2; }
  export QLHS_MAX_EXPOSURE_NS=$(cat "$MODDIR/max-exposure-ns")
  case "$QLHS_MAX_EXPOSURE_NS" in ''|*[!0-9]*) exit 2;; esac
  [ "$QLHS_MAX_EXPOSURE_NS" -gt 0 ] && [ "$QLHS_MAX_EXPOSURE_NS" -le 3000000 ] || exit 2
  export QLHS_CALIBRATED=1
  if [ -f "$MODDIR/factory-trial.json" ]; then
    [ -f "$MODDIR/factory-map.bin" ] && [ -f "$MODDIR/factory-source.sha256" ] || exit 2
    FACTORY=$(sha256sum /mnt/vendor/efs/device_profile.textproto | cut -d ' ' -f 1)
    [ "$FACTORY" = "$(cat "$MODDIR/factory-source.sha256")" ] || { echo 'Factory calibration changed; rebuild trial' >&2; exit 2; }
    export QLHS_FACTORY_MAP="$MODDIR/factory-map.bin"
    [ "$(cat "$MODDIR/frame-timestamp")" = "sensor-boottime-to-monotonic" ] || exit 2
    export QLHS_SENSOR_TIME=1
  elif [ -f "$MODDIR/factory-map.bin" ]; then
    echo 'Factory map without trial manifest; capture refused' >&2
    exit 2
  fi
fi
exec "$MODDIR/lhsyncd" "$MODDIR"
