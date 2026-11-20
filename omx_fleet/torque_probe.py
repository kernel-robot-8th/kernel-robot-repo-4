#!/usr/bin/env python3
"""
팔 모터의 토크 켜짐(Torque_Enable)을 읽기만 하고 끝내는 도구 (쓰기 없음, 팔을 움직이지 않음).

왜: 실행기가 강제로 꺼지면 토크를 끄지 못하고, 모터는 전원이 있는 동안 토크를 유지한다.
팔 노드(cobot_manipulation arm_adapter, backend=worker)는 실행기가 떠 있지 않을 때 이 도구로
실제 토크 상태를 재서 관제에 보인다. 실행기가 포트를 쓰는 동안에는 부르지 않는다.

  ~/venv/il/bin/python torque_probe.py --port /dev/serial/by-id/usb-ROBOTIS_OpenRB-150_<시리얼>-if00

출력 (한 줄 JSON):
  {"torque": {"11": 1, ...}, "errors": {"16": "..."}, "enabled": true | false | null}
  enabled: 읽은 모터 중 하나라도 켜져 있으면 true, 모두 꺼져 있으면 false, 하나도 못 읽으면 null.
모터 ID·통신 속도는 lerobot omx_follower 와 같다 (ID 11~16, 1 Mbps, 프로토콜 2.0).
"""

import argparse
import json
import sys

TORQUE_ENABLE_ADDR = 64     # Torque_Enable (1 byte), XL430·XL330 공통
DEFAULT_IDS = '11,12,13,14,15,16'
DEFAULT_BAUD = 1_000_000


def summarize(torque):
    """모터별 값 → 전체 판정. 하나라도 켜져 있으면 켜짐."""
    if not torque:
        return None
    return any(value != 0 for value in torque.values())


def probe(port_name, ids, baud):
    """모터별 Torque_Enable 을 읽는다. 쓰지 않는다."""
    from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler

    port = PortHandler(port_name)
    if not port.openPort():
        raise OSError(f'포트를 열지 못함: {port_name}')
    try:
        if not port.setBaudRate(baud):
            raise OSError(f'통신 속도 설정 실패: {baud}')
        packet = PacketHandler(2.0)
        torque, errors = {}, {}
        for motor_id in ids:
            value, comm, error = packet.read1ByteTxRx(port, motor_id, TORQUE_ENABLE_ADDR)
            if comm != COMM_SUCCESS:
                errors[str(motor_id)] = packet.getTxRxResult(comm)
            elif error:
                errors[str(motor_id)] = packet.getRxPacketError(error)
            else:
                torque[str(motor_id)] = int(value)
        return torque, errors
    finally:
        port.closePort()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument('--port', required=True)
    p.add_argument('--ids', default=DEFAULT_IDS, help='모터 ID (쉼표로 구분)')
    p.add_argument('--baud', type=int, default=DEFAULT_BAUD)
    args = p.parse_args(argv)
    try:
        ids = [int(x) for x in args.ids.split(',') if x.strip()]
        torque, errors = probe(args.port, ids, args.baud)
    except (OSError, ValueError, ImportError) as error:
        print(json.dumps({'torque': {}, 'errors': {'port': str(error)}, 'enabled': None},
                         ensure_ascii=False), flush=True)
        return 1
    print(json.dumps({'torque': torque, 'errors': errors, 'enabled': summarize(torque)},
                     ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
