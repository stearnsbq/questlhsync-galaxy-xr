"""Evaluate fixed factory camera geometry against an existing checkerboard capture.

Fits only each board pose; camera parameters remain fixed. Reports angular
residuals scaled by focal length, not literal image reprojection error.
This is a developer investigation tool, not an alignment-profile generator.
"""
import argparse,json
from pathlib import Path
import numpy as np,cv2
from factory_camera_model import factory_rays, validate_camera
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('inventory',type=Path)
ap.add_argument('session',type=Path)
ap.add_argument('--output',type=Path,required=True)
ap.add_argument('--window',choices=('none','inner','outer','mid'),required=True)
args=ap.parse_args()
session=args.session
inv=json.loads(args.inventory.read_text()); cams=inv['cameras']; ext=inv['camera_extrinsics']
order={('tracking','0'):0,('tracking','1'):1,('ctrl-tracking','0'):2,('ctrl-tracking','1'):3}
cams=sorted(cams,key=lambda c:order[c['logical_camera_id'],c['physical_camera_id']])
if len(cams)!=4 or len({(c['logical_camera_id'],c['physical_camera_id']) for c in cams})!=4:
 raise ValueError('Need exactly four unique camera entries, not mixed fallback variants')
for camera in cams:validate_camera(camera)
ext_by_id={e['camera_id']:e for e in ext}
ext=[ext_by_id[c['camera_id']] for c in cams]
if any(e['frame_id']!='IMU_0' for e in ext):raise ValueError('Expected common IMU_0 frame')
det=json.loads((session/'calibration/detections.json').read_text()); meta=json.loads((session/'metadata.json').read_text())
times={(d['sample'],d['camera']):d['sensor_timestamp'] for d in meta['frames']}
obj=np.zeros((54,3));obj[:,:2]=np.mgrid[0:9,0:6].T.reshape(-1,2)*(meta['grid_width_mm']/10000)
def rotation(q):
 w,x,y,z=q
 return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
observations={}
for d in det:
 if d['detected']:
  c=d['camera']; origins,rays=factory_rays(cams[c],d['corners'],args.window!='none',args.window=='outer',args.window=='mid')
  observations.setdefault(d['sample'],{})[c]=(origins,rays)
results={}
for mode in ('R-p','RT-p','RT-inverse-p','R-inverse-p'):
 E=[]
 for e in ext:
  R=rotation(e['quaternion_wxyz']); t=np.array(e['position'])
  if mode.startswith('RT'):R=R.T
  if 'inverse' in mode:t=-R@t
  E.append((R,t))
 errors=[]
 for sample,obs in observations.items():
  if 0 not in obs:continue
  obs={c:v for c,v in obs.items() if abs(times[sample,c]-times[sample,0])<=2000000}
  if len(obs)<2:continue
  rays=obs[0][1]; ok,rv,tv=cv2.solvePnP(obj,rays[:,:2]/rays[:,2:],np.eye(3),None)
  if not ok:continue
  R0,t0=E[0]; Rb=R0@cv2.Rodrigues(rv)[0]; tb=R0@tv.ravel()+t0
  x=np.r_[cv2.Rodrigues(Rb)[0].ravel(),tb]
  def residual(x):
   world=obj@cv2.Rodrigues(x[:3])[0].T+x[3:]
   rr=[]
   for c,(orig,rays) in obs.items():
    R,t=E[c]; pred=(world-t)@R-orig; pred/=np.linalg.norm(pred,axis=1,keepdims=True)
    rr.extend(((pred-rays)*np.mean(cams[c]['focal_length'])).ravel())
   return np.array(rr)
  damping=.01
  for it in range(35):
   r=residual(x); J=np.column_stack([(residual(x+np.eye(6)[j]*1e-5)-r)/1e-5 for j in range(6)])
   delta=np.linalg.solve(J.T@J+damping*np.eye(6),-J.T@r)
   trial=x+delta
   if np.linalg.norm(residual(trial))<np.linalg.norm(r):x=trial;damping=max(damping/3,1e-8)
   else:damping*=10
  r=residual(x).reshape(-1,3); errors.append(float(np.sqrt(np.mean(np.sum(r*r,axis=1)))))
 if not errors:raise ValueError('No synchronized detected camera pairs')
 results[mode]={'views':len(errors),'median_angular_pixel_equivalent':float(np.median(errors)),'max':max(errors)}
 print(mode,results[mode],flush=True)
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps({'status':'offline_investigation_only','window_hypothesis':args.window,'metric':'RMS unit-ray chord error times mean factory focal length','results':results},indent=2))
