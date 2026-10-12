#!/system/bin/sh
# KernelSU's Action button provides a manual start after this device's late root load.
MODDIR=${0%/*}
if [ -e "$MODDIR/disable" ] || [ -e "$MODDIR/remove" ]; then
  echo 'Module is disabled or marked for removal.'
  exit 1
fi
nohup sh "$MODDIR/service.sh" </dev/null >/dev/null 2>&1 &
sleep 2
PID=$(cat /dev/questlhsync-gxr/daemon.pid 2>/dev/null)
case "$PID" in ''|*[!0-9]*) echo 'Service did not start; inspect /dev/questlhsync-gxr/service.log'; exit 1;; esac
if kill -0 "$PID" 2>/dev/null; then
  echo 'QuestLHSync Galaxy XR service is running.'
else
  echo 'Service exited; inspect /dev/questlhsync-gxr/service.log'
  exit 1
fi
