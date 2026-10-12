"""Record synchronized tracking-camera checkerboard views; preserve raw local evidence."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
from contextlib import nullcontext

from capture_pose_clock import PoseClock

from build_module import FINGERPRINT, LIB_HASH, HERE


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--serial', required=True)
    ap.add_argument('--seconds', type=int, default=60)
    ap.add_argument('--grid-width-mm', type=float, required=True)
    ap.add_argument('--pose-session', type=Path, help='Active record_poses output directory')
    ap.add_argument('--clock-host', help='Galaxy XR module IP; required with --pose-session')
    args = ap.parse_args()
    if bool(args.pose_session) != bool(args.clock_host):
        ap.error('--pose-session and --clock-host must be supplied together')
    if not 1 <= args.seconds <= 300 or not 0 < args.grid_width_mm < 5000:
        ap.error('Invalid duration/grid width')
    adb = ['adb', '-s', args.serial]
    def run(argv, timeout=25):
        return subprocess.run(argv, check=True, capture_output=True, timeout=timeout).stdout
    def root(command, timeout=25):
        return run(adb + ['exec-out', 'su -c '+shlex.quote(command)], timeout)
    if root('getprop ro.build.fingerprint').decode().strip() != FINGERPRINT:
        raise RuntimeError('Unsupported firmware')
    if hashlib.sha256(root('cat /vendor/lib64/libqvrcamera_client.qti.so')).hexdigest() != LIB_HASH:
        raise RuntimeError('Unsupported camera client')
    tag = datetime.now().strftime('%Y%m%d-%H%M%S')
    remote = '/data/local/tmp/qlhs-gxr-cal-'+tag
    out = HERE/'build'/('tracking-calibration-'+tag)
    out.mkdir()
    if args.pose_session:
        from capture_pose_clock import snapshot_poses
        snapshot_poses(args.pose_session, out)
    root('mkdir -m 700 '+remote)
    run(adb+['push', str(HERE/'build/gxr-lhsight'), remote+'-reader'])
    root('chmod 755 '+remote+'-reader')
    print('Capturing all four cameras for', args.seconds, 'seconds.', flush=True)
    clock = PoseClock(args.clock_host, args.pose_session, out) if args.pose_session else nullcontext()
    with clock, (out/'capture.log').open('wb') as log:
        result = subprocess.run(adb+['exec-out', 'su -c '+shlex.quote(
            f'LD_LIBRARY_PATH=/vendor/lib64:/vendor/lib64/hw timeout {args.seconds+10} {remote}-reader capture {remote} {args.seconds}')],
            stdout=log, stderr=log, timeout=args.seconds+30)
    entries = []
    for line in (out/'capture.log').read_text(errors='replace').splitlines():
        match = re.fullmatch(r'I saved sample=(\d+) cam=(\d+) seq=(\d+) sensor=(\d+) arrival=(\d+) exposure=(\d+) path=(\S+)', line)
        if not match:
            continue
        sample, cam, seq, sensor, arrival, exposure = map(int, match.groups()[:6])
        name = f'pair-{sample:03d}-cam-{cam}.pgm'
        path = remote+'/'+name
        if match[7] != path or cam not in range(4):
            raise RuntimeError('Unexpected capture path')
        data = root('cat '+path)
        if len(data) != 409615 or not data.startswith(b'P5\n640 640\n255\n'):
            raise RuntimeError('Invalid image: '+path)
        (out/name).write_bytes(data)
        root('rm -f '+path)
        entries.append(dict(sample=sample, camera=cam, sequence=seq, sensor_timestamp=sensor,
                            arrival_monotonic_ns=arrival, exposure_field=exposure, image=name,
                            sha256=hashlib.sha256(data).hexdigest()))
    (out/'metadata.json').write_text(json.dumps(dict(fingerprint=FINGERPRINT, grid_width_mm=args.grid_width_mm,
        checkerboard_inner_corners=[9,6], width=640, height=640, frames=entries,
        reader_exit=result.returncode), indent=2)+'\n')
    root('rm -f '+remote+'-reader; rmdir '+remote)
    print('Saved', len(entries), 'images to', out, flush=True)
    result.check_returncode()
    if len(entries) < 4:
        raise RuntimeError('Not enough images')


if __name__ == '__main__':
    main()
