"""Replay shoebox_D and activate a runtime weld after bilateral finger contact.

The weld is a calibration proxy for a compliant gripper: it is disabled at reset,
then enabled only after both collision pads have touched the same sole. Runtime
relative anchors are computed from the measured contact pose, avoiding the
initial-pose impulse that caused the old proxy to wobble. This is not a hardware
or sim-to-real claim; the report separates contact and attachment metrics.
"""
from __future__ import annotations
import argparse, csv, json, sys
from pathlib import Path
import mujoco, numpy as np, pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'versions/v018/code'))
from retarget import plan
ARRANGE=np.array([-12.97,-17.31,-.85,43.59,-.85,59.68],float)
def arm(v): return ((np.asarray(v,float)+100)/200*4095-2048)*2*np.pi/4096
def grip(v,z): return (float(v)-z)/100*4095*2*np.pi/4096

def main():
 p=argparse.ArgumentParser(); p.add_argument('--scene',type=Path,required=True); p.add_argument('--out',type=Path,required=True); p.add_argument('--seconds',type=float,default=20); p.add_argument('--gripper-zero',type=float,default=46.8); p.add_argument('--shift-z',type=float,default=-.004); p.add_argument('--attach-window',type=int,default=30); p.add_argument('--lift-target',type=float,default=.03); a=p.parse_args()
 if a.out.exists(): raise FileExistsError(a.out)
 rows=pq.read_table(ROOT/'.local/demonstrations/shoebox_D/data/chunk-000/file-000.parquet').to_pylist(); rows.sort(key=lambda r:r['frame_index'])
 m=mujoco.MjModel.from_xml_path(str(a.scene)); d=mujoco.MjData(m); probe=mujoco.MjData(m)
 rows,report=plan(m,rows,a.seconds,np.array([.0349720067,-.0034275971,a.shift_z]))
 pose=ARRANGE; d.qpos[:5]=arm(pose[:5]); d.qpos[5:7]=[grip(pose[5],a.gripper_zero),-grip(pose[5],a.gripper_zero)]; d.ctrl[:5]=d.qpos[:5]; d.ctrl[5]=grip(pose[5],a.gripper_zero); mujoco.mj_forward(m,d)
 shoes=['shoe0','shoe1']; fingers={'finger6_proxy','finger7_proxy'}; shoe='shoe1'; sid=m.body(shoe).id; lid=m.body('link6').id; z0=float(d.xpos[sid,2]); wid=0 if m.neq else -1
 if wid<0: raise RuntimeError('scene must contain equality weld named grasp_weld')
 d.eq_active[wid]=0
 seen=set(); attached=False; attach_step=None; armhold=None; max_pen=0.; max_lift=0.; contacts=0; traj=[]; reason='DURATION_COMPLETE'
 def pad_contacts():
  nonlocal max_pen,contacts
  pads=set(); pen=0.
  for i in range(d.ncon):
   c=d.contact[i]; names=(m.geom(int(c.geom[0])).name,m.geom(int(c.geom[1])).name)
   if any('finger6_proxy'==n or 'finger7_proxy'==n for n in names) and any(n.startswith(shoe+'_') for n in names):
    pads.update(n for n in names if n in fingers); pen=max(pen,max(0.,-float(c.dist)))
  max_pen=max(max_pen,pen); return pads
 for step in range(int(a.seconds/m.opt.timestep)):
  row=rows[min(int(d.time*30),len(rows)-1)]; q=arm(row['action'][:5])
  if armhold is not None:
   # hold until planned TCP has risen 8mm, then let the welded object follow the arm
   b=m.body('link5').id; probe.qpos[:5]=q; mujoco.mj_forward(m,probe)
   tcpz=float(probe.xpos[b,2]+probe.xmat[b].reshape(3,3)[2,:]@np.array([.09193,-.0016,0]))
   if tcpz < armhold[1]+.008: q=armhold[0]
   else: armhold=None
  d.ctrl[:5]=q; d.ctrl[5]=float(d.qpos[5]+.008) if attached else grip(row['action'][5],a.gripper_zero)
  mujoco.mj_step(m,d)
  pads=pad_contacts()
  if pads:
   seen.update(pads); contacts += int(bool(pads))
   if step%100==0: print('pads',step,pads,'seen',seen)
  if not attached and len(seen)>=2 and step>30:
   # Use most recent contact point for local anchors.
   cands=[]
   for i in range(d.ncon):
    c=d.contact[i]; names=(m.geom(int(c.geom[0])).name,m.geom(int(c.geom[1])).name)
    if any(n in fingers for n in names) and any(n.startswith(shoe+'_') for n in names): cands.append(c)
   if cands:
    c=cands[-1]; w=c.pos.copy(); R1=d.xmat[sid].reshape(3,3); R2=d.xmat[lid].reshape(3,3)
    m.eq_data[wid,0:3]=R1.T@(w-d.xpos[sid]); m.eq_data[wid,3:6]=R2.T@(w-d.xpos[lid]); qr=np.zeros(4); mujoco.mju_mat2Quat(qr,(R1.T@R2).reshape(-1)); m.eq_data[wid,6:10]=qr; m.eq_data[wid,10]=1.; d.eq_active[wid]=1; attached=True; attach_step=step; armhold=(q,float(tcpz if 'tcpz' in locals() else d.xpos[lid,2])); d.qvel[5:7]=0.; seen=set()
  z=float(d.xpos[sid,2])-z0; max_lift=max(max_lift,z)
  if step%15==0: traj.append([d.time,*d.qpos[:7],float(d.xpos[sid,2]),float(d.xpos[m.body('shoe0').id,2])])
  if not np.isfinite(d.qpos).all() or d.warning.number.sum(): reason='STOPPED_NUMERICS'; break
 a.out.mkdir(parents=True); np.savetxt(a.out/'trajectory.csv',traj,delimiter=',',header='time,q1,q2,q3,q4,q5,grip,mimic,shoe1_z,shoe0_z',comments='')
 summary={'status':reason,'scene':str(a.scene),'plan':report,'attached':attached,'attach_step':attach_step,'simulated_seconds':float(d.time),'bilateral_contact_steps':contacts,'max_finger_penetration_m':max_pen,'peak_shoe_lift_m':max_lift,'criterion_penetration_le_1mm':max_pen<=.001,'criterion_lift_ge_30mm':max_lift>=a.lift_target,'grasp_success':bool(attached and max_pen<=.001 and max_lift>=a.lift_target),'weld_id':wid,'warning':'Runtime weld is a calibrated contact proxy; no sim-to-real claim.'}
 (a.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n'); print(json.dumps(summary,indent=2))
if __name__=='__main__': main()
