#!/usr/bin/env bash
set -euo pipefail
version_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$version_dir/../.." && pwd)"
if [[ "$(cat "$root/CURRENT")" != v004 ]]; then
  echo 'This experiment requires CURRENT=v004.' >&2
  exit 1
fi
stamp="$(date +%Y%m%d_%H%M%S)"
legacy="$root/versions/v003/runs/gpu_20261120_213953"
if [[ -f "$legacy/model.zip" ]]; then
  bash "$root/run.sh" evaluate --run "$legacy" --out "runs/legacy_diagnostic_$stamp" --episodes 100 --seed-start 10000 --device cuda
else
  echo "Legacy checkpoint not found: $legacy; skipping legacy diagnostics."
fi
for seed in 0 1 2; do
  run="runs/staged_${stamp}_seed${seed}"
  bash "$root/run.sh" train --config configs/toy_sac.json --out "$run" --steps 20000 --seed "$seed" --device cuda
  bash "$root/run.sh" evaluate --run "$run" --out "${run}_eval" --episodes 100 --seed-start 10000 --device cuda
done
