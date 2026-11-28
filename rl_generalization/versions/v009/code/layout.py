"""Build measured static scene for inspection. Does not control hardware or train."""
import argparse,json,math,shutil,struct,time,zlib
from pathlib import Path
import xml.etree.ElementTree as ET
import mujoco
import numpy as np
from shoe_mesh import shoe_mesh
ROOT=Path(__file__).resolve().parents[3]
V=ROOT/'versions/v009'

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
    vertices,faces=shoe_mesh(m['shoe_length_x'],m['shoe_width_y'],m['shoe_height_min'],m['shoe_height_max'],a['shoe_rear_height'])
    ET.SubElement(scene.find('asset'),'mesh',name='curved_shoe',
        vertex=' '.join(map(str,vertices.ravel())),face=' '.join(map(str,faces.ravel())))
    for i,(dx,dy) in enumerate(a['shoe_centers_relative_table_xy']):
        ET.SubElement(wb,'geom',name=f'shoe{i}_sole',type='mesh',mesh='curved_shoe',
            pos=f'{x+dx} {y+dy} {h}',rgba='0.85 0.48 0.62 1')
    # Decoration geoms have no contact response and zero mass. Full envelope remains unchanged.
    for mesh_name,thickness in [('white_sole',.003),('sole_stripe',.0005)]:
        sv,sf=shoe_mesh(m['shoe_length_x'],m['shoe_width_y'],thickness,thickness,thickness)
        ET.SubElement(scene.find('asset'),'mesh',name=mesh_name,
            vertex=' '.join(map(str,sv.ravel())),face=' '.join(map(str,sf.ravel())))
    def visual(name,kind,**kwargs):
        return ET.SubElement(wb,'geom',name=name,type=kind,contype='0',conaffinity='0',mass='0',**kwargs)
    length=m['shoe_length_x']; width=m['shoe_width_y']
    def surface(sx,sy):
        t=min(1.,abs(sx)/(length/2)); blend=t*t*(3-2*t)
        end=m['shoe_height_min'] if sx>=0 else a['shoe_rear_height']
        return (m['shoe_height_max']+(end-m['shoe_height_max'])*blend)*(1-.20*(sy/(width/2))**2)
    for i,(dx,dy) in enumerate(a['shoe_centers_relative_table_xy']):
        cx=x+dx;cy=y+dy
        visual(f'shoe{i}_rubber','mesh',mesh='white_sole',pos=f'{cx} {cy} {h+.00003}',rgba='.96 .96 .94 1')
        # Narrow dark foxing stripe on side: capsule paths along the elliptical perimeter.
        for j in range(64):
            pts=[]
            for theta in [2*math.pi*j/64,2*math.pi*(j+1)/64]:
                pts += [cx+length/2*math.cos(theta),cy+width/2*math.sin(theta),h+.0017]
            visual(f'shoe{i}_stripe{j}','capsule',fromto=' '.join(map(str,pts)),size='.00025',rgba='.08 .08 .09 1')
        for j,sx in enumerate([.001,.004,.007,.010]):
            for cross in [-1,1]:
                p1=[cx+sx,cy+cross*.003,h+surface(sx,cross*.003)+.00035]
                p2=[cx+sx+.002,cy-cross*.003,h+surface(sx+.002,-cross*.003)+.00035]
                visual(f'shoe{i}_lace{j}_{cross}','capsule',fromto=' '.join(map(str,p1+p2)),size='.0003',rgba='.98 .98 .97 1')
        # White rubber toe patch; decorative, not a separately calibrated collision body.
        visual(f'shoe{i}_toe','ellipsoid',pos=f'{cx+.014} {cy} {h+.0065}',size='.0035 .0058 .0015',rgba='.95 .95 .93 1')
    dx,dy=a['box_center_relative_table_xy']
    rw=m['rim_outer_width_y']; rd=m['rim_outer_depth_x']; rh=m['rim_height']; t=a['rim_wall_thickness']
    for sign in [-1,1]:
        box(f'rim_x_{sign}',[x+dx+sign*(rd-t)/2,y+dy,h+rh/2],[t,rw,rh],'0.95 0.95 0.95 1')
        box(f'rim_y_{sign}',[x+dx,y+dy+sign*(rw-t)/2,h+rh/2],[rd-2*t,t,rh],'0.95 0.95 0.95 1')
    box('closed_box_placeholder',[x+dx,y+dy,h+m['box_height']/2],[m['box_depth_x'],m['box_width_y'],m['box_height']],'0.6 0.4 0.21 1')
    # Cardboard lid seam: visual-only strips, no extra collision edges.
    for sign in [-1,1]:
        visual(f'box_seam_y{sign}','box',pos=f'{x+dx} {y+dy+sign*(m["box_width_y"]/2+.00002)} {h+.037}',
            size=f'{m["box_depth_x"]/2} .00005 .0003',rgba='.30 .20 .12 1')
        visual(f'box_seam_x{sign}','box',pos=f'{x+dx+sign*(m["box_depth_x"]/2+.00002)} {y+dy} {h+.037}',
            size=f'.00005 {m["box_width_y"]/2} .0003',rgba='.30 .20 .12 1')
    scene.write(out/'scene.xml')
    (out/'layout.json').write_text(json.dumps(config,indent=2))
    return out/'scene.xml'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--pose',choices=['home','arrange','load'],default='arrange')
    p.add_argument('--view',action='store_true');p.add_argument('--png',action='store_true');p.add_argument('--shoe-closeup',action='store_true')
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
    a_cfg=cfg['assumed']
    # Both shoes must remain to the robot's right of the box, within tabletop.
    for dx,dy in a_cfg['shoe_centers_relative_table_xy']:
        assert abs(dx)+cfg['measured']['shoe_length_x']/2 <= cfg['measured']['table_depth_x']/2
        assert abs(dy)+cfg['measured']['shoe_width_y']/2 <= cfg['measured']['table_width_y']/2
    for n in ['closed_box_placeholder']:
        g=geom(n)
        assert np.all(np.abs(d.geom_xpos[g,:2]-d.geom_xpos[table,:2])+model.geom_size[g,:2] <= model.geom_size[table,:2]+1e-9)
    assert all(d.geom_xpos[geom(n),1] < d.geom_xpos[geom('closed_box_placeholder'),1] for n in ['shoe0_sole','shoe1_sole'])
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
    if a.shoe_closeup:
        cam.lookat[:]=[.1725,-.10,.187];cam.distance=.12;cam.azimuth=115;cam.elevation=-25
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
