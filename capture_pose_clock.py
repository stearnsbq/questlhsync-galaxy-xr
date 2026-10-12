"""Clock evidence for camera/SteamVR hand-eye captures; does not enable alignment."""
import csv
import json
from pathlib import Path
import socket
import threading
import time


def snapshot_poses(session, destination):
    session, destination = Path(session), Path(destination)
    text = (session/'poses.csv').read_text()
    # The recorder may be writing its last row. Preserve only complete rows.
    text = text[:text.rfind('\n')+1]
    rows = list(csv.DictReader(text.splitlines()))
    valid = [r for r in rows if r['valid'] == '1' and r['connected'] == '1']
    if not valid or not 0 <= time.perf_counter()-float(valid[-1]['after_s']) < 3:
        raise RuntimeError('Pose recorder has no recent valid HMD poses; start it on the user desktop')
    (destination/'poses.csv').write_text(text)
    (destination/'pose-identity.txt').write_text((session/'identity.txt').read_text())
    if (session/'stations.csv').exists():
        stations = (session/'stations.csv').read_text()
        (destination/'stations.csv').write_text(stations[:stations.rfind('\n')+1])


class PoseClock:
    def __init__(self, host, pose_session, out):
        self.host, self.pose_session, self.out = host, pose_session, Path(out)
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.samples = []
        self.error = None
        self.hello = None

    def collect(self):
        try:
            with socket.create_connection((self.host, 47280), timeout=3) as sock:
                sock.settimeout(2)
                buf = b''
                seq = 0
                while not self.stop.is_set():
                    seq += 1
                    before = time.perf_counter_ns()
                    sock.sendall(f'P {seq} {before}\n'.encode())
                    replied = False
                    while not replied and not self.stop.is_set():
                        data = sock.recv(65536)
                        after = time.perf_counter_ns()
                        if not data:
                            raise RuntimeError('Galaxy XR clock connection closed')
                        buf += data
                        while b'\n' in buf:
                            line, buf = buf.split(b'\n', 1)
                            line = line.decode(errors='replace')
                            if line.startswith('H '):
                                if ' model=Galaxy_XR ' not in line:
                                    raise RuntimeError('Clock endpoint is not Galaxy XR: '+line)
                                self.hello = line
                            if line.startswith('Q '):
                                _, received_seq, echoed, mono = line.split()
                                if int(received_seq) == seq and int(echoed) == before:
                                    if not self.hello:
                                        raise RuntimeError('Missing Galaxy XR identity')
                                    self.samples.append(dict(pc_before_ns=before, pc_after_ns=after,
                                                             headset_monotonic_ns=int(mono)))
                                    replied = True
                                    self.ready.set()
                        if len(buf) > 100000:
                            raise RuntimeError('Invalid clock protocol')
                    self.stop.wait(.05)
        except Exception as exc:
            self.error = str(exc)
            self.ready.set()

    def __enter__(self):
        snapshot_poses(self.pose_session, self.out)
        self.thread = threading.Thread(target=self.collect, daemon=True)
        self.thread.start()
        if not self.ready.wait(6) or self.error:
            self.stop.set()
            self.thread.join(4)
            raise RuntimeError(self.error or 'Galaxy XR clock timed out')
        return self

    def __exit__(self, kind, value, trace):
        self.stop.set()
        self.thread.join(4)
        (self.out/'clock-sync.json').write_text(json.dumps(dict(
            hello=self.hello, error=self.error, samples=self.samples,
            timestamp_mode='camera-arrival-monotonic',
            limitations=['Sensor-to-arrival delay and streaming pose latency are not removed; use stationary views.']), indent=2))
        if kind is None:
            snapshot_poses(self.pose_session, self.out)
            if self.error or len(self.samples) < 10:
                raise RuntimeError(self.error or 'Not enough clock samples')
