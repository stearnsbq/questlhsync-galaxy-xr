// Run on the user's desktop alongside Virtual Desktop and SteamVR.
#include <windows.h>
#include <openvr.h>
#include <cstdio>
#include <filesystem>
#include <initializer_list>
#include <string>

static double now() {
    LARGE_INTEGER count, frequency;
    QueryPerformanceCounter(&count); QueryPerformanceFrequency(&frequency);
    return double(count.QuadPart) / double(frequency.QuadPart);
}

int main() {
    vr::EVRInitError error = vr::VRInitError_None;
    auto *system = vr::VR_Init(&error, vr::VRApplication_Background);
    if (error != vr::VRInitError_None) {
        std::fprintf(stderr, "SteamVR: %s\n", vr::VR_GetVRInitErrorAsEnglishDescription(error));
        return 1;
    }
    SYSTEMTIME time; GetSystemTime(&time);
    char name[128];
    std::snprintf(name, sizeof(name), "poses-%04d%02d%02d-%02d%02d%02d-%lu",
        time.wYear, time.wMonth, time.wDay, time.wHour, time.wMinute, time.wSecond, GetCurrentProcessId());
    std::filesystem::path dir = std::filesystem::absolute(name);
    std::filesystem::create_directory(dir);
    FILE *meta = std::fopen((dir / "identity.txt").string().c_str(), "w");
    FILE *poses = std::fopen((dir / "poses.csv").string().c_str(), "w");
    FILE *stations = std::fopen((dir / "stations.csv").string().c_str(), "w");
    if (!meta || !poses || !stations) {
        if (meta) std::fclose(meta);
        if (poses) std::fclose(poses);
        if (stations) std::fclose(stations);
        vr::VR_Shutdown(); return 2;
    }
    std::fprintf(meta, "coordinate_frame=TrackingUniverseRawAndUncalibrated\nprediction_seconds=0\nclock=QueryPerformanceCounter_seconds\n");
    for (auto property : {vr::Prop_TrackingSystemName_String, vr::Prop_ModelNumber_String,
                          vr::Prop_SerialNumber_String, vr::Prop_ManufacturerName_String}) {
        char value[1024] = {}; vr::ETrackedPropertyError pe;
        system->GetStringTrackedDeviceProperty(0, property, value, sizeof(value), &pe);
        std::fprintf(meta, "property_%d=%s (error %d)\n", int(property), value, int(pe));
        std::printf("HMD property %d: %s\n", int(property), value);
    }
    std::fclose(meta);
    std::fprintf(poses, "before_s,after_s,valid,connected,result,m00,m01,m02,tx,m10,m11,m12,ty,m20,m21,m22,tz,vx,vy,vz,wx,wy,wz\n");
    std::fflush(poses);
    std::fprintf(stations, "pc_s,device,serial,m00,m01,m02,tx,m10,m11,m12,ty,m20,m21,m22,tz\n");
    FILE *latest = std::fopen("latest-pose-session.txt", "w");
    if (!latest) { std::fclose(poses); vr::VR_Shutdown(); return 2; }
    std::fprintf(latest, "%s\n", dir.string().c_str()); std::fclose(latest);
    std::printf("Recording for 5 minutes. Keep this window open.\nOutput: %s\n", dir.string().c_str());
    double start = now(), flushed = start, status = start, station_time = start - 1;
    int valid = 0, total = 0;
    while (now() - start < 300) {
        vr::TrackedDevicePose_t p[vr::k_unMaxTrackedDeviceCount] = {};
        double before = now();
        system->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseRawAndUncalibrated, 0,
                                               p, vr::k_unMaxTrackedDeviceCount);
        double after = now(); auto &h = p[0];
        std::fprintf(poses, "%.9f,%.9f,%d,%d,%d", before, after, h.bPoseIsValid,
                     h.bDeviceIsConnected, int(h.eTrackingResult));
        for (auto &row : h.mDeviceToAbsoluteTracking.m)
            for (float v : row) std::fprintf(poses, ",%.9g", v);
        for (float v : h.vVelocity.v) std::fprintf(poses, ",%.9g", v);
        for (float v : h.vAngularVelocity.v) std::fprintf(poses, ",%.9g", v);
        std::fprintf(poses, "\n"); total++; valid += h.bPoseIsValid && h.bDeviceIsConnected;
        if (after-station_time >= 1) {
            for (unsigned i=1; i<vr::k_unMaxTrackedDeviceCount; i++) {
                if (system->GetTrackedDeviceClass(i) != vr::TrackedDeviceClass_TrackingReference ||
                    !p[i].bPoseIsValid || !p[i].bDeviceIsConnected) continue;
                char serial[1024] = {};
                system->GetStringTrackedDeviceProperty(i, vr::Prop_SerialNumber_String, serial, sizeof(serial));
                for (char *c=serial; *c; c++) if (*c==',' || *c=='\n' || *c=='\r') *c='_';
                std::fprintf(stations, "%.9f,%u,%s", after, i, serial);
                for (auto &row : p[i].mDeviceToAbsoluteTracking.m)
                    for (float v : row) std::fprintf(stations, ",%.9g", v);
                std::fprintf(stations, "\n");
            }
            std::fflush(stations); station_time=after;
        }
        if (after - flushed > .1) { std::fflush(poses); flushed = after; }
        if (std::ferror(poses)) { std::fclose(poses); vr::VR_Shutdown(); return 3; }
        if (after - status > 5) {
            std::printf("%d/%d valid poses; %.0f seconds remaining\n", valid, total, 300-(after-start));
            status = after;
        }
        Sleep(5);
    }
    std::fclose(poses); std::fclose(stations); vr::VR_Shutdown();
    return valid ? 0 : 4;
}
