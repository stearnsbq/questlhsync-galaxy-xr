"""Record diagnostic spots, SteamVR poses, station poses and clock evidence offline."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

from build_module import HERE, FINGERPRINT, LIB_HASH
from capture_pose_clock import PoseClock, snapshot_poses


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--serial',required=True)
    ap.add_argument('--host',required=True)
    ap.add_argument('--seconds',type=int,default=30)
    ap.add_argument('--pose-session',type=Path)
    args=ap.parse_args()
    if not 1<=args.seconds<=300:ap.error('duration must be 1..300 seconds')
    adb=['adb','-s',args.serial]
    def run(argv,timeout=25):
        return subprocess.run(argv,check=True,capture_output=True,timeout=timeout).stdout
    def root(command,timeout=25):
        return run(adb+['exec-out','su -c '+shlex.quote(command)],timeout)
    if root('getprop ro.build.fingerprint').decode().strip()!=FINGERPRINT:
        raise RuntimeError('Unsupported firmware')
    if hashlib.sha256(root('cat /vendor/lib64/libqvrcamera_client.qti.so')).hexdigest()!=LIB_HASH:
        raise RuntimeError('Unsupported camera library')
    tag=datetime.now().strftime('%Y%m%d-%H%M%S')
    out=HERE/'build'/('lighthouse-capture-'+tag);out.mkdir()
    poses=args.pose_session or Path((HERE/'build/latest-pose-session.txt').read_text().strip())
    snapshot_poses(poses,out)
    remote='/data/local/tmp/qlhs-gxr-audit-'+tag
    run(adb+['push',str(HERE/'build/gxr-lhsight'),remote])
    try:
        root('chmod 755 '+remote)
        with PoseClock(args.host,poses,out):
            print('Capturing',args.seconds,'seconds to',out,flush=True)
            data=root(f'LD_LIBRARY_PATH=/vendor/lib64:/vendor/lib64/hw timeout {args.seconds+5} {remote} audit {args.seconds}',args.seconds+15)
            (out/'audit.txt').write_bytes(data)
        text=data.decode()
        if 'I GXR capture closed errors=0' not in text:
            raise RuntimeError('Camera capture did not close cleanly')
        if any(line.startswith(('C ','F ')) for line in text.splitlines()):
            raise RuntimeError('Audit unexpectedly emitted live alignment records')
        (out/'metadata.json').write_text(json.dumps(dict(fingerprint=FINGERPRINT,seconds=args.seconds,
            mode='offline_audit',pose_source=str(poses),reader_sha256=hashlib.sha256((HERE/'build/gxr-lhsight').read_bytes()).hexdigest()),indent=2))
        print('Saved',out,flush=True)
    finally:
        root('rm -f '+remote)


if __name__=='__main__':main()
