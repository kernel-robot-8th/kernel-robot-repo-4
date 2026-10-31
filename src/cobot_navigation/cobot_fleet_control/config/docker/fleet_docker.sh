#!/usr/bin/env bash
# 관제 Docker 실행 진입점. build/config는 로봇 통신 프로세스를 실행하지 않는다.
set -euo pipefail
config_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
nav_root="$(cd -- "${config_dir}/../../.." && pwd)"

usage() {
  cat <<'HELP'
사용법: bash cobot_fleet_control/config/docker/fleet_docker.sh <명령> [Compose 옵션]
  build         고정 의존성과 현재 코드를 이미지로 빌드
  config        해석된 Compose 구성 확인
  up            기존 브로커를 사용해 관제·구역 매니저·브릿지 실행
  up-local      개발용 로컬 브로커까지 함께 실행
  down          컨테이너 중지·제거, DB 볼륨은 보존
  logs          서비스 로그 확인
  versions      실행 중 fleet의 이미지 내부 버전 기록 확인
  export-bt ID  명령별 BT 기록을 표준 출력 JSON으로 내보내기
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
    revision="$(git -C "$nav_root" rev-parse HEAD 2>/dev/null || printf unknown)"
    dirty=false
    if [[ -n "$(git -C "$nav_root" status --porcelain -- . 2>/dev/null)" ]]; then dirty=true; fi
    export COBOT_SOURCE_REVISION="$revision" COBOT_SOURCE_DIRTY="$dirty"
    "${compose[@]}" build "$@" fleet
    ;;
  config) "${compose[@]}" config "$@" ;;
  up) "${compose[@]}" up -d "$@" bridge zone-manager fleet ;;
  up-local) "${compose[@]}" --profile local-broker up -d "$@" broker bridge zone-manager fleet ;;
  down) "${compose[@]}" --profile local-broker down "$@" ;;
  logs) "${compose[@]}" --profile local-broker logs "$@" ;;
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
  *) usage >&2; exit 2 ;;
esac
