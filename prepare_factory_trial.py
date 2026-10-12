"""Build a private factory pixel-map trial; requires a saved runtime head transform.

This is not automatic startup calibration or a generic release.
No installation is performed here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess

import cv2
import numpy as np
from build_module import FINGERPRINT, LIB_HASH
from factory_camera_model import factory_projection_rays, distorted_radius, validate_camera


def quaternion_rotation(q):
    if len(q) != 4 or not np.all(np.isfinite(q)):
        raise ValueError('Invalid factory quaternion')
    w, x, y, z = q
    if abs(sum(v*v for v in q)-1) > 1e-4:
        raise ValueError('Factory quaternion is not normalized')
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def load_factory_geometry(inventory, head_origin_log):
    inv = json.loads(inventory.read_text())
    order = {('tracking', '0'): 0, ('tracking', '1'): 1,
             ('ctrl-tracking', '0'): 2, ('ctrl-tracking', '1'): 3}
    cams = sorted(inv['cameras'], key=lambda c: order[c['logical_camera_id'], c['physical_camera_id']])
    if len(cams) != 4 or len({(c['logical_camera_id'], c['physical_camera_id']) for c in cams}) != 4:
        raise ValueError('Expected one factory entry for each tracking buffer')
    ext = {e['camera_id']: e for e in inv['camera_extrinsics']}
    match = re.search(r'FRAME_IMU_0_t_SENSOR_THIRD_EYE status = 0 r=\[([^]]+)\] t=\[([^]]+)\]',
                      head_origin_log.read_text())
    if not match:
        raise ValueError('No successful runtime third-eye transform in log')
    rv, pos = (np.array([float(v) for v in part.split()]) for part in match.groups())
    if rv.shape != (3,) or pos.shape != (3,) or not np.all(np.isfinite(np.r_[rv, pos])):
        raise ValueError('Invalid runtime head transform')
    imu_from_head = np.eye(4)
    imu_from_head[:3, :3] = cv2.Rodrigues(rv)[0]
    imu_from_head[:3, 3] = pos
    calibration = []
    for i, c in enumerate(cams):
        validate_camera(c)
        if 'curved_window' not in c:
            raise ValueError('Window conversion requires factory window parameters')
        e = ext[c['camera_id']]
        if e['frame_id'] != 'IMU_0':
            raise ValueError('Factory camera is not in the expected common frame')
        imu_from_camera = np.eye(4)
        imu_from_camera[:3, :3] = quaternion_rotation(e['quaternion_wxyz']).T
        imu_from_camera[:3, 3] = e['position']
        if not np.all(np.isfinite(imu_from_camera)):
            raise ValueError('Invalid factory camera transform')
        calibration.append(dict(Id=i, ImageSize=[640, 640], SensorType='s5k931',
            Shutter={'Type': 'Global'}, Projection={'Model': 'PinholeXY', 'Coefficients': [200, 200, 320, 320]},
            Distortion={'Model': 'Fisheye62', 'Coefficients': [0]*8},
            DeviceFromCamera=(np.linalg.inv(imu_from_head)@imu_from_camera).ravel().tolist()))
    return inv, cams, {'kind': 'galaxy_xr_sensor', 'GxrCameraCalibration': calibration}


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
    inv, cams, calibration = load_factory_geometry(args.inventory, args.head_origin_log)

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
