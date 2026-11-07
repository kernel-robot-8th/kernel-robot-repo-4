"""Run lerobot-rollout with k-step temporal ensembling for ACT.

ACT re-predicts a full chunk every k control steps; the executed action is the weighted average
of every stored chunk that covers the current step (weights exp(-m * i), i = 0 for the oldest,
as in lerobot's ACTTemporalEnsembler). k=1 is lerobot's own temporal ensembling; k=chunk_size
is the default chunk-by-chunk execution.

Usage (same arguments as lerobot-rollout; works only with the default sync inference):
  ACT_ENSEMBLE_K=5 ACT_ENSEMBLE_M=0.01 python act_ensemble.py --policy.path=... --robot.type=... ...
"""

import os

import torch

from lerobot.policies.act.modeling_act import ACTPolicy

K = int(os.environ.get("ACT_ENSEMBLE_K", "5"))
M = float(os.environ.get("ACT_ENSEMBLE_M", "0.01"))

_orig_reset = ACTPolicy.reset


def _reset(self):
    _orig_reset(self)
    self._ens_t = 0
    self._ens_chunks = []  # (start step, chunk tensor (B, chunk_size, action_dim)), oldest first


@torch.no_grad()
def _select_action(self, batch):
    self.eval()
    t = self._ens_t
    if t % K == 0:
        self._ens_chunks.append((t, self.predict_action_chunk(batch)))
    self._ens_chunks = [(s, c) for s, c in self._ens_chunks if t - s < c.shape[1]]
    actions = torch.stack([c[:, t - s] for s, c in self._ens_chunks])  # (n, B, action_dim), oldest first
    w = torch.exp(-M * torch.arange(len(actions), device=actions.device, dtype=actions.dtype))
    self._ens_t = t + 1
    return (w[:, None, None] * actions).sum(0) / w.sum()


ACTPolicy.reset = _reset
ACTPolicy.select_action = _select_action

if __name__ == "__main__":
    from lerobot.scripts.lerobot_rollout import main

    print(f"ACT k-step temporal ensembling: k={K}, m={M}")
    main()
