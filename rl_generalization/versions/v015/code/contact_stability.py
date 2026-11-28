"""Compare untouched shoes settling with optional flat sole-table contact proxy."""
from pathlib import Path
import argparse,json,shutil,xml.etree.ElementTree as E
import numpy as np
import mujoco
ROOT=Path(__file__).resolve().parents[3]
def prepare(source,out):
 shutil.copytree(source,out)
 p=out/'robotis_omx/omx.xml';t=E.parse(p);t.find('compiler').set('meshdir',str((p.parent/'assets').resolve()))
 # All arm collision geoms keep collision with both table and upper shoe.
 t.find(".//default[@class='collision']/geom").set('contype','3');t.find(".//default[@class='collision']/geom").set('conaffinity','3');t.write(p)
 p=out/'scene.xml';t=E.parse(p)
 for g in t.findall('.//geom'):
  if g.get('contype')=='0':continue
  if g.get('name')=='white_table':g.set('contype','1');g.set('conaffinity','1')
  else:g.set('contype','3');g.set('conaffinity','3')
 for i in range(2):
  b=t.find(f".//body[@name='shoe{i}']");g=b.find(f"geom[@name='shoe{i}_sole']")
  g.set('contype','2');g.set('conaffinity','2');g.set('mass','.009')
  E.SubElement(b,'geom',name=f'shoe{i}_flat_contact_sole',type='box',pos='0 0 .0015',size='.015 .008 .0015',mass='.001',rgba='.9 .9 .9 0',contype='1',conaffinity='1',friction='.8 .005 .0001',solref='.005 1',solimp='.99 .99 .001',priority='1')
 t.write(p)
 return p

def test(scene):
 m=mujoco.MjModel.from_xml_path(str(scene));d=mujoco.MjData(m)
 d.qpos[:5]=[-.40957,-.54456,-.02761,1.36831,-.02761];d.ctrl[:5]=d.qpos[:5];mujoco.mj_forward(m,d)
 b=[m.body(f'shoe{i}').id for i in range(2)];initial=d.xpos[b].copy();points=[];speeds=[];fingers=0;penetration=0
 for step in range(int(4/m.opt.timestep)):
  mujoco.mj_step(m,d);mujoco.mj_forward(m,d)
  for c in d.contact:
   names=[m.body(int(m.geom_bodyid[g])).name for g in c.geom]
   if any(n.startswith('shoe') for n in names):
    fingers+=any(n in ['link6','link7'] for n in names)
    penetration=max(penetration,-float(c.dist))
  if d.time>1:points.append(d.xpos[b].copy())
 points=np.array(points)
 return {'late_xyz_peak_to_peak_mm':(np.ptp(points,axis=0)*1000).tolist(),'final_displacement_mm':((d.xpos[b]-initial)*1000).tolist(),'max_penetration_mm':penetration*1000,'finger_contacts':fingers,'warnings':int(d.warning.number.sum())}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
 src=ROOT/'.local/inspection_v011/v011';dest=a.out/'scene';prepare(src,dest)
 result={'before':test(src/'scene.xml'),'after':test(dest/'scene.xml'),'note':'Free rigid shoes, no weld; flat sole contact proxy, not measured compliance.'}
 (a.out/'summary.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
