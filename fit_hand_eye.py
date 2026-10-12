"""Fit a candidate HMD-from-camera-0 transform using stationary checkerboard views.

Uses fixed measured intrinsics, raw-universe OpenVR poses, and measured clock
round trips. Writes evidence only; never installs an alignment profile.
"""
import argparse
import csv
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
import cv2
import numpy as np


def transform(r, t):
    a = np.eye(4)
    a[:3, :3], a[:3, 3] = r, np.asarray(t).reshape(3)
    return a


def angle(r):
    return float(np.linalg.norm(cv2.Rodrigues(r)[0]))


def scatter(mats, reference=None):
    if reference is None:
        u, _, vt = np.linalg.svd(sum(m[:3, :3] for m in mats))
        r = u @ np.diag([1, 1, np.linalg.det(u@vt)]) @ vt
        reference = transform(r, np.median([m[:3, 3] for m in mats], axis=0))
    distances = [float(np.linalg.norm(m[:3, 3]-reference[:3, 3])*1000) for m in mats]
    angles = [float(np.degrees(angle(m[:3, :3] @ reference[:3, :3].T))) for m in mats]
    return reference, dict(position_mm=distances, rotation_degrees=angles,
                           median_position_mm=float(np.median(distances)),
                           max_position_mm=max(distances), median_rotation_degrees=float(np.median(angles)),
                           max_rotation_degrees=max(angles))


def refine_pixels(train, held, x, world_board, obj, k, d):
    # Jointly fit one camera mounting transform and one fixed board pose.
    # This avoids treating noisy per-view planar PnP rotations as exact.
    def pack(m):
        return np.r_[cv2.Rodrigues(m[:3,:3])[0].ravel(), m[:3,3]]
    def unpack(v):
        return transform(cv2.Rodrigues(v[:3])[0], v[3:6])
    def residual(v, views):
        camera_from_hmd = np.linalg.inv(unpack(v[:6]))
        board = unpack(v[6:])
        out = []
        for s in views:
            cb = camera_from_hmd @ np.linalg.inv(s['hmd']) @ board
            projected, _ = cv2.fisheye.projectPoints(obj, cv2.Rodrigues(cb[:3,:3])[0], cb[:3,3], k, d)
            out.extend((projected-s['points']).ravel())
        return np.array(out)
    v = np.r_[pack(x), pack(world_board)]
    damping = .001
    for iteration in range(60):
        res = residual(v, train)
        jac = np.column_stack([(residual(v+np.eye(12)[j]*1e-6, train)-res)/1e-6 for j in range(12)])
        normal, gradient = jac.T@jac, jac.T@res
        step = np.linalg.solve(normal+damping*np.diag(np.maximum(np.diag(normal), 1)), -gradient)
        proposal = v+step
        trial = residual(proposal, train)
        if trial@trial < res@res:
            v = proposal
            damping = max(damping/3, 1e-9)
            if np.linalg.norm(step) < 1e-8:
                break
        else:
            damping = min(damping*10, 1e12)
    def errors(views):
        e = residual(v, views).reshape(len(views), -1, 2)
        rms = np.sqrt(np.mean(np.sum(e*e, axis=2), axis=1))
        return dict(per_view_rms_px=rms.tolist(), median_rms_px=float(np.median(rms)), max_rms_px=float(max(rms)))
    return dict(hmd_from_camera_0=unpack(v[:6]).tolist(), world_from_board=unpack(v[6:]).tolist(),
                training=errors(train), held_out=errors(held), iterations=iteration+1,
                method='Joint pixel least squares; fixed intrinsics and measured HMD poses; training views only')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('session', type=Path)
    ap.add_argument('--intrinsics', type=Path, required=True)
    args = ap.parse_args()
    cv2.setNumThreads(2)
    meta = json.loads((args.session/'metadata.json').read_text())
    clocks = json.loads((args.session/'clock-sync.json').read_text())
    if clocks['error'] or len(clocks['samples']) < 10:
        raise ValueError('Incomplete clock evidence')
    optics = json.loads(args.intrinsics.read_text())
    cal = optics['cameras']['0']
    k, d = np.array(cal['K']), np.array(cal['D']).reshape(4, 1)
    with (args.session/'poses.csv').open() as f:
        rows = list(csv.DictReader(f))
    # Preserve invalid rows too, so gaps cannot masquerade as stationary tracking.
    pt = np.array([(float(r['before_s'])+float(r['after_s']))/2 for r in rows])
    pm = [transform(np.array([float(r[f'm{i}{j}']) for i in range(3) for j in range(3)]).reshape(3, 3),
                    [float(r[n]) for n in ('tx', 'ty', 'tz')]) for r in rows]
    obj = np.zeros((54, 1, 3), np.float64)
    obj[:, 0, :2] = np.mgrid[0:9, 0:6].T.reshape(-1, 2)*(meta['grid_width_mm']/10000)
    samples, rejected = [], []
    for f in meta['frames']:
        if f['camera'] != 0:
            continue
        entry = dict(sample=f['sample'], image=f['image'])
        def reject(reason):
            rejected.append(dict(entry, reason=reason))
        nearby = [c for c in clocks['samples'] if abs(c['headset_monotonic_ns']-f['arrival_monotonic_ns']) < 3e9]
        if not nearby:
            reject('no nearby clock samples'); continue
        best = min(nearby, key=lambda c:c['pc_after_ns']-c['pc_before_ns'])
        rtt = (best['pc_after_ns']-best['pc_before_ns'])/1e9
        if rtt > .02:
            reject('clock round trip exceeds 20 ms'); continue
        t = (f['arrival_monotonic_ns']-best['headset_monotonic_ns']+(best['pc_before_ns']+best['pc_after_ns'])/2)/1e9
        index = int(np.argmin(abs(pt-t)))
        window = np.flatnonzero(abs(pt-t) < .2)
        if abs(pt[index]-t) > .025 or len(window) < 10 or pt[window[0]] > t-.17 or pt[window[-1]] < t+.17:
            reject('insufficient pose coverage'); continue
        if any(rows[i]['valid'] != '1' or rows[i]['connected'] != '1' for i in window) or np.max(np.diff(pt[window])) > .05:
            reject('invalid tracking or pose gap'); continue
        motion_mm = max(np.linalg.norm(pm[i][:3, 3]-pm[index][:3, 3])*1000 for i in window)
        motion_deg = max(np.degrees(angle(pm[i][:3, :3] @ pm[index][:3, :3].T)) for i in window)
        if motion_mm > 5 or motion_deg > .6:
            reject('head moving within 400 ms pose window'); continue
        gray = cv2.imread(str(args.session/f['image']), 0)
        ok, corners = cv2.findChessboardCornersSB(gray, (9, 6), cv2.CALIB_CB_NORMALIZE_IMAGE)
        if not ok:
            reject('checkerboard not found'); continue
        points = corners.astype(np.float64).reshape(-1, 1, 2)
        normalized = cv2.fisheye.undistortPoints(points, k, d)
        ok, r, trans = cv2.solvePnP(obj, normalized, np.eye(3), None)
        if not ok or trans[2, 0] <= 0:
            reject('board pose invalid'); continue
        projected, _ = cv2.fisheye.projectPoints(obj, r, trans, k, d)
        error = float(np.sqrt(np.mean(np.sum((projected-points)**2, axis=2))))
        if error > 1:
            reject('reprojection RMS exceeds 1 px'); continue
        samples.append(dict(entry, hmd=pm[index], board=transform(cv2.Rodrigues(r)[0], trans), points=points,
                            reprojection_px=error, motion_mm=float(motion_mm), motion_degrees=float(motion_deg),
                            clock_rtt_ms=rtt*1000))
    report = dict(status='need_more_stationary_views', accepted=len(samples), rejected=rejected,
                  limitations=['Candidate only; no activation', 'Clock mapping uses camera arrival, not exposure time',
                               'Virtual Desktop pose latency is not calibrated', 'Board must remain fixed in the room'],
                  accepted_views=[{k:v for k,v in s.items() if k not in ('hmd','board','points')} for s in samples])
    train = [s for i,s in enumerate(samples) if i % 4 != 0]
    held = [s for i,s in enumerate(samples) if i % 4 == 0]
    if len(train) >= 8 and len(held) >= 3:
        rotations = [cv2.Rodrigues(s['hmd'][:3,:3] @ train[0]['hmd'][:3,:3].T)[0].ravel() for s in train[1:]]
        sv = np.linalg.svd(rotations, compute_uv=False)
        report['rotation_excitation_singular_values'] = sv.tolist()
        if sv[1] < .15:
            report['status'] = 'need_rotations_about_multiple_axes'
        else:
            r, t = cv2.calibrateHandEye([s['hmd'][:3,:3] for s in train], [s['hmd'][:3,3] for s in train],
                [s['board'][:3,:3] for s in train], [s['board'][:3,3] for s in train], method=cv2.CALIB_HAND_EYE_PARK)
            x = transform(r,t)
            if np.isfinite(x).all() and abs(np.linalg.det(r)-1) < 1e-4:
                center, train_error = scatter([s['hmd']@x@s['board'] for s in train])
                _, held_error = scatter([s['hmd']@x@s['board'] for s in held], center)
                report.update(status='candidate_only', hmd_from_camera_0=x.tolist(),
                              training=train_error, held_out=held_error,
                              held_out_samples=[s['sample'] for s in held])
                report['pixel_refinement'] = refine_pixels(train, held, x, center, obj, k, d)
                refined = report['pixel_refinement']
                hx = np.array(refined['hmd_from_camera_0'])
                wb = np.array(refined['world_from_board'])
                rig = {'0': hx.tolist()}
                cross = {}
                frames = {(f['sample'], f['camera']):f for f in meta['frames']}
                for cam in (1, 2, 3):
                    stereo = optics['stereo'][str(cam)]
                    hc = hx @ transform(np.array(stereo['camera0_from_camera_R']), stereo['camera0_from_camera_t_m'])
                    rig[str(cam)] = hc.tolist()
                    other = optics['cameras'][str(cam)]
                    ck, cd = np.array(other['K']), np.array(other['D']).reshape(4,1)
                    errors = []
                    for s in held:
                        frame = frames.get((s['sample'], cam))
                        zero = frames[(s['sample'], 0)]
                        if not frame or abs(frame['sensor_timestamp']-zero['sensor_timestamp']) > 2e6:
                            continue
                        im = cv2.imread(str(args.session/frame['image']), 0)
                        ok, corners = cv2.findChessboardCornersSB(im, (9,6), cv2.CALIB_CB_NORMALIZE_IMAGE)
                        if not ok:
                            continue
                        cb = np.linalg.inv(hc) @ np.linalg.inv(s['hmd']) @ wb
                        pp, _ = cv2.fisheye.projectPoints(obj, cv2.Rodrigues(cb[:3,:3])[0], cb[:3,3], ck, cd)
                        errors.append(dict(sample=s['sample'], rms_px=float(np.sqrt(np.mean(np.sum((pp-corners)**2, axis=2))))))
                    cross[str(cam)] = errors
                report['hmd_from_cameras'] = rig
                report['held_out_cross_camera_pixels'] = cross
            else:
                report['status'] = 'hand_eye_fit_failed'
    (args.session/'hand-eye.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
