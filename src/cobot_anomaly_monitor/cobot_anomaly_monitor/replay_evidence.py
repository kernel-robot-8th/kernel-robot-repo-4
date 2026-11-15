"""루프백 MQTT 시험 브로커로 합성 구역 결과 또는 녹화된 추론 결과를 보낸다. 영상 추론을 수행하지 않는다."""

import argparse
import json
import math
import os
from pathlib import Path
import time
import uuid


def recorded_frames(path, epoch, start_seq, limit):
    """한 녹화·모드만 선택하고 자료의 상대 시각과 원본 순번을 검증한다."""
    frames = []
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if row.get('stream_epoch') != epoch:
                continue
            seq, stamp = row['frame_seq'], row['capture_time_rel']
            if (type(seq) is not int or type(stamp) not in (int, float)
                    or not math.isfinite(stamp) or stamp < 0 or row.get('source_kind') != 'model_output'):
                raise ValueError('잘못된 녹화 프레임')
            if seq < start_seq:
                continue
            if frames and (seq <= frames[-1]['frame_seq'] or stamp <= frames[-1]['capture_time_rel']):
                raise ValueError('녹화 순번 또는 시각 역전')
            frames.append(row)
            if len(frames) == limit:
                break
    if not frames:
        raise ValueError('선택한 녹화·순번에 프레임이 없습니다')
    return frames


def play_recording(frames, publish):
    start, wall = time.monotonic(), time.time()
    epoch = uuid.uuid4().hex
    for frame in frames:
        offset = frame['capture_time_rel'] - frames[0]['capture_time_rel']
        time.sleep(max(0, start + offset - time.monotonic()))
        publish(dict(frame, capture_time=wall + offset, stream_epoch=epoch,
                     recorded_epoch=frame['stream_epoch']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zone', choices=['ZA', 'ZB'])
    parser.add_argument('--state', choices=['LOADED', 'EMPTY', 'MULTI', 'UNKNOWN'])
    parser.add_argument('--port', type=int, default=1883)
    # 송출이 끝나면 3초 뒤 표본이 만료된다. 단계가 끝날 때까지 보내려면 --duration 을 늘린다.
    parser.add_argument('--duration', type=float, default=10.0, help='송출 시간(초)')
    parser.add_argument('--interval', type=float, default=0.5, help='프레임 간격(초)')
    parser.add_argument('--recording', type=Path, help='실사 추론 JSONL')
    parser.add_argument('--epoch', help='원본 stream_epoch (녹화·모드)')
    parser.add_argument('--start-seq', type=int, default=0)
    parser.add_argument('--limit', type=int, default=120)
    args = parser.parse_args()
    frames = None
    if args.recording:
        if args.zone or args.state or not args.epoch or args.limit <= 0 or args.start_seq < 0:
            parser.error('녹화 모드에는 --epoch와 유효한 순번·개수가 필요합니다')
        frames = recorded_frames(args.recording, args.epoch, args.start_seq, args.limit)
    elif not args.zone or not args.state or args.epoch:
        parser.error('합성 모드에는 --zone과 --state가 필요합니다')
    if not 0 < args.interval <= 1 or not 0 < args.duration <= 600:
        parser.error('--interval 은 0~1 초, --duration 은 0~600 초')
    if (os.environ.get('ROS_DOMAIN_ID') not in ('77', '140')
            or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'):
        parser.error('홈랩 시뮬 셸에서만 실행')
    import paho.mqtt.client as mqtt
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect('127.0.0.1', args.port)
    client.loop_start()
    epoch = uuid.uuid4().hex
    def publish(frame):
        sent = client.publish('relay/evidence/zones', json.dumps(frame), qos=1, retain=False)
        sent.wait_for_publish(timeout=2)
        if not sent.is_published():
            raise RuntimeError('시험 브로커 PUBACK 시간 초과')

    try:
        if frames is not None:
            play_recording(frames, publish)
            return
        end, seq = time.time() + args.duration, -1
        while time.time() < end:
            seq += 1
            frame = dict(source_kind='sim_fixture', stream_id='ceiling', stream_epoch=epoch,
                         model_id='pinky-v1', calibration_id='replay-v1', marker_state='OK',
                         zones={args.zone: args.state}, capture_time=time.time(), clock_error_sec=0,
                         frame_seq=seq)
            publish(frame)
            time.sleep(args.interval)
    finally:
        client.disconnect()
        client.loop_stop()
