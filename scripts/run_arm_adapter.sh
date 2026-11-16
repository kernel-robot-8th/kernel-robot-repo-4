#!/usr/bin/env bash
# Copyright 2026 Pinky_Team4
# Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
#
# 팔 어댑터 노드 하나(기본 omx1, --arm 으로 바꿈)를 Station PC 에서 띄운다. 노드는 꺼짐(DISARMED)으로 시작하므로
# 띄우기만 해서는 팔이 움직이지 않는다. 관제 '켜기'(CMD_START)를 받으면 실행기를 띄워 실제 팔에 연결한다.
#
#   scripts/run_arm_adapter.sh                    # 관제와 연결: 도메인 100, 같은 망 공개, backend=worker
#   scripts/run_arm_adapter.sh --domain 101 --localhost --backend fake   # 혼자 시험 (팔 안 씀)
#
# 끝내기: Ctrl+C. 팔이 켜져 있었으면 토크가 꺼지므로 팔을 받친다.
# 자세한 흐름: src/cobot_manipulation/docs/prd.md 4·5절.
#
# 환경변수 (기본값이 맞지 않을 때):
#   OMX_FLEET_DIR  실행기 폴더 (tool/omx-dashboard 브랜치 omx_fleet/).
#                  기본: 이 저장소 옆 worktree <저장소>-omx-dashboard/omx_fleet
#   OMX_VENV_PY    lerobot 0.4.4 파이썬. 기본: ~/venv/il/bin/python
set -eo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
FLEET=${OMX_FLEET_DIR:-"$(dirname "$REPO")/$(basename "$REPO")-omx-dashboard/omx_fleet"}
VENV_PY=${OMX_VENV_PY:-"$HOME/venv/il/bin/python"}
ARM_ID=omx1   # --arm 으로 바꾼다. 이 PC 자리 팔은 cobot_control_center/config/site_arms.yaml 의 host

DOMAIN=100
LOCALHOST=0
BACKEND=worker
AUTO_START=false

usage() {
    sed -n '5,17p' "$0" | sed 's/^# \{0,1\}//'
    echo
    echo "옵션: --arm omxN (기본 omx1)  --domain N  --localhost  --backend worker|fake|none  --auto-start"
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --arm) ARM_ID="$2"; shift 2 ;;
        --domain) DOMAIN="$2"; shift 2 ;;
        --localhost) LOCALHOST=1; shift ;;
        --backend) BACKEND="$2"; shift 2 ;;
        --auto-start) AUTO_START=true; shift ;;
        -h|--help) usage 0 ;;
        *) echo "모르는 옵션: $1"; usage 1 ;;
    esac
done

fail() { echo "✗ $*" >&2; exit 1; }
ok() { echo "✓ $*"; }

case "$ARM_ID" in omx[0-9]|omx[0-9][0-9]) ;; *) fail "팔 이름은 omxN 형태 ($ARM_ID)" ;; esac
case "$BACKEND" in worker|fake|none) ;; *) fail "backend 는 worker·fake·none 중 하나 ($BACKEND)" ;; esac
case "$DOMAIN" in ''|*[!0-9]*) fail "도메인은 숫자 ($DOMAIN)" ;; esac
if [ "$DOMAIN" = 10 ] || [ "$DOMAIN" = 12 ]; then
    # CLAUDE.md 7절: 10·12 는 실물 구동용 설계 제안(D2). 확정 전에는 이 스크립트로 쓰지 않는다
    fail "도메인 $DOMAIN 은 실물 구동용 설계 제안(D2). 이 스크립트로 띄우지 않는다"
fi
[ -f "$REPO/install/setup.bash" ] \
    || fail "빌드가 없음: $REPO 에서 colcon build --symlink-install --packages-up-to cobot_manipulation"

# ---- 사전 검사 ----
# 같은 팔 어댑터가 이미 떠 있으면 같은 토픽에 두 노드가 답한다
if pgrep -f "arm_adapter_node.*arm_id:=$ARM_ID" >/dev/null; then
    fail "$ARM_ID 어댑터가 이미 떠 있음: $(pgrep -af "arm_adapter_node.*arm_id:=$ARM_ID" | head -1)"
fi

if [ "$BACKEND" = worker ]; then
    # 단독 실행기가 시리얼 포트를 잡고 있으면 어댑터가 띄운 실행기가 연결하지 못한다
    if pgrep -f omx_fleet_worker.py >/dev/null; then
        echo "✗ 단독으로 띄운 실행기가 팔을 잡고 있음:" >&2
        pgrep -af omx_fleet_worker.py | sed 's/^/    /' >&2
        fail "그 터미널에서 {\"cmd\":\"release\"} (거절되면 팔을 받치고 {\"cmd\":\"quit\"}) 로 먼저 끈다"
    fi
    [ -x "$VENV_PY" ] || fail "lerobot 0.4.4 파이썬이 없음: $VENV_PY (OMX_VENV_PY 로 지정)"
    [ -f "$FLEET/omx_fleet_worker.py" ] \
        || fail "실행기가 없음: $FLEET/omx_fleet_worker.py (OMX_FLEET_DIR 로 지정)"
    [ -f "$FLEET/fleet_arms.yaml" ] \
        || fail "팔 설정이 없음: $FLEET/fleet_arms.yaml (fleet_arms.example.yaml 을 복사해 고친다)"
    ok "실행기 $FLEET/omx_fleet_worker.py"
fi

if [ "$BACKEND" != none ]; then
    SERIAL=$(sed -n "/^  $ARM_ID:/,/^  [a-z]/s/^ *serial: *\([A-Za-z0-9]*\).*/\1/p" \
        "$REPO/src/cobot_manipulation/config/arm_registry.yaml" | head -1)
    if [ -n "$SERIAL" ] && ls /dev/serial/by-id/ 2>/dev/null | grep -q "_${SERIAL}-if00"; then
        ok "보드 $SERIAL 연결됨"
    else
        echo "! $ARM_ID 보드(${SERIAL:-시리얼 미등록})가 안 보임. 노드는 뜨지만 UNKNOWN 으로 일을 안 한다"
    fi
fi

# ---- ROS 환경 ----
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
# shellcheck disable=SC1091
source "$REPO/install/setup.bash"
export ROS_DOMAIN_ID="$DOMAIN"
if [ "$LOCALHOST" = 1 ]; then
    export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
else
    unset ROS_AUTOMATIC_DISCOVERY_RANGE   # 기본(SUBNET): 같은 망의 관제 PC 와 통신
fi
SHARE=$(ros2 pkg prefix cobot_manipulation)/share/cobot_manipulation

ARGS=(--ros-args -r "__node:=${ARM_ID}_adapter"
      --params-file "$SHARE/config/arm_adapter.yaml"
      -p "arm_id:=$ARM_ID" -p "backend:=$BACKEND" -p "auto_start:=$AUTO_START"
      -p "registry_file:=$SHARE/config/arm_registry.yaml")
if [ "$BACKEND" = worker ]; then
    # 셸을 거치지 않고 공백으로 나눠 실행되므로 경로에 공백이 있으면 안 된다
    ARGS+=(-p "worker_command:=$VENV_PY $FLEET/omx_fleet_worker.py --arms-file $FLEET/fleet_arms.yaml")
fi

echo
echo "  도메인 $ROS_DOMAIN_ID  범위 ${ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET (같은 망 공개)}  backend $BACKEND  auto_start $AUTO_START"
if [ "$BACKEND" = worker ]; then
    echo "  ⚠ 관제 '켜기'(START)를 받으면 실제 팔에 연결해 토크를 켠다. 팔은 쉬는 자세, 12 V 스위치에 손을 둔다."
    [ "$AUTO_START" = true ] && echo "  ⚠ auto_start: 노드가 뜨자마자 팔에 연결한다."
    [ "$LOCALHOST" = 0 ] && echo "  ⚠ 관제 fleet_control 이 PICK 단계를 보내면 팔이 실제로 움직인다. 시험 중 주문 금지."
    echo "  ⚠ 팔 옆에 사람이 없을 때는 이 노드를 끈다 (관제 웹에 로그인이 없다)."
fi
echo "  끝내기 Ctrl+C (팔이 켜져 있으면 토크가 꺼진다 → 팔을 받친다)"
echo
exec ros2 run cobot_manipulation arm_adapter_node "${ARGS[@]}"
