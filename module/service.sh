#!/system/bin/sh
MODDIR=${0%/*}
RUN=/dev/questlhsync-gxr
STATE=/data/adb/questlhsync-gxr
until [ "$(getprop sys.boot_completed)" = 1 ]; do
  [ -e "$MODDIR/disable" ] || [ -e "$MODDIR/remove" ] && exit 0
  sleep 2
done
mkdir -p "$RUN" "$STATE"
chmod 0700 "$RUN" "$STATE"
# Atomic ownership lock. A dead owner may leave a lock across a manual restart.
if ! mkdir "$RUN/lock" 2>/dev/null; then
  OLD=$(cat "$RUN/lock/pid" 2>/dev/null)
  case "$OLD" in ''|*[!0-9]*) exit 1;; esac
  kill -0 "$OLD" 2>/dev/null && exit 0
  rm -f "$RUN/lock/pid"
  rmdir "$RUN/lock" || exit 1
  mkdir "$RUN/lock" || exit 1
fi
echo $$ > "$RUN/lock/pid"
CHILD=
cleanup() {
  if [ -n "$CHILD" ]; then kill "$CHILD" 2>/dev/null; wait "$CHILD" 2>/dev/null; fi
  rm -f "$RUN/daemon.pid" "$RUN/lock/pid"
  rmdir "$RUN/lock" 2>/dev/null
}
trap 'exit 0' TERM INT
trap cleanup EXIT
if [ ! -s "$STATE/id" ]; then
  cat /proc/sys/kernel/random/uuid > "$STATE/id"
  chmod 0600 "$STATE/id"
fi
export QLHS_ID=gxr-$(cat "$STATE/id")
while [ ! -e "$MODDIR/disable" ] && [ ! -e "$MODDIR/remove" ]; do
  # Bound logs by rotating between runs; diagnostics stay in RAM.
  [ -f "$RUN/service.log" ] && mv -f "$RUN/service.log" "$RUN/previous.log"
  sh "$MODDIR/run.sh" >> "$RUN/service.log" 2>&1 &
  CHILD=$!
  echo "$CHILD" > "$RUN/daemon.pid"
  while kill -0 "$CHILD" 2>/dev/null; do
    [ -e "$MODDIR/disable" ] || [ -e "$MODDIR/remove" ] && exit 0
    # Keep a long-lived daemon's connection/error log bounded too.
    if [ "$(wc -c < "$RUN/service.log")" -gt 262144 ]; then
      tail -c 65536 "$RUN/service.log" > "$RUN/previous.log"
      : > "$RUN/service.log"
    fi
    sleep 2
  done
  wait "$CHILD"
  RESULT=$?
  CHILD=
  [ "$RESULT" = 2 ] && exit 2
  sleep 5
done
