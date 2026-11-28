"""Read-only jitter report for one episode, long-format joint CSV.

Columns: t_s,joint,act_target,sent_target,actual_position,chunk_id.
Units are the recorder's joint units, NOT assumed to be radians/degrees.
"""
import argparse
import csv
import json
from pathlib import Path
import numpy as np


def analyze(rows):
    groups = {}
    for row in rows:
        groups.setdefault(row['joint'], []).append(row)
    report = {}
    for joint, data in groups.items():
        if len(data) < 3:
            raise ValueError(f'{joint}: at least 3 samples needed')
        values = np.array([[float(r[k]) for k in ['t_s','act_target','sent_target','actual_position']] for r in data])
        if not np.isfinite(values).all() or np.any(np.diff(values[:,0]) <= 0):
            raise ValueError(f'{joint}: finite values and strictly increasing timestamps required')
        dt = np.diff(values[:,0])
        delta = np.abs(np.diff(values[:,1:], axis=0))
        boundary = np.array([data[i]['chunk_id'] != data[i-1]['chunk_id'] for i in range(1,len(data))])
        report[joint] = {'samples':len(data), 'median_dt_s':float(np.median(dt)),
            'max_dt_s':float(dt.max()), 'target_delta_p95':float(np.percentile(delta[:,0],95)),
            'sent_delta_p95':float(np.percentile(delta[:,1],95)),
            'actual_speed_p95_units_per_s':float(np.percentile(delta[:,2]/dt,95)),
            'tracking_rmse_units':float(np.sqrt(np.mean((values[:,2]-values[:,3])**2))),
            'chunk_boundary_target_delta_mean':float(delta[boundary,0].mean()) if boundary.any() else None,
            'non_boundary_target_delta_mean':float(delta[~boundary,0].mean()) if (~boundary).any() else None}
    if not report: raise ValueError('no samples')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('csv_path',type=Path)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    with args.csv_path.open() as f: report=analyze(list(csv.DictReader(f)))
    with args.out.open('x') as f: json.dump(report,f,indent=2)

if __name__ == '__main__': main()
