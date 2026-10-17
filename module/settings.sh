#!/system/bin/sh
# Persistent numeric settings only; never source writable configuration as shell.
MODDIR=${0%/*}
STATE=/data/adb/questlhsync-gxr
CONFIG=$STATE/max-exposure-ns
valid() {
  case "$1" in ???????|10000000) ;; *) return 1;; esac
  case "$1" in *[!0-9]*) return 1;; esac
  [ "$1" -ge 1000000 ] && [ "$1" -le 10000000 ] && [ "$(( $1 % 100000 ))" -eq 0 ]
}
case "$1" in
  get)
    VALUE=10000000
    if [ -f "$CONFIG" ]; then VALUE=$(cat "$CONFIG") || exit 1; fi
    valid "$VALUE" || { echo 'Invalid saved exposure cutoff.' >&2; exit 2; }
    echo "$VALUE"
    ;;
  set)
    [ "$#" -eq 2 ] && valid "$2" || { echo 'Choose 1 to 10 ms in 0.1 ms steps.' >&2; exit 2; }
    umask 077
    mkdir -p "$STATE" || exit 1
    TEMP=$CONFIG.$$
    trap 'rm -f "$TEMP"' EXIT
    printf '%s\n' "$2" > "$TEMP" && mv -f "$TEMP" "$CONFIG" || exit 1
    echo 'Settings saved.'
    ;;
  apply)
    [ ! -e "$MODDIR/disable" ] && [ ! -e "$MODDIR/remove" ] || { echo 'Settings saved. Enable the module to apply them.' >&2; exit 1; }
    [ -f "$MODDIR/automatic-setup" ] && [ ! -f "$MODDIR/profile.sha256" ] || { echo 'Exposure settings require automatic factory calibration.' >&2; exit 1; }
    sh "$MODDIR/settings.sh" get >/dev/null || exit $?
    sh "$MODDIR/uninstall.sh"
    COUNT=0
    while [ -d /dev/questlhsync-gxr/lock ]; do
      PID=$(cat /dev/questlhsync-gxr/lock/pid 2>/dev/null)
      case "$PID" in ''|*[!0-9]*) break;; esac
      kill -0 "$PID" 2>/dev/null || break
      COUNT=$((COUNT + 1))
      [ "$COUNT" -le 10 ] || { echo 'Settings saved; service did not stop. Reboot to apply.' >&2; exit 1; }
      sleep 1
    done
    sh "$MODDIR/action.sh"
    ;;
  *) echo 'Usage: settings.sh get | set NANOSECONDS | apply' >&2; exit 2;;
esac
