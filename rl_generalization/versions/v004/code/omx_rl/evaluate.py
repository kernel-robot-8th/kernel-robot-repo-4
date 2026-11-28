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
from .device import resolve_device


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--episodes', type=int, default=30)
    p.add_argument('--seed-start', type=int, default=10000)
    p.add_argument('--spread-m', type=float)
    p.add_argument('--device', choices=['auto','cpu','cuda'], default='auto')
    args = p.parse_args()
    device = resolve_device(args.device)
    if args.episodes < 1:
        raise ValueError('episodes must be positive')
    run = json.loads((args.run/'run.json').read_text())
    if run.get('deployment') != 'TOY_ONLY_NOT_FOR_ROBOT':
        raise ValueError('not a toy checkpoint')
    cfg = dict(run['env'])
    # Old run metadata lacks reward_mode; retain its original reward.
    cfg.setdefault('reward_mode', 'legacy_v003')
    if args.spread_m is not None:
        cfg['spread_m'] = args.spread_m
    env = ToyGraspEnv(EnvConfig(**cfg))
    torch.set_num_threads(1)
    model = SAC.load(args.run/'model.zip', device=device)
    args.out.mkdir(parents=True, exist_ok=False)
    rows = []
    traces = []
    try:
        for i in range(args.episodes):
            seed = args.seed_start+i
            obs, _ = env.reset(seed=seed)
            xy = env.obj[:2].copy()
            done = False
            total = 0.0
            min_distance = float(np.linalg.norm(env.obj-env.ee))
            ever_held = False
            max_height = float(env.obj[2])
            grasps = releases = 0
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, term, trunc, info = env.step(action)
                total += reward
                min_distance = min(min_distance, info['distance_before_grasp_m'])
                ever_held |= info['held']
                max_height = max(max_height, info['object_m'][2])
                grasps += int(info['grasp_event'])
                releases += int(info['release_event'])
                traces.append(dict(seed=seed, step=env.steps, reward=reward,
                    distance_m=info['distance_before_grasp_m'], grip=info['grip'],
                    held=info['held'], object_z_m=info['object_m'][2],
                    ee_x_m=env.ee[0], ee_y_m=env.ee[1], ee_z_m=env.ee[2],
                    action_x=float(action[0]), action_y=float(action[1]),
                    action_z=float(action[2]), action_grip=float(action[3])))
                done = term or trunc
            rows.append(dict(seed=seed, x_m=float(xy[0]), y_m=float(xy[1]),
                success=info['is_success'], steps=env.steps, reward=total,
                reason=info['termination_reason'], min_distance_m=min_distance,
                ever_held=ever_held, max_object_z_m=max_height, grasps=grasps, releases=releases,
                failure_stage=('success' if info['is_success'] else
                    'lift_or_hold' if ever_held else 'grasp' if min_distance < 0.015 else 'approach')))
    finally:
        env.close()
    with (args.out/'episodes.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    with (args.out/'trajectory.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(traces[0]))
        writer.writeheader(); writer.writerows(traces)
    successes = sum(r['success'] for r in rows)
    n = len(rows); rate = successes/n; z = 1.96
    center = (rate+z*z/(2*n))/(1+z*z/n)
    half = z*np.sqrt(rate*(1-rate)/n+z*z/(4*n*n))/(1+z*z/n)
    summary = {'domain':'toy_only','device':device,'successes': successes, 'episodes': n,
        'success_rate': rate, 'wilson_95_interval':[center-half, center+half],
        'seed_start':args.seed_start,'env':cfg,'training_seed':run['seed'],
        'failure_stages': {stage: sum(r['failure_stage']==stage for r in rows)
            for stage in ['approach','grasp','lift_or_hold','success']},
        'ever_held_episodes': sum(r['ever_held'] for r in rows),
        'checkpoint_sha256':hashlib.sha256((args.run/'model.zip').read_bytes()).hexdigest(),
        'warning':'Software check only. Not robot performance or proof of transfer.'}
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))

if __name__ == '__main__':
    main()
