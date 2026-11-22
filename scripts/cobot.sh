#!/usr/bin/env bash
# Copyright 2026 Pinky_Team4
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# 관제 PC 실행 입구 하나. 켜기·끄기·상태 보기를 여기서 한다.
#   bash scripts/cobot.sh help
#
# 현장은 도커 관제 하나로 돌린다 (브릿지·zone_manager·fleet·관제 화면 8080·고객 화면 8081).
# 로봇은 전원을 켜면 systemd 로 스스로 기동한다 (cobot_pinky_patrol README). 이 스크립트는 로봇에 접속하지 않는다.
# 도메인 100(실물)에 닿는 명령(site up/rebuild/down, view, stop)은 기본이 미리보기이고,
# --execute 를 붙여야 실행하며 그때도 한 번 묻는다 (--yes 로 건너뜀).
# 도커는 지혁 님 fleet_docker.sh 를 그대로 부른다 (그 파일·versions.env 는 고치지 않고 환경변수로만 넘긴다).
# 포트 정본: docs/ports.md. 켜는 순서: docs/system_startup.md.

set -euo pipefail

WS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAV_ROOT="${WS_DIR}/src/cobot_navigation"
DOCKER_DIR="${NAV_ROOT}/cobot_fleet_control/config/docker"
FLEET_DOCKER="${DOCKER_DIR}/fleet_docker.sh"

# 화면 포트 (docs/ports.md 와 같게. launch 기본값을 바꾸면 여기도 고친다)
PORT_SITE=8080      # 실물 관제 (도커 web 또는 bringup)
PORT_CUSTOMER=8081  # 고객 주문 화면 (도커 customer)
PORT_MOCK=8181      # 가짜 핑키
PORT_SIM=8182       # 가제보
PORT_ANOMALY=8083   # 이상 감지 콘솔 (127.0.0.1, 강건한 님)
REAL_DOMAIN=100
MOCK_DOMAIN="${MOCK_DOMAIN_ID:-101}"
HEALTH_WAIT_SEC=60  # site up 뒤 작업 노드 응답을 기다리는 최대 시간 [s]

# 도커 관제 프로젝트 이름은 'cobot-fleet' 로 시작한다 (예: cobot-fleet-customer3).
# 프로젝트마다 주문·재고 DB 볼륨(<프로젝트>_fleet-data)이 따로라서, 이름을 잘못 고르면 다른 원장으로 뜬다.
PROJECT_PREFIX=cobot-fleet
# 이 PC 에서 직접 띄우는 launch (stop·status 가 찾는다). 도커 안 프로세스(/opt/cobot)는 빼고 센다.
LAUNCH_PATTERNS=(
  "ros2 launch cobot_mock mock_fleet.launch.xml"
  "ros2 launch cobot_gazebo sim_fleet.launch.xml"
  "ros2 launch cobot_bringup bringup.launch.xml"
  "ros2 launch cobot_control_center fleet_api_dev.launch.xml"
)
# 예전 draft 스크립트가 만들던 tmux 세션 (로봇 SSH 기동). 떠 있으면 도메인 100 을 함께 쓰므로 알린다.
TMUX_SESSIONS=(prod dev_real)

TAG=cobot
EXECUTE=false
ASSUME_YES=false

log() { echo "[${TAG}] $*"; }
die() { echo "[${TAG}] $*" >&2; exit 1; }

confirm() {
  [[ "${ASSUME_YES}" == true ]] && return 0
  local answer
  read -r -p "[${TAG}] $1 [y/N] " answer
  [[ "${answer}" == "y" || "${answer}" == "Y" ]]
}

usage() {
  cat <<EOF
관제 PC 실행 입구 (bash scripts/cobot.sh <명령> [인자])

준비
  setup                 .venv 만들기·고정 버전 설치 (fastapi 등, 시스템 파이썬은 건드리지 않음)
  build [--no-test]     관제 관련 패키지 빌드 (+ 시험)

로봇 없이 (실물과 격리)
  mock [--manual] [launch 인자]   가짜 핑키 3대 + 관제. 화면 http://localhost:${PORT_MOCK}/service/
                                  --manual: 자동 순찰 끔 (명령 시험용). 도메인 ${MOCK_DOMAIN}, 이 PC 안에서만
  sim [--headless] [launch 인자]  가제보 시뮬. 화면 http://localhost:${PORT_SIM}/service/

현장 (도메인 ${REAL_DOMAIN}, 실물. 기본은 미리보기, --execute 로 실행)
  site up       [--execute] [--yes]  지금 커밋 이미지로 도커 관제 켜기
  site rebuild  [--execute] [--yes]  지금 커밋으로 이미지 빌드 → 스모크 → 켜기
  site down     [--execute] [--yes]  도커 관제 내리기 (주문·재고 DB 볼륨은 남김)
  site logs [서비스]                 도커 로그 (서비스: fleet, web, customer, bridge, zone-manager)
  view          [--execute] [--yes]  실물을 보기만 (bringup, 작업 노드 없음, ${PORT_SITE})
  stop          [--execute] [--yes] [--down|--keep-docker]
                                     이 PC 에서 띄운 관제·가짜 핑키·가제보·도커를 끄기

보기
  status        지금 떠 있는 것 (도커·launch·포트, 로봇팔 서비스, 이상 감지, 로봇·팔 연결, 주문 준비 여부)

환경변수
  COBOT_PROJECT   도커 프로젝트 이름 (기본: 떠 있는 것 → 가장 최근 것 → ${PROJECT_PREFIX})
  COBOT_IMAGE     도커 이미지 (기본: cobot-fleet:dev-<지금 커밋 7자리>)
  MOCK_DOMAIN_ID  가짜 핑키 도메인 (기본 101)

화면: 매장 관리 http://<관제 PC>:${PORT_SITE}/service/   엔지니어 http://<관제 PC>:${PORT_SITE}/
EOF
}

# ---------- 공통 ----------

load_env() {
  [[ -d "${WS_DIR}/.venv" ]] || die ".venv 가 없음. 먼저: bash scripts/cobot.sh setup"
  [[ -f "${WS_DIR}/install/setup.bash" ]] || die "빌드 결과가 없음. 먼저: bash scripts/cobot.sh build"
  # ROS setup 스크립트는 정의 안 된 변수를 읽으므로 -u 를 잠시 끈다.
  set +u
  # shellcheck source=/dev/null
  source /opt/ros/jazzy/setup.bash
  # shellcheck source=/dev/null
  source "${WS_DIR}/.venv/bin/activate"
  # shellcheck source=/dev/null
  source "${WS_DIR}/install/setup.bash"
  set -u
}

# 실행 플래그만 떼어 낸다. 남은 인자는 REST 에 담긴다.
parse_flags() {
  REST=()
  local arg
  for arg in "$@"; do
    case "${arg}" in
      --execute) EXECUTE=true ;;
      --yes) ASSUME_YES=true ;;
      *) REST+=("${arg}") ;;
    esac
  done
}

has_tmux_session() { command -v tmux >/dev/null && tmux has-session -t "$1" 2>/dev/null; }

# 이 사용자가 직접 띄운 launch 의 pid (도커 안 /opt/cobot 프로세스는 뺀다)
launch_pids() {
  { pgrep -u "${USER}" -f "$1" 2>/dev/null || true; } | while read -r pid; do
    if ! tr '\0' ' ' <"/proc/${pid}/cmdline" 2>/dev/null | grep -q '/opt/cobot'; then
      echo "${pid}"
    fi
  done
}

port_in_use() { ss -ltn 2>/dev/null | grep -qE ":$1\b"; }

have_docker() { command -v docker >/dev/null && docker info >/dev/null 2>&1; }

# 떠 있는 도커 관제 컨테이너 이름 (모든 cobot-fleet* 프로젝트)
running_containers() {
  have_docker || return 0
  docker ps --format '{{.Label "com.docker.compose.project"}} {{.Names}}' 2>/dev/null \
    | awk -v p="${PROJECT_PREFIX}" 'index($1, p) == 1 { print $2 }'
}

# 쓸 도커 프로젝트: COBOT_PROJECT → 떠 있는 것 → 가장 최근에 만든 것 → 기본 이름
site_project() {
  if [[ -n "${COBOT_PROJECT:-}" ]]; then
    echo "${COBOT_PROJECT}"
    return
  fi
  local found=""
  if have_docker; then
    found="$(docker ps --filter label=com.docker.compose.service=fleet \
      --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null \
      | grep "^${PROJECT_PREFIX}" | head -1 || true)"
    if [[ -z "${found}" ]]; then
      found="$(docker ps -a --filter label=com.docker.compose.service=fleet \
        --format '{{.CreatedAt}}|{{.Label "com.docker.compose.project"}}' 2>/dev/null \
        | grep "|${PROJECT_PREFIX}" | sort -r | head -1 | cut -d'|' -f2 || true)"
    fi
  fi
  echo "${found:-${PROJECT_PREFIX}}"
}

head_short() { git -C "${WS_DIR}" rev-parse --short=7 HEAD; }

site_image() { echo "${COBOT_IMAGE:-cobot-fleet:dev-$(head_short)}"; }

# 이 PC 에서 직접 띄운 관제·세션 (도커와 같은 도메인 100·포트 8080 을 다툰다)
local_blockers() {
  local out="" session pattern
  for session in "${TMUX_SESSIONS[@]}"; do
    has_tmux_session "${session}" && out+=" tmux:${session}"
  done
  for pattern in "${LAUNCH_PATTERNS[@]}"; do
    [[ -n "$(launch_pids "${pattern}")" ]] && out+=" launch:$(echo "${pattern}" | awk '{print $3}')"
  done
  echo "${out}"
}

health_line() {
  local body
  body="$(curl -s -m 2 "http://127.0.0.1:$1/api/health" 2>/dev/null || true)"
  [[ -z "${body}" ]] && { echo "응답 없음"; return; }
  python3 - "${body}" <<'PY'
import json
import sys
try:
    h = json.loads(sys.argv[1])
except ValueError:
    print('응답이 JSON 이 아님')
    sys.exit(0)
print('도메인 {} · 관제 노드 {} · 주문 처리기 {} · 주문 받기 {}{}'.format(
    h.get('domain_id'),
    '연결' if h.get('source_online') else '끊김',
    '연결' if h.get('controller_online') else '끊김',
    '켜짐' if h.get('commands_armed') else '꺼짐',
    ' · 보기 전용' if h.get('read_only') else ''))
PY
}

# ---------- 준비 ----------

cmd_setup() {
  local venv="${WS_DIR}/.venv"
  # 버전을 바꾸면 cobot_control_center/README.md '처음 설치' 도 같이 고친다.
  local packages=(
    fastapi==0.115.6
    uvicorn==0.34.0
    websockets==14.1  # uvicorn 의 WebSocket 지원
    httpx==0.28.1     # 시험(TestClient)용
    py_trees==2.2.3   # cobot_fleet_control 실행·시험용
  )
  if [[ -d "${venv}" ]]; then
    log "이미 있음: ${venv} (고정 버전만 확인)"
  else
    log "만드는 중: ${venv}"
    # rclpy 등 ROS 패키지를 그대로 쓰려고 시스템 site-packages 를 연다 (CLAUDE.md §5).
    python3 -m venv --system-site-packages "${venv}"
  fi
  touch "${venv}/COLCON_IGNORE"
  "${venv}/bin/pip" install "${packages[@]}"
  log "완료. 다음: bash scripts/cobot.sh build"
}

cmd_build() {
  local run_test=true
  [[ "${1:-}" == "--no-test" ]] && run_test=false
  [[ -d "${WS_DIR}/.venv" ]] || die ".venv 가 없음. 먼저: bash scripts/cobot.sh setup"
  set +u
  # shellcheck source=/dev/null
  source /opt/ros/jazzy/setup.bash
  # shellcheck source=/dev/null
  source "${WS_DIR}/.venv/bin/activate"
  set -u
  cd "${WS_DIR}"
  # .venv 를 켠 채 빌드해야 fleet_api_node 가 venv 파이썬(fastapi)을 쓴다.
  python -m colcon build --symlink-install \
    --packages-up-to cobot_bringup cobot_mock cobot_gazebo cobot_fleet_control
  if [[ "${run_test}" == true ]]; then
    python -m colcon test --packages-select cobot_control_center cobot_bringup cobot_mock \
      cobot_gazebo cobot_fleet_control
    # 이번에 시험한 패키지 결과만 본다 (build/ 의 다른 패키지 예전 결과는 섞지 않음).
    local pkg failed=false
    for pkg in cobot_control_center cobot_bringup cobot_mock cobot_gazebo cobot_fleet_control; do
      python -m colcon test-result --test-result-base "build/${pkg}" --verbose || failed=true
    done
    [[ "${failed}" == false ]] || die "시험 실패가 있음 (위 목록)"
  fi
  log "빌드 끝. 화면 파일(web/)은 다시 빌드하지 않아도 새로 고침으로 반영된다."
}

# ---------- 로봇 없이 ----------

cmd_mock() {
  local args=() arg
  for arg in "$@"; do
    if [[ "${arg}" == "--manual" ]]; then args+=("auto_patrol:=false"); else args+=("${arg}"); fi
  done
  load_env
  export ROS_DOMAIN_ID="${MOCK_DOMAIN}"
  export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
  log "가짜 핑키: 도메인 ${ROS_DOMAIN_ID}, 이 PC 안에서만 (실물 도메인이면 가짜 핑키가 시작을 거부한다)"
  log "화면: http://localhost:${PORT_MOCK}/service/ (매장 관리)  http://localhost:${PORT_MOCK}/ (엔지니어)"
  log "토픽 보기: export ROS_DOMAIN_ID=${ROS_DOMAIN_ID} ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST"
  exec ros2 launch cobot_mock mock_fleet.launch.xml "${args[@]}"
}

cmd_sim() {
  local args=() arg
  for arg in "$@"; do
    if [[ "${arg}" == "--headless" ]]; then args+=("headless:=true"); else args+=("${arg}"); fi
  done
  load_env
  # 도메인은 launch 가 고정한다 (관제 140 / 로봇 141~143, LOCALHOST). 실물 도메인이면 sim_guard 가 내린다.
  log "가제보 시뮬. 화면: http://localhost:${PORT_SIM}/service/"
  exec ros2 launch cobot_gazebo sim_fleet.launch.xml "${args[@]}"
}

# ---------- 보기 ----------

cmd_status() {
  local session pattern pids
  log "작업 폴더 $(git -C "${WS_DIR}" branch --show-current) @ $(head_short)"
  log "tmux 세션:"
  for session in "${TMUX_SESSIONS[@]}"; do
    has_tmux_session "${session}" && log "  ${session}"
  done
  log "이 PC 에서 띄운 launch:"
  for pattern in "${LAUNCH_PATTERNS[@]}"; do
    pids="$(launch_pids "${pattern}" | xargs)"
    [[ -n "${pids}" ]] && log "  ${pattern#ros2 launch } (pid ${pids})"
  done
  if have_docker; then
    log "도커 관제 (쓸 프로젝트: $(site_project), 지금 커밋 이미지: $(site_image)):"
    docker ps -a --format '{{.Label "com.docker.compose.project"}}|{{.Names}}|{{.Image}}|{{.Status}}' \
      2>/dev/null | awk -F'|' -v p="${PROJECT_PREFIX}" 'index($1, p) == 1 { printf "[cobot]   %s  %s  (%s)\n", $2, $3, $4 }'
  else
    log "도커: 없음 또는 권한 없음"
  fi
  log "화면 포트:"
  local port
  for port in "${PORT_SITE}" "${PORT_CUSTOMER}" 8180 "${PORT_MOCK}" "${PORT_SIM}" "${PORT_ANOMALY}"; do
    if port_in_use "${port}"; then
      if [[ "${port}" == "${PORT_CUSTOMER}" ]]; then
        log "  ${port} 열림 (고객 화면)"
      elif [[ "${port}" == "${PORT_ANOMALY}" ]]; then
        log "  ${port} 열림 (이상 감지 콘솔)"
      else
        log "  ${port} 열림 · $(health_line "${port}")"
      fi
    fi
  done

  log "로봇팔 서비스 (이 PC, systemd 사용자 서비스):"
  local units
  units="$(systemctl --user list-units 'cobot-arm-adapter@*' --type=service --all --no-legend \
    2>/dev/null | awk '{print $1, $3, $4}' || true)"
  if [[ -n "${units}" ]]; then
    echo "${units}" | sed "s/^/[${TAG}]   /"
  else
    log "  없음 (이 PC 에 팔이 없거나 서비스를 설치하지 않음)"
  fi

  # 이상 감지(cobot_anomaly_monitor, 강건한 님): 수동 어댑터가 주문의 확인 단계(도착·마커·적재·출구)에
  # 답한다. 꺼져 있으면 주문이 그 단계에서 멈춘다. 누가 띄웠든 이 PC 의 프로세스를 찾는다.
  log "이상 감지 (이 PC):"
  local name pids
  for name in monitor_node mqtt_zone_evidence; do
    pids="$({ pgrep -f "cobot_anomaly_monitor/lib/cobot_anomaly_monitor/${name}" 2>/dev/null || true; } | xargs)"
    if [[ -n "${pids}" ]]; then
      log "  ${name} 떠 있음 (pid ${pids})"
    elif [[ "${name}" == monitor_node ]]; then
      log "  ${name} 없음 → 주문이 확인 단계에서 멈춤. 담당(강건한 님) 실행법: cobot_anomaly_monitor anomaly_monitor.launch.xml"
    else
      log "  ${name} 없음 (비전 근거 수신. 지금은 판정 없이 자동 통과라 주문에는 영향 없음)"
    fi
  done

  # 관제가 떠 있으면 로봇·팔 전체(다른 PC 의 팔 포함)를 관제 API 로 본다.
  if port_in_use "${PORT_SITE}"; then
    log "현장 장비 (관제 ${PORT_SITE} 기준):"
    site_equipment "${PORT_SITE}"
  fi
}

# 관제 API 로 로봇·로봇팔 연결과 주문 준비 여부를 한 번에 본다 (읽기만).
site_equipment() {
  local base="http://127.0.0.1:$1" robots arms health
  robots="$(curl -s -m 3 "${base}/api/robots" 2>/dev/null || true)"
  arms="$(curl -s -m 3 "${base}/api/arms" 2>/dev/null || true)"
  health="$(curl -s -m 3 "${base}/api/health" 2>/dev/null || true)"
  local anomaly=false
  pgrep -f "cobot_anomaly_monitor/lib/cobot_anomaly_monitor/monitor_node" >/dev/null 2>&1 && anomaly=true
  python3 - "${robots}" "${arms}" "${health}" "${anomaly}" "${TAG}" <<'PY'
import json
import sys

def load(text, default):
    try:
        return json.loads(text)
    except ValueError:
        return default

robots = load(sys.argv[1], [])
arms = load(sys.argv[2], {}).get('arms', []) if sys.argv[2] else []
health = load(sys.argv[3], {})
anomaly = sys.argv[4] == 'true'
tag = sys.argv[5]
problems = []
for robot in robots if isinstance(robots, list) else []:
    rid = robot.get('robot_id')
    online = robot.get('online')
    battery = robot.get('battery_percent')
    hold = (health.get('holds') or {}).get(rid)
    text = '연결' if online else '끊김'
    print(f'[{tag}]   {rid}: {text} · {robot.get("state") or "상태 없음"}'
          f' · 배터리 {"—" if battery is None else round(battery)}%' + (f' · 정지 잠금 {hold}' if hold else ''))
    if not online:
        problems.append(f'{rid} 끊김')
    elif hold:
        problems.append(f'{rid} 정지 잠금')
for arm in arms:
    site = arm.get('site') or {}
    alarms = ', '.join(a.get('code', '') for a in arm.get('alarms') or [])
    print(f'[{tag}]   {arm.get("alias") or arm.get("arm_id")} ({site.get("station") or "-"}, '
          f'{site.get("host") or "-"}): {"연결" if arm.get("online") else "끊김"} · {arm.get("state")}'
          + (f' · 알람 {alarms}' if alarms else ''))
    if arm.get('state') not in ('READY', 'BUSY'):
        problems.append(f'{arm.get("alias") or arm.get("arm_id")} {arm.get("state")}')
if not health.get('controller_online'):
    problems.append('주문 처리기 끊김')
if not anomaly:
    problems.append('이상 감지 없음')
if not robots:
    problems.append('로봇 정보 없음')
armed = '켜짐' if health.get('commands_armed') else '꺼짐'
if problems:
    print(f'[{tag}] 주문 준비: 안 됨 ({", ".join(problems)}) · 주문 받기 {armed}')
else:
    print(f'[{tag}] 주문 준비: 됨 (로봇·로봇팔·주문 처리기·이상 감지 모두 정상) · 주문 받기 {armed}')
PY
}

# ---------- 현장 도커 ----------

site_compose_env() {
  # fleet_docker.sh 는 compose.yaml 의 name(cobot-fleet)을 쓴다. 환경변수가 그보다 앞선다.
  export COMPOSE_PROJECT_NAME="${PROJECT}"
  export COBOT_IMAGE="${IMAGE}"
}

site_wait_ready() {
  local _
  log "준비 기다리는 중 (최대 ${HEALTH_WAIT_SEC}초)"
  for _ in $(seq 1 "${HEALTH_WAIT_SEC}"); do
    if curl -s -m 2 "http://127.0.0.1:${PORT_SITE}/api/health" | grep -q '"controller_online": *true'; then
      log "준비 끝 · $(health_line "${PORT_SITE}")"
      log "매장 관리 http://<관제 PC>:${PORT_SITE}/service/   엔지니어 http://<관제 PC>:${PORT_SITE}/"
      log "주문 받기는 꺼진 채 시작한다. 현장 확인 뒤 매장 관리화면에서 '주문 받기'."
      return 0
    fi
    sleep 1
  done
  die "${HEALTH_WAIT_SEC}초 안에 주문 처리기가 응답하지 않음. 확인: bash scripts/cobot.sh site logs fleet"
}

cmd_site() {
  local action="${1:-}"
  [[ $# -gt 0 ]] && shift
  [[ -x "${FLEET_DOCKER}" || -f "${FLEET_DOCKER}" ]] || die "도커 도구가 없음: ${FLEET_DOCKER}"
  have_docker || die "docker 를 쓸 수 없음 (설치·권한 확인: ${DOCKER_DIR}/README.md)"
  parse_flags "$@"
  PROJECT="$(site_project)"
  IMAGE="$(site_image)"

  case "${action}" in
    logs)
      site_compose_env
      exec bash "${FLEET_DOCKER}" logs --tail 200 -f "${REST[@]}"
      ;;
    up|rebuild|down) ;;
    *) die "site 다음에 up / rebuild / down / logs" ;;
  esac
  [[ ${#REST[@]} -eq 0 ]] || die "모르는 인자: ${REST[*]}"

  log "프로젝트 ${PROJECT} (주문·재고 DB 볼륨 ${PROJECT}_fleet-data)"
  [[ -z "${COBOT_PROJECT:-}" ]] && log "  다른 프로젝트를 쓰려면 COBOT_PROJECT=<이름>"
  log "지금 컨테이너:"
  docker ps -a --filter "label=com.docker.compose.project=${PROJECT}" \
    --format '[cobot]   {{.Names}}  {{.Image}}  ({{.Status}})' 2>/dev/null || true

  if [[ "${action}" == down ]]; then
    if [[ "${EXECUTE}" != true ]]; then
      log "미리보기: 위 컨테이너를 내린다 (DB 볼륨은 남김). 실행: bash scripts/cobot.sh site down --execute"
      return 0
    fi
    confirm "도커 관제 ${PROJECT} 를 내릴까요? (현장 관제 화면·주문 처리가 멈춤)" || { log "취소"; return 0; }
    site_compose_env
    bash "${FLEET_DOCKER}" down
    log "내림. 다시 켜기: bash scripts/cobot.sh site up --execute"
    return 0
  fi

  local blockers dirty=false
  blockers="$(local_blockers)"
  log "띄울 이미지: ${IMAGE} (컨테이너 다섯 개 모두 이 이미지)"
  [[ -n "${blockers}" ]] && log "막는 것:${blockers} → 먼저 bash scripts/cobot.sh stop --execute --keep-docker"
  if [[ "${action}" == rebuild ]]; then
    if [[ -n "$(git -C "${WS_DIR}" status --porcelain -- src/cobot_control_center \
      src/cobot_patrol_interfaces src/cobot_interfaces src/cobot_gui)" ]]; then
      log "주의: 화면 패키지에 커밋 안 한 변경이 있음 (커밋한 뒤 빌드해야 이미지와 커밋이 맞는다)"
      dirty=true
    fi
    [[ -n "$(git -C "${WS_DIR}" status --porcelain -- src/cobot_navigation)" ]] \
      && log "참고: src/cobot_navigation 에 커밋 안 한 변경이 있음 (작업 폴더 그대로 들어감)"
  elif ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
    log "주의: ${IMAGE} 이미지가 없음 → bash scripts/cobot.sh site rebuild"
  fi

  if [[ "${EXECUTE}" != true ]]; then
    log "미리보기만 했습니다. 실행: bash scripts/cobot.sh site ${action} --execute"
    return 0
  fi
  [[ -z "${blockers}" ]] || die "막는 것이 떠 있어 멈춤:${blockers}"
  [[ "${dirty}" == false ]] || die "화면 패키지 변경을 먼저 커밋하세요"
  [[ "${action}" == rebuild ]] || docker image inspect "${IMAGE}" >/dev/null 2>&1 \
    || die "${IMAGE} 이미지가 없음. 먼저: bash scripts/cobot.sh site rebuild --execute"
  confirm "도메인 ${REAL_DOMAIN}(실물)에 도커 관제 ${PROJECT} 를 ${IMAGE} 로 띄울까요?" \
    || { log "취소"; return 0; }

  site_compose_env
  if [[ "${action}" == rebuild ]]; then
    log "빌드 (몇 분 걸림)"
    # fleet_docker.sh 는 관제 화면을 versions.env 의 고정 커밋에서 꺼내므로 지금 커밋을 넘긴다.
    CONTROL_CENTER_REVISION="$(git -C "${WS_DIR}" rev-parse HEAD)" bash "${FLEET_DOCKER}" build
    log "스모크 (격리 네트워크, 도메인 77)"
    bash "${FLEET_DOCKER}" smoke || die "스모크 실패: 띄우지 않음"
  fi
  log "띄우기"
  bash "${FLEET_DOCKER}" up
  site_wait_ready
}

# ---------- 실물 보기만 ----------

cmd_view() {
  parse_flags "$@"
  local args=("${REST[@]}") arg has_controller=false blockers
  for arg in "${args[@]}"; do
    [[ "${arg}" == controller:=* ]] && has_controller=true
  done
  # bringup 기본값은 controller:=fleet 이라 보기 전용이면 반드시 넘긴다.
  [[ "${has_controller}" == true ]] || args+=("controller:=none")

  blockers="$(local_blockers)"
  [[ -n "$(running_containers)" ]] && blockers+=" 도커:$(running_containers | xargs)"
  log "실물 도메인 ${REAL_DOMAIN} 에서 bringup 을 띄운다 (브릿지·zone_manager·관제 화면 ${PORT_SITE}). 인자: ${args[*]}"
  [[ -n "${blockers}" ]] && log "막는 것:${blockers} (같은 도메인·포트) → 먼저 bash scripts/cobot.sh stop --execute"
  if [[ "${EXECUTE}" != true ]]; then
    log "미리보기만 했습니다. 실행: bash scripts/cobot.sh view --execute"
    return 0
  fi
  [[ -z "${blockers}" ]] || die "막는 것이 떠 있어 멈춤:${blockers}"
  confirm "계속할까요?" || { log "취소"; return 0; }
  load_env
  export ROS_DOMAIN_ID="${REAL_DOMAIN}"
  unset ROS_AUTOMATIC_DISCOVERY_RANGE ROS_LOCALHOST_ONLY
  exec ros2 launch cobot_bringup bringup.launch.xml "${args[@]}"
}

# ---------- 끄기 ----------

cmd_stop() {
  parse_flags "$@"
  local docker_mode=stop arg
  for arg in "${REST[@]}"; do
    case "${arg}" in
      --down) docker_mode=down ;;
      --keep-docker) docker_mode=keep ;;
      *) die "모르는 인자: ${arg} (--execute, --yes, --down, --keep-docker)" ;;
    esac
  done

  local found=false session pattern pids containers
  log "지금 떠 있는 것:"
  for session in "${TMUX_SESSIONS[@]}"; do
    if has_tmux_session "${session}"; then
      log "  tmux 세션 ${session} (끄면 로봇 쪽 SSH 프로세스도 정리됨)"
      found=true
    fi
  done
  for pattern in "${LAUNCH_PATTERNS[@]}"; do
    pids="$(launch_pids "${pattern}" | xargs)"
    if [[ -n "${pids}" ]]; then
      log "  launch ${pattern#ros2 launch } (pid ${pids})"
      found=true
    fi
  done
  containers="$(running_containers | xargs)"
  if [[ -n "${containers}" ]]; then
    case "${docker_mode}" in
      stop) log "  도커 ${containers} → docker stop (다시: docker start 또는 site up)"; found=true ;;
      down) log "  도커 ${containers} → 프로젝트 down (DB 볼륨은 남김)"; found=true ;;
      keep) log "  도커 ${containers} → 그대로 둠 (--keep-docker)" ;;
    esac
  fi
  [[ "${found}" == true ]] || { log "  끌 것 없음"; return 0; }

  if [[ "${EXECUTE}" != true ]]; then
    log "미리보기만 했습니다. 끄기: bash scripts/cobot.sh stop --execute"
    return 0
  fi
  confirm "위 목록을 끌까요? (로봇은 움직이지 않고 관제만 꺼짐)" || { log "취소"; return 0; }

  local stopped=false
  for session in "${TMUX_SESSIONS[@]}"; do
    if has_tmux_session "${session}"; then
      log "tmux 세션 ${session} 끄기"
      tmux kill-session -t "${session}"
      stopped=true
    fi
  done
  # 세션 안 launch·SSH 가 정리될 시간을 준다
  [[ "${stopped}" == true ]] && sleep 3

  local _
  for pattern in "${LAUNCH_PATTERNS[@]}"; do
    pids="$(launch_pids "${pattern}" | xargs)"
    [[ -z "${pids}" ]] && continue
    log "launch ${pattern#ros2 launch } 끄기 (Ctrl+C 와 같은 SIGINT, pid ${pids})"
    # shellcheck disable=SC2086
    kill -INT ${pids} 2>/dev/null || true
    for _ in $(seq 1 10); do
      sleep 1
      pids="$(launch_pids "${pattern}" | xargs)"
      [[ -z "${pids}" ]] && break
    done
    if [[ -n "${pids}" ]]; then
      log "  10초 안에 안 꺼져서 SIGTERM (pid ${pids})"
      # shellcheck disable=SC2086
      kill -TERM ${pids} 2>/dev/null || true
      sleep 2
    fi
  done

  containers="$(running_containers | xargs)"
  if [[ -n "${containers}" ]]; then
    case "${docker_mode}" in
      stop)
        log "도커 멈추기: ${containers}"
        # shellcheck disable=SC2086
        docker stop ${containers} >/dev/null
        ;;
      down)
        local project
        for project in $(docker ps --format '{{.Label "com.docker.compose.project"}}' \
          | grep "^${PROJECT_PREFIX}" | sort -u); do
          log "도커 프로젝트 ${project} 내리기 (DB 볼륨은 남김)"
          COMPOSE_PROJECT_NAME="${project}" bash "${FLEET_DOCKER}" down
        done
        ;;
      keep) ;;
    esac
  fi

  sleep 1
  local ports
  ports="$(ss -ltn 2>/dev/null | grep -E ":(${PORT_SITE}|8180|${PORT_MOCK}|${PORT_SIM})\b" || true)"
  if [[ -z "${ports}" ]]; then
    log "정리 끝: ${PORT_SITE}·8180·${PORT_MOCK}·${PORT_SIM} 포트가 비었음"
  else
    log "아직 열린 포트 (자동으로 더 끄지 않음, 확인: bash scripts/cobot.sh status):"
    echo "${ports}" | sed "s/^/[${TAG}]   /"
  fi
}

# ---------- 입구 ----------

main() {
  local command="${1:-help}"
  [[ $# -gt 0 ]] && shift
  case "${command}" in
    help|-h|--help) usage ;;
    setup) cmd_setup ;;
    build) cmd_build "$@" ;;
    mock) cmd_mock "$@" ;;
    sim) cmd_sim "$@" ;;
    status) cmd_status ;;
    site) cmd_site "$@" ;;
    view) cmd_view "$@" ;;
    stop) cmd_stop "$@" ;;
    *) usage >&2; die "모르는 명령: ${command}" ;;
  esac
}

main "$@"
