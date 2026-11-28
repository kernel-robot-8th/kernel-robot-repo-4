"""Evaluate a toy policy on an explicit reset-seed set; never updates policy."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
import torch
from stable_baselines3 import SAC
from .env import EnvConfig, ToyGraspEnv


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--episodes', type=int, default=30)
    p.add_argument('--seed-start', type=int, default=10000)
    p.add_argument('--spread-m', type=float)
    args = p.parse_args()
    if args.episodes < 1:
        raise ValueError('episodes must be positive')
    run = json.loads((args.run/'run.json').read_text())
    if run.get('deployment') != 'TOY_ONLY_NOT_FOR_ROBOT':
        raise ValueError('not a toy checkpoint')
    cfg = dict(run['env'])
    if args.spread_m is not None:
        cfg['spread_m'] = args.spread_m
    env = ToyGraspEnv(EnvConfig(**cfg))
    torch.set_num_threads(1)
    model = SAC.load(args.run/'model.zip', device='cpu')
    args.out.mkdir(parents=True, exist_ok=False)
    rows = []
    try:
        for i in range(args.episodes):
            seed = args.seed_start+i
            obs, _ = env.reset(seed=seed)
            xy = env.obj[:2].copy()
            done = False
            total = 0.0
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, term, trunc, info = env.step(action)
                total += reward
                done = term or trunc
            rows.append(dict(seed=seed, x_m=float(xy[0]), y_m=float(xy[1]),
                success=info['is_success'], steps=env.steps, reward=total,
                reason=info['termination_reason']))
    finally:
        env.close()
    with (args.out/'episodes.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    successes = sum(r['success'] for r in rows)
    n = len(rows); rate = successes/n; z = 1.96
    center = (rate+z*z/(2*n))/(1+z*z/n)
    half = z*np.sqrt(rate*(1-rate)/n+z*z/(4*n*n))/(1+z*z/n)
    summary = {'domain':'toy_only','successes': successes, 'episodes': n,
        'success_rate': rate, 'wilson_95_interval':[center-half, center+half],
        'seed_start':args.seed_start,'env':cfg,'training_seed':run['seed'],
        'checkpoint_sha256':hashlib.sha256((args.run/'model.zip').read_bytes()).hexdigest(),
        'warning':'Software check only. Not robot performance or proof of transfer.'}
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))

if __name__ == '__main__':
    main()
