"""Read the pinned Galaxy XR factory profile into a private local build directory.

Does not install a profile, change services or modify any headset files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

from build_module import FINGERPRINT, LIB_HASH, HERE

FACTORY_PATH = '/mnt/vendor/efs/device_profile.textproto'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--serial', required=True, help='Galaxy XR ADB transport')
    ap.add_argument('--output-dir', type=Path, default=HERE/'build/factory-calibration')
    args = ap.parse_args()
    adb = ['adb', '-s', args.serial, 'exec-out']

    def root(command):
        # adb exec-out itself does not reliably propagate the remote exit code.
        wrapped = command + "; result=$?; printf '\\nQLHS_REMOTE_EXIT=%s\\n' \"$result\""
        result = subprocess.run(adb + ['su -c ' + shlex.quote(wrapped)],
                                check=True, capture_output=True, timeout=45)
        body, marker, status = result.stdout.rpartition(b'\nQLHS_REMOTE_EXIT=')
        if not marker or status.strip() != b'0':
            raise RuntimeError('Remote read failed; check device connection and KernelSU root')
        return body

    if root('getprop ro.build.fingerprint').decode().strip() != FINGERPRINT:
        raise RuntimeError('Unsupported firmware; calibration source path is firmware-pinned')
    if hashlib.sha256(root('cat /vendor/lib64/libqvrcamera_client.qti.so')).hexdigest() != LIB_HASH:
        raise RuntimeError('Unsupported QVR client')
    data = root('cat ' + shlex.quote(FACTORY_PATH))
    if not 1024 <= len(data) <= 16*1024*1024 or b'camera_extrinsics {' not in data:
        raise RuntimeError('Unexpected factory profile format or size')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'factory-device-profile.textproto').write_bytes(data)
    (args.output_dir/'source.json').write_text(json.dumps(dict(
        status='extracted_only_not_enabled', firmware=FINGERPRINT,
        source_path=FACTORY_PATH, sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data), runtime_selection='Not checked by this extraction command'), indent=2)+'\n')
    print('Saved factory profile to', args.output_dir)
    print('Private per-device data; not an installable QuestLHSync calibration.')


if __name__ == '__main__':
    main()
