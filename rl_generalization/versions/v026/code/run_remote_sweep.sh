#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-$HOME/venv/il/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  echo "missing Python interpreter: $PYTHON" >&2
  exit 2
fi
export PYTHONPATH="$ROOT/versions/v026/code:$ROOT/versions/v018/code${PYTHONPATH:+:$PYTHONPATH}"
if ! "$PYTHON" -c 'import mujoco, pyarrow, numpy; from mujoco_grasp_env import ResidualGraspEnv' >/dev/null 2>&1; then
  echo "Python environment lacks required MuJoCo dependencies or retarget.py: $PYTHON" >&2
  exit 3
fi

mkdir -p versions/v026/evidence/remote_sweep_logs
echo "START $(date -Is) python=$PYTHON root=$ROOT" | tee -a versions/v026/evidence/remote_sweep_logs/runner.log

# Keep running independent physical-mode searches.  Each run has a unique
# output directory, so a disconnect or one failed trial does not lose prior
# evidence.  The best result is selected later from summary.json files.
for zero in 46.6 46.8 47.0 47.2; do
  for shift in -0.003 -0.004 -0.005; do
    for seed in 0 1 2 3; do
      stamp="$(date +%Y%m%d_%H%M%S)"
      tag="z${zero}_s${shift#-}_seed${seed}_${stamp}"
      out="versions/v026/evidence/remote_sweep_${tag}"
      log="versions/v026/evidence/remote_sweep_logs/${tag}.log"
      echo "RUN zero=$zero shift=$shift seed=$seed out=$out" | tee -a versions/v026/evidence/remote_sweep_logs/runner.log
      PYTHONPATH="$ROOT/versions/v026/code:$ROOT/versions/v018/code" "$PYTHON" \
        versions/v026/code/train_cem.py \
        --scene .local/grasp_proxy_v026/scene.xml \
        --shoe shoe1 \
        --attachment-mode physical \
        --iterations 8 \
        --population 24 \
        --elite 6 \
        --horizon 360 \
        --gripper-zero "$zero" \
        --shift-z "$shift" \
        --seed "$seed" \
        --out "$out" >"$log" 2>&1
      rc=$?
      echo "DONE rc=$rc out=$out" | tee -a versions/v026/evidence/remote_sweep_logs/runner.log
    done
  done
done

echo "COMPLETE $(date -Is)" | tee -a versions/v026/evidence/remote_sweep_logs/runner.log
