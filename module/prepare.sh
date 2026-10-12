#!/system/bin/sh
# Called under the service ownership lock, before the daemon starts. Outputs
# stay in private RAM storage and are regenerated on every service start.
MODDIR=${0%/*}
. "$MODDIR/guard.sh"
gxr_guard && gxr_calibration_guard || exit 2
umask 077
OUT=/dev/questlhsync-gxr/calibration
SOURCE=/mnt/vendor/efs/device_profile.textproto
mkdir -p "$OUT" || exit 1
BEFORE=$(sha256sum "$SOURCE") || exit 1
export LD_LIBRARY_PATH=/vendor/lib64:/system/lib64
"$MODDIR/gxr-head-origin" > "$OUT/head-origin.txt" || exit $?
"$MODDIR/gxr-prepare" "$SOURCE" "$OUT/head-origin.txt" "$OUT" || exit $?
"$MODDIR/gxr-head-origin" > "$OUT/head-origin-after.txt" || exit $?
AFTER=$(sha256sum "$SOURCE") || exit 1
if [ "$BEFORE" != "$AFTER" ] || ! cmp -s "$OUT/head-origin.txt" "$OUT/head-origin-after.txt"; then
  echo 'Factory calibration changed during setup; retrying.' >&2
  exit 1
fi
printf '%s\n' "$AFTER" > "$OUT/source.sha256" || exit 1
echo 'Automatic factory calibration ready (four tracking cameras).' >&2
