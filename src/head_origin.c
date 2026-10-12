/* AZF3 calibration client ABI, guarded by the library SHA256 in guard.sh.
   Only the lifecycle and read-only getLatestTransform operation are used.
   The 0xc0001 interface exposes that operation at byte offset 0xa0 and returns
   six float32 values: Rodrigues rotation, then translation in metres. */
extern void *dlopen(const char *, int), *dlsym(void *, const char *);
extern char *dlerror(void);
extern int dprintf(int, const char *, ...);
extern unsigned int alarm(unsigned int);

int main(void) {
    alarm(15);
    void *lib = dlopen("/vendor/lib64/libperception_calibration_client_plugin.so", 2);
    if (!lib) { dprintf(2, "Calibration client unavailable: %s\n", dlerror()); return 1; }
    int (*create)(int, const char *, void **) = dlsym(lib, "GoogleClient_CreateInstance");
    void (*activate)(void *) = dlsym(lib, "PerceptionClient_Activated");
    void (*deactivate)(void *) = dlsym(lib, "PerceptionClient_Deactivated");
    void (*destroy)(void *) = dlsym(lib, "GoogleClient_DestroyInstance");
    if (!create || !activate || !deactivate || !destroy) return 2;
    void *client = 0;
    if (create(0xc0001, "QuestLHSync", &client) || !client) return 1;
    if (*(unsigned int *)client != 0xc0001) { destroy(client); return 2; }
    activate(client);
    int (*get)(void *, const char *, const char *, void *) =
        *(int (**)(void *, const char *, const char *, void *))((char *)client + 0xa0);
    /* The large buffer and canary also reject unexpected output layouts. */
    union { float values[1024]; unsigned int words[1024]; } output;
    for (int i = 0; i < 1024; i++) output.words[i] = 0x7fc00001;
    int result = get ? get(client, "FRAME_IMU_0", "SENSOR_THIRD_EYE", &output) : 2;
    deactivate(client);
    destroy(client);
    if (result) { dprintf(2, "Head-origin query failed: %d\n", result); return 1; }
    for (int i = 0; i < 6; i++) {
        float v = output.values[i];
        if (!__builtin_isfinite(v) || __builtin_fabsf(v) > (i < 3 ? 3.15f : .5f)) return 2;
    }
    for (int i = 6; i < 1024; i++) if (output.words[i] != 0x7fc00001) return 2;
    for (int i = 0; i < 6; i++)
        if (dprintf(1, "%.9g%c", (double)output.values[i], i == 5 ? '\n' : ' ') < 0) return 1;
    return 0;
}
