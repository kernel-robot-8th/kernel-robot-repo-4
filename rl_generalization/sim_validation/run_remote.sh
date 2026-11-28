#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
mkdir -p logs runs
run_id="$(date +%Y%m%d_%H%M%S)_$$"
exec >>"logs/$run_id.log" 2>&1
trap 'code=$?; if ((code)); then echo "FAILED exit=$code"; fi' EXIT
printf 'Starting model sweep %s\n' "$run_id"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -u sweep.py --trials 900 --out "runs/$run_id"
echo 'COMPLETE'
