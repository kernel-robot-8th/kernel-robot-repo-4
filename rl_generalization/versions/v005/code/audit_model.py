"""Offline OMX MJCF audit. No robot imports, device access, or hardware commands."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tarfile
import xml.etree.ElementTree as ET
import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
ARM = ['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll']
ORIGINS = [(-.01125,0,.034),(0,0,.0635),(.0415,0,.11315),(.162,0,0),(.0287,0,0)]
AXES = [(0,0,1),(0,1,0),(0,1,0),(0,1,0),(1,0,0)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=ROOT/'.local/sim_sources/robotis_mujoco_menagerie')
    p.add_argument('--inputs',type=Path,default=ROOT/'.local/operating_source/omx_control_inputs.tar.gz')
    p.add_argument('--out',type=Path,required=True)
    a = p.parse_args()
    source = a.source.resolve(); model_dir = source/'robotis_omx'
    xml = ET.parse(model_dir/'omx.xml').getroot()
    for i,(origin,axis) in enumerate(zip(ORIGINS,AXES),1):
        body = xml.find(f".//body[@name='link{i}']")
        default = xml.find(f"./default/default/default[@class='Joint{i}']/joint")
        np.testing.assert_allclose(np.fromstring(body.attrib['pos'],sep=' '),origin,atol=1e-10)
        np.testing.assert_allclose(np.fromstring(default.attrib['axis'],sep=' '),axis,atol=1e-10)
    model = mujoco.MjModel.from_xml_path(str(model_dir/'scene.xml'))
    assert model.nq == 7 and model.nu == 6
    joint_info = []
    for i in range(model.njnt):
        joint_info.append({'name':mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_JOINT,i),
                           'range_rad':model.jnt_range[i].tolist()})
    report = {'domain':'model_audit_only_not_hardware_validation','mujoco':mujoco.__version__,
        'source_commit':subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip(),
        'source_dirty':bool(subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True).strip()),
        'assets_sha256':{str(f.relative_to(model_dir)):hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(model_dir.rglob('*')) if f.is_file()},
        'nq':model.nq,'nu':model.nu,'joints':joint_info,
        'fk_origins_axes_match':True,'poses':[],
        'mapping_assumption':'Arm candidate: integer motor ticks -> (tick-2048)*2pi/4096, signs+1 offsets0. Not hardware validated. Gripper held at model0, NOT mapped from recorded gripper.'}
    with tarfile.open(a.inputs) as t:
        cal=json.load(t.extractfile('.cache/huggingface/lerobot/calibration/robots/omx_follower/omx_follower.json'))
        for bundle in ['omx_arrange_shoe_zc','omx_load_zc']:
            pose=json.load(t.extractfile(f'il_ws/bundles/{bundle}/v1/init_pose.json'))['pose']
            q=[]
            for name in ARM:
                c=cal[name]; u=-pose[name] if c['drive_mode'] else pose[name]
                tick=int((np.clip(u,-100,100)+100)/200*(c['range_max']-c['range_min'])+c['range_min'])
                q.append((tick-2048)*2*math.pi/4096)
            data=mujoco.MjData(model)
            for i,angle in enumerate(q,1):
                j=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_JOINT,f'Joint{i}')
                assert model.jnt_range[j,0] <= angle <= model.jnt_range[j,1], (bundle,i,angle)
                data.qpos[model.jnt_qposadr[j]]=angle
            mujoco.mj_forward(model,data)
            contacts=[]
            for c in data.contact:
                contacts.append({'body1':mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_BODY,int(model.geom_bodyid[c.geom1])),
                    'body2':mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_BODY,int(model.geom_bodyid[c.geom2])), 'distance_m':float(c.dist)})
            report['poses'].append({'bundle':bundle,'candidate_arm_rad':q,'recorded_gripper':pose['gripper'],
                'gripper_mapping_validated':False,'arm_in_model_ranges':True,'contacts_at_candidate_pose':contacts})
    # Finite stepping smoke check at official home, not a grasp or tracking test.
    data=mujoco.MjData(model)
    for _ in range(500): mujoco.mj_step(model,data)
    assert np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all()
    report['home_smoke']={'steps':500,'sim_time_s':data.time,'finite':True,'final_qpos':data.qpos.tolist(),
        'warning_counts':data.warning.number.tolist()}
    a.out.parent.mkdir(parents=True,exist_ok=True)
    with a.out.open('x') as f: json.dump(report,f,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k!='assets_sha256'},indent=2))

if __name__=='__main__': main()
