"""Compare two grasp-window FK points against current shoe layout. No calibration claims."""
from pathlib import Path
import json
import numpy as np
import pyarrow.parquet as pq
import mujoco
ROOT=Path(__file__).resolve().parents[3]
r=pq.read_table(ROOT/'.local/demonstrations/shoebox_D/data/chunk-000/file-000.parquet').to_pylist()
m=mujoco.MjModel.from_xml_path(str(ROOT/'.local/stability_v015/scene/scene.xml'));d=mujoco.MjData(m);mujoco.mj_forward(m,d)
# Windows selected from previously inspected video contact sheet, not automated success labels.
points=[]
for lo,hi in [(6,9),(23,27)]:
 candidates=[x for x in r if lo<=x['timestamp']<=hi];x=min(candidates,key=lambda x:x['aux.ee_pose'][2]);p=np.array(x['aux.ee_pose'][:3])+[0,0,.08]
 points.append(p);print(x['timestamp'],p,x['observation.state'][5])
shoes=d.xpos[[m.body('shoe0').id,m.body('shoe1').id]].copy();options=[]
for perm in [(0,1),(1,0)]:
 offsets=shoes[list(perm),:2]-np.array(points)[:,:2];translation=offsets.mean(0);residual=offsets-translation
 options.append({'shoe_order':perm,'per_grasp_xy_offset_cm':(offsets*100).tolist(),'common_translation_cm':(translation*100).tolist(),'residual_norm_cm':(np.linalg.norm(residual,axis=1)*100).tolist()})
result={'recorded_points_world_m':np.array(points).tolist(),'current_shoe_origins_world_m':shoes.tolist(),'translation_hypotheses':options,'note':'Lowest recorded computed TCP in video-selected grasp windows, NOT measured shoe centers. Correspondence and grasp offset unknown. Never apply these translations as calibrated transforms.'}
(ROOT/'versions/v016/evidence/alignment.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
