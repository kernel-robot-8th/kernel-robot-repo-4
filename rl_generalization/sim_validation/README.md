# Detached remote physical-model checks

Not RL training or shoe grasping. Uses upstream OMX model plus v005 candidate arm poses, explicit simulator gripper angles0/.4/.8 radians. Model files hash-checked against v005 evidence. No robot code imports or devices. CPU MuJoCo headless (no GLFW/EGL), 900 trials,4 simulated seconds/trial; two poses, three perturbation amplitudes and three gripper settings. 2-second smooth joint-target ramp then2-second settling. Records tracking error, numerical warnings, contact counts/distances/body pairs and actuator force. Contact count alone is not a failure criterion. Unknown real gripper calibration, dynamics and zero remain unresolved.

The job installs separate .venv, writes logs and runs under its bundle directory, exits after finite work. No dependency on Codex remaining active. Remote host must stay awake; network needed for initial pip installation only. CPU smoke18trials:18finite,0warnings,0contact trials, median final max error0.0042164rad;1.16s on local hardware. Full900 may complete in minutes, not overnight. No benefit claimed from increasing runtime arbitrarily.

Bundle creation: copy sweep.py,run_remote.sh,requirements.txt,model_audit.json and full upstream robotis_omx directory into omx_sim_batch; preserve LICENSE. Tar into /tmp/omx_sim_batch.tar.gz. Model assets remain in ignored .local upstream source; do not add copied meshes unnecessarily to Git.

Remote start (after unpack into ~/rl_ws):
`tmux new-session -d -s simcheck 'bash ~/rl_ws/omx_sim_batch/run_remote.sh; exec bash'`

Inspect latest logs/*.log and runs/*/summary.json; DONE marker indicates completed sweep. No successful grasp/policy metric. If install fails, log ends FAILED. Existing simcheck session is not replaced automatically. Packaging smoke test used same scripts/model under /tmp/omx_sim_batch,18trials; not a remote execution.
