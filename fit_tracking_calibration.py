"""Fit and evaluate per-camera KB4 intrinsics from the tracking checkerboard session.

Produces a candidate report, never an enabled QuestLHSync profile. Camera-to-HMD
extrinsics, exposure selection, and lighthouse timing are separate measurements.
"""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
import cv2
import numpy as np


def pose_error(obj, pts, k, d):
    norm = cv2.fisheye.undistortPoints(pts, k, d)
    ok, r, t = cv2.solvePnP(obj, norm, np.eye(3), None, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok or t[2, 0] <= 0:
        return float('inf')
    projected, _ = cv2.fisheye.projectPoints(obj, r, t, k, d)
    return float(np.sqrt(np.mean(np.sum((projected-pts)**2, axis=2))))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('session', type=Path)
    args = ap.parse_args()
    cv2.setNumThreads(2)
    meta = json.loads((args.session/'metadata.json').read_text())
    out = args.session/'calibration'
    out.mkdir(exist_ok=True)
    obj = np.zeros((54, 1, 3), np.float64)
    obj[:, 0, :2] = np.mgrid[0:9, 0:6].T.reshape(-1, 2)*(meta['grid_width_mm']/10000)
    records = {c: [] for c in range(4)}
    thumbs = {c: [] for c in range(4)}
    detections = []
    for frame in meta['frames']:
        cam, sample = frame['camera'], frame['sample']
        gray = cv2.imread(str(args.session/frame['image']), cv2.IMREAD_GRAYSCALE)
        if gray is None or gray.shape != (640, 640):
            raise ValueError('Invalid image: '+frame['image'])
        ok, corners = cv2.findChessboardCorners(gray, (9, 6), cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
        if ok:
            corners = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1),
                                      (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, .001))
        else:
            ok, corners = cv2.findChessboardCornersSB(gray, (9, 6), cv2.CALIB_CB_NORMALIZE_IMAGE)
        annotated = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        entry = dict(sample=sample, camera=cam, image=frame['image'], detected=bool(ok))
        if ok:
            points = corners.astype(np.float64).reshape(-1, 1, 2)
            cv2.drawChessboardCorners(annotated, (9, 6), corners, True)
            records[cam].append((frame, points))
            entry['corners'] = points[:, 0, :].tolist()
        detections.append(entry)
        thumb = cv2.resize(annotated, (192, 192))
        cv2.putText(thumb, f'{sample}: '+('OK' if ok else 'no board'), (5, 16), cv2.FONT_HERSHEY_SIMPLEX, .4, (0, 255, 0) if ok else (0, 0, 255), 1)
        thumbs[cam].append(thumb)
        if cam == 3:
            print('Detected through sample', sample, {c: len(v) for c, v in records.items()}, flush=True)
    (out/'detections.json').write_text(json.dumps(detections)+'\n')
    report = {'status': 'candidate_only', 'grid_width_mm': meta['grid_width_mm'], 'cameras': {},
              'limitations': ['No camera-to-SteamVR-HMD transform', 'No verified lighthouse identity',
                              'Optical coverage must be reviewed; no automatic activation']}
    for cam, views in records.items():
        tiles = thumbs[cam]
        if tiles:
            sheet = np.zeros((((len(tiles)+5)//6)*192, 6*192, 3), np.uint8)
            for i, tile in enumerate(tiles):
                sheet[(i//6)*192:(i//6+1)*192,(i%6)*192:(i%6+1)*192] = tile
            cv2.imwrite(str(out/f'camera-{cam}-detections.jpg'), sheet)
        item = report['cameras'][cam] = {'detected_views': len(views)}
        if len(views) < 15:
            item['status'] = 'need_more_board_views'
            continue
        # Split by capture ID, consistently across cameras; stereo validation
        # must not reuse views that trained either camera's intrinsics.
        train = [v for v in views if v[0]['sample'] % 5 != 0]
        held = [v for v in views if v[0]['sample'] % 5 == 0]
        k = np.array([[240., 0, 320.], [0, 240., 320.], [0, 0, 1.]])
        d = np.zeros((4, 1))
        flags = cv2.fisheye.CALIB_USE_INTRINSIC_GUESS | cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC | cv2.fisheye.CALIB_FIX_SKEW
        try:
            rms, k, d, _, _ = cv2.fisheye.calibrate([obj]*len(train), [v[1] for v in train], (640, 640), k, d,
                flags=flags, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 150, 1e-9))
            errors = [pose_error(obj, v[1], k, d) for v in held]
            finite = np.isfinite(k).all() and np.isfinite(d).all() and np.isfinite(errors).all()
            if not finite or not (50 < k[0,0] < 1000 and 50 < k[1,1] < 1000):
                raise ValueError('Non-finite or implausible calibration')
            points = np.concatenate([v[1] for v in train]).reshape(-1, 2).astype(np.float32)
            item.update(status='candidate', model='opencv_fisheye_KB4', K=k.tolist(), D=d.reshape(-1).tolist(),
                        training_rms_px=float(rms), heldout_rms_px=errors,
                        heldout_median_rms_px=float(np.median(errors)), heldout_max_rms_px=max(errors),
                        observed_hull_fraction=float(cv2.contourArea(cv2.convexHull(points))/(640*640)),
                        training_samples=[v[0]['sample'] for v in train], heldout_samples=[v[0]['sample'] for v in held])
        except (cv2.error, ValueError) as exc:
            item.update(status='fit_failed', error=str(exc))
    report['stereo'] = {}
    base = {v[0]['sample']: v for v in records[0]}
    for cam in range(1, 4):
        item = report['stereo'][cam] = {}
        if any(report['cameras'][c].get('status') != 'candidate' for c in (0, cam)):
            item['status'] = 'missing_intrinsics'
            continue
        other = {v[0]['sample']: v for v in records[cam]}
        common = sorted(set(base) & set(other))
        valid = [s for s in common if abs(base[s][0]['sensor_timestamp']-other[s][0]['sensor_timestamp']) <= 2000000]
        train = [s for s in valid if s % 5 != 0]
        held = [s for s in valid if s % 5 == 0]
        item.update(training_samples=train, heldout_samples=held,
                    rejected_timestamp_samples=sorted(set(common)-set(valid)))
        if len(train) < 12 or len(held) < 3:
            item['status'] = 'need_more_synchronized_views'
            continue
        k0 = np.array(report['cameras'][0]['K'])
        d0 = np.array(report['cameras'][0]['D'])
        k1 = np.array(report['cameras'][cam]['K'])
        d1 = np.array(report['cameras'][cam]['D'])
        try:
            fitted = cv2.fisheye.stereoCalibrate([obj]*len(train), [base[s][1] for s in train],
                [other[s][1] for s in train], k0, d0, k1, d1, (640, 640),
                flags=cv2.fisheye.CALIB_FIX_INTRINSIC,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 150, 1e-9))
            rms, _, _, _, _, rotation, translation = fitted[:7]
            errors = []
            for s in held:
                normalized = cv2.fisheye.undistortPoints(base[s][1], k0, d0)
                ok, rv, tv = cv2.solvePnP(obj, normalized, np.eye(3), None)
                if not ok:
                    raise ValueError('Held-out board pose failed')
                board_r, _ = cv2.Rodrigues(rv)
                target_r, _ = cv2.Rodrigues(rotation @ board_r)
                projected, _ = cv2.fisheye.projectPoints(obj, target_r, rotation @ tv + translation, k1, d1)
                errors.append(float(np.sqrt(np.mean(np.sum((projected-other[s][1])**2, axis=2)))))
            if not np.isfinite(errors).all() or not np.isfinite(rotation).all() or not np.isfinite(translation).all():
                raise ValueError('Non-finite stereo result')
            # OpenCV estimates camera_i <- camera_0. Store both directions
            # explicitly; neither is a camera-to-SteamVR-headset transform.
            item.update(status='candidate', training_rms_px=float(rms),
                        camera_from_camera0_R=rotation.tolist(), camera_from_camera0_t_m=translation.reshape(-1).tolist(),
                        camera0_from_camera_R=rotation.T.tolist(), camera0_from_camera_t_m=(-rotation.T @ translation).reshape(-1).tolist(),
                        baseline_mm=float(np.linalg.norm(translation)*1000),
                        heldout_cross_camera_rms_px=errors,
                        heldout_median_rms_px=float(np.median(errors)), heldout_max_rms_px=max(errors))
        except (cv2.error, ValueError) as exc:
            item.update(status='fit_failed', error=str(exc))
    (out/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
