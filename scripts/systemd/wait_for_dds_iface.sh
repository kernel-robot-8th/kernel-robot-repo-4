#!/usr/bin/env bash
# Copyright 2026 Pinky_Team4
# Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
#
# Station PC 서비스의 ExecStartPre. DDS 가 쓰는 인터페이스에 IPv4 주소가 생길 때까지 기다린다.
#
# 왜: Cyclone DDS 는 노드가 켜질 때 한 번만 인터페이스 주소를 정한다. 부팅 때 Wi-Fi 연결 전에
# 노드가 켜지면 프로세스는 살아 있어도 DDS 그래프에 보이지 않는다 (2026-11-16 부팅에서 확인).
# 사용자 서비스에는 network-online.target 이 없어서 After= 로는 순서를 맞출 수 없다.
#
# 인터페이스 이름은 CYCLONEDDS_URI 가 가리키는 xml 의 NetworkInterface name="..." 에서 읽는다.
# 못 읽으면 기다리지 않고 통과한다. 최대 대기 시간은 COBOT_NET_WAIT_SEC (기본 60 초).
# 시간 안에 주소가 안 생기면 1 로 끝난다 → 서비스의 Restart 규칙대로 다시 시도한다.
# 설명서: docs/station_pc_services.md
set -uo pipefail

WAIT_SEC=${COBOT_NET_WAIT_SEC:-60}
URI=${CYCLONEDDS_URI:-}
XML=${URI#file://}

if [ -z "$URI" ] || [ ! -f "$XML" ]; then
    echo "DDS 설정 파일 없음 (CYCLONEDDS_URI='$URI'): 인터페이스를 기다리지 않는다"
    exit 0
fi

IFACE=$(grep -o '<NetworkInterface[^>]*name="[^"]*"' "$XML" | head -n1 | sed 's/.*name="\([^"]*\)".*/\1/')
if [ -z "$IFACE" ]; then
    echo "$XML 에 NetworkInterface name 없음: 인터페이스를 기다리지 않는다"
    exit 0
fi

echo "$IFACE 주소 기다림 (최대 ${WAIT_SEC} 초)"
for ((i = 0; i <= WAIT_SEC; i++)); do
    ADDR=$(ip -4 -o addr show dev "$IFACE" 2>/dev/null | awk '{print $4}' | head -n1)
    if [ -n "$ADDR" ]; then
        echo "$IFACE 주소 확인: $ADDR (${i} 초)"
        exit 0
    fi
    [ "$i" -lt "$WAIT_SEC" ] && sleep 1
done

echo "$IFACE 에 ${WAIT_SEC} 초 안에 IPv4 주소가 생기지 않음" >&2
exit 1
