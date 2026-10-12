#!/system/bin/sh
[ "$KSU" = true ] || abort 'Install using KernelSU Manager.'
[ "$ARCH" = arm64 ] || abort 'Android arm64 required.'
. "$MODPATH/guard.sh"
gxr_guard || abort 'Unsupported firmware or QVR binaries. This build requires SM-I610 AZF3.'
[ ! -f "$MODPATH/automatic-setup" ] || gxr_calibration_guard || abort 'Unsupported calibration client.'
set_perm_recursive "$MODPATH" 0 0 0755 0644
for f in service.sh action.sh run.sh guard.sh prepare.sh uninstall.sh lhsyncd gxr-lhsight gxr-head-origin gxr-prepare; do
  set_perm "$MODPATH/$f" 0 0 0755
done
ui_print 'Native QVR service: TCP 47280 / UDP 47281.'
if [ -f "$MODPATH/automatic-setup" ]; then
  ui_print 'Factory calibration will be prepared automatically at service startup.'
  ui_print 'Requires the Galaxy XR compatible QuestLHSync PC driver.'
else
  ui_print 'Diagnostics unless a measured profile or private factory trial was bundled.'
fi
ui_print 'If late root loading skips startup, use the module Action button.'
ui_print 'No system overlay, Frida, or SELinux policy changes.'
