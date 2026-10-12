// Galaxy XR platform adapter. Static musl daemon; Android/QVR live in a separate
// bionic child so the two C runtimes never share an address space.
#define _GNU_SOURCE
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <unistd.h>
#include "headset.h"

const char *const hs_capture_name = "gxr-camera";
static const char *moddir;
void hs_log(const char *s) { fprintf(stderr, "%s\n", s); }
void hs_init(int argc, char **argv) {
  if (argc != 2 || argv[1][0] != '/') { hs_log("absolute module directory required"); exit(2); }
  moddir = argv[1];
}
static void envfield(char *out, size_t n, const char *key, const char *fallback) {
  const char *v = getenv(key);
  snprintf(out, n, "%s", v && *v ? v : fallback);
}
void hs_device_info(char *serial, char *model, char *fw, size_t n) {
  envfield(serial, n, "QLHS_ID", "gxr-development");
  snprintf(model, n, "Galaxy_XR");
  envfield(fw, n, "QLHS_FW", "unknown");
}
static int calibrated(void) {
  const char *mode = getenv("QLHS_CALIBRATED");
  return mode && !strcmp(mode, "1");
}
int hs_calibration(char **data, size_t *len, char *name, size_t n) {
  *data = NULL; *len = 0;
  if (!calibrated()) {
    snprintf(name, n, "GXR diagnostic mode: verified per-device optics/exposure required; alignment disabled");
    return -1;
  }
  char path[1024];
  const char *caldir = getenv("QLHS_CALIBRATION_DIR");
  snprintf(path, sizeof path, "%s/calibration.json", caldir ? caldir : moddir);
  FILE *f = fopen(path, "rb");
  if (!f) goto bad;
  if (fseek(f, 0, SEEK_END)) { fclose(f); goto bad; }
  long size = ftell(f);
  if (size < 1 || size > 65536 || fseek(f, 0, SEEK_SET)) { fclose(f); goto bad; }
  char *buf = malloc((size_t)size);
  if (!buf) { fclose(f); goto bad; }
  size_t got = fread(buf, 1, (size_t)size, f);
  fclose(f);
  if (got != (size_t)size) { free(buf); goto bad; }
  *data = buf; *len = got;
  snprintf(name, n, "gxr/%s", caldir ? "automatic-factory" : getenv("QLHS_FACTORY_MAP") ? "factory-trial.json" : "measured-trial-profile.json");
  return 0;
bad:
  snprintf(name, n, "GXR calibration unavailable; capture refused");
  return -1;
}
pid_t hs_capture_start(int out_fd, char *msg, size_t n) {
  if (calibrated()) {
    char *buf; size_t len;
    if (hs_calibration(&buf, &len, msg, n)) return 0;
    free(buf);
  }
  char exe[1024];
  snprintf(exe, sizeof exe, "%s/gxr-lhsight", moddir);
  pid_t parent = getpid(), pid = fork();
  if (pid < 0) { snprintf(msg, n, "fork failed"); return 0; }
  if (!pid) {
    prctl(PR_SET_PDEATHSIG, SIGTERM);
    if (getppid() != parent) _exit(1);
    signal(SIGTERM, SIG_DFL); signal(SIGINT, SIG_DFL); signal(SIGPIPE, SIG_DFL);
    dup2(out_fd, 1); dup2(out_fd, 2);
    int nul = open("/dev/null", O_RDONLY);
    if (nul >= 0) dup2(nul, 0);
    for (int fd = 3; fd < 1024; fd++) close(fd);
    setenv("LD_LIBRARY_PATH", "/vendor/lib64:/vendor/lib64/hw", 1);
    execl(exe, exe, calibrated() ? "calibrated" : "diagnostic", (char *)NULL);
    _exit(127);
  }
  snprintf(msg, n, "GXR tracking + ctrl-tracking; %s; %s CLOCK_MONOTONIC timestamps",
           calibrated() ? (getenv("QLHS_FACTORY_MAP") ? "factory calibration enabled" : "measured trial profile enabled") : "diagnostics only (no C/F alignment records)",
           getenv("QLHS_SENSOR_TIME") ? "sensor" : "arrival");
  return pid;
}
