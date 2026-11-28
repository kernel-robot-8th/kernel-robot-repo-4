#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs runs
RUN_ID="$(date +%Y%m%d_%H%M%S)_$$"
exec > >(tee -a "logs/$RUN_ID.log") 2>&1
echo "START $RUN_ID: physical settling checks only, NOT RL training"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python check.py --scene scene/scene.xml --out "runs/$RUN_ID" --trials "${TRIALS:-900}"
echo "COMPLETE: runs/$RUN_ID/summary.json"
