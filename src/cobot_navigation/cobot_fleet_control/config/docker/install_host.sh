#!/usr/bin/env bash
# 새 Ubuntu 24.04 관제 PC용. ROS/Python은 이미지 안에 설치한다.
# Docker 공식 apt 설치 절차: https://docs.docker.com/engine/install/ubuntu/
set -euo pipefail

usage() {
  echo '사용법: sudo bash install_host.sh [--check]'
  echo '  기본: Docker Engine·Buildx·Compose 설치 및 Docker 서비스 시작'
  echo '  --check: 설치·데몬 접근만 확인, 시스템 변경 없음'
}

check() {
  docker --version
  docker compose version
  docker info --format '{{.ServerVersion}}'
}

case "${1:-}" in
  --help|-h) usage; exit 0 ;;
  --check) check; exit 0 ;;
  '') ;;
  *) usage >&2; exit 2 ;;
esac
if [[ $# -gt 1 ]]; then usage >&2; exit 2; fi

source /etc/os-release
if [[ "${ID:-}" != ubuntu || "${VERSION_ID:-}" != 24.04 ]]; then
  echo '자동 설치 대상은 Ubuntu 24.04 Linux 관제 PC입니다.' >&2
  exit 2
fi
if [[ $EUID -ne 0 ]]; then
  echo '시스템 패키지 설치에는 sudo bash install_host.sh를 사용하세요.' >&2
  exit 2
fi
# 이미 준비된 Docker는 교체하거나 재시작하지 않는다.
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  check
  exit 0
fi
# 기존 배포판 Docker/containerd를 자동 제거하지 않는다.
for package in docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc; do
  if [[ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)" == 'install ok installed' ]]; then
    echo "기존 ${package}가 설치돼 있습니다. 기존 Docker에 Compose를 추가하거나 공식 설치 문서의 전환 절차를 사용하세요." >&2
    exit 2
  fi
done

apt-get update
apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
architecture="$(dpkg --print-architecture)"
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: ${architecture}
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
check
echo 'Docker 준비 완료. fleet_docker.sh build → check → up 순서로 실행하세요.'
