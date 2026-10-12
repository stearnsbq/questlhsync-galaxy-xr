"""Temporary real-device protocol/capture check. No module install or reboot."""
import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import re
import shlex
import socket
import subprocess
import time

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--serial')
    ap.add_argument('--seconds', type=int, default=12)
    args = ap.parse_args()
    adb = ['adb'] + (['-s', args.serial] if args.serial else [])
    stage = HERE/'build/stage'
    if (stage/'profile.sha256').exists():
        raise RuntimeError('This check is for the default diagnostic build only')
    tag = datetime.now().strftime('%Y%m%d-%H%M%S')
    remote = '/data/local/tmp/qlhs-gxr-check-' + tag
    logpath = HERE/'build'/('live-'+tag+'.log')
    port = None
    proc = None

    def run(cmd):
        return subprocess.run(cmd, capture_output=True, check=True, timeout=25).stdout.decode(errors='replace').strip()

    def root(cmd):
        return run(adb + ['shell', 'su -c ' + shlex.quote(cmd)])

    def stop():
        # Verify executable path, never signal other daemons or camera services.
        root('for p in $(pidof lhsyncd); do '
             f'if [ "$(readlink "/proc/$p/exe")" = {shlex.quote(remote+"/lhsyncd")} ]; then '
             'kill -TERM "$p"; fi; done; true')

    report = {'lines': [], 'cameras': {}, 'clock_replies': 0}
    try:
        run(adb + ['push', str(stage), remote])
        root(f'chmod 755 {remote}/lhsyncd {remote}/gxr-lhsight')
        port = int(run(adb + ['forward', 'tcp:0', 'tcp:47280']))
        with logpath.open('wb') as log:
            proc = subprocess.Popen(adb + ['exec-out', 'su -c ' + shlex.quote('sh '+remote+'/run.sh')], stdout=log, stderr=log)
            time.sleep(2)
            if proc.poll() is not None:
                raise RuntimeError('Daemon exited: '+logpath.read_text(errors='replace'))
            frames = defaultdict(list)
            with socket.create_connection(('127.0.0.1', port), timeout=5) as s:
                s.settimeout(2)
                start = time.monotonic(); ping = 0; buf = b''
                while time.monotonic()-start < args.seconds:
                    now = time.monotonic()
                    if now-ping >= 1:
                        s.sendall(b'P 1 123456\n'); ping = now
                    try:
                        chunk = s.recv(16384)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break
                    buf += chunk
                    while b'\n' in buf:
                        line, buf = buf.split(b'\n', 1)
                        text = line.decode(errors='replace')
                        report['lines'].append(text)
                        if text.startswith(('C ', 'F ')):
                            raise RuntimeError('Diagnostic mode emitted alignment data')
                        if text.startswith('Q 1 123456 '):
                            report['clock_replies'] += 1
                        m = re.match(r'I gxr cam=(\d+) frames=(\d+)', text)
                        if m:
                            frames[int(m[1])].append(int(m[2]))
                report['cameras'] = dict(frames)
            # The upstream daemon grants five seconds before stopping capture.
            # Five-second idle grace + up to three seconds for child cleanup.
            time.sleep(10)
            children = root('for p in $(pidof gxr-lhsight); do '
                            f'[ "$(readlink "/proc/$p/exe")" = {shlex.quote(remote+"/gxr-lhsight")} ] && echo "$p"; done; true')
            report['capture_stopped_on_disconnect'] = not children
            stop()
            proc.wait(timeout=10)
        report['daemon_exit'] = proc.returncode
        report['passed'] = (len(frames) == 4 and all(len(v) > 1 and v[-1] > v[0] for v in frames.values())
                            and report['clock_replies'] > 0 and not children and proc.returncode == 0)
        print(json.dumps({k: v for k, v in report.items() if k != 'lines'}, indent=2))
        if not report['passed']:
            raise RuntimeError('Live check did not pass; inspect '+str(logpath))
    finally:
        if proc is not None:
            stop()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.terminate()
        if port is not None:
            run(adb + ['forward', '--remove', 'tcp:'+str(port)])
        # Exact uniquely-created directory; no recursion or unrelated files.
        names = [p.name for p in stage.iterdir() if p.is_file()]
        root('rm -f '+ ' '.join(shlex.quote(remote+'/'+n) for n in names)+'; rmdir '+shlex.quote(remote))
        (HERE/'build'/('live-'+tag+'.json')).write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print('Evidence:', logpath)


if __name__ == '__main__':
    main()
