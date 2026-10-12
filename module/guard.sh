#!/system/bin/sh
# Sourced by installer and launcher. No changes to vendor files or SELinux.
gxr_guard() {
  [ "$(getprop ro.build.fingerprint)" = 'samsung/xrvst2ue/xrvst2:14/UML2.260301.001/I610UEU2AZF3:user/release-keys' ] || return 1
  [ "$(sha256sum /vendor/lib64/libqvrcamera_client.qti.so | cut -d ' ' -f 1)" = cd34ddf44087a764d67f654b2be77f31fad74fedf164c39193ff5af1f6a62a94 ] || return 1
  [ "$(sha256sum /vendor/lib64/libqvrcameraservice.so | cut -d ' ' -f 1)" = 0e33dd338e6a12e0a298067ff30cb3af169f9b235e57fe51700950b9ef10dfc9 ] || return 1
}

gxr_calibration_guard() {
  [ "$(sha256sum /vendor/lib64/libperception_calibration_client_plugin.so | cut -d ' ' -f 1)" = bdd157bc645a733b6ce7d29106d906c05001bde3e70cc1a0c8bd5bb604f2d142 ]
}
