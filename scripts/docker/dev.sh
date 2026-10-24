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

# 팀 개발·시험용 도커 도우미 (Linux · macOS · Windows 의 WSL).
#   도움말: bash scripts/docker/dev.sh help
#   설명서: docs/dev_docker_guide.md
#
# 이 스크립트가 지키는 것
#   - 컨테이너는 기본으로 네트워크 없이 돈다 (--network none). --online 일 때만 bridge.
#   - --privileged, --network host, --device 를 쓰지 않는다. 실물 장치를 열지 않는다.
#   - 레포 루트를 /ws 로 마운트한다. 빌드 산출물(build/ install/ log/)은 레포에 남고
#     .gitignore 대상이다.
#   - 컨테이너 안에서도 같은 파일을 '__inside' 로 다시 부른다 (규칙을 한 곳에 둔다).
# macOS 기본 bash 3.2 에서도 돌게 쓴다 (연관 배열·mapfile 을 쓰지 않는다).

set -euo pipefail

# 이미지 태그 규칙: cobot-dev:jazzy-<YYYYMMDD>.
# Dockerfile 을 고치는 PR 은 IMAGE_VERSION 을 그날 날짜로 바꾼다.
IMAGE_VERSION="20261022"
IMAGE="cobot-dev:jazzy-${IMAGE_VERSION}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
DOCKERFILE="${SCRIPT_DIR}/Dockerfile"
CONTAINER_WS="/ws"
GUIDE="docs/dev_docker_guide.md"
ROS_SETUP="/opt/ros/jazzy/setup.bash"

# shell·build·test 의 네트워크. --online 을 주면 bridge 로 바꾼다.
NETWORK="none"
# 이미지 UID 와 지금 사용자 UID 가 다르면 1 (그때는 --user 로 맞춰 돌린다).
USER_OVERRIDE=0

info() {
  printf '[dev.sh] %s\n' "$*" >&2
}

warn() {
  printf '[dev.sh] 주의: %s\n' "$*" >&2
}

die() {
  printf '[dev.sh] 오류: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<EOF
사용법: bash scripts/docker/dev.sh <하위 명령> [옵션]

하위 명령
  build-image [docker build 옵션]  이미지를 만든다 (처음 한 번, 인터넷 필요)
  shell                            컨테이너 안 셸에 들어간다 (나가기: exit)
  build [colcon 옵션]              colcon build --symlink-install
  test  [colcon 옵션]              빌드 -> colcon test -> colcon test-result --verbose
  clean [--image] [--yes]          build/ install/ log/ 를 지운다 (--image: 이미지도)
  save  [폴더]                     이미지를 tar 와 .sha256 로 저장한다 (기본: ~/cobot_offline_bundle)
  load  <tar 파일>                 sha256 을 확인한 뒤 이미지를 불러온다
  help                             이 도움말

shell·build·test 옵션
  --online       컨테이너에 네트워크를 준다 (기본: 네트워크 없음)
test 옵션
  --no-build     빌드를 건너뛰고 시험만 한다
  --allow-skip   skip 된 시험이 있어도 통과로 친다 (기본: skip 이 있으면 실패)

예
  bash scripts/docker/dev.sh build-image
  bash scripts/docker/dev.sh test
  bash scripts/docker/dev.sh test --packages-select cobot_gui

이미지: ${IMAGE}
설명서: ${GUIDE}
EOF
}

is_macos() {
  [ "$(uname -s)" = "Darwin" ]
}

# macOS 의 Docker Desktop 은 마운트한 파일의 주인을 알아서 맞춘다. 그래서 기본값을 쓴다.
# sudo 로 실행했으면 원래 사용자(SUDO_UID)에 맞춘다.
host_uid() {
  if is_macos; then
    printf '1000\n'
  else
    printf '%s\n' "${SUDO_UID:-$(id -u)}"
  fi
}

host_gid() {
  if is_macos; then
    printf '1000\n'
  else
    printf '%s\n' "${SUDO_GID:-$(id -g)}"
  fi
}

# sudo 로 실행했는가 (지금 root 이고 SUDO_UID 가 있다).
run_by_sudo() {
  [ "$(id -u)" = 0 ] && [ -n "${SUDO_UID:-}" ]
}

# save 의 기본 폴더를 둘 홈. Ubuntu 의 sudo 는 HOME 을 /root 로 바꾸므로
# sudo 로 실행했으면 원래 사용자(SUDO_USER)의 홈을 쓴다.
host_home() {
  local home=""
  if run_by_sudo && [ -n "${SUDO_USER:-}" ] && command -v getent > /dev/null 2>&1; then
    home="$(getent passwd "${SUDO_USER}" | cut -d: -f6)" || home=""
  fi
  printf '%s\n' "${home:-${HOME}}"
}

sha256_of() {
  if command -v sha256sum > /dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum > /dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    die "sha256sum 또는 shasum 명령이 없다."
  fi
}

# 레포 위치·줄끝처럼 도커와 상관없이 먼저 볼 수 있는 것을 확인한다.
preflight() {
  case "$(uname -s)" in
    MINGW* | MSYS* | CYGWIN*)
      # Git Bash 는 경로를 바꿔 넘겨서 마운트가 엉뚱한 곳으로 간다.
      die "Git Bash 에서는 쓰지 않는다. WSL 의 Ubuntu 터미널에서 쓴다 (${GUIDE} 2.2)."
      ;;
  esac
  if [ ! -d "${REPO_ROOT}/src" ] || [ ! -f "${REPO_ROOT}/CLAUDE.md" ]; then
    die "레포 루트를 찾지 못했다 (${REPO_ROOT}). 이 파일은 레포의 scripts/docker/ 에 있어야 한다."
  fi
  if [ -n "$(tr -cd '\r' < "${DOCKERFILE}")" ]; then
    die "Dockerfile 의 줄끝이 CRLF 다. ${GUIDE} '5. 자주 나는 오류' 의 CRLF 항목을 본다."
  fi
  if [ -r /proc/version ] && grep -qi microsoft /proc/version; then
    case "${REPO_ROOT}" in
      /mnt/[a-zA-Z]/*)
        warn "레포가 Windows 드라이브(${REPO_ROOT})에 있다. 느리고 줄끝 문제가 난다. WSL 홈(~)에 다시 clone 하기를 권한다 (${GUIDE} 2.2)."
        ;;
    esac
  fi
}

check_user() {
  if [ "$(host_uid)" = "0" ] || [ "$(host_gid)" = "0" ]; then
    die "root 사용자로는 쓰지 않는다. 일반 사용자로 다시 실행한다 (WSL 이 root 로 열리면 ${GUIDE} 5장)."
  fi
}

require_docker() {
  if ! command -v docker > /dev/null 2>&1; then
    die "docker 명령이 없다. 설치 방법은 ${GUIDE} '2. 설치' 를 본다."
  fi
  local err
  if ! err="$(docker info 2>&1 > /dev/null)"; then
    case "${err}" in
      *"permission denied"* | *"Permission denied"*)
        die "docker 에 접근할 권한이 없다. ${GUIDE} '5. 자주 나는 오류' 의 '권한 거부' 를 본다."
        ;;
      *)
        printf '[dev.sh] docker 메시지: %s\n' "${err%%$'\n'*}" >&2
        die "docker 데몬에 연결하지 못했다. Docker Desktop 을 켰는지(Windows·macOS), 'sudo systemctl start docker' 를 했는지(Ubuntu) 본다."
        ;;
    esac
  fi
}

image_exists() {
  docker image inspect "${IMAGE}" > /dev/null 2>&1
}

label_of() {
  docker image inspect --format "{{ index .Config.Labels \"$1\" }}" "${IMAGE}"
}

# shell·build·test 앞에서 부른다. 이미지가 있는지, 낡지 않았는지, UID 가 맞는지 본다.
prepare_run() {
  require_docker
  check_user
  if ! image_exists; then
    die "이미지 ${IMAGE} 가 없다. 먼저 'bash scripts/docker/dev.sh build-image'(인터넷 필요) 또는 'load'(오프라인) 를 한다."
  fi
  if ! is_macos; then
    local img_uid img_gid
    img_uid="$(label_of cobot.dev.uid)"
    img_gid="$(label_of cobot.dev.gid)"
    if [ "${img_uid}" != "$(host_uid)" ] || [ "${img_gid}" != "$(host_gid)" ]; then
      warn "이미지 사용자(${img_uid}:${img_gid})와 지금 사용자($(host_uid):$(host_gid))가 다르다. 이번에는 --user 로 맞춰 돌린다 (셸 이름이 'I have no name!' 으로 보일 수 있다). 인터넷이 되면 build-image 로 다시 만들기를 권한다."
      USER_OVERRIDE=1
    fi
  fi
  local img_sha cur_sha
  img_sha="$(label_of cobot.dev.dockerfile_sha256)"
  cur_sha="$(sha256_of "${DOCKERFILE}")"
  if [ "${img_sha}" != "${cur_sha}" ]; then
    warn "이미지를 만든 뒤 Dockerfile 이 바뀌었다. 'bash scripts/docker/dev.sh build-image' 로 다시 만들기를 권한다."
  fi
}

# 사용: run_container <셸이면 1, 아니면 0> <컨테이너 안 명령...>
run_container() {
  local interactive="$1"
  shift
  local args=(run --rm --init
    --network "${NETWORK}"
    --cap-drop ALL
    --security-opt no-new-privileges
    --volume "${REPO_ROOT}:${CONTAINER_WS}"
    --workdir "${CONTAINER_WS}")
  if [ -t 0 ] && [ -t 1 ]; then
    # 터미널이면 -it. Ctrl+C 가 컨테이너 안 명령까지 간다.
    args+=(--interactive --tty)
  elif [ "${interactive}" = 1 ]; then
    die "shell 은 터미널에서만 쓴다."
  fi
  if [ "${USER_OVERRIDE}" = 1 ]; then
    args+=(--user "$(host_uid):$(host_gid)" --env HOME=/tmp)
  fi
  docker "${args[@]}" "${IMAGE}" "$@"
}

cmd_build_image() {
  require_docker
  check_user
  local sha var
  sha="$(sha256_of "${DOCKERFILE}")"
  local args=(build --pull
    --file "${DOCKERFILE}"
    --tag "${IMAGE}"
    --build-arg "USER_UID=$(host_uid)"
    --build-arg "USER_GID=$(host_gid)"
    --build-arg "DOCKERFILE_SHA256=${sha}")
  # 프록시가 있는 곳이면 값을 그대로 넘긴다 (값은 화면에 찍지 않는다).
  for var in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
    if printenv "${var}" > /dev/null 2>&1; then
      args+=(--build-arg "${var}")
    fi
  done
  info "이미지를 만든다: ${IMAGE} (인터넷이 필요하고, 처음에는 몇 분 걸린다)"
  # 빌드 컨텍스트는 scripts/docker 폴더뿐이다. 레포의 다른 파일은 이미지에 들어가지 않는다.
  docker "${args[@]}" "$@" "${SCRIPT_DIR}"
  info "완료. 다음: bash scripts/docker/dev.sh test"
}

cmd_shell() {
  local arg
  for arg in "$@"; do
    case "${arg}" in
      --online) NETWORK="bridge" ;;
      *) die "shell 이 모르는 옵션: ${arg}" ;;
    esac
  done
  prepare_run
  info "컨테이너 셸 (네트워크: ${NETWORK}). /ws = 레포 루트. 나가기: exit"
  run_container 1 bash
}

cmd_build() {
  local rest=() arg
  for arg in "$@"; do
    case "${arg}" in
      --online) NETWORK="bridge" ;;
      *) rest+=("${arg}") ;;
    esac
  done
  prepare_run
  info "colcon build (네트워크: ${NETWORK})"
  run_container 0 bash "${CONTAINER_WS}/scripts/docker/dev.sh" __inside build \
    ${rest[@]+"${rest[@]}"}
}

cmd_test() {
  local rest=() arg do_build=1 allow_skip=0
  for arg in "$@"; do
    case "${arg}" in
      --online) NETWORK="bridge" ;;
      --no-build) do_build=0 ;;
      --allow-skip) allow_skip=1 ;;
      *) rest+=("${arg}") ;;
    esac
  done
  prepare_run
  info "빌드·시험 (네트워크: ${NETWORK})"
  run_container 0 bash "${CONTAINER_WS}/scripts/docker/dev.sh" __inside test \
    "${do_build}" "${allow_skip}" ${rest[@]+"${rest[@]}"}
}

confirm() {
  local answer
  if [ ! -t 0 ]; then
    die "확인을 받을 수 없다 (터미널이 아니다). 정말 지우려면 --yes 를 붙인다."
  fi
  read -r -p "[dev.sh] 정말 지울까요? [y/N] " answer
  case "${answer}" in
    y | Y | yes | YES) return 0 ;;
    *) return 1 ;;
  esac
}

cmd_clean() {
  local remove_image=0 assume_yes=0 arg dir found=""
  for arg in "$@"; do
    case "${arg}" in
      --image) remove_image=1 ;;
      --yes) assume_yes=1 ;;
      *) die "clean 이 모르는 옵션: ${arg}" ;;
    esac
  done
  for dir in build install log; do
    if [ -e "${REPO_ROOT}/${dir}" ]; then
      found="${found} ${dir}/"
    fi
  done
  if [ -z "${found}" ] && [ "${remove_image}" = 0 ]; then
    info "지울 것이 없다 (build/ install/ log/ 없음)."
    return 0
  fi
  if [ -n "${found}" ]; then
    info "지울 폴더 (레포 ${REPO_ROOT} 안):${found}"
  fi
  if [ "${remove_image}" = 1 ]; then
    info "지울 이미지: ${IMAGE}"
  fi
  if [ "${assume_yes}" != 1 ] && ! confirm; then
    info "취소했다. 아무것도 지우지 않았다."
    return 0
  fi
  for dir in build install log; do
    if [ -e "${REPO_ROOT}/${dir}" ]; then
      if ! rm -rf -- "${REPO_ROOT:?}/${dir}"; then
        die "${dir}/ 를 지우지 못했다. 파일 주인이 다를 수 있다 (${GUIDE} 5장 '파일 주인이 root')."
      fi
    fi
  done
  if [ "${remove_image}" = 1 ]; then
    require_docker
    if image_exists; then
      docker image rm "${IMAGE}"
    else
      info "이미지 ${IMAGE} 는 이미 없다."
    fi
  fi
  info "정리 완료."
}

cmd_save() {
  if [ $# -gt 1 ]; then
    die "사용법: bash scripts/docker/dev.sh save [폴더]"
  fi
  local out_dir="${1:-$(host_home)/cobot_offline_bundle}"
  require_docker
  if ! image_exists; then
    die "저장할 이미지 ${IMAGE} 가 없다. 먼저 build-image 를 한다."
  fi
  local created=0
  if [ ! -d "${out_dir}" ]; then
    mkdir -p "${out_dir}"
    created=1
  fi
  local out_abs
  out_abs="$(cd "${out_dir}" && pwd -P)"
  case "${out_abs}/" in
    "${REPO_ROOT}/"*)
      if [ "${created}" = 1 ]; then
        rmdir "${out_abs}" 2> /dev/null || true
      fi
      die "레포 안(${out_abs})에는 저장하지 않는다. 큰 파일은 커밋하지 않는다. 레포 밖 폴더를 준다."
      ;;
  esac
  local arch name tar_path sum
  arch="$(docker image inspect --format '{{.Architecture}}' "${IMAGE}")"
  name="$(printf '%s' "${IMAGE}" | tr ':/' '__')_${arch}.tar"
  tar_path="${out_abs}/${name}"
  if [ -e "${tar_path}" ] || [ -e "${tar_path}.sha256" ]; then
    die "${tar_path} 가 이미 있다. 지우거나 다른 폴더를 준다."
  fi
  info "저장 중: ${tar_path} (몇 분 걸릴 수 있다)"
  # 중간에 끊기면 반쪽 파일이 남지 않게 .part 로 쓰고 끝나면 이름을 바꾼다.
  docker save --output "${tar_path}.part" "${IMAGE}"
  mv "${tar_path}.part" "${tar_path}"
  sum="$(sha256_of "${tar_path}")"
  printf '%s  %s\n' "${sum}" "${name}" > "${tar_path}.sha256"
  if run_by_sudo; then
    # sudo 로 만든 파일은 root 것이 된다. 원래 사용자가 옮기고 지울 수 있게 주인을 돌려준다.
    local owner="${SUDO_UID}${SUDO_GID:+:${SUDO_GID}}"
    chown "${owner}" "${tar_path}" "${tar_path}.sha256"
    if [ "${created}" = 1 ]; then
      chown "${owner}" "${out_abs}"
    fi
    info "sudo 로 실행해서 파일 주인을 원래 사용자(${owner})로 바꿨다."
  fi
  info "완료. 아래 두 파일을 함께 옮긴다 (CPU 종류: ${arch}):"
  info "  ${tar_path}"
  info "  ${tar_path}.sha256"
}

cmd_load() {
  if [ $# -ne 1 ]; then
    die "사용법: bash scripts/docker/dev.sh load <tar 파일>"
  fi
  local tar_path="$1"
  local sum_path="${tar_path}.sha256"
  if [ ! -f "${tar_path}" ]; then
    die "tar 파일이 없다: ${tar_path}"
  fi
  if [ ! -f "${sum_path}" ]; then
    die "sha256 파일이 없다: ${sum_path} (tar 와 함께 옮겨야 한다). 확인 없이는 불러오지 않는다."
  fi
  local expected listed actual
  expected="$(awk 'NR == 1 {print $1}' "${sum_path}")"
  listed="$(awk 'NR == 1 {print $2}' "${sum_path}")"
  listed="${listed#\*}"
  if ! [[ "${expected}" =~ ^[0-9a-f]{64}$ ]]; then
    die "sha256 파일 형식이 틀렸다: ${sum_path}"
  fi
  if [ "${listed}" != "$(basename "${tar_path}")" ]; then
    die "sha256 파일이 다른 파일(${listed})을 가리킨다. 짝이 맞는 두 파일을 쓴다."
  fi
  require_docker
  info "sha256 확인 중 (몇 분 걸릴 수 있다)"
  actual="$(sha256_of "${tar_path}")"
  if [ "${actual}" != "${expected}" ]; then
    die "sha256 이 맞지 않는다. 파일이 깨졌거나 바뀌었다. 다시 복사한다."
  fi
  docker load --input "${tar_path}"
  if ! image_exists; then
    die "불러온 이미지에 ${IMAGE} 태그가 없다. 이 레포의 dev.sh 와 버전이 다른 번들이다."
  fi
  local img_arch host_arch
  img_arch="$(docker image inspect --format '{{.Architecture}}' "${IMAGE}")"
  host_arch="$(docker version --format '{{.Server.Arch}}' 2> /dev/null || true)"
  if [ -n "${host_arch}" ] && [ "${img_arch}" != "${host_arch}" ]; then
    warn "이미지 CPU 종류(${img_arch})가 이 PC(${host_arch})와 다르다. 느리거나 'exec format error' 가 날 수 있다."
  fi
  info "완료. 다음: bash scripts/docker/dev.sh test"
}

# ---- 아래는 컨테이너 안에서만 돈다 (dev.sh __inside ...) ----

source_ros() {
  # ROS setup.bash 는 정의 안 된 변수를 읽어서 set -u 를 잠시 끈다.
  set +u
  # shellcheck disable=SC1090
  source "${ROS_SETUP}"
  set -u
}

# colcon test-result 출력의 'Summary:' 줄로 통과를 판정한다.
# 사용: judge_test_result <출력> <colcon test 반환값> <test-result 반환값> <allow_skip 0/1>
judge_test_result() {
  local result="$1" test_rc="$2" result_rc="$3" allow_skip="$4"
  local summary tests skipped
  summary="$(printf '%s\n' "${result}" | sed -n '/^Summary: /p' | tail -n 1)"
  tests="$(printf '%s\n' "${summary}" | sed -n 's/^Summary: \([0-9][0-9]*\) tests*,.*/\1/p')"
  skipped="$(printf '%s\n' "${summary}" | sed -n 's/.* \([0-9][0-9]*\) skipped.*/\1/p')"
  if [ "${test_rc}" != 0 ] || [ "${result_rc}" != 0 ]; then
    die "시험 실패 (colcon test=${test_rc}, colcon test-result=${result_rc}). 위의 실패 내용을 본다."
  fi
  if [ -z "${tests}" ] || [ -z "${skipped}" ]; then
    die "colcon test-result 의 'Summary:' 줄을 읽지 못했다. 통과로 치지 않는다."
  fi
  if [ "${tests}" = 0 ]; then
    die "실행된 시험이 0개다. 통과로 치지 않는다."
  fi
  if [ "${skipped}" != 0 ] && [ "${allow_skip}" != 1 ]; then
    die "skip 이 ${skipped}개다. skip 은 통과가 아니다. 이유를 확인하고, 일부러 넘길 때만 --allow-skip 을 붙인다."
  fi
  info "통과: ${summary}"
}

inside_test() {
  local do_build="$1" allow_skip="$2"
  shift 2
  if [ "${do_build}" = 1 ]; then
    info "1/3 colcon build --symlink-install $*"
    colcon build --symlink-install "$@"
  fi
  if [ ! -d build ]; then
    die "build/ 가 없다. --no-build 를 빼고 다시 돌린다."
  fi
  # 지난 결과가 이번 요약에 섞이지 않게 먼저 지운다.
  # 못 지워도 지난 결과는 실패 쪽으로만 섞이므로(통과로 둔갑하지 않음) 경고만 한다.
  if ! colcon test-result --delete-yes > /dev/null 2>&1; then
    warn "지난 시험 결과를 지우지 못했다. 요약에 지난 결과가 섞일 수 있다."
  fi
  info "2/3 colcon test $*"
  local test_rc=0
  colcon test --return-code-on-test-failure "$@" || test_rc=$?
  info "3/3 colcon test-result --verbose"
  local result result_rc=0
  result="$(colcon test-result --verbose)" || result_rc=$?
  printf '%s\n' "${result}"
  judge_test_result "${result}" "${test_rc}" "${result_rc}" "${allow_skip}"
}

cmd_inside() {
  if [ ! -f "${ROS_SETUP}" ]; then
    die "__inside 는 컨테이너 안에서 dev.sh 가 부르는 내부 명령이다."
  fi
  local mode="${1:-}"
  if [ $# -gt 0 ]; then
    shift
  fi
  cd "${REPO_ROOT}"
  source_ros
  case "${mode}" in
    build)
      info "colcon build --symlink-install $*"
      colcon build --symlink-install "$@"
      ;;
    test)
      if [ $# -lt 2 ]; then
        die "__inside test 인자가 모자란다."
      fi
      inside_test "$@"
      ;;
    *)
      die "__inside 가 모르는 모드: ${mode}"
      ;;
  esac
}

main() {
  local cmd="${1:-help}"
  if [ $# -gt 0 ]; then
    shift
  fi
  case "${cmd}" in
    help | -h | --help)
      usage
      ;;
    __inside)
      cmd_inside "$@"
      ;;
    build-image | shell | build | test | clean | save | load)
      preflight
      case "${cmd}" in
        build-image) cmd_build_image "$@" ;;
        shell) cmd_shell "$@" ;;
        build) cmd_build "$@" ;;
        test) cmd_test "$@" ;;
        clean) cmd_clean "$@" ;;
        save) cmd_save "$@" ;;
        load) cmd_load "$@" ;;
      esac
      ;;
    *)
      usage >&2
      die "모르는 하위 명령: ${cmd}"
      ;;
  esac
}

# 시험에서 함수만 불러 쓸 수 있게, 직접 실행할 때만 main 을 돈다.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
