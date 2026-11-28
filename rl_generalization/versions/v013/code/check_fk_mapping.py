"""Compare candidate normalized-to-radian mapping to recorded computed FK (not metrology)."""
from pathlib import Path
import json
import numpy as np
import pyarrow.parquet as pq
import mujoco
ROOT=Path(__file__).resolve().parents[3]
m=mujoco.MjModel.from_xml_path(str(ROOT/'.local/inspection_v011/v011/scene.xml'));d=mujoco.MjData(m);body=m.body('link5').id
results={}
for name in ['shoebox_D','move_in_success']:
    offsets=[];outside=np.zeros(5,dtype=int);samples=0
    for p in sorted((ROOT/'.local/demonstrations'/name/'data').rglob('*.parquet')):
        for r in pq.read_table(p).to_pylist()[::30]:
            q=(np.floor((np.array(r['observation.state'][:5])+100)/200*4095+1e-4)-2048)*2*np.pi/4096
            outside+=((q<m.jnt_range[:5,0])|(q>m.jnt_range[:5,1]));samples+=1
            d.qpos[:5]=q;mujoco.mj_forward(m,d)
            expected=np.array(r['aux.ee_pose'][:3])+[0,0,.08]
            offsets.append(d.xmat[body].reshape(3,3).T@(expected-d.xpos[body]))
    offsets=np.array(offsets);offset=np.median(offsets,axis=0);err=np.linalg.norm(offsets-offset,axis=1)
    results[name]={'samples':samples,'candidate_link5_local_fk_point_m':offset.tolist(),'residual_median_m':float(np.median(err)),'residual_p95_m':float(np.percentile(err,95)),'samples_outside_sim_joint_limits':outside.tolist()}
out=ROOT/'versions/v013/evidence/fk_candidate.json';out.write_text(json.dumps({'mapping':'floor((u+100)/200*4095)-2048 ticks, all signs +1; not hardware calibrated','comparison':'Recorded FK is computed, not measured. Assumes recorded FK origin at robot base and adds wood height0.08m.','results':results},indent=2));print(out.read_text())
