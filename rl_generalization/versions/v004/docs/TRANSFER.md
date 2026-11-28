# GPU update (local shell vs remote shell)

Local `noma@noma-pc`:

```bash
cd ~/dev_ws/Project2/rl_generalization
tar --exclude='runs' --exclude='__pycache__' --exclude='.pytest_cache' \
  -czf /tmp/omx_rl_v004.tar.gz CURRENT README.md HANDOFF.md CHANGELOG.md versions/v004
scp /tmp/omx_rl_v004.tar.gz team11@100.97.16.25:~/rl_ws/
ssh team11@100.97.16.25
```

After remote login (`team11`), separately:

```bash
cd ~/rl_ws/rl_generalization
tar -xzf ../omx_rl_v004.tar.gz
bash run.sh test
tmux new -A -s rl
```

Inside tmux (ensure no previous job is running):

```bash
cd ~/rl_ws/rl_generalization
bash versions/v004/remote_experiment.sh
```

Detach with Ctrl+B, release, D. Local PC may disconnect. Remote GPU must remain awake. Dependencies already installed: do not repeat setup downloads. Current experiment requires no internet once installed. v003/runs and .venvs are not transferred, overwritten or deleted by this archive. Original remote model is used for diagnostics only.
