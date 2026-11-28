"""SAC training entry point for TOY validation only; deliberately has no real backend."""
import argparse
from dataclasses import asdict
import importlib.metadata
import json
from pathlib import Path
import random
import numpy as np
import torch
from stable_baselines3 import SAC
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.callbacks import CheckpointCallback
from stable_baselines3.common.env_checker import check_env
from .env import EnvConfig, ToyGraspEnv


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--steps', type=int)
    p.add_argument('--seed', type=int, default=0)
    args = p.parse_args()
    cfg = json.loads(args.config.read_text())
    if cfg.get('backend') != 'toy':
        raise ValueError('Only toy backend implemented. Real hardware needs a validated adapter.')
    steps = args.steps if args.steps is not None else cfg['total_timesteps']
    if steps < 1:
        raise ValueError('steps must be positive')
    env_cfg = EnvConfig(**cfg['env'])
    args.out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    versions = {x: importlib.metadata.version(x) for x in ['torch','gymnasium','stable-baselines3','numpy']}
    effective = {**cfg, 'env': asdict(env_cfg), 'total_timesteps': steps, 'seed': args.seed,
                 'versions': versions, 'deployment': 'TOY_ONLY_NOT_FOR_ROBOT'}
    (args.out/'run.json').write_text(json.dumps(effective, indent=2))
    env = ToyGraspEnv(env_cfg)
    check_env(env)
    env = Monitor(env, str(args.out/'monitor.csv'))
    try:
        model = SAC('MlpPolicy', env, seed=args.seed, device='cpu', verbose=1,
                    policy_kwargs={'net_arch': [64,64]}, **cfg['sac'])
        callback = CheckpointCallback(save_freq=max(1000, steps//5),
            save_path=str(args.out/'checkpoints'), save_replay_buffer=True)
        model.learn(total_timesteps=steps, callback=callback)
        model.save(str(args.out/'model'))
        model.save_replay_buffer(str(args.out/'replay.pkl'))
    finally:
        env.close()

if __name__ == '__main__':
    main()
