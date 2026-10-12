"""Offline consistency check of bright-spot rays. Sources are not identified stations."""
import argparse
import csv
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('session', type=Path)
    ap.add_argument('--optics', required=True, type=Path)
    ap.add_argument('--hand-eye', required=True, type=Path)
    ap.add_argument('--lag-ms', type=float, default=10)
    args = ap.parse_args()
    optics = json.loads(args.optics.read_text())['cameras']
    rig = json.loads(args.hand_eye.read_text())['hmd_from_cameras']
    clock = json.loads((args.session/'clock-sync.json').read_text())
    if clock['error'] or not clock['samples']:
        raise ValueError('Invalid clock evidence')
    with (args.session/'poses.csv').open() as f:
        poses = list(csv.DictReader(f))
    times = np.array([(float(p['before_s'])+float(p['after_s']))/2 for p in poses])
    mats = np.array([[float(p[n]) for n in ('m00','m01','m02','tx','m10','m11','m12','ty','m20','m21','m22','tz')] for p in poses]).reshape(-1,3,4)
    origins, directions, cameras, seconds = [], [], [], []
    frames = 0
    for line in (args.session/'audit.txt').read_text().splitlines():
        if not line.startswith('I sample '):
            continue
        v = list(map(int,line.split()[2:]));cam,seq,arrival,boot,sensor,expo,mean,nb = v[:8]
        frames += 1
        nearby = [s for s in clock['samples'] if abs(s['headset_monotonic_ns']-arrival)<3e9]
        if not nearby:
            continue
        best = min(nearby,key=lambda s:s['pc_after_ns']-s['pc_before_ns'])
        if best['pc_after_ns']-best['pc_before_ns']>20e6:
            continue
        t = (arrival-best['headset_monotonic_ns']+(best['pc_before_ns']+best['pc_after_ns'])/2)/1e9-args.lag_ms/1000
        hi = int(np.searchsorted(times,t));lo=hi-1
        if lo<0 or hi>=len(times) or times[hi]-times[lo]>.05:
            continue
        if any(poses[i]['valid']!='1' or poses[i]['connected']!='1' for i in (lo,hi)):
            continue
        alpha=(t-times[lo])/(times[hi]-times[lo])
        delta=cv2.Rodrigues(mats[lo,:,:3].T@mats[hi,:,:3])[0]
        rotation=mats[lo,:,:3]@cv2.Rodrigues(alpha*delta)[0]
        position=mats[lo,:,3]*(1-alpha)+mats[hi,:,3]*alpha
        hc=np.array(rig[str(cam)])
        world_r=rotation@hc[:3,:3];world_p=position+rotation@hc[:3,3]
        pts=[]
        for b in range(nb):
            x,y,count,peak=v[8+b*4:12+b*4]
            if peak>=250 and count<=400:
                pts.append([x/10-.5,y/10-.5])
        if not pts:
            continue
        cal=optics[str(cam)]
        uv=cv2.fisheye.undistortPoints(np.array(pts).reshape(-1,1,2),np.array(cal['K']),np.array(cal['D']))
        rays=np.c_[uv.reshape(-1,2),np.ones(len(pts))]@world_r.T
        rays/=np.linalg.norm(rays,axis=1)[:,None]
        directions.extend(rays);origins.extend([world_p]*len(pts));cameras.extend([cam]*len(pts));seconds.extend([t]*len(pts))
    o,d=np.array(origins),np.array(directions)
    if len(o)<100:
        raise ValueError('Not enough usable rays')
    cams=np.array(cameras);seconds=np.array(seconds)
    rng=np.random.default_rng(672)
    available=np.arange(len(o));sources=[]
    cosine=np.cos(np.radians(.5))
    def mask(point, oo, dd):
        v=point-oo;distance=np.linalg.norm(v,axis=1)
        return np.einsum('ij,ij->i',v,dd)>distance*cosine
    for source in range(6):
        if len(available)<100:
            break
        subset=rng.choice(available,min(4000,len(available)),replace=False)
        oo,dd=o[subset],d[subset]
        a,b=rng.choice(len(subset),(2,4000))
        c=np.sum(dd[a]*dd[b],axis=1);gap=oo[b]-oo[a]
        ba=np.sum(gap*dd[a],axis=1);bb=np.sum(gap*dd[b],axis=1)
        denominator=np.maximum(1-c*c,1e-12)
        u=(ba-c*bb)/denominator;v=(c*ba-bb)/denominator
        pa=oo[a]+u[:,None]*dd[a];pb=oo[b]+v[:,None]*dd[b]
        good=(np.linalg.norm(gap,axis=1)>.06)&(denominator>.001)&(u>.2)&(u<8)&(v>.2)&(v<8)&(np.linalg.norm(pa-pb,axis=1)<.04)
        candidates=(pa[good]+pb[good])/2
        if not len(candidates):
            break
        scores=[int(mask(p,oo,dd).sum()) for p in candidates]
        p=candidates[int(np.argmax(scores))]
        for _ in range(5):
            chosen=available[mask(p,o[available],d[available])]
            if len(chosen)<30:
                break
            # Train on alternating one-second time intervals; evaluate the rest.
            train=chosen[(seconds[chosen].astype(int)%2)==0]
            if len(train)<20:
                break
            project=np.eye(3)[None,:,:]-d[train,:,None]*d[train,None,:]
            p=np.linalg.lstsq(project.sum(axis=0),np.einsum('nij,nj->i',project,o[train]),rcond=None)[0]
        selected=available[mask(p,o[available],d[available])]
        if len(selected)<50:
            break
        vec=p-o[selected];dist=np.linalg.norm(vec,axis=1)
        angles=np.degrees(np.arccos(np.clip(np.sum(vec*d[selected],axis=1)/dist,-1,1)))
        held=(seconds[selected].astype(int)%2)==1
        sources.append(dict(position_m=p.tolist(),rays=len(selected),
            camera_counts={str(c):int((cams[selected]==c).sum()) for c in range(4)},
            ray_origin_span_m=np.ptp(o[selected],axis=0).tolist(),median_residual_degrees=float(np.median(angles)),
            held_out_inlier_rays=int(held.sum()),held_out_inlier_median_degrees=float(np.median(angles[held])) if held.any() else None))
        available=available[~mask(p,o[available],d[available])]
    pairs=[dict(a=a,b=b,distance_m=float(np.linalg.norm(np.array(sources[a]['position_m'])-sources[b]['position_m']))) for a in range(len(sources)) for b in range(a+1,len(sources))]
    report=dict(status='unidentified_source_candidates',frames=frames,rays=len(o),assumed_lag_ms=args.lag_ms,
                sources=sources,pair_distances=pairs,
                limitations=['Bright stationary objects can also produce consistent rays',
                             'Source hypotheses and inlier membership use all observations; held-out residuals are conditional on inlier selection',
                             'No base-station identity or live alignment established','Lag is assumed, not calibrated'])
    path=args.session/f'triangulation-{args.lag_ms:g}ms.json';path.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
