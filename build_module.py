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
import struct
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE
FINGERPRINT = 'samsung/xrvst2ue/xrvst2:14/UML2.260301.001/I610UEU2AZF3:user/release-keys'
LIB_HASH = 'cd34ddf44087a764d67f654b2be77f31fad74fedf164c39193ff5af1f6a62a94'
VERSION = '0.5.2'


def validate_calibration(cal):
    if cal.get('kind') not in ('galaxy_xr', 'galaxy_xr_sensor') or 'CameraCalibration' in cal:
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
    validate_calibration(cal)
    if cal['kind'] != 'galaxy_xr':
        raise ValueError('Measured arrival-timestamp profiles require kind galaxy_xr')
    return p, (json.dumps(cal, separators=(',', ':'), allow_nan=False) + '\n').encode()


def factory_trial_files(directory):
    manifest = (directory/'factory-trial.json').read_bytes()
    p = json.loads(manifest)
    if p.get('schema') != 'questlhsync-gxr-factory-trial-v1' or p.get('firmware') != FINGERPRINT:
        raise ValueError('Invalid factory trial schema/firmware')
    for key in ('device_serial_sha256', 'factory_source_sha256', 'map_sha256', 'calibration_sha256', 'head_origin_sha256'):
        if not re.fullmatch('[a-f0-9]{64}', p.get(key, '')):
            raise ValueError('Invalid factory trial binding: '+key)
    if p.get('max_exposure_ns') != 3000000 or p.get('window') != 'mid':
        raise ValueError('Unsupported factory trial exposure/window')
    if p.get('projection_model') != 'window-plane-1m-lut1000':
        raise ValueError('Regenerate factory trial: central window projection required')
    if p.get('frame_timestamp') != 'sensor-boottime-to-monotonic' or p.get('pixel_centres') != 'wire-half-pixel':
        raise ValueError('Regenerate factory trial: sensor timestamps and pixel-centre convention required')
    blob = (directory/'factory-map.bin').read_bytes()
    cal = (directory/'calibration.json').read_bytes()
    if len(blob)!=20+4*640*640*8 or blob[:20]!=b'GXRMAP1\0'+struct.pack('<III',640,640,4):
        raise ValueError('Invalid factory map layout')
    if hashlib.sha256(blob).hexdigest()!=p['map_sha256'] or hashlib.sha256(cal).hexdigest()!=p['calibration_sha256']:
        raise ValueError('Factory trial content hash mismatch')
    parsed = json.loads(cal)
    validate_calibration(parsed)
    if parsed['kind'] != 'galaxy_xr_sensor':
        raise ValueError('Sensor-stamped frames require explicit PC compatibility')
    for camera in parsed['GxrCameraCalibration']:
        if camera['Projection']['Coefficients'] != [200,200,320,320] or camera['Distortion']['Coefficients'] != [0]*8:
            raise ValueError('Factory map requires matching virtual camera optics')
    for x,y in struct.iter_unpack('<ff', blob[20:]):
        if (x,y)!=(-1,-1) and not (0<=x<640 and 0<=y<640):
            raise ValueError('Invalid factory map coordinate')
    return {'factory-trial.json': manifest, 'factory-map.bin': blob, 'calibration.json': cal,
            'device.sha256': (p['device_serial_sha256']+'\n').encode(),
            'factory-source.sha256': (p['factory_source_sha256']+'\n').encode(),
            'frame-timestamp': b'sensor-boottime-to-monotonic\n',
            'max-exposure-ns': b'3000000\n'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--serial', help='ADB transport serial for local bionic link libraries')
    ap.add_argument('--bionic-dir', type=Path, help='Directory containing arm64 device or Android NDK libc.so/libdl.so link inputs')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--diagnostic', action='store_true', help='Disable automatic factory setup and alignment')
    mode.add_argument('--profile', type=Path, help='Verified measured per-device profile')
    mode.add_argument('--factory-trial', type=Path, help='Existing private factory-trial bundle (legacy)')
    args = ap.parse_args()
    out = HERE / 'build'
    out.mkdir(exist_ok=True)
    profile = verified_profile(args.profile) if args.profile else None
    factory_files = factory_trial_files(args.factory_trial) if args.factory_trial else None
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
         '-Werror', '-Wno-unused-but-set-variable', '-DMODULE_VERSION="gxr-'+VERSION+'"',
         '-DHS_TIMER_CLOCK=CLOCK_BOOTTIME', '-DHS_LOG_CAPTURE_STATUS=1',
         '-I'+str(ROOT/'vendor/questlhsync'), str(ROOT/'vendor/questlhsync/lhsyncd.c'), str(HERE/'src/gxr.c'),
         '-o', str(out/'lhsyncd')], env=env)
    run(['zig', 'cc', '-target', 'aarch64-linux-musl', '-static', '-O2', '-Wall', '-Wextra',
         '-Werror', '-ffp-contract=off', str(HERE/'src/prepare.c'), '-lm',
         '-o', str(out/'gxr-prepare')], env=env)
    for source, binary in (('capture.c', 'gxr-lhsight'), ('head_origin.c', 'gxr-head-origin')):
        run(['clang', '--target=aarch64-linux-android29', '-fuse-ld=lld', '-nostdlib',
             '-fPIE', '-pie', '-O2', '-Wall', '-Wextra', '-Werror', '-fno-stack-protector',
             '-Wl,-e,_start', '-Wl,--dynamic-linker=/system/bin/linker64', '-Wl,-z,max-page-size=16384',
             str(HERE/'src/start.S'), str(HERE/'src'/source), str(bionic/'libc.so'), str(bionic/'libdl.so'),
             '-o', str(out/binary)])
    files = {p.relative_to(HERE/'module').as_posix(): p.read_bytes().replace(b'\r\n', b'\n')
             for p in (HERE/'module').rglob('*') if p.is_file()}
    binaries = ('lhsyncd', 'gxr-lhsight', 'gxr-head-origin', 'gxr-prepare')
    files.update({name: (out/name).read_bytes() for name in binaries})
    files['LICENSE'] = (ROOT/'LICENSE').read_bytes()
    files['README.md'] = (HERE/'README.md').read_bytes()
    if not args.diagnostic and not profile and not factory_files:
        files['automatic-setup'] = b'1\n'
    if profile:
        p, cal = profile
        files['calibration.json'] = cal
        files['device.sha256'] = (p['device_serial_sha256']+'\n').encode()
        files['profile.json'] = args.profile.read_bytes()
        files['max-exposure-ns'] = (str(round(p['max_exposure_us']*1000))+'\n').encode()
        files['profile.sha256'] = ''.join(hashlib.sha256(files[k]).hexdigest()+'  '+k+'\n' for k in ('calibration.json', 'device.sha256', 'profile.json', 'max-exposure-ns')).encode()
    if factory_files:
        files.update(factory_files)
        files['profile.sha256'] = ''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n'
                                         for name, data in sorted(factory_files.items())).encode()
    # Directory for temporary deployment always reflects this ZIP, without stale profile files.
    stage = out/'stage'
    stage.mkdir(exist_ok=True)
    for p in stage.rglob('*'):
        if p.is_file() and p.relative_to(stage).as_posix() not in files:
            p.unlink()
    variant = 'factory-trial' if factory_files else 'trial' if profile else 'diagnostic' if args.diagnostic else 'automatic'
    zip_path = out / ('QuestLHSync-GXR-'+VERSION+'-'+variant+'.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            (stage/name).parent.mkdir(parents=True, exist_ok=True)
            (stage/name).write_bytes(data)
            info = zipfile.ZipInfo(name, (2026, 10, 12, 0, 0, 0))
            info.create_system = 3
            mode = 0o755 if name.endswith('.sh') or name in binaries else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    print(zip_path)
    print('SHA256', hashlib.sha256(zip_path.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
