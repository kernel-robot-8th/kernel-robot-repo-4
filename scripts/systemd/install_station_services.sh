#!/usr/bin/env bash
# Copyright 2026 Pinky_Team4
# Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
#
# Station PC 서비스(팔 어댑터, PC 상태 보고)를 사용자 systemd 에 설치한다. sudo 를 쓰지 않는다.
#
#   scripts/systemd/install_station_services.sh             # 복사 + daemon-reload 만 (켜지 않음)
#   scripts/systemd/install_station_services.sh --enable    # 부팅 때 자동 시작도 등록 (COBOT_ARMS 의 팔마다)
#   scripts/systemd/install_station_services.sh --uninstall # 끄고 지운다 (station.env 는 남긴다)
#
# 팔 어댑터는 템플릿(cobot-arm-adapter@.service)이라 팔마다 cobot-arm-adapter@<팔> 로 켠다.
# 처음 실행하면 ~/.config/cobot/station.env 를 만들고 멈춘다. 값을 확인한 뒤 다시 실행한다.
# 옛 단일 서비스(cobot-arm-adapter.service)가 깔려 있으면 끄고 지운다 (팔 목록은 COBOT_ARM_ID 로 이어받는다).
# 부팅 때 로그인 없이 뜨려면 linger 가 켜져 있어야 한다 (loginctl show-user "$USER" -p Linger).
# 설명서: docs/station_pc_services.md
set -eo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SRC="$REPO/scripts/systemd"
UNIT_DIR="$HOME/.config/systemd/user"
ENV_DIR="$HOME/.config/cobot"
ENV_FILE="$ENV_DIR/station.env"
UNITS=(cobot-host-status.service cobot-arm-adapter@.service)
ARM_UNIT=cobot-arm-adapter
OLD_UNIT=cobot-arm-adapter.service   # 템플릿 전에 쓰던 단일 서비스
SYSTEMCTL=${SYSTEMCTL:-systemctl}    # 시험 때 echo 로 바꿔 실제 사용자 매니저를 건드리지 않는다

MODE=install
case "${1:-}" in
    '') ;;
    --enable) MODE=enable ;;
    --uninstall) MODE=uninstall ;;
    -h|--help) sed -n '5,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "모르는 옵션: $1 (--enable, --uninstall)" >&2; exit 1 ;;
esac

# 옛 단일 서비스를 끄고 지운다. 없으면 아무것도 안 한다
remove_old_unit() {
    [ -f "$UNIT_DIR/$OLD_UNIT" ] || return 0
    $SYSTEMCTL --user disable --now "$OLD_UNIT" 2>/dev/null || true
    rm -f "$UNIT_DIR/$OLD_UNIT"
    echo "✓ 옛 단일 서비스 $OLD_UNIT 를 끄고 지움 (이제 $ARM_UNIT@<팔>)"
}

if [ "$MODE" = uninstall ]; then
    # 켜져 있는 팔 서비스(@omx1 등)를 모두 끈다
    for u in $($SYSTEMCTL --user list-units --all --plain --no-legend "$ARM_UNIT@*" 2>/dev/null \
            | grep -o "$ARM_UNIT@[^ ]*\.service"); do
        $SYSTEMCTL --user disable --now "$u" 2>/dev/null || true
        echo "✓ $u 끔"
    done
    for u in "${UNITS[@]}"; do
        $SYSTEMCTL --user disable --now "$u" 2>/dev/null || true
        rm -f "$UNIT_DIR/$u"
        echo "✓ $u 지움"
    done
    remove_old_unit
    # enable 해 둔 팔 서비스의 링크(default.target.wants/cobot-arm-adapter@<팔>.service)가 남지 않게
    rm -f "$UNIT_DIR"/default.target.wants/"$ARM_UNIT"@*.service
    $SYSTEMCTL --user daemon-reload
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
    echo "! $ENV_FILE 을 만들었다. 값(ROS_DOMAIN_ID, COBOT_ARMS 등)을 확인한 뒤 다시 실행한다."
    exit 0
fi

# 이 PC 팔 목록과 실제로 돌릴 팔. 옛 station.env 는 COBOT_ARM_ID 하나와 COBOT_ARM_BACKEND 만 있다
read_env() (
    # shellcheck disable=SC1090
    set -a; . "$ENV_FILE"; eval "echo \"$1\""
)
ARMS=$(read_env '${COBOT_ARMS:-${COBOT_ARM_ID:-}}')
WORKERS=$(read_env '${COBOT_WORKER_ARMS:-}')
DEFAULT_BACKEND=$(read_env '${COBOT_ARM_BACKEND:-none}')
for a in $ARMS $WORKERS; do
    case "$a" in omx[0-9]|omx[0-9][0-9]) ;; *)
        echo "✗ $ENV_FILE 의 팔 목록에 팔 이름이 아닌 값: $a (omxN 형태)" >&2; exit 1 ;;
    esac
done
for w in $WORKERS; do
    case " $ARMS " in *" $w "*) ;; *)
        echo "✗ COBOT_WORKER_ARMS 의 $w 가 COBOT_ARMS($ARMS)에 없음" >&2; exit 1 ;;
    esac
done
# 7edc9bf 에서 잠깐 쓰던 팔별 파일. 이제 서비스가 읽지 않는다
for f in "$ENV_DIR"/arm-*.env; do
    [ -e "$f" ] && echo "! $f 은 이제 안 읽는다. 내용을 $ENV_FILE 의 COBOT_WORKER_ARMS·OMX_FLEET_DIR 로 옮긴다"
done

mkdir -p "$UNIT_DIR"
remove_old_unit
for u in "${UNITS[@]}"; do
    sed "s|@REPO@|$REPO|g" "$SRC/$u" > "$UNIT_DIR/$u"
    echo "✓ $UNIT_DIR/$u"
done
$SYSTEMCTL --user daemon-reload

ARM_UNITS=()
for a in $ARMS; do ARM_UNITS+=("$ARM_UNIT@$a"); done
if [ "$MODE" = enable ]; then
    $SYSTEMCTL --user enable cobot-host-status.service "${ARM_UNITS[@]}"
    echo "✓ 부팅 때 자동 시작 등록: cobot-host-status ${ARM_UNITS[*]} (지금 켜지는 않음)"
fi
echo
if [ ${#ARM_UNITS[@]} -eq 0 ]; then
    echo "! $ENV_FILE 의 COBOT_ARMS 가 비어 있음. 팔 서비스는 등록하지 않았다"
fi
echo "  이 PC 팔:"
for a in $ARMS; do
    b=$DEFAULT_BACKEND
    for w in $WORKERS; do [ "$w" = "$a" ] && b=worker; done
    echo "    $a: $b"
done
echo "  켜기:  systemctl --user start cobot-host-status ${ARM_UNITS[*]:-$ARM_UNIT@<팔>}"
echo "  상태:  systemctl --user status '$ARM_UNIT@*'"
echo "  로그:  journalctl --user -u $ARM_UNIT@<팔> -f"
echo "  ⚠ 팔 옆에 사람이 없으면: systemctl --user stop '$ARM_UNIT@*'"
