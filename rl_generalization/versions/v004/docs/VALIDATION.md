# Validation — 2026-11-20

- 34 pytest tests passed, including reproduction of legacy grasp reward reversal, corrected ordering, and 20 scripted-oracle reach/grasp/lift reachability cases. Scripted cases are not learned performance.
- Local CPU seed0, 20,000 SAC steps, evaluation reset seeds 10000–10099: **0/100 full successes**. All 100 episodes grasped exactly once, with no release. All classified lift_or_hold. Max object z across episodes ranged 0.02196–0.03590 m (mean 0.02961), below 0.09 m success threshold. This correction does not establish a successful policy. Need investigate lift exploration/value learning and replicate across seeds before further tuning.
- CPU evidence in evidence/cpu_seed0_*. Training ran before adding code_sha256 provenance metadata to train.py; environment/evaluation/training logic was otherwise unchanged. New runs record code hashes.
- Legacy local v003 400-step checkpoint evaluation (3 episodes) with v004 diagnostic evaluator exactly matches all original episode CSV fields, including rewards and termination. This is not the remote user's 20k checkpoint.
- v003 snapshot: 17 file hashes verified unchanged. No remote v004 run, physical robot trial, or claim of transfer performed.
- Remote CUDA three-seed script is supplied but unexecuted; no CUDA improvement claim. User's v003 reported GPU 0/100 cannot be directly compared causally with this single CPU run without matched seeds/device experiments.
