"""Experimental factory-derived ray conversion for offline Lighthouse replay only.

Consumes a native QuestLHSync recording, factory inventory and runtime third-eye
log. Rewrites blob coordinates into an ideal equidistant camera. This output is
NOT compatible with an unchanged live reader: it must never be installed as a
calibration profile for raw camera pixels.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

import cv2
import numpy as np
from factory_camera_model import factory_rays, validate_camera


def quaternion_rotation(q):
    if len(q) != 4 or not np.all(np.isfinite(q)):
        raise ValueError('Invalid factory quaternion')
    w, x, y, z = q
    if abs(sum(v*v for v in q)-1) > 1e-4:
        raise ValueError('Factory quaternion is not normalized')
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def load_factory_geometry(inventory, head_origin_log, window):
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
        if window != 'none' and 'curved_window' not in c:
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
    return inv, cams, {'kind': 'galaxy_xr', 'GxrCameraCalibration': calibration}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('recording', type=Path)
    ap.add_argument('--inventory', type=Path, required=True)
    ap.add_argument('--head-origin-log', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    ap.add_argument('--window', choices=('none', 'inner', 'outer', 'mid'), required=True)
    args = ap.parse_args()
    outputs = [args.output_dir/name for name in ('replay.txt', 'calibration.json', 'notes.json')]
    inputs = [p.resolve() for p in (args.recording, args.inventory, args.head_origin_log)]
    if any(p.resolve() in inputs for p in outputs):
        raise ValueError('Output must not overwrite an input file')
    inv, cams, calibration = load_factory_geometry(args.inventory, args.head_origin_log, args.window)
    lines = []
    accepted = rejected = frames = 0
    for line in args.recording.read_text().splitlines():
        values = line.split()
        if len(values) < 2 or values[1] != 'F':
            lines.append(line)
            continue
        cam, seq, ts, mean, count = map(int, values[2:7])
        if not 0 <= cam < 4 or count < 0 or len(values) != 7+4*count:
            raise ValueError('Unexpected frame record')
        blobs = []
        ray_batch = None
        valid_pixels = None
        if count:
            pixels = np.array([[int(values[7+4*j])/10, int(values[8+4*j])/10] for j in range(count)])
            camera = cams[cam]
            normalized = (pixels-camera['principal_point'])/camera['focal_length']
            valid_pixels = np.linalg.norm(normalized, axis=1) <= camera['max_valid_distorted_radius']
            try:
                ray_batch = np.full((count, 3), np.nan)
                if np.any(valid_pixels):
                    _, ray_batch[valid_pixels] = factory_rays(camera, pixels[valid_pixels], args.window != 'none', args.window == 'outer', args.window == 'mid')
            except ValueError:
                ray_batch = None  # Retry individually so one out-of-domain blob cannot discard the frame.
        for j in range(count):
            x, y, size, peak = map(int, values[7+4*j:11+4*j])
            if not valid_pixels[j]:
                rejected += 1
                continue
            try:
                if ray_batch is None:
                    _, rays = factory_rays(cams[cam], [[x/10, y/10]], args.window != 'none', args.window == 'outer', args.window == 'mid')
                    ray = rays[0]
                else:
                    ray = ray_batch[j]
            except ValueError:
                rejected += 1
                continue
            if not np.all(np.isfinite(ray)) or ray[2] <= 0:
                rejected += 1
                continue
            radius = np.linalg.norm(ray[:2])
            theta = np.arctan2(radius, ray[2])
            xy = ray[:2]*(200*theta/radius if radius > 1e-12 else 200)+320
            if np.any(xy < 0) or np.any(xy >= 640):
                rejected += 1
                continue
            blobs.extend([round(xy[0]*10), round(xy[1]*10), size, peak])
            accepted += 1
        lines.append(f'{values[0]} F {cam} {seq} {ts} {mean} {len(blobs)//4} '+ ' '.join(map(str, blobs)))
        frames += 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'replay.txt').write_text('\n'.join(lines)+'\n')
    (args.output_dir/'calibration.json').write_text(json.dumps(
        calibration, indent=2))
    (args.output_dir/'notes.json').write_text(json.dumps(dict(
        status='offline_remapped_pixels_only_do_not_install', window_hypothesis=args.window,
        frames=frames, accepted_blobs=accepted, rejected_blobs=rejected,
        factory_source_sha256=inv['source_sha256'],
        input_sha256={name: hashlib.sha256(path.read_bytes()).hexdigest()
                      for name, path in [('recording', args.recording), ('inventory', args.inventory),
                                         ('head_origin_log', args.head_origin_log)]},
        limitations=['Head transform inferred from runtime log; API still needed for generic startup',
                     'Curved-window model is experimental; exit points discarded in this far-field replay',
                     'Virtual camera bounds do not exactly reproduce original sensor visibility']), indent=2))
    print('Remapped', frames, 'frames;', accepted, 'blobs;', rejected, 'rejected')


if __name__ == '__main__':
    main()
