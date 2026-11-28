"""Physical replay of recorded commands with UNCALIBRATED gripper zero candidate."""
import argparse,json,time,csv
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
import mujoco
ROOT=Path(__file__).resolve().parents[3]
def arm(u):return ((np.asarray(u)+100)/200*4095-2048)*2*np.pi/4096
def grip(g,zero):return (g-zero)/100*4095*2*np.pi/4096
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--view',action='store_true');p.add_argument('--scene',type=Path,default=ROOT/'.local/finger_proxy_v018/scene.xml');p.add_argument('--shift-z',type=float,default=-.006);p.add_argument('--shift-x',type=float,default=.0349720067);p.add_argument('--shift-y',type=float,default=-.0034275971);p.add_argument('--seconds',type=float,default=12);p.add_argument('--gripper-zero',type=float,default=46.8);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
if not 0<a.seconds<=45:p.error('seconds must be in (0,45]')
rows=pq.read_table(ROOT/'.local/demonstrations/shoebox_D/data/chunk-000/file-000.parquet').to_pylist();rows.sort(key=lambda r:r['frame_index'])
mujoco_scene = a.scene if a.scene.is_absolute() else ROOT / a.scene
m=mujoco.MjModel.from_xml_path(str(mujoco_scene));d=mujoco.MjData(m)
# Experimental translation of recorded TCP trajectory, NOT calibrated registration.
from retarget import plan
rows,plan_report=plan(m,rows,a.seconds,np.array([a.shift_x,a.shift_y,a.shift_z]))
print(json.dumps(plan_report),flush=True)
d.qpos[:5]=arm(rows[0]['observation.state'][:5]);g=grip(rows[0]['observation.state'][5],a.gripper_zero)
if not 0<=g<=m.jnt_range[5,1]:raise SystemExit('Initial candidate gripper angle outside model limits')
d.qpos[5:7]=[g,-g];d.ctrl[:5]=d.qpos[:5];d.ctrl[5]=g;mujoco.mj_forward(m,d)
a.out.mkdir(parents=True,exist_ok=False)
print('SIMULATION ONLY: recorded action replay, candidate gripper mapping; NO attachment/weld and no hardware.',flush=True)
shoes=[m.body(f'shoe{i}').id for i in range(2)];z0=d.xpos[shoes,2].copy();peak=np.zeros(2);contact_steps=np.zeros(2,dtype=int);bilateral_steps=np.zeros(2,dtype=int);streak=np.zeros(2);hold=np.zeros(2);trajectory=[];reason='DURATION_COMPLETE';v=None
if a.view:
 from mujoco import viewer
 v=viewer.launch_passive(m,d);v.cam.lookat[:]=[.15,-.07,.17];v.cam.distance=.7;v.cam.azimuth=135;v.cam.elevation=-30
diagnostics=[];state_history=[];max_finger_penetration=0.;max_finger_pair=None
start=time.monotonic()
for step in range(int(a.seconds/m.opt.timestep)):
 r=rows[min(int(d.time*30),len(rows)-1)];q=arm(r['action'][:5]);g=grip(r['action'][5],a.gripper_zero)
 if np.any(q<m.jnt_range[:5,0]) or np.any(q>m.jnt_range[:5,1]):reason='STOPPED_ARM_COMMAND_OUTSIDE_MODEL_LIMIT';break
 if not 0<=g<=m.jnt_range[5,1]:reason='STOPPED_GRIPPER_CANDIDATE_OUTSIDE_MODEL_LIMIT';break
 d.ctrl[:5]=q;d.ctrl[5]=g;mujoco.mj_step(m,d);mujoco.mj_forward(m,d)
 if not np.isfinite(d.qpos).all() or d.warning.number.sum():reason='STOPPED_NUMERICS';break
 touches=[set(),set()];obstacles=[];normal=np.zeros((2,2));vertical=np.zeros(2);contact_height=[[],[]]
 for ci,c in enumerate(d.contact):
  bodies=[int(m.geom_bodyid[x]) for x in c.geom];names=[m.body(b).name for b in bodies]
  for i,b in enumerate(shoes):
   if b in bodies:
    for name in names:
      if name in ['link6','link7']:
       touches[i].add(name)
       if max(0.,-float(c.dist)) >= max_finger_penetration:
        max_finger_penetration=max(0.,-float(c.dist))
        max_finger_pair={'time_s':float(d.time),'geom_names':[m.geom(int(x)).name for x in c.geom],'dist_m':float(c.dist)}
       force=np.zeros(6);mujoco.mj_contactForce(m,d,ci,force)
       normal[i,0 if name=='link6' else 1]+=max(0.,float(force[0]))
       world_force=c.frame.reshape(3,3).T@force[:3]
       vertical[i]+=float(world_force[2])*(1 if bodies[1]==b else -1)
       contact_height[i].append(float(c.pos[2]-d.xpos[b,2]))
  if c.dist<-.002 and any(n.startswith('link') and n!='link0' for n in names):
   gn=[m.geom(int(x)).name for x in c.geom]
   if any(n in ['white_table','wood_support','fixed_rectangular_chassis','tray_floor'] or n.startswith('rim_') for n in gn):obstacles.append(gn)
 for i in range(2):
  dz=d.xpos[shoes[i],2]-z0[i];peak[i]=max(peak[i],dz);contact_steps[i]+=bool(touches[i]);bilateral_steps[i]+=len(touches[i])==2
  streak[i]=streak[i]+m.opt.timestep if dz>.03 and len(touches[i])==2 else 0;hold[i]=max(hold[i],streak[i])
 b=m.body('link5').id;tcp=d.xpos[b]+d.xmat[b].reshape(3,3)@np.array([.09193,-.0016,0])
 tips=[]
 for bn,local in [('link6',[.06243,-.0091,0]),('link7',[.06243,.0092,0])]:
  bi=m.body(bn).id;tips.append(d.xpos[bi]+d.xmat[bi].reshape(3,3)@np.array(local))
 diagnostic={'time_s':float(d.time),'gripper_target_rad':float(g),'gripper_actual_rad':float(d.qpos[5]),'gripper_torque_Nm':float(d.actuator_force[5]),'tip_landmark_gap_mm':float(np.linalg.norm(tips[0]-tips[1])*1000),'tcp_z_m':float(tcp[2]),'recorded_gripper_current_raw':float(r['aux.gripper_current'])}
 for i in range(2):
  diagnostic.update({f'shoe{i}_z_m':float(d.xpos[shoes[i],2]),f'shoe{i}_finger6_normal_N':float(normal[i,0]),f'shoe{i}_finger7_normal_N':float(normal[i,1]),f'shoe{i}_finger_vertical_N':float(vertical[i]),f'shoe{i}_contact_height_m':float(np.mean(contact_height[i])) if contact_height[i] else None})
 diagnostics.append(diagnostic)
 if step%15==0:
  state_history.append(d.qpos.copy())
  trajectory.append([d.time,*d.qpos[:7],*d.xpos[shoes,2],len(touches[0]),len(touches[1])])
  if v is not None:
   if not v.is_running():reason='VIEWER_CLOSED';break
   v.sync();delay=d.time-(time.monotonic()-start)
   if delay>0:time.sleep(delay)
 if obstacles:reason='STOPPED_SUPPORT_PENETRATION';break
if v is not None:v.close()
np.savez_compressed(a.out/'states.npz',qpos=np.array(state_history),time=np.array([r[0] for r in trajectory]))
with (a.out/'contact_diagnostics.csv').open('w') as f:
 writer=csv.DictWriter(f,fieldnames=diagnostics[0]);writer.writeheader();writer.writerows(diagnostics)
loaded=[x for x in diagnostics if x['shoe1_finger6_normal_N']>.001 and x['shoe1_finger7_normal_N']>.001]
force_report={'max_finger_shoe_penetration_m':max_finger_penetration,'max_finger_pair':max_finger_pair,'loaded_bilateral_steps':len(loaded),'loaded_bilateral_first_s':loaded[0]['time_s'] if loaded else None,'loaded_bilateral_last_s':loaded[-1]['time_s'] if loaded else None,'peak_finger6_normal_N':max(x['shoe1_finger6_normal_N'] for x in diagnostics),'peak_finger7_normal_N':max(x['shoe1_finger7_normal_N'] for x in diagnostics),'peak_gripper_abs_torque_Nm':max(abs(x['gripper_torque_Nm']) for x in diagnostics),'note':'Simulated forces; recorded current shown as context only, not a torque calibration. Tip landmark gap is not minimum mesh distance.'}
(a.out/'force_summary.json').write_text(json.dumps(force_report,indent=2))
print(json.dumps(force_report),flush=True)
summary={'status':reason,'experimental_translation_m':[a.shift_x,a.shift_y,a.shift_z],'plan':plan_report,'simulated_seconds':float(d.time),'mapping_status':'UNCALIBRATED_CANDIDATE','gripper_zero_normalized_assumed':a.gripper_zero,'gripper_gain_rad_per_unit':4095*2*np.pi/4096/100,'scene_objects_repositioned':False,'grasp_constraint_added':False,'peak_shoe_lift_m':peak.tolist(),'finger_contact_steps':contact_steps.tolist(),'bilateral_contact_steps':bilateral_steps.tolist(),'max_bilateral_lift_hold_s':hold.tolist(),'candidate_lift_criterion_met':(hold>=.5).tolist(),'warnings':int(d.warning.number.sum()),'limitation':'Physical command replay is not calibrated sim-to-real. Candidate zero inferred from near-closed low-load recorded state; camera gap fitting not done. Props differ from historical demo. Grasp detection only heuristic.'}
(a.out/'summary.json').write_text(json.dumps(summary,indent=2));np.savetxt(a.out/'trajectory.csv',trajectory,delimiter=',',header='time,q1,q2,q3,q4,q5,grip,mimic,shoe0_z,shoe1_z,shoe0_fingers,shoe1_fingers',comments='');print(json.dumps(summary,indent=2))
