"""Inventory a device-profile textproto without enabling alignment.

Extracts camera blocks from the observed human-readable profile format. This is
not a general protobuf parser or a spline-to-KB4 calibration converter. Keep raw
profiles and reports in ignored local directories; they may identify a device.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re


def blocks(text, name):
    # Observed dump uses unindented top-level messages and closing braces.
    return re.findall(r'^' + re.escape(name) + r'\s*\{\s*\n(.*?)^\}', text, re.M | re.S)


def field(text, name):
    match = re.search(r'^\s*' + re.escape(name) + r':\s*("[^"\n]*"|[^\s#]+)', text, re.M)
    return match.group(1).strip('"') if match else None


def vector(text, name, axes):
    match = re.search(r'\b' + re.escape(name) + r'\s*\{([^{}]*)\}', text, re.S)
    if not match:
        raise ValueError('Missing vector: ' + name)
    values = [float(field(match.group(1), axis)) for axis in axes]
    if not all(math.isfinite(value) for value in values):
        raise ValueError('Non-finite vector: ' + name)
    return values


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('profile', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    raw = args.profile.read_bytes()
    text = raw.decode('utf-8')
    cameras = []
    for block in blocks(text, 'cameras'):
        logical = field(block, 'logical_camera_id')
        if logical not in ('tracking', 'ctrl-tracking'):
            continue
        camera = dict(camera_id=field(block, 'camera_id'), logical_camera_id=logical,
                      physical_camera_id=field(block, 'physical_camera_id'),
                      width=int(field(block, 'calibrated_width')),
                      height=int(field(block, 'calibrated_height')),
                      focal_length=vector(block, 'calibrated_focal_length', ('x', 'y')),
                      principal_point=vector(block, 'calibrated_principal_point', ('x', 'y')))
        if 'distortion_fisheye_spline3' in block:
            camera['distortion_model'] = 'fisheye_spline3'
            camera['distortion_coefficients'] = vector(block, 'distortion_fisheye_spline3', tuple('k'+str(i) for i in range(6)))
        else:
            camera['distortion_model'] = 'unrecognized'
        cameras.append(camera)
    extrinsics = []
    ids = {camera['camera_id'] for camera in cameras}
    for block in blocks(text, 'camera_extrinsics'):
        if field(block, 'camera_id') in ids:
            extrinsics.append(dict(camera_id=field(block, 'camera_id'),
                                   frame_id=field(block, 'frame_id'),
                                   position=vector(block, 'p', ('x', 'y', 'z')),
                                   quaternion_wxyz=vector(block, 'q', ('w', 'x', 'y', 'z'))))
    if not cameras or not extrinsics:
        raise ValueError('No matching tracking camera calibration blocks found')
    report = dict(status='inventory_only_not_alignment_calibration',
                  source_sha256=hashlib.sha256(raw).hexdigest(),
                  cameras=cameras, camera_extrinsics=extrinsics,
                  unresolved=['Confirm runtime-selected per-device source, not nominal fallback',
                              'Establish fisheye_spline3 projection definition',
                              'Establish frame transform to streamed SteamVR HMD origin',
                              'Validate against measured observations before enabling'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print('Inventoried', len(cameras), 'tracking camera entries;', len(extrinsics), 'extrinsics')
    print(args.output)


if __name__ == '__main__':
    main()
