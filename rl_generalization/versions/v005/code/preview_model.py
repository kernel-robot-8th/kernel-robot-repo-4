"""View candidate arm poses only. Gripper angle is a simulator parameter, not hardware mapping."""
import argparse
import json
import math
from pathlib import Path
import time
import mujoco

ROOT = Path(__file__).resolve().parents[3]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--pose', choices=['home','arrange','load'],default='arrange')
p.add_argument('--gripper-rad',type=float,default=0.0)
p.add_argument('--png',type=Path,help='Headless render; set MUJOCO_GL=egl or osmesa before running')
a=p.parse_args()
if not math.isfinite(a.gripper_rad) or not 0 <= a.gripper_rad <= 1.745329:
    raise SystemExit('gripper-rad must be in [0,1.745329]')
model=mujoco.MjModel.from_xml_path(str(ROOT/'.local/sim_sources/robotis_mujoco_menagerie/robotis_omx/scene.xml'))
data=mujoco.MjData(model)
report=json.loads((ROOT/'versions/v005/evidence/model_audit.json').read_text())
if a.pose!='home':
    record=report['poses'][0 if a.pose=='arrange' else 1]
    for i,q in enumerate(record['candidate_arm_rad'],1):
        j=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_JOINT,f'Joint{i}')
        data.qpos[model.jnt_qposadr[j]]=q
for name,q in [('Gripper',a.gripper_rad),('Gripper_mimic',-a.gripper_rad)]:
    j=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_JOINT,name)
    data.qpos[model.jnt_qposadr[j]]=q
mujoco.mj_forward(model,data)
cam=mujoco.MjvCamera()
cam.lookat[:]=[0.13,0,0.16]; cam.distance=.75; cam.azimuth=135; cam.elevation=-20
print('SIMULATION PREVIEW ONLY: arm zero/sign assumptions unverified; gripper NOT calibrated.')
if a.png:
    import struct,zlib
    with mujoco.Renderer(model,height=480,width=640) as renderer:
        renderer.update_scene(data,camera=cam)
        pixels=renderer.render()
    def chunk(tag,body):
        return struct.pack('>I',len(body))+tag+body+struct.pack('>I',zlib.crc32(tag+body)&0xffffffff)
    raw=b''.join(b'\0'+row.tobytes() for row in pixels)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',640,480,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
    with a.png.open('xb') as f:f.write(png)
else:
    import mujoco.viewer
    with mujoco.viewer.launch_passive(model,data) as viewer:
        viewer.cam.lookat[:]=cam.lookat; viewer.cam.distance=cam.distance
        viewer.cam.azimuth=cam.azimuth; viewer.cam.elevation=cam.elevation
        while viewer.is_running():
            viewer.sync(); time.sleep(.03)
