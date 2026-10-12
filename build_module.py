"""Build the Galaxy XR KernelSU ZIP (Zig + Clang; no NDK or Frida download)."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE
FINGERPRINT = 'samsung/xrvst2ue/xrvst2:14/UML2.260301.001/I610UEU2AZF3:user/release-keys'
LIB_HASH = 'cd34ddf44087a764d67f654b2be77f31fad74fedf164c39193ff5af1f6a62a94'


def verified_profile(path):
    """Only accept measured optics in the existing driver's supported model.

    Evidence strings are human validation records, not automatic proof. No default
    vendor calibration or assumed identity camera-to-HMD transform is supplied.
    """
    p = json.loads(path.read_text(encoding='utf-8'))
    if p.get('schema') != 'questlhsync-gxr-profile-v2' or p.get('fingerprint') != FINGERPRINT:
        raise ValueError('Profile schema/firmware mismatch')
    if not re.fullmatch('[a-f0-9]{64}', p.get('device_serial_sha256', '')):
        raise ValueError('Profile requires SHA256 of this headset serial (without newline)')
    if p.get('camera_order') != ['tracking:0', 'tracking:1', 'ctrl-tracking:0', 'ctrl-tracking:1']:
        raise ValueError('Camera order must match QVR buffer indices')
    if p.get('coordinate_frame') != 'steamvr-hmd' or p.get('timestamp_mode') != 'arrival-monotonic':
        raise ValueError('Requires measured SteamVR HMD extrinsics and arrival-monotonic timing')
    evidence = p.get('evidence', {})
    for key in ('intrinsics', 'camera_order', 'camera_to_hmd', 'short_exposure', 'lighthouse_visibility', 'timing'):
        if not isinstance(evidence.get(key), str) or len(evidence[key].strip()) < 16:
            raise ValueError('Missing measurement record: ' + key)
    exposure = p.get('max_exposure_us')
    if p.get('frame_selection') != 'exposure-metadata':
        raise ValueError('Requires the measured Galaxy XR exposure metadata policy')
    if isinstance(exposure, bool) or not isinstance(exposure, (int, float)) or not 0 < exposure <= 3000:
        raise ValueError('Validated frames must have exposure <= 3000 us')
    cal = p['calibration']
    if cal.get('kind') != 'galaxy_xr' or 'CameraCalibration' in cal:
        raise ValueError('Galaxy XR profiles must be rejected by older PC drivers')
    cams = cal.get('GxrCameraCalibration', [])
    if len(cams) != 4:
        raise ValueError('Exactly four calibrated tracking cameras required')
    for i, cam in enumerate(cams):
        if str(cam.get('Id')) != str(i) or cam.get('ImageSize') != [640, 640]:
            raise ValueError('Wrong camera ID or dimensions')
        if cam.get('Shutter', {}).get('Type') != 'Global':
            raise ValueError('Global shutter verification required')
        if cam.get('SensorType') == 'OV7251':
            raise ValueError('Do not enable the Quest-specific IR correction')
        proj, dist = cam['Projection'], cam['Distortion']
        if proj.get('Model') != 'PinholeXY' or dist.get('Model') != 'Fisheye62':
            raise ValueError('Galaxy XR driver requires PinholeXY + Fisheye62')
        pc, dc, transform = proj['Coefficients'], dist['Coefficients'], cam['DeviceFromCamera']
        if len(pc) != 4 or len(dc) != 8 or len(transform) != 16:
            raise ValueError('Incorrect optics coefficient count')
        if not all(type(v) in (int, float) and math.isfinite(v) for v in pc + dc + transform):
            raise ValueError('Non-finite optics')
        if pc[0] <= 0 or pc[1] <= 0 or not (0 <= pc[2] < 640 and 0 <= pc[3] < 640):
            raise ValueError('Invalid focal length/principal point')
        if transform[12:] != [0, 0, 0, 1] or max(abs(transform[j]) for j in (3, 7, 11)) > .5:
            raise ValueError('Extrinsics must be row-major rigid transform in metres')
        rows = [transform[j:j+3] for j in (0, 4, 8)]
        for a in range(3):
            for b in range(3):
                if abs(sum(rows[a][k]*rows[b][k] for k in range(3)) - (a == b)) > 1e-4:
                    raise ValueError('Non-orthonormal camera rotation')
        r = rows
        det = r[0][0]*(r[1][1]*r[2][2]-r[1][2]*r[2][1])-r[0][1]*(r[1][0]*r[2][2]-r[1][2]*r[2][0])+r[0][2]*(r[1][0]*r[2][1]-r[1][1]*r[2][0])
        if abs(det-1) > 1e-4:
            raise ValueError('Camera rotation must be right-handed')
    return p, (json.dumps(cal, separators=(',', ':'), allow_nan=False) + '\n').encode()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--serial', help='ADB transport serial for local bionic link libraries')
    ap.add_argument('--bionic-dir', type=Path, help='Offline directory containing device libc.so/libdl.so')
    ap.add_argument('--profile', type=Path, help='Verified per-device profile; otherwise diagnostics only')
    args = ap.parse_args()
    out = HERE / 'build'
    out.mkdir(exist_ok=True)
    profile = verified_profile(args.profile) if args.profile else None
    adb = ['adb'] + (['-s', args.serial] if args.serial else [])

    def run(cmd, **kwargs):
        return subprocess.run(cmd, check=True, **kwargs)

    def remote(cmd):
        return run(adb + ['exec-out', 'su -c ' + shlex.quote(cmd)], capture_output=True, timeout=20).stdout

    bionic = args.bionic_dir or out / 'bionic'
    if not args.bionic_dir:
        if remote('getprop ro.build.fingerprint').decode().strip() != FINGERPRINT:
            raise RuntimeError('Unsupported device firmware')
        if hashlib.sha256(remote('cat /vendor/lib64/libqvrcamera_client.qti.so')).hexdigest() != LIB_HASH:
            raise RuntimeError('Unsupported QVR client')
        bionic.mkdir(exist_ok=True)
        for name in ('libc.so', 'libdl.so'):
            data = remote('cat /apex/com.android.runtime/lib64/bionic/' + name)
            if not data.startswith(b'\x7fELF\x02\x01'):
                raise RuntimeError('Invalid Android ELF: ' + name)
            (bionic / name).write_bytes(data)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'), ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'))
    run(['zig', 'cc', '-target', 'aarch64-linux-musl', '-static', '-O2', '-Wall', '-Wextra',
         '-Werror', '-Wno-unused-but-set-variable', '-DMODULE_VERSION="gxr-0.2.0"',
         '-DHS_TIMER_CLOCK=CLOCK_BOOTTIME', '-DHS_LOG_CAPTURE_STATUS=1',
         '-I'+str(ROOT/'vendor/questlhsync'), str(ROOT/'vendor/questlhsync/lhsyncd.c'), str(HERE/'src/gxr.c'),
         '-o', str(out/'lhsyncd')], env=env)
    run(['clang', '--target=aarch64-linux-android29', '-fuse-ld=lld', '-nostdlib',
         '-fPIE', '-pie', '-O2', '-Wall', '-Wextra', '-Werror', '-fno-stack-protector',
         '-Wl,-e,_start', '-Wl,--dynamic-linker=/system/bin/linker64', '-Wl,-z,max-page-size=16384',
         str(HERE/'src/start.S'), str(HERE/'src/capture.c'), str(bionic/'libc.so'), str(bionic/'libdl.so'),
         '-o', str(out/'gxr-lhsight')])
    files = {p.name: p.read_bytes().replace(b'\r\n', b'\n') for p in (HERE/'module').iterdir() if p.is_file()}
    files.update({name: (out/name).read_bytes() for name in ('lhsyncd', 'gxr-lhsight')})
    files['LICENSE'] = (ROOT/'LICENSE').read_bytes()
    files['README.md'] = (HERE/'README.md').read_bytes()
    if profile:
        p, cal = profile
        files['calibration.json'] = cal
        files['device.sha256'] = (p['device_serial_sha256']+'\n').encode()
        files['profile.json'] = args.profile.read_bytes()
        files['max-exposure-ns'] = (str(round(p['max_exposure_us']*1000))+'\n').encode()
        files['profile.sha256'] = ''.join(hashlib.sha256(files[k]).hexdigest()+'  '+k+'\n' for k in ('calibration.json', 'device.sha256', 'profile.json', 'max-exposure-ns')).encode()
    # Directory for temporary deployment always reflects this ZIP, without stale profile files.
    stage = out/'stage'
    stage.mkdir(exist_ok=True)
    for p in stage.iterdir():
        if p.is_file() and p.name not in files:
            p.unlink()
    zip_path = out / ('QuestLHSync-GXR-0.2.0-'+('trial' if profile else 'diagnostic')+'.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            (stage/name).write_bytes(data)
            info = zipfile.ZipInfo(name, (2026, 10, 12, 0, 0, 0))
            info.create_system = 3
            mode = 0o755 if name.endswith('.sh') or name in ('lhsyncd', 'gxr-lhsight') else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    print(zip_path)
    print('SHA256', hashlib.sha256(zip_path.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
