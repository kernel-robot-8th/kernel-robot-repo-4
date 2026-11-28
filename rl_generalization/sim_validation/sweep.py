"""Headless model-only tracking/contact sweep. No hardware, network, policy training."""
import argparse,csv,hashlib,json,time
from pathlib import Path
import mujoco
import numpy as np
p=argparse.ArgumentParser(); p.add_argument('--trials',type=int,default=900); p.add_argument('--out',type=Path,required=True)
a=p.parse_args()
if a.trials<1: raise SystemExit('trials must be positive')
root=Path(__file__).resolve().parent
model_path=root/'robotis_omx/scene.xml'
report=json.loads((root/'model_audit.json').read_text())
for name,sha in report['assets_sha256'].items():
 if hashlib.sha256((root/'robotis_omx'/name).read_bytes()).hexdigest()!=sha: raise SystemExit('Model hash mismatch: '+name)
a.out.mkdir(parents=True,exist_ok=False)
model=mujoco.MjModel.from_xml_path(str(model_path))
ids=[mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_JOINT,n) for n in ['Joint1','Joint2','Joint3','Joint4','Joint5','Gripper']]
addresses=model.jnt_qposadr[ids]
mimic=model.jnt_qposadr[mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_JOINT,'Gripper_mimic')]
meta={'domain':'simulation_model_only','not_training':True,'trials':a.trials,'mujoco':mujoco.__version__,
 'model_commit':report['source_commit'],'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
 'duration_sim_s':4,'ramp_sim_s':2,'warning':'Candidate arm zeros unverified; simulator gripper radians not hardware mapping. No shoe object.'}
(a.out/'run.json').write_text(json.dumps(meta,indent=2))
rows=[]; started=time.time()
with (a.out/'trials.csv').open('w',newline='') as f:
 writer=None
 for trial in range(a.trials):
  rng=np.random.default_rng(20000+trial)
  pose=report['poses'][trial%2]['candidate_arm_rad']
  amplitude=[.02,.1,.2][(trial//2)%3]
  grip=[0,.4,.8][(trial//6)%3]
  start=np.array([*pose,grip]); target=start.copy()
  target[:5]+=rng.uniform(-amplitude,amplitude,5)
  target=np.clip(target,model.jnt_range[ids,0]+1e-5,model.jnt_range[ids,1]-1e-5)
  d=mujoco.MjData(model); d.qpos[addresses]=start; d.qpos[mimic]=-grip
  d.ctrl[:]=start; mujoco.mj_forward(model,d)
  contact_steps=0; min_dist=0.; finite=True; max_force=0.; pairs=set()
  for step in range(round(4/model.opt.timestep)):
   t=min(1.,d.time/2); blend=.5-.5*np.cos(np.pi*t)
   d.ctrl[:]=start+(target-start)*blend
   mujoco.mj_step(model,d)
   if not (np.isfinite(d.qpos).all() and np.isfinite(d.qvel).all()): finite=False; break
   max_force=max(max_force,float(np.max(np.abs(d.actuator_force))))
   if d.ncon:
    contact_steps+=1
    for c in d.contact:
     min_dist=min(min_dist,float(c.dist))
     pairs.add(tuple(sorted(int(model.geom_bodyid[g]) for g in (c.geom1,c.geom2))))
  error=float(np.max(np.abs(d.qpos[addresses]-target))) if finite else None
  row=dict(trial=trial,reset_seed=20000+trial,pose=trial%2,amplitude_rad=amplitude,gripper_rad=grip,
    finite=finite,warning_count=int(d.warning.number.sum()),final_max_error_rad=error,
    contact_steps=contact_steps,min_contact_distance_m=min_dist,max_actuator_force=max_force,
    contact_body_pairs=json.dumps(sorted(pairs)))
  if writer is None: writer=csv.DictWriter(f,fieldnames=row);writer.writeheader()
  writer.writerow(row);f.flush();rows.append(row)
  if (trial+1)%10==0 or trial==a.trials-1:
   summary={'completed':len(rows),'requested':a.trials,'elapsed_s':time.time()-started,
    'finite_trials':sum(x['finite'] for x in rows),'trials_with_warnings':sum(x['warning_count']>0 for x in rows),
    'trials_with_contacts':sum(x['contact_steps']>0 for x in rows),
    'median_final_max_error_rad':float(np.median([x['final_max_error_rad'] for x in rows if x['finite']])) if any(x['finite'] for x in rows) else None}
   tmp=a.out/'progress.tmp';tmp.write_text(json.dumps(summary,indent=2));tmp.replace(a.out/'summary.json')
   print(json.dumps(summary),flush=True)
(a.out/'DONE').write_text('Sweep complete; inspect errors and contacts. Not robot/grasp validation.\n')
