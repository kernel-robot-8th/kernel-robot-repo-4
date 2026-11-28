"""Audit shoebox_D demonstrations and print MuJoCo calibration recommendations.

This is data audit only: it does not claim a hardware gripper zero. It scans
all 50 parquet episodes, validates the user supplied initial pose, finds the
closed/open action bands, and checks which shoe the retargeted path approaches.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
USER_INIT = np.array([-12.97,-17.31,-0.85,43.59,-0.85,59.68], dtype=float)
GAIN = 4095.0 * 2*np.pi / 4096.0 / 100.0

def main() -> None:
    ap=argparse.ArgumentParser(); ap.add_argument('--dataset',type=Path,default=ROOT/'.local/demonstrations/shoebox_D/data/chunk-000'); ap.add_argument('--out',type=Path,default=None); a=ap.parse_args()
    paths=sorted(a.dataset.glob('file-*.parquet')) if a.dataset.is_dir() else [a.dataset]
    if not paths: raise SystemExit(f'no parquet files: {a.dataset}')
    rows=[]
    for p in paths: rows.extend(pq.read_table(p).to_pylist())
    episodes=sorted({int(r['episode_index']) for r in rows})
    first=[next(r for r in rows if int(r['episode_index'])==e) for e in episodes]
    obs=np.asarray([r['observation.state'] for r in first],float)
    actions=np.asarray([r['action'] for r in rows],float)
    states=np.asarray([r['observation.state'] for r in rows],float)
    currents=np.asarray([r['aux.gripper_current'] for r in rows],float)
    out={
      'episodes':len(episodes),'rows':len(rows),
      'initial_observation_median_lerobot':np.median(obs,0).tolist(),
      'initial_observation_max_abs_error_from_user':float(np.max(np.abs(np.median(obs,0)-USER_INIT))),
      'action_gripper_range_lerobot':[float(actions[:,5].min()),float(actions[:,5].max())],
      'state_gripper_range_lerobot':[float(states[:,5].min()),float(states[:,5].max())],
      'action_gripper_final_median_lerobot':float(np.median([max((r for r in rows if int(r['episode_index'])==e), key=lambda r: float(r['timestamp']))['action'][5] for e in episodes])),
      'aux_gripper_current_range_raw':[float(currents.min()),float(currents.max())],
      'gain_rad_per_lerobot_unit':GAIN,
      'candidate_zeros_lerobot':[46.6,46.8,47.0,47.2],
      'warning':'Data-derived candidates only; select zero using contact/lift sweep, not current alone.'
    }
    text=json.dumps(out,indent=2); print(text)
    if a.out: a.out.write_text(text+'\n')
if __name__=='__main__':main()
