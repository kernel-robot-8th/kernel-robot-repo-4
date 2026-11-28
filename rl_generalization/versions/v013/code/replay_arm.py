"""Kinematic demonstration replay ONLY: gripper frozen, no actuation/contact simulation."""
import argparse,time
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
import mujoco
from mujoco import viewer
ROOT=Path(__file__).resolve().parents[3]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',choices=['shoebox_D','move_in_success'],default='shoebox_D');p.add_argument('--episode',type=int,default=0);p.add_argument('--speed',type=float,default=1);a=p.parse_args()
if a.speed<=0:p.error('--speed must be positive')
rows=[]
for f in sorted((ROOT/'.local/demonstrations'/a.dataset/'data').rglob('*.parquet')):
    rows.extend(pq.read_table(f,filters=[('episode_index','=',a.episode)]).to_pylist())
rows.sort(key=lambda r:r['frame_index'])
if not rows:raise SystemExit('Episode not found')
m=mujoco.MjModel.from_xml_path(str(ROOT/'.local/inspection_v011/v011/scene.xml'));d=mujoco.MjData(m)
print('KINEMATIC ARM REPLAY: state from demonstration; NO dynamics, NO gripper mapping, NO moving props. Simulator limits not clamped; this visualizes mismatches, NOT executable commands.',flush=True)
with viewer.launch_passive(m,d) as v:
    v.cam.lookat[:]=[.12,-.06,.17];v.cam.distance=.8;v.cam.azimuth=135;v.cam.elevation=-30
    t0=time.monotonic();t_first=rows[0]['timestamp']
    for r in rows:
        if not v.is_running():break
        wait=(r['timestamp']-t_first)/a.speed-(time.monotonic()-t0)
        if wait>0:time.sleep(wait)
        u=np.array(r['observation.state'][:5]);d.qpos[:5]=(np.floor((u+100)/200*4095+1e-4)-2048)*2*np.pi/4096
        # No mj_step: no fabricated grasp or force inference. Gripper stays at model zero.
        mujoco.mj_forward(m,d);v.sync()
print('Replay ended. This is not a task success evaluation.')
