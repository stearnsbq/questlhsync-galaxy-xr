# Vendored QuestLHSync daemon

Source: https://github.com/CreoleVR/QuestLHSync

Revision: `faf2287985e0ccdfd1fb0e4254ad4d8800c78cdb` (1.14).
MIT license; copyright retained in LICENSE.

Local changes to lhsyncd.c add optional HS_TIMER_CLOCK and HS_LOG_CAPTURE_STATUS
compile definitions. Default behavior remains upstream. The Galaxy XR build uses
BOOTTIME for lifecycle deadlines and logs camera diagnostics. Protocol clock
responses remain CLOCK_MONOTONIC. headset.h is unchanged.
