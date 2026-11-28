"""Numerical trajectory translation preserving recorded orientation approximately."""
import copy
import numpy as np
import mujoco
TCP=np.array([.09193,-.0016,0])
def plan(m,rows,seconds,shift):
 d=mujoco.MjData(m);b=m.body('link5').id;low=m.jnt_range[:5,0];high=m.jnt_range[:5,1]
 def pose(q):
  d.qpos[:5]=q;mujoco.mj_forward(m,d);rot=d.xmat[b].reshape(3,3).copy();return d.xpos[b]+rot@TCP,rot
 def to_q(u):return ((np.asarray(u)+100)/200*4095-2048)*2*np.pi/4096
 result=copy.deepcopy(rows);maxerr=0.;maxrot=0.;qprev=None
 for i,row in enumerate(result):
  if row['timestamp']>seconds+1/30:break
  original=to_q(row['action'][:5]);pos,R=pose(original);target=pos+shift
  def residual(q):
   p,r=pose(q);return np.r_[p-target,.025*(r[:,:2]-R[:,:2]).ravel()]
  q=np.clip(original if qprev is None else qprev,low+.001,high-.001)
  for _ in range(35):
   e=residual(q)
   J=np.column_stack([(residual(q+np.eye(5)[j]*1e-5)-e)/1e-5 for j in range(5)])
   dq=-np.linalg.solve(J.T@J+1e-6*np.eye(5),J.T@e);q=np.clip(q+np.clip(dq,-.08,.08),low+.001,high-.001)
   if np.linalg.norm(dq)<1e-6:break
  p,r=pose(q);maxerr=max(maxerr,float(np.linalg.norm(p-target)));angle=np.degrees(np.arccos(np.clip((np.trace(R.T@r)-1)/2,-1,1)));maxrot=max(maxrot,float(angle))
  row['action'][:5]=(((q*4096/(2*np.pi)+2048)/4095)*200-100).tolist();qprev=q
  if i==0:row['observation.state'][:5]=row['action'][:5]
 if maxerr>.005 or maxrot>15:raise RuntimeError(f'Retarget rejected: max position error {maxerr}m, rotation {maxrot}deg')
 return result,{'max_position_error_m':maxerr,'max_orientation_error_deg':maxrot,'shift_is_calibrated':False,'initial_pose_changed_to_retargeted_start':True}
