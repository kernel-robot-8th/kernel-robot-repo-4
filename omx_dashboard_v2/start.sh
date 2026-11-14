#!/usr/bin/env bash
# OMX Studio v2 실행 (바탕화면 아이콘이 이 파일을 실행)
cd "$(dirname "$0")"
LOG="$HOME/.cache/omx_dashboard_v2.log"
mkdir -p "$(dirname "$LOG")"
[ -f "$HOME/venv/il/bin/activate" ] && source "$HOME/venv/il/bin/activate"
unset PYTHONPATH
if ! python app.py >"$LOG" 2>&1; then
  msg="대시보드 실행 실패. 로그: $LOG"
  command -v zenity >/dev/null && zenity --error --title="OMX Studio v2" --text="$msg" || notify-send "OMX Studio v2" "$msg"
fi
