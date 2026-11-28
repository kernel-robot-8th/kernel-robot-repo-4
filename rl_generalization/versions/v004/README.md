# v004 — toy reward correction and failure diagnostics

This is an oracle-state kinematic toy, not a shoe/OMX simulator or real robot policy.

User-reported v003 GPU result: run gpu_20261120_213953, seed 0, 20,000 steps, deterministic evaluation 0/100, evaluation seeds 10000–10099. Checkpoint SHA256: 9d7e6b06cbe014f23657145ba6a52a9db3bc3ab4d8c12aaa168f1a86e56b2b27. The checkpoint remains on the remote machine; it has not been independently inspected locally.

## Change

Original reward penalizes grasp: at zero approach distance, unheld cost=0 but held lift cost=0.07 at tabletop height. New staged_v1 cost is 1+10*distance while unheld, 10*remaining_lift while held. Retains step/action costs and terminal +5. No repeated grasp-event bonus. This is a task reward redesign, not policy-invariant shaping; scale and stage ordering both change. Success condition, observations, action semantics, and grasp threshold-crossing physics are unchanged. Holding at height still requires three steps. Repeatable grasps do not grant event bonuses, but absence of all reward exploits is not proven.

## Diagnosis

Evaluator writes trajectory.csv and episodes.csv: approach distance measured before attachment snap, gripper state, grasp/release events, max object height, actions, EE coordinates. Failure stage is a descriptive heuristic: never within 1.5 cm -> approach; reached but never held -> grasp; ever held without success -> lift_or_hold. A stage label is not a causal proof.

Run metadata missing reward_mode is evaluated with legacy_v003 reward, preserving old reward totals and dynamics. Do not relabel legacy policies as v004-trained. Compare success/stages, not raw reward totals across reward definitions.

## Remote run

After transferring v004 and CURRENT (preserve remote v003/runs), inside tmux:

```bash
cd ~/rl_ws/rl_generalization
bash run.sh test
bash versions/v004/remote_experiment.sh
```

The script diagnoses the existing v003 checkpoint when present, then trains fresh seeds 0/1/2 at 20,000 steps and evaluates each on the same 100 reset seeds. CUDA is mandatory; there is no silent CPU fallback. No new dependencies. All results are local remote-machine files under versions/v004/runs. Repeated seeds across policies are a paired comparison; report each training seed separately. These evaluation seeds are development seeds after tuning; a final report needs a separate untouched reset-seed set and independently specified test layouts. A matched legacy retraining across the same training seeds is still needed for a rigorous multi-seed reward ablation.
