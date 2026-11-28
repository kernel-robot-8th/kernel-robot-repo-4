"""Simulation-only approach diagnostic. No hardware, grasp or RL success claims."""
import argparse,json,time
from pathlib import Path
import numpy as np
import mujoco
ROOT=Path(__file__).resolve().parents[3]
START=np.array([-.40957287,-.54456318,-.02761165,1.36831086,-.02761165])
# Provisional link5-local center between fingertips. Must be calibrated before grasping.
TCP=np.array([.075,-.00165,0.])
def forward(m,d,q):
    d.qpos[:5]=q;mujoco.mj_forward(m,d)
    b=m.body('link5').id;rot=d.xmat[b].reshape(3,3)
    return d.xpos[b]+rot@TCP,rot[:,0]
def solve(m,target,q0,axis_target):
    d=mujoco.MjData(m);low=m.jnt_range[:5,0];high=m.jnt_range[:5,1]
    def residual(q):
        pos,axis=forward(m,d,q)
        return np.r_[pos-target,.06*(axis-axis_target)]
    best=None
    for seed in range(8):
        q=np.clip(q0 if seed==0 else q0+np.random.default_rng(seed).normal(0,.5,5),low+.01,high-.01)
        for _ in range(180):
            err=residual(q);jac=np.column_stack([(residual(q+np.eye(5)[j]*1e-5)-err)/1e-5 for j in range(5)])
            dq=-jac.T@np.linalg.solve(jac@jac.T+1e-5*np.eye(6),err)
            q=np.clip(q+np.clip(dq,-.1,.1),low+.01,high-.01)
            if np.linalg.norm(err)<.0005:break
        score=np.linalg.norm(residual(q))
        if best is None or score<best[0]:best=(score,q.copy())
    pos,axis=forward(m,d,best[1]);return best[1],float(np.linalg.norm(pos-target)),float(np.degrees(np.arccos(np.clip(axis@axis_target,-1,1))))
def collisions(m,d):
    result=[]
    for c in d.contact:
        if c.dist>=-.0005:continue
        b=[m.body(int(m.geom_bodyid[g])).name for g in c.geom]
        arm=[n.startswith('link') for n in b]
        if not any(arm):continue
        # Fixed mounting support contact is expected; moving links never exempt.
        if 'link0' in b and not all(arm):continue
        result.append({'bodies':b,'geoms':[m.geom(int(g)).name for g in c.geom],'penetration_m':float(-c.dist)})
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--scene',type=Path,default=ROOT/'.local/inspection_v011/v011/scene.xml');p.add_argument('--out',type=Path,required=True);p.add_argument('--view',action='store_true');a=p.parse_args()
    m=mujoco.MjModel.from_xml_path(str(a.scene.resolve()));a.out.mkdir(parents=True,exist_ok=False)
    results=[];viewer=None
    if a.view:
        from mujoco import viewer as mjviewer
    for shoe in [0,1]:
        d=mujoco.MjData(m);d.qpos[:5]=START;d.ctrl[:5]=START;mujoco.mj_forward(m,d)
        center=d.xpos[m.body(f'shoe{shoe}').id].copy()
        # 4cm above maximum shoe height; the target is NOT a grasp pose.
        target=center+np.array([0,0,.025+.04]);radial=target[:2]-np.array([-.01125,0]);radial/=np.linalg.norm(radial)
        candidates=[]
        for pitch in [45,60,75,90]:
            rad=np.radians(pitch);desired=np.r_[radial*np.cos(rad),-np.sin(rad)]
            q,error,angle=solve(m,target,START,desired)
            candidates.append((error+.001*angle,q,error,angle,pitch))
        _,q,error,angle,pitch=min(candidates,key=lambda v:v[0])
        row={'shoe':shoe,'target_xyz_m':target.tolist(),'tcp_local_assumed_m':TCP.tolist(),'ik_error_m':error,'axis_error_deg':angle,'q_target_rad':q.tolist(),'task_success':None,'approach_pitch_deg':pitch,'candidate_errors':[{'pitch_deg':v[4],'position_error_m':v[2],'axis_error_deg':v[3]} for v in candidates]}
        # Reject a penetrating interpolated joint path before simulated actuation.
        probe=mujoco.MjData(m);bad=[]
        for alpha in np.linspace(0,1,121):
            forward(m,probe,START+alpha*(q-START));bad=collisions(m,probe)
            if bad:break
        row['path_collision']=bad
        if error>.003 or angle>8 or bad:
            row['status']='REJECTED_IK_OR_PATH';results.append(row);continue
        if a.view:
            viewer=mjviewer.launch_passive(m,d);viewer.cam.lookat[:]=[.12,-.06,.17];viewer.cam.distance=.75;viewer.cam.azimuth=135;viewer.cam.elevation=-30
        rows=[];reason=None;duration=max(6.,float(np.max(np.abs(q-START)))/.35*1.5)
        for step in range(int((duration+2)/m.opt.timestep)):
            alpha=min(1.,step*m.opt.timestep/duration);smooth=alpha*alpha*(3-2*alpha)
            d.ctrl[:5]=START+smooth*(q-START);d.ctrl[5]=0
            mujoco.mj_step(m,d)
            bad=collisions(m,d)
            if bad:reason='STOPPED_CONTACT';row['dynamic_collision']=bad;break
            if not np.isfinite(d.qpos).all() or d.warning.number.sum():reason='STOPPED_NUMERICS';break
            if np.any(d.qpos[:5]<m.jnt_range[:5,0]-.01) or np.any(d.qpos[:5]>m.jnt_range[:5,1]+.01):reason='STOPPED_JOINT_LIMIT';break
            if step%10==0:
                b=m.body('link5').id;tcp=d.xpos[b]+d.xmat[b].reshape(3,3)@TCP
                rows.append([float(d.time),*tcp.tolist(),*d.qpos[:5].tolist()])
            if viewer is not None and step%15==0:
                if not viewer.is_running():reason='VIEWER_CLOSED';break
                viewer.sync();time.sleep(m.opt.timestep*15)
        if viewer is not None:viewer.close();viewer=None
        mujoco.mj_forward(m,d);b=m.body('link5').id;tcp=d.xpos[b]+d.xmat[b].reshape(3,3)@TCP
        desired=np.r_[radial*np.cos(np.radians(pitch)),-np.sin(np.radians(pitch))]
        row['final_axis_error_deg']=float(np.degrees(np.arccos(np.clip(d.xmat[b].reshape(3,3)[:,0]@desired,-1,1))))
        row['final_tcp_error_m']=float(np.linalg.norm(tcp-target));row['warnings']=int(d.warning.number.sum());row['status']=reason or ('APPROACH_REACHED' if row['final_tcp_error_m']<.01 and row['final_axis_error_deg']<8 else 'TRACKING_ERROR')
        np.savetxt(a.out/f'shoe{shoe}_trajectory.csv',rows,delimiter=',',header='time,tcp_x,tcp_y,tcp_z,q1,q2,q3,q4,q5',comments='')
        results.append(row)
    summary={'domain':'simulation_only','stage':'pregrasp_approach_only','grasp_or_task_success_evaluated':False,'limitations':['TCP provisional','Real joint zero/sign/gripper calibration unverified','Rigid proxies and assumed dynamics','Simulator provides target position, no camera perception'],'results':results}
    (a.out/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
