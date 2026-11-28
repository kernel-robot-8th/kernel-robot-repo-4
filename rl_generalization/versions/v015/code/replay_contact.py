"""Physical replay of recorded commands with UNCALIBRATED gripper zero candidate."""
import argparse,json,time
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
import mujoco
ROOT=Path(__file__).resolve().parents[3]
def arm(u):return ((np.asarray(u)+100)/200*4095-2048)*2*np.pi/4096
def grip(g,zero):return (g-zero)/100*4095*2*np.pi/4096
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--view',action='store_true');p.add_argument('--seconds',type=float,default=12);p.add_argument('--gripper-zero',type=float,default=47.16);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
if not 0<a.seconds<=45:p.error('seconds must be in (0,45]')
rows=pq.read_table(ROOT/'.local/demonstrations/shoebox_D/data/chunk-000/file-000.parquet').to_pylist();rows.sort(key=lambda r:r['frame_index'])
m=mujoco.MjModel.from_xml_path(str(ROOT/'.local/stability_v015/scene/scene.xml'));d=mujoco.MjData(m)
d.qpos[:5]=arm(rows[0]['observation.state'][:5]);g=grip(rows[0]['observation.state'][5],a.gripper_zero)
if not 0<=g<=m.jnt_range[5,1]:raise SystemExit('Initial candidate gripper angle outside model limits')
d.qpos[5:7]=[g,-g];d.ctrl[:5]=d.qpos[:5];d.ctrl[5]=g;mujoco.mj_forward(m,d)
a.out.mkdir(parents=True,exist_ok=False)
print('SIMULATION ONLY: recorded action replay, candidate gripper mapping; NO attachment/weld and no hardware.',flush=True)
shoes=[m.body(f'shoe{i}').id for i in range(2)];z0=d.xpos[shoes,2].copy();peak=np.zeros(2);contact_steps=np.zeros(2,dtype=int);bilateral_steps=np.zeros(2,dtype=int);streak=np.zeros(2);hold=np.zeros(2);trajectory=[];reason='DURATION_COMPLETE';v=None
if a.view:
 from mujoco import viewer
 v=viewer.launch_passive(m,d);v.cam.lookat[:]=[.15,-.07,.17];v.cam.distance=.7;v.cam.azimuth=135;v.cam.elevation=-30
start=time.monotonic()
for step in range(int(a.seconds/m.opt.timestep)):
 r=rows[min(int(d.time*30),len(rows)-1)];q=arm(r['action'][:5]);g=grip(r['action'][5],a.gripper_zero)
 if np.any(q<m.jnt_range[:5,0]) or np.any(q>m.jnt_range[:5,1]):reason='STOPPED_ARM_COMMAND_OUTSIDE_MODEL_LIMIT';break
 if not 0<=g<=m.jnt_range[5,1]:reason='STOPPED_GRIPPER_CANDIDATE_OUTSIDE_MODEL_LIMIT';break
 d.ctrl[:5]=q;d.ctrl[5]=g;mujoco.mj_step(m,d);mujoco.mj_forward(m,d)
 if not np.isfinite(d.qpos).all() or d.warning.number.sum():reason='STOPPED_NUMERICS';break
 touches=[set(),set()];obstacles=[]
 for c in d.contact:
  bodies=[int(m.geom_bodyid[x]) for x in c.geom];names=[m.body(b).name for b in bodies]
  for i,b in enumerate(shoes):
   if b in bodies:
    for name in names:
     if name in ['link6','link7']:touches[i].add(name)
  if c.dist<-.002 and any(n.startswith('link') and n!='link0' for n in names):
   gn=[m.geom(int(x)).name for x in c.geom]
   if any(n in ['white_table','wood_support','fixed_rectangular_chassis','tray_floor'] or n.startswith('rim_') for n in gn):obstacles.append(gn)
 for i in range(2):
  dz=d.xpos[shoes[i],2]-z0[i];peak[i]=max(peak[i],dz);contact_steps[i]+=bool(touches[i]);bilateral_steps[i]+=len(touches[i])==2
  streak[i]=streak[i]+m.opt.timestep if dz>.03 and len(touches[i])==2 else 0;hold[i]=max(hold[i],streak[i])
 if step%15==0:
  trajectory.append([d.time,*d.qpos[:7],*d.xpos[shoes,2],len(touches[0]),len(touches[1])])
  if v is not None:
   if not v.is_running():reason='VIEWER_CLOSED';break
   v.sync();delay=d.time-(time.monotonic()-start)
   if delay>0:time.sleep(delay)
 if obstacles:reason='STOPPED_SUPPORT_PENETRATION';break
if v is not None:v.close()
summary={'status':reason,'simulated_seconds':float(d.time),'mapping_status':'UNCALIBRATED_CANDIDATE','gripper_zero_normalized_assumed':a.gripper_zero,'gripper_gain_rad_per_unit':4095*2*np.pi/4096/100,'scene_objects_repositioned':False,'grasp_constraint_added':False,'peak_shoe_lift_m':peak.tolist(),'finger_contact_steps':contact_steps.tolist(),'bilateral_contact_steps':bilateral_steps.tolist(),'max_bilateral_lift_hold_s':hold.tolist(),'candidate_lift_criterion_met':(hold>=.5).tolist(),'warnings':int(d.warning.number.sum()),'limitation':'Physical command replay is not calibrated sim-to-real. Candidate zero inferred from near-closed low-load recorded state; camera gap fitting not done. Props differ from historical demo. Grasp detection only heuristic.'}
(a.out/'summary.json').write_text(json.dumps(summary,indent=2));np.savetxt(a.out/'trajectory.csv',trajectory,delimiter=',',header='time,q1,q2,q3,q4,q5,grip,mimic,shoe0_z,shoe1_z,shoe0_fingers,shoe1_fingers',comments='');print(json.dumps(summary,indent=2))
