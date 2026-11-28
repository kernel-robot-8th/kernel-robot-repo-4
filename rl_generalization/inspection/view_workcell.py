"""Rebuild v011 and inspect frozen pose; never connects to hardware."""
import argparse, importlib.util, json, sys, time, struct, zlib
from pathlib import Path
import numpy as np
import mujoco
ROOT=Path(__file__).resolve().parents[1]
def module(name,version,file):
    folder=ROOT/'versions'/version/'code';sys.path.insert(0,str(folder))
    spec=importlib.util.spec_from_file_location(name,folder/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
p=argparse.ArgumentParser();p.add_argument('--view',action='store_true');args=p.parse_args()
base=ROOT/'.local/inspection_v011';base.mkdir(parents=True,exist_ok=True)
scene=base/'v011/scene.xml'
if not scene.exists():
    module('layout','v009','layout.py').build(base/'v009',json.loads((ROOT/'versions/v009/configs/layout.json').read_text()))
    module('prepare','v010','prepare.py').prepare(base/'v009',base/'v010',json.loads((ROOT/'versions/v010/configs/dynamics.json').read_text()))
    module('mobile','v011','replace_mobile.py').build(base/'v010',base/'v011',json.loads((ROOT/'versions/v011/configs/mobile_layout.json').read_text()))
m=mujoco.MjModel.from_xml_path(str(scene));d=mujoco.MjData(m)
d.qpos[:5]=[-.4095728703654662,-.5445631796994026,-.02761165418194154,1.368310862793992,-.02761165418194154];mujoco.mj_forward(m,d)
def bounds(names):
    lows=[];highs=[]
    for n in names:
        g=m.geom(n);i=g.id
        if g.type[0]==mujoco.mjtGeom.mjGEOM_MESH:
            mid=int(g.dataid[0]);a=m.mesh_vertadr[mid];num=m.mesh_vertnum[mid];v=m.mesh_vert[a:a+num]@d.geom_xmat[i].reshape(3,3).T+d.geom_xpos[i];lows.append(v.min(0));highs.append(v.max(0))
        else:
            half=g.size.copy()
            if g.type[0]==mujoco.mjtGeom.mjGEOM_CYLINDER:half=np.array([half[0],half[0],half[1]])
            extent=np.abs(d.geom_xmat[i].reshape(3,3))@half;lows.append(d.geom_xpos[i]-extent);highs.append(d.geom_xpos[i]+extent)
    return np.min(lows,axis=0),np.max(highs,axis=0)
names=[m.geom(i).name for i in range(m.ngeom)]
groups={'wood':['wood_support'],'table':['white_table'],'box':[n for n in names if n.startswith('box_wall') or n=='box_bottom'],'retaining_rim':[n for n in names if n.startswith('rim_')],'shoe':['shoe0_sole'],'tray':['tray_floor']+[n for n in names if n.startswith('tray_rim_')]}
report={}
for label,ns in groups.items():
    lo,hi=bounds(ns);report[label]={'size_xyz_cm':((hi-lo)*100).tolist(),'min_xyz_cm':(lo*100).tolist(),'max_xyz_cm':(hi*100).tolist()}
report['support_gap_cm']=(bounds(['white_table'])[0][0]-bounds(['wood_support'])[1][0])*100
report['tray_floor_height_cm']=float((d.geom_xpos[m.geom('tray_floor').id,2]+m.geom('tray_floor').size[1])*100)
expected={'wood':[20,27,8],'table':[17.2,28,17.5],'box':[6,6,5.5],'retaining_rim':[7,7,1],'shoe':[3.5,2,2.5]}
for key,value in expected.items():np.testing.assert_allclose(report[key]['size_xyz_cm'],value,atol=.001)
np.testing.assert_allclose([report['support_gap_cm'],report['tray_floor_height_cm']],[2.5,14],atol=.001)
out=ROOT/'inspection/output';out.mkdir(exist_ok=True)
(out/'dimensions.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
cam=mujoco.MjvCamera();cam.lookat[:]=[.12,-.07,.13];cam.distance=.85
if args.view:
    import mujoco.viewer
    with mujoco.viewer.launch_passive(m,d) as viewer:
        viewer.cam.lookat[:]=cam.lookat;viewer.cam.distance=cam.distance;viewer.cam.azimuth=135;viewer.cam.elevation=-35
        while viewer.is_running():viewer.sync();time.sleep(.03)
else:
    def chunk(t,b):return struct.pack('>I',len(b))+t+b+struct.pack('>I',zlib.crc32(t+b)&0xffffffff)
    m.vis.global_.offwidth=960;m.vis.global_.offheight=720
    with mujoco.Renderer(m,height=720,width=960) as r:
        for name,az,el in [('overview',135,-35),('top',90,-89.9),('side',0,-5)]:
            cam.azimuth=az;cam.elevation=el;r.update_scene(d,camera=cam)
            r.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW]=False
            r.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION]=False
            pixels=r.render()
            png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',960,720,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(b'\0'+row.tobytes() for row in pixels)))+chunk(b'IEND',b'')
            (out/f'{name}.png').write_bytes(png)
