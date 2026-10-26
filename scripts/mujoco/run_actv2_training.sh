#!/usr/bin/env bash
set -euo pipefail
systemctl --user start omx-actv2-training.service
systemctl --user enable --now omx-actv2-discord.timer
systemctl --user status omx-actv2-training.service --no-pager
