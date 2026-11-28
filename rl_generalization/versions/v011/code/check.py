"""Headless settling tests only: no reaching/grasping/opening/loading controller."""
import argparse,json,time,csv
from pathlib import Path
import xml.etree.ElementTree as E
import mujoco
import numpy as np
p=argparse.ArgumentParser();p.add_argument('--scene',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--trials',type=int,default=90);a=p.parse_args()
if a.trials<1:raise SystemExit('trials must be positive')
# Relocate generated XML assets on the destination machine.
robot=a.scene.parent/'robotis_omx/omx.xml';tree=E.parse(robot);tree.find('compiler').set('meshdir',str((robot.parent/'assets').resolve()));tree.write(robot)
m=mujoco.MjModel.from_xml_path(str(a.scene.resolve()));a.out.mkdir(parents=True,exist_ok=False)
rows=[];started=time.time()
free=['shoe0_free','shoe1_free','box_free','lid_free']
addresses=[m.jnt_qposadr[mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_JOINT,n)] for n in free]
with (a.out/'trials.csv').open('w',newline='') as f:
 writer=None
 for i in range(a.trials):
  d=mujoco.MjData(m)
  q=[-.4095728703654662,-.5445631796994026,-.02761165418194154,1.368310862793992,-.02761165418194154]
  d.qpos[:5]=q;d.ctrl[:5]=q
  friction=[.3,.6,1.0][i%3];m.geom_friction[:,0]=friction
  # Small vertical offsets only. Nominal layout, not task or position generalization trials.
  lift=[0,.002,.005][(i//3)%3]
  for j in addresses:d.qpos[j+2]+=lift
  rng=np.random.default_rng(31000+i)
  for j in addresses[:2]:d.qpos[j:j+2]+=rng.uniform(-.001,.001,2)
  peak_speed=0.;finite=True
  for step in range(round(2/m.opt.timestep)):
   mujoco.mj_step(m,d)
   if not np.isfinite(d.qpos).all() or not np.isfinite(d.qvel).all():finite=False;break
   peak_speed=max(peak_speed,float(np.max(np.abs(d.qvel))))
  row={'trial':i,'seed':31000+i,'friction_assumed':friction,'drop_offset_m':lift,'finite':finite,'warnings':int(d.warning.number.sum()),'max_generalized_speed_mixed_units':peak_speed,'final_generalized_speed_mixed_units':float(np.max(np.abs(d.qvel)))}
  for name,j in zip(free,addresses):
   for axis,k in zip('xyz',range(3)):row[f'{name}_{axis}']=float(d.qpos[j+k])
  if writer is None:writer=csv.DictWriter(f,fieldnames=row);writer.writeheader()
  writer.writerow(row);f.flush();rows.append(row)
  result={'completed':len(rows),'requested':a.trials,'elapsed_s':time.time()-started,'finite_trials':sum(x['finite'] for x in rows),'trials_with_warnings':sum(x['warnings']>0 for x in rows),'task_success_rate':None,'task_stages':'NOT_RUN: reach/grasp/open/insert/close/load','warning':'Rigid proxies; assumed masses/friction; tray diameter from image, floor height user-reported; rim/chassis/parking provisional.'}
  (a.out/'summary.json').write_text(json.dumps(result,indent=2))
  if (i+1)%10==0 or i==a.trials-1:print(json.dumps(result),flush=True)
(a.out/'DONE').write_text('Settling checks finished. Task controller NOT implemented.\n')
