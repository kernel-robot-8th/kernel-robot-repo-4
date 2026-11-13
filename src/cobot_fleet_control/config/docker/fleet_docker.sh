#!/usr/bin/env bash
# 관제 Docker 실행 진입점. build/config는 로봇 통신 프로세스를 실행하지 않는다.
set -euo pipefail
config_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# build context 는 src/ 다 (이 패키지와 주행·웹 패키지가 모두 그 아래에 있다).
src_root="$(cd -- "${config_dir}/../../.." && pwd)"

usage() {
  cat <<'HELP'
사용법: bash cobot_fleet_control/config/docker/fleet_docker.sh <명령> [Compose 옵션]
  build         고정 의존성과 현재 코드를 이미지로 빌드
  config        해석된 Compose 구성 확인
  up            웹·중앙 제어기·구역 매니저·브릿지 실행
  check         이미지의 의존성·웹 기동 계획 확인 (ROS 노드·웹 서버 실행 안 함)
  smoke         격리 컨테이너에서 웹·중앙 실행기·HTTP·WebSocket 확인 후 종료
  ps            컨테이너와 웹 상태 확인
  down          컨테이너 중지·제거, DB 볼륨은 보존
  logs          서비스 로그 확인
  versions      실행 중 fleet의 이미지 내부 버전 기록 확인
  export-bt ID  명령별 BT 기록을 표준 출력 JSON으로 내보내기
  view-bt      실행 중인 fleet의 원장으로 실시간 BT 뷰어 실행 (127.0.0.1:8091)
배포 이미지 선택: COBOT_IMAGE 환경변수. 이 도구는 호스트 패키지를 설치하지 않습니다.
HELP
}
if [[ $# -eq 0 || "$1" == help || "$1" == --help ]]; then usage; exit 0; fi
if ! command -v docker >/dev/null 2>&1; then
  echo 'Docker 명령이 없습니다. Docker Engine과 Compose 플러그인을 먼저 준비하세요.' >&2
  exit 127
fi
if ! docker compose version >/dev/null 2>&1; then
  echo 'Docker Compose 플러그인이 필요합니다.' >&2
  exit 127
fi
compose=(docker compose --env-file "${config_dir}/versions.env" -f "${config_dir}/compose.yaml")
operation="$1"
shift
case "$operation" in
  build)
    repo_root="$(cd -- "${src_root}/.." && pwd)"
    # sudo 기동도 사용자가 지정한 이 저장소 하나만 신뢰한다.
    git_repo=(git -c "safe.directory=${repo_root}" -C "$repo_root")
    # 이미지에 들어가는 폴더. 고친 채 커밋하지 않은 것이 있으면 dirty 로 남긴다.
    image_sources=(src/cobot_fleet_control src/cobot_control_center src/cobot_patrol_interfaces
                   src/cobot_navigation/cobot_zone_traffic_control
                   src/cobot_navigation/cobot_domain_bridge
                   src/cobot_navigation/cobot_pinky_patrol/config
                   src/cobot_navigation/map_view_pc/maps)
    revision="$("${git_repo[@]}" rev-parse HEAD 2>/dev/null || printf unknown)"
    dirty=false
    if [[ -n "$("${git_repo[@]}" status --porcelain -- "${image_sources[@]}" 2>/dev/null)" ]]; then
      dirty=true
    fi
    export COBOT_SOURCE_REVISION="$revision" COBOT_SOURCE_DIRTY="$dirty"
    "${compose[@]}" build "$@" fleet
    ;;
  config) "${compose[@]}" config "$@" ;;
  up) "${compose[@]}" up -d "$@" bridge zone-manager fleet web ;;
  check)
    if [[ $# -ne 0 ]]; then usage >&2; exit 2; fi
    "${compose[@]}" run --rm --no-deps web /opt/cobot/entrypoint.sh bash -c \
      'python -c "import py_trees, fastapi, uvicorn; import cobot_control_center.fleet_api_node; import cobot_control_center.fleet_status_node" && ros2 run cobot_fleet_control control_center_web --navigation-root /opt/cobot_ws/src --mode preview --fleet existing'
    ;;
  smoke)
    if [[ $# -ne 0 ]]; then usage >&2; exit 2; fi
    image_ref="${COBOT_IMAGE:-$(sed -n 's/^COBOT_IMAGE=//p' "${config_dir}/versions.env")}"
    docker run --rm --init --network none --cap-drop ALL \
      --security-opt no-new-privileges:true \
      --env ROS_DOMAIN_ID=77 --env ROS_LOCALHOST_ONLY=1 \
      --env ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
      --env RMW_IMPLEMENTATION="${COBOT_RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}" \
      "$image_ref" python /opt/cobot/smoke_check.py
    ;;
  ps) "${compose[@]}" ps "$@" ;;
  down) "${compose[@]}" down "$@" ;;
  logs) "${compose[@]}" logs "$@" ;;
  versions)
    "${compose[@]}" images fleet
    "${compose[@]}" exec -T fleet bash -c \
      'cat /opt/cobot/build-versions/source-revision.txt /opt/cobot/build-versions/source-dirty.txt /opt/cobot/build-versions/python.txt /opt/cobot/build-versions/dpkg.tsv'
    ;;
  export-bt)
    if [[ $# -ne 1 || ! "$1" =~ ^[A-Za-z0-9_-]{1,80}$ ]]; then
      echo 'export-bt에는 명령 ID 1개가 필요합니다.' >&2; exit 2
    fi
    "${compose[@]}" exec -T fleet /opt/cobot/entrypoint.sh bash -c \
      'ros2 run cobot_fleet_control fleet_bt_trace --db /var/lib/cobot/fleet_control.sqlite3 --command-id "$1" --output /tmp/bt_trace.json && cat /tmp/bt_trace.json' \
      bash "$1"
    ;;
  view-bt)
    if [[ $# -ne 0 ]]; then usage >&2; exit 2; fi
    "${compose[@]}" exec -T fleet /opt/cobot/entrypoint.sh \
      ros2 run cobot_fleet_control fleet_bt_viewer \
      --db /var/lib/cobot/fleet_control.sqlite3
    ;;
  *) usage >&2; exit 2 ;;
esac
