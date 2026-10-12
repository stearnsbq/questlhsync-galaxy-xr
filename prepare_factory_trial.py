"""Build a private factory pixel-map trial; requires a saved runtime head transform.

This is not automatic startup calibration or a generic release.
No installation is performed here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import struct
import subprocess

import numpy as np
from build_module import FINGERPRINT, LIB_HASH
from factory_camera_model import factory_projection_rays, distorted_radius
from prepare_factory_replay import load_factory_geometry


def make_map(camera):
    y, x = np.mgrid[:640, :640]
    pixels = np.stack((x.ravel(), y.ravel()), axis=1)
    normalized = (pixels-camera['principal_point'])/camera['focal_length']
    limit = min(camera['max_valid_distorted_radius'], float(distorted_radius(
        np.arctan(camera['max_valid_undistorted_radius']), camera['distortion_coefficients'])))
    valid = np.linalg.norm(normalized, axis=1) <= limit
    indices = np.flatnonzero(valid)
    rays = factory_projection_rays(camera, pixels[valid])
    r = np.linalg.norm(rays[:, :2], axis=1)
    theta = np.arctan2(r, rays[:, 2])
    scale = np.divide(200*theta, r, out=np.full_like(r, 200), where=r>1e-12)
    xy = rays[:, :2]*scale[:, None]+320
    keep = (rays[:, 2]>0) & np.all(np.isfinite(xy) & (xy>=0) & (xy<640), axis=1)
    out = np.full((640*640, 2), -1, dtype='<f4')
    out[indices[keep]] = xy[keep]
    return out.tobytes(), int(np.count_nonzero(keep))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--serial', required=True, help='ADB transport for firmware/source/device binding')
    ap.add_argument('--inventory', type=Path, required=True)
    ap.add_argument('--head-origin-log', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    args = ap.parse_args()
    inv, cams, calibration = load_factory_geometry(args.inventory, args.head_origin_log, 'mid')
    calibration['kind'] = 'galaxy_xr_sensor'

    def root(command):
        wrapped = command + "; result=$?; printf '\\nQLHS_REMOTE_EXIT=%s\\n' \"$result\""
        data = subprocess.run(['adb', '-s', args.serial, 'exec-out', 'su -c '+shlex.quote(wrapped)],
                              check=True, capture_output=True, timeout=45).stdout
        body, marker, code = data.rpartition(b'\nQLHS_REMOTE_EXIT=')
        if not marker or code.strip()!=b'0':
            raise RuntimeError('Failed to read factory trial binding')
        return body

    if root('getprop ro.build.fingerprint').decode().strip()!=FINGERPRINT:
        raise ValueError('Unsupported firmware')
    if hashlib.sha256(root('cat /vendor/lib64/libqvrcamera_client.qti.so')).hexdigest()!=LIB_HASH:
        raise ValueError('Unsupported QVR library')
    source = hashlib.sha256(root('cat /mnt/vendor/efs/device_profile.textproto')).hexdigest()
    if source!=inv['source_sha256']:
        raise ValueError('Inventory is not from the currently connected factory profile')
    serial = root('getprop ro.serialno').strip()
    if not serial:
        raise ValueError('Missing hardware serial')
    maps, valid = [], []
    for camera in cams:
        data, count = make_map(camera)
        maps.append(data); valid.append(count)
        print('Mapped', camera['camera_id'], count, 'valid grid points', flush=True)
    blob = b'GXRMAP1\0'+struct.pack('<III',640,640,4)+b''.join(maps)
    cal = (json.dumps(calibration, indent=2)+'\n').encode()
    manifest = dict(schema='questlhsync-gxr-factory-trial-v1', firmware=FINGERPRINT,
        device_serial_sha256=hashlib.sha256(serial).hexdigest(), factory_source_sha256=source,
        map_sha256=hashlib.sha256(blob).hexdigest(), calibration_sha256=hashlib.sha256(cal).hexdigest(),
        head_origin_sha256=hashlib.sha256(args.head_origin_log.read_bytes()).hexdigest(),
        max_exposure_ns=3000000, window='mid', valid_grid_points=valid,
        projection_model='window-plane-1m-lut1000',
        frame_timestamp='sensor-boottime-to-monotonic', pixel_centres='wire-half-pixel',
        head_origin_source='saved_runtime_log_not_automatic',
        status='experimental_private_trial')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'factory-map.bin').write_bytes(blob)
    (args.output_dir/'calibration.json').write_bytes(cal)
    (args.output_dir/'factory-trial.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Private trial bundle:', args.output_dir)


if __name__=='__main__':
    main()
