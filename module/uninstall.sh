#!/system/bin/sh
# Signal only our own supervisor, never a different lhsyncd/camera service.
PID=$(cat /dev/questlhsync-gxr/lock/pid 2>/dev/null)
case "$PID" in ''|*[!0-9]*) exit 0;; esac
if tr '\000' '\n' < "/proc/$PID/cmdline" 2>/dev/null | grep -Fxq /data/adb/modules/questlhsync_gxr/service.sh; then
  kill "$PID" 2>/dev/null
fi
# Retain the tiny stable discovery ID for reinstall; no images are stored.
