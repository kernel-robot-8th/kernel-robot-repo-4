"""Build measured static scene for inspection. Does not control hardware or train."""
import argparse,json,math,shutil,struct,time,zlib
from pathlib import Path
import xml.etree.ElementTree as ET
import mujoco
import numpy as np
ROOT=Path(__file__).resolve().parents[3]
V=ROOT/'versions/v006'

def build(out,config):
    out.mkdir(parents=True,exist_ok=False)
    src=ROOT/'.local/sim_sources/robotis_mujoco_menagerie/robotis_omx'
    shutil.copytree(src,out/'robotis_omx')
    robot=ET.parse(out/'robotis_omx/omx.xml')
    robot.find('compiler').set('meshdir',str((out/'robotis_omx/assets').resolve()))
    m=config['measured']; a=config['assumed']
    body=robot.find("./worldbody/body[@name='link0']")
    xy=a['robot_origin_xy_on_wood']
    body.set('pos',f'{xy[0]} {xy[1]} {m["wood_height"]}')
    yaw=a['robot_yaw_rad']; body.set('quat',f'{math.cos(yaw/2)} 0 0 {math.sin(yaw/2)}')
    robot.write(out/'robotis_omx/omx.xml')
    scene=ET.parse(out/'robotis_omx/scene.xml'); scene.find('include').set('file','robotis_omx/omx.xml')
    wb=scene.find('worldbody')
    def box(name,center,size,color):
        return ET.SubElement(wb,'geom',name=name,type='box',pos=' '.join(map(str,center)),
           size=' '.join(str(x/2) for x in size),rgba=color)
    x=m['wood_depth_x']/2+m['edge_gap_x']+m['table_depth_x']/2
    y=a['table_center_y']; h=m['table_height']
    box('wood_support',[0,0,m['wood_height']/2],[m['wood_depth_x'],m['wood_width_y'],m['wood_height']],'0.55 0.35 0.17 1')
    box('white_table',[x,y,h/2],[m['table_depth_x'],m['table_width_y'],h],'0.9 0.9 0.88 1')
    for i,(dx,dy) in enumerate(a['shoe_centers_relative_table_xy']):
        length=m['shoe_length_x']; width=m['shoe_width_y']; low=m['shoe_height_min']; high=m['shoe_height_max']
        box(f'shoe{i}_sole',[x+dx,y+dy,h+low/2],[length,width,low],'0.9 0.8 0.85 1')
        box(f'shoe{i}_heel',[x+dx-length/3,y+dy,h+low+(high-low)/2],[length/3,width,high-low],'0.8 0.4 0.55 1')
    dx,dy=a['box_center_relative_table_xy']
    box('closed_box_placeholder',[x+dx,y+dy,h+m['box_height']/2],[m['box_depth_x'],m['box_width_y'],m['box_height']],'0.6 0.4 0.21 1')
    scene.write(out/'scene.xml')
    (out/'layout.json').write_text(json.dumps(config,indent=2))
    return out/'scene.xml'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--pose',choices=['home','arrange','load'],default='arrange')
    p.add_argument('--view',action='store_true');p.add_argument('--png',action='store_true')
    a=p.parse_args(); cfg=json.loads((V/'configs/layout.json').read_text())
    model=mujoco.MjModel.from_xml_path(str(build(a.out,cfg).resolve())); d=mujoco.MjData(model)
    audit=json.loads((ROOT/'versions/v005/evidence/model_audit.json').read_text())
    if a.pose!='home':
        for i,q in enumerate(audit['poses'][0 if a.pose=='arrange' else 1]['candidate_arm_rad'],1):
            j=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_JOINT,f'Joint{i}'); d.qpos[model.jnt_qposadr[j]]=q
    mujoco.mj_forward(model,d)
    # Assert the actual compiled geometry, not only config values.
    def geom(name): return mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_GEOM,name)
    wood=geom('wood_support'); table=geom('white_table')
    gap=float((d.geom_xpos[table,0]-model.geom_size[table,0])-(d.geom_xpos[wood,0]+model.geom_size[wood,0]))
    np.testing.assert_allclose(gap,.025,atol=1e-10)
    np.testing.assert_allclose(d.geom_xpos[table,2]+model.geom_size[table,2],.175,atol=1e-10)
    contacts=[]
    for c in d.contact:
        contacts.append({'geom1':mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,c.geom1),
           'geom2':mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,c.geom2),
           'body1':mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_BODY,model.geom_bodyid[c.geom1]),
           'body2':mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_BODY,model.geom_bodyid[c.geom2]),'distance_m':float(c.dist)})
    result={'pose':a.pose,'edge_gap_m':gap,'support_height_difference_m':.175-.08,
      'contacts_at_candidate_pose':contacts,'limitations':cfg['limitations'],'gripper_model_rad':0,'real_mapping_validated':False}
    (a.out/'inspection.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    cam=mujoco.MjvCamera();cam.lookat[:]=[.12,0,.16];cam.distance=.9;cam.azimuth=135;cam.elevation=-30
    if a.png:
        with mujoco.Renderer(model,height=480,width=640) as r:
            r.update_scene(d,camera=cam);pixels=r.render()
        def chunk(tag,b):return struct.pack('>I',len(b))+tag+b+struct.pack('>I',zlib.crc32(tag+b)&0xffffffff)
        data=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',640,480,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(b'\0'+row.tobytes() for row in pixels)))+chunk(b'IEND',b'')
        (a.out/'preview.png').write_bytes(data)
    if a.view:
        from mujoco import viewer
        with viewer.launch_passive(model,d) as v:
            v.cam.lookat[:]=cam.lookat;v.cam.distance=cam.distance;v.cam.azimuth=cam.azimuth;v.cam.elevation=cam.elevation
            while v.is_running():v.sync();time.sleep(.03)
if __name__=='__main__':main()
