#!/usr/bin/env bash
# Copyright 2026 Pinky_Team4
# Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
#
# Station PC 서비스(팔 어댑터, PC 상태 보고)를 사용자 systemd 에 설치한다. sudo 를 쓰지 않는다.
#
#   scripts/systemd/install_station_services.sh             # 복사 + daemon-reload 만 (켜지 않음)
#   scripts/systemd/install_station_services.sh --enable    # 부팅 때 자동 시작도 등록
#   scripts/systemd/install_station_services.sh --uninstall # 끄고 지운다 (station.env 는 남긴다)
#
# 처음 실행하면 ~/.config/cobot/station.env 를 만들고 멈춘다. 값을 확인한 뒤 다시 실행한다.
# 부팅 때 로그인 없이 뜨려면 linger 가 켜져 있어야 한다 (loginctl show-user "$USER" -p Linger).
# 설명서: docs/station_pc_services.md
set -eo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SRC="$REPO/scripts/systemd"
UNIT_DIR="$HOME/.config/systemd/user"
ENV_DIR="$HOME/.config/cobot"
ENV_FILE="$ENV_DIR/station.env"
UNITS=(cobot-host-status.service cobot-arm-adapter.service)

MODE=install
case "${1:-}" in
    '') ;;
    --enable) MODE=enable ;;
    --uninstall) MODE=uninstall ;;
    -h|--help) sed -n '5,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "모르는 옵션: $1 (--enable, --uninstall)" >&2; exit 1 ;;
esac

if [ "$MODE" = uninstall ]; then
    for u in "${UNITS[@]}"; do
        systemctl --user disable --now "$u" 2>/dev/null || true
        rm -f "$UNIT_DIR/$u"
        echo "✓ $u 지움"
    done
    systemctl --user daemon-reload
    echo "  $ENV_FILE 은 남겨 두었다"
    exit 0
fi

case "$REPO" in *' '*) echo "✗ 저장소 경로에 공백이 있음: $REPO" >&2; exit 1 ;; esac
[ -f "$REPO/install/setup.bash" ] || {
    echo "✗ 빌드가 없음: $REPO 에서 colcon build --symlink-install" \
        "--packages-up-to cobot_manipulation cobot_control_center" >&2
    exit 1
}

if [ ! -f "$ENV_FILE" ]; then
    mkdir -p "$ENV_DIR"
    sed "s|@HOME@|$HOME|g" "$SRC/station.env.example" > "$ENV_FILE"
    echo "! $ENV_FILE 을 만들었다. 값(ROS_DOMAIN_ID 등)을 확인한 뒤 다시 실행한다."
    exit 0
fi

mkdir -p "$UNIT_DIR"
for u in "${UNITS[@]}"; do
    sed "s|@REPO@|$REPO|g" "$SRC/$u" > "$UNIT_DIR/$u"
    echo "✓ $UNIT_DIR/$u"
done
systemctl --user daemon-reload

if [ "$MODE" = enable ]; then
    systemctl --user enable "${UNITS[@]}"
    echo "✓ 부팅 때 자동 시작 등록 (지금 켜지는 않음)"
fi
echo
echo "  켜기:  systemctl --user start cobot-host-status cobot-arm-adapter"
echo "  상태:  systemctl --user status cobot-arm-adapter"
echo "  로그:  journalctl --user -u cobot-arm-adapter -f"
echo "  ⚠ 팔 옆에 사람이 없으면: systemctl --user stop cobot-arm-adapter"
