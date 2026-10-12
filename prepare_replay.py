"""Convert a Galaxy XR diagnostic audit to an offline QuestLHSync replay.

Outputs are experimental local evidence, never a module activation profile.
Requires the local replay build with PinholeXY support.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
import cv2
import numpy as np


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('session',type=Path)
    ap.add_argument('--optics',type=Path,required=True)
    ap.add_argument('--hand-eye',type=Path,required=True)
    ap.add_argument('--max-exposure-us',type=float,
                    help='Offline comparison only: accept positive exposures up to this limit')
    ap.add_argument('--output-dir',type=Path,help='Keep comparison outputs separate from the capture')
    args=ap.parse_args()
    if args.max_exposure_us is not None and (not math.isfinite(args.max_exposure_us) or args.max_exposure_us<=0):
        ap.error('--max-exposure-us must be finite and positive')
    out=args.output_dir or args.session
    out.mkdir(parents=True,exist_ok=True)
    optics=json.loads(args.optics.read_text())['cameras']
    rig=json.loads(args.hand_eye.read_text())['hmd_from_cameras']
    cal=[]
    for c in range(4):
        k=np.array(optics[str(c)]['K']);d=np.array(optics[str(c)]['D']).ravel().tolist()
        cal.append(dict(Id=c,ImageSize=[640,640],SensorType='s5k931',Shutter={'Type':'Global'},
            Projection={'Model':'PinholeXY','Coefficients':[k[0,0],k[1,1],k[0,2],k[1,2]]},
            Distortion={'Model':'Fisheye62','Coefficients':d+[0,0,0,0]},
            DeviceFromCamera=np.array(rig[str(c)]).ravel().tolist()))
    (out/'offline-calibration.json').write_text(json.dumps({'kind':'galaxy_xr','GxrCameraCalibration':cal},indent=2))
    clock=json.loads((args.session/'clock-sync.json').read_text())
    if clock['error'] or not clock['samples']:
        raise ValueError('Invalid clock evidence')
    events=[];frame_times=[];accepted=0;rejected=0
    for line in (args.session/'audit.txt').read_text().splitlines():
        if not line.startswith('I sample '):continue
        v=list(map(int,line.split()[2:]));cam,seq,arrival,boot,sensor,expo,mean,nb=v[:8]
        near=[s for s in clock['samples'] if abs(s['headset_monotonic_ns']-arrival)<3e9]
        if not near:continue
        best=min(near,key=lambda s:s['pc_after_ns']-s['pc_before_ns'])
        pc=arrival-best['headset_monotonic_ns']+(best['pc_before_ns']+best['pc_after_ns'])//2
        # Preserve the full observation window across exposure comparisons.
        frame_times.append(pc)
        if args.max_exposure_us is not None and not 0<expo<=args.max_exposure_us*1000:
            rejected+=1
            continue
        accepted+=1
        # Audit output arrival is not PC receive time. Record an explicitly
        # reconstructed receive event with 1 ms transport delay; Q carries the
        # actual measured clock evidence and --pings bypasses arrival fitting.
        events.append((pc+1000000,f'F {cam} {seq} {arrival//1000} {mean} {nb} '+ ' '.join(map(str,v[8:]))))
    if not frame_times:
        raise ValueError('No camera frames with matching clock evidence')
    start,end=min(frame_times)-500000000,max(frame_times)+500000000
    for s in clock['samples']:
        events.append((s['pc_after_ns'],f"Q {s['pc_before_ns']/1e9:.9f} {s['pc_after_ns']/1e9:.9f} {s['headset_monotonic_ns']/1e9:.9f}"))
    with (args.session/'poses.csv').open() as f:
        for row in csv.DictReader(f):
            t=int((float(row['before_s'])+float(row['after_s']))*5e8)
            if start<=t<=end and row['valid']=='1' and row['connected']=='1':
                events.append((t,'P 0 '+' '.join(row[n] for n in ('m00','m01','m02','tx','m10','m11','m12','ty','m20','m21','m22','tz'))))
    station_rows=[]
    with (args.session/'stations.csv').open() as f:
        for row in csv.DictReader(f):
            t=int(float(row['pc_s'])*1e9)
            if not start<=t<=end:continue
            r=np.array([float(row[f'm{i}{j}']) for i in range(3) for j in range(3)]).reshape(3,3)
            rv=cv2.Rodrigues(r)[0].ravel();angle=np.linalg.norm(rv)
            q=np.r_[np.cos(angle/2),rv*(np.sin(angle/2)/angle if angle>1e-12 else .5)]
            values=[float(row[n]) for n in ('tx','ty','tz')]+q.tolist()
            events.append((t,'S '+row['serial']+' '+' '.join(f'{v:.9f}' for v in values)))
            station_rows.append(row)
    if len({r['serial'] for r in station_rows})<2:
        raise ValueError('Need two current base-station poses')
    events.sort(key=lambda v:v[0])
    (out/'replay.txt').write_text(''.join(f'{t} {line}\n' for t,line in events))
    (out/'replay-notes.json').write_text(json.dumps(dict(
        status='offline_only',frames=accepted,events=len(events),
        source_session=str(args.session.resolve()),max_exposure_us=args.max_exposure_us,
        exposure_rejected_frames=rejected,clock_matched_frames=len(frame_times),
        limitations=['F PC receive times reconstructed; use --pings',
                     'Station poses are OpenVR-visible poses and can include the current driver correction',
                     'No controller trajectory exported; mirror identity cannot be resolved by worn-device motion',
                     'Candidate calibration; no live alignment enabled']),indent=2))
    print(out/'replay.txt',len(events),'events',accepted,'accepted frames',rejected,'exposure rejections')


if __name__=='__main__':main()
