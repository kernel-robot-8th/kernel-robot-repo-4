"""Audit actual IL demonstrations. No unit conversion or hardware commands."""
import argparse,csv,hashlib,json
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[3]
SOURCES={'shoebox_D':('Yuzriha00/shoebox_D','d641442875f08264680b19fe7d961c0f1343c40c'),'move_in_success':('hfhfhf111/move_in_success','71f08f2ca8ec29386ead547542578ccbc09b17e7')}
def stats(a):
    a=np.asarray(a,dtype=float)
    return {'min':np.nanmin(a,axis=0).tolist(),'max':np.nanmax(a,axis=0).tolist(),'median':np.nanmedian(a,axis=0).tolist(),'nonfinite_count':int((~np.isfinite(a)).sum())}
def plot(out,t,a,s,c):
    parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="660" viewBox="0 0 1000 660"><rect width="1000" height="660" fill="white"/>']
    for panel,(title,series) in enumerate([('Gripper normalized units (not degrees): blue=command red=state',[(a[:,5],'#1976d2'),(s[:,5],'#d32f2f')]),('Gripper current raw (collector declares 1mA/unit)',[(c,'#00875a')]),('Arm command-state absolute error, normalized units',[(np.max(abs(a[:,:5]-s[:,:5]),axis=1),'#7443ab')])]):
        top=40+panel*210;low=min(float(x.min()) for x,_ in series);high=max(float(x.max()) for x,_ in series);span=max(high-low,1.)
        parts.append(f'<text x="60" y="{top-12}" font-size="16">{title}</text><path d="M60 {top} V{top+155} H970" stroke="black" fill="none"/>')
        parts.append(f'<text x="2" y="{top+12}">{high:.1f}</text><text x="2" y="{top+155}">{low:.1f}</text>')
        for values,color in series:
            pts=' '.join(f'{60+910*float(x-t[0])/max(float(t[-1]-t[0]),.01):.2f},{top+155-155*(float(y)-low)/span:.2f}' for x,y in zip(t,values))
            parts.append(f'<polyline points="{pts}" stroke="{color}" stroke-width="1.5" fill="none"/>')
        parts.append(f'<text x="60" y="{top+180}">0 s</text><text x="900" y="{top+180}">{t[-1]:.2f} s</text>')
    parts.append('</svg>');out.write_text(''.join(parts))
def main():
    p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,default=ROOT/'.local/demonstrations');p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    summaries={};hashes={}
    for name,(repo,revision) in SOURCES.items():
        root=a.data_root/name;info=json.loads((root/'meta/info.json').read_text());collector=json.loads((root/'meta/collector_info.json').read_text())
        tables=[]
        for file in sorted((root/'data').rglob('*.parquet')):
            tables.extend(pq.read_table(file).to_pylist());hashes[f'{name}/{file.relative_to(root)}']=hashlib.sha256(file.read_bytes()).hexdigest()
        for file in (root/'meta').rglob('*'):
            if file.is_file():hashes[f'{name}/{file.relative_to(root)}']=hashlib.sha256(file.read_bytes()).hexdigest()
        tables.sort(key=lambda r:(r['episode_index'],r['frame_index']))
        ep=np.array([r['episode_index'] for r in tables]);act=np.array([r['action'] for r in tables]);state=np.array([r['observation.state'] for r in tables]);current=np.array([r['aux.gripper_current'] for r in tables]).reshape(-1);ts=np.array([r['timestamp'] for r in tables]);success=np.array([r['episode_success'] for r in tables])
        records=[]
        for e in np.unique(ep):
            idx=ep==e;dt=np.diff(ts[idx]);records.append({'episode':int(e),'frames':int(idx.sum()),'duration_last_timestamp_s':float(ts[idx][-1]),'success_labels':np.unique(success[idx]).tolist(),'nonincreasing_timestamp_count':int((dt<=0).sum()),'median_dt':float(np.median(dt)),'gripper_current_min_raw':float(current[idx].min()),'gripper_current_max_raw':float(current[idx].max()),'gripper_state_min':float(state[idx,5].min()),'gripper_state_max':float(state[idx,5].max())})
        assert len(tables)==info['total_frames'];assert len(records)==info['total_episodes'];assert act.shape==state.shape==(len(tables),6)
        summary={'repo':repo,'revision':revision,'frames':len(tables),'episodes':len(records),'fps_metadata':info['fps'],'names':info['features']['action']['names'],'units':collector['units'],'success_labels':np.unique(success).tolist(),'action':stats(act),'state':stats(state),'abs_same_frame_action_state_error':stats(abs(act-state)),'gripper_current_raw':stats(current),'gripper_current_nonzero_frames':int(np.count_nonzero(current)),'episodes_detail':records,'warning':'Collector labels are not independent outcome validation; demonstrations are teleoperation, not ACT inference rollout. Current is not contact force/pressure. Same-frame error includes command timing/latency.'}
        summaries[name]=summary
        idx=ep==0;columns=['timestamp']+[f'action_{n}' for n in summary['names']]+[f'state_{n}' for n in summary['names']]+['gripper_current_raw']
        with (a.out/f'{name}_episode000.csv').open('w') as f:
            w=csv.writer(f);w.writerow(columns);w.writerows(np.column_stack([ts[idx],act[idx],state[idx],current[idx]]))
        plot(a.out/f'{name}_episode000.svg',ts[idx],act[idx],state[idx],current[idx])
    (a.out/'summary.json').write_text(json.dumps(summaries,indent=2,ensure_ascii=False));(a.out/'source_hashes.json').write_text(json.dumps(hashes,indent=2))
    for k,v in summaries.items():print(k,json.dumps({key:v[key] for key in ['episodes','frames','success_labels','gripper_current_raw','gripper_current_nonzero_frames']},ensure_ascii=False))
if __name__=='__main__':main()
