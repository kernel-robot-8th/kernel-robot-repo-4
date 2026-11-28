"""Ray/triangle cross sections of actual visual finger meshes, not force calibration."""
from pathlib import Path
import json
import numpy as np
import mujoco
ROOT=Path(__file__).resolve().parents[3];m=mujoco.MjModel.from_xml_path(str(ROOT/'.local/stability_v015/scene/scene.xml'));d=mujoco.MjData(m)
def sections(body,x):
 b=m.body(body).id;g=next(i for i in range(m.ngeom) if m.geom_bodyid[i]==b and m.geom_contype[i]);mesh=m.geom_dataid[g];a=m.mesh_vertadr[mesh];verts=m.mesh_vert[a:a+m.mesh_vertnum[mesh]]@d.geom_xmat[g].reshape(3,3).T+d.geom_xpos[g];base=m.body('link5').id;verts=(verts-d.xpos[base])@d.xmat[base].reshape(3,3)
 fa=m.mesh_faceadr[mesh];faces=m.mesh_face[fa:fa+m.mesh_facenum[mesh]];hits=[]
 for face in faces:
  tri=verts[face];mat=np.column_stack([(tri[1]-tri[0])[[0,2]],(tri[2]-tri[0])[[0,2]]])
  if abs(np.linalg.det(mat))<1e-12:continue
  u,v=np.linalg.solve(mat,np.array([x,0])-tri[0,[0,2]])
  if u>=-1e-7 and v>=-1e-7 and u+v<=1+1e-7:hits.append(float(tri[0,1]+u*(tri[1,1]-tri[0,1])+v*(tri[2,1]-tri[0,1])))
 return hits
results=[]
for value in [46.8,47.16,48.94,51.14,56.21,59.68]:
 q=(value-46.8)*4095/4096*2*np.pi/100;d.qpos[5:7]=[q,-q];mujoco.mj_forward(m,d);record={'normalized':value,'candidate_rad':q,'cross_sections':[]}
 for x in [.055,.065,.075,.085,.09193]:
  a,b=sections('link6',x),sections('link7',x);record['cross_sections'].append({'link5_x_m':x,'inner_gap_mm':(min(a)-max(b))*1000 if a and b else None})
 results.append(record)
(ROOT/'versions/v016/evidence/gripper_gap.json').write_text(json.dumps({'candidate_zero':46.8,'note':'At local z0. Null means ray misses one finger. Mesh surfaces, not MuJoCo convex-hull contact surface; neither validates real linkage.', 'samples':results},indent=2));print(json.dumps(results,indent=2))
