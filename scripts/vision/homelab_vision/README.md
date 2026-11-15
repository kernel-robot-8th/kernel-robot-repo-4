# homelab-vision (2a 단계: 중계 노트북에서 빌드와 CPU 검증만)

작성 2026-11-10. 이 폴더와 이미지는 중계 노트북(kgh1005)에만 있다.
omen-8 에는 아무것도 보내지 않았고, 실제 브로커(1883)와 실제 카메라에도 붙지 않았다.

## 무엇을 만들었나

- 이미지 `homelab-vision:20261110` (python:3.12-slim 기반, 사용자 app uid 10001)
  - torch 2.11.0+cu128, torchvision 0.26.0+cu128, ultralytics 8.4.193,
    opencv-contrib-python-headless 4.14.0.94, paho-mqtt 2.2.0, numpy 2.5.4
  - 정확한 버전 전체: 이미지 안 `/app/requirements.lock`
  - 가중치 2개(홈랩 묶음 homelab-20261110-omen-yolo 그대로, 빌드 때 SHA-256 13개 대조)
    - pinky_v2_final.pt 58a8fe5f...3c0573
    - kneg_d_final.pt f7991cdc...8595bd
  - zone 모듈 11개 파일(수정 없이 복사)
- 앱(`app/`): MJPEG 를 읽어 두 모델로 추론하고, 구역 판정 근거를 MQTT 로 내보낸다.
  - 주제: `relay/evidence/zones`, `relay/evidence/boxes` (QoS 1, retain 없음),
    `relay/status/vision` (1초 상태, QoS 0, 유언 "offline")
  - 메시지 필드·수신 규칙·관제 연동(비전 어댑터 개발용): [MQTT_MESSAGE_SPEC.md](MQTT_MESSAGE_SPEC.md)
  - `PUBLISH=false`(기본)면 MQTT 라이브러리를 불러오지도 않는다. 연결 0.
  - 듣는 포트 없음. 프레임과 사진을 디스크에 쓰지 않는다. ROS 를 쓰지 않는다.
- `compose.yaml`: omen-8 에서 나중에 쓸 구성. 여기서는 실행하지 않았다.
- `verify/golden_check.py`: 홈랩 기준 사진 4장과 검출 결과를 대조하는 스크립트.
- `verify/test_publisher.py`: 발행기 시험(가짜 브로커를 같은 프로세스에 띄운다. 네트워크 없음). 이미지에는 넣지 않았다.

## 발행 동작 (11-10 검토 뒤 고침)

- 근거 메시지는 촬영 시각(capture_time)에서 2초가 지나면 보내지 않고 버린다(`drops.stale`).
- 연결이 끊기면 paho 클라이언트를 버리고 새로 만든다(`mqtt_renewals`).
  paho 2.2.0 은 재접속 때 응답을 못 받은 QoS 1 메시지를 DUP 로 다시 보내는데, 그러면 수십 초 묵은 근거가 나간다.
  새 클라이언트에는 밀린 메시지가 없으므로 다시 보내는 것이 없다. 끊길 때 응답을 못 받은 것은
  다시 보내지 않고 `publish_unacked_lost` 로 센다.
- 재접속은 브로커가 돌아온 뒤 최대 5초 걸린다(시도 간격 1초에서 5초까지 늘어남. 측정 1.3~4.0초).
- 상태 메시지(`relay/status/vision`)의 발행 계수
  - `published`: paho 에 넘긴 수(브로커 도착 수가 아니다)
  - `published_acked`: 브로커가 PUBACK 으로 받았다고 답한 수
  - `publish_unacked_lost`: 응답 없이 연결이 끊겨 버린 수
  - `publish_inflight`: 아직 응답을 기다리는 수
  - 항상 `published = published_acked + publish_unacked_lost + publish_inflight`
- 남은 한계: 연결은 살아 있는데 브로커가 읽지 않는 동안(약 8.6초, keepalive 5초 기준) 이미 넘긴 메시지는
  끊김을 알아챌 때까지 계수에 `publish_inflight` 로 남는다. 그 뒤에는 버려진다.
- 마커 판정은 프레임 간격이 1초보다 짧을 때만 약 1초에 한 번 한다.
  CPU 에서는 프레임 간격이 약 0.85초라 두 프레임에 한 번(약 1.7초)이다.

## monitor_node 에 붙일 때 (이 이미지 밖의 일. 아직 하지 않았다)

- 이 이미지는 `calibration_id` 를 `ceil-20261108` 로 보낸다.
- `cobot_anomaly_monitor/monitor_node.py` 의 기본값은 `replay-v1` 이다. 기본값 그대로면
  `load_evidence.py` 가 모든 프레임을 거절하고 이력을 비운다(코드로 확인. 실행해 보지는 않았다).
- 그래서 monitor 를 띄울 때 매개변수 `calibration_id:=ceil-20261108` 을 줘야 한다.
  `model_id`(`pinky-v1`), `stream_id`(`ceiling`) 는 기본값과 같다. monitor 코드는 건드리지 않았다.
- 금지 주제(`/fleet/work_result` 등): 앱 코드(`app/*.py`)에는 문자열이 없다.
  수정 없이 복사한 `zone/vision_answer.py`, `zone/pinky_evidence.py` 의 설명글에만 있고, 앱은 그 두 파일을 불러오지 않는다.

## 환경 변수

| 이름 | 기본 | 뜻 |
|---|---|---|
| PUBLISH | false | true 일 때만 브로커에 붙는다 |
| MQTT_BROKER / MQTT_PORT | 192.168.0.3 / 1883 | 브로커 주소 |
| CAMERA_SOURCE | http://192.168.0.7:18086/processed | MJPEG 주소 |
| INFERENCE_FPS | 10 | 추론 상한 |
| DEVICE | auto | cuda 가 보이면 cuda, 아니면 cpu |
| STATUS_LOG_SEC | 10 | 상태 로그 주기(초) |
| TORCH_THREADS | 0 | 0 이면 컨테이너 CPU 한도에 맞춘다 |
| PUBLISH_QUEUE_MAX | 20 | 발행 대기열 길이. 넘치면 오래된 것부터 버린다 |
| NET_AUDIT | false | true 면 소켓 connect/bind 를 로그에 남긴다(시험용) |

## 나중에 실행하는 법 (omen-8, 2b 단계. 사용자 승인 뒤에만)

1. 이미지를 그 PC 로 옮긴다. 예: `docker save homelab-vision:20261110 | gzip > hv.tar.gz` 후 복사, `docker load`.
   디스크 약 12 GB 가 필요하다.
2. `docker compose -f compose.yaml up -d`
3. 로그: `docker logs -f homelab-vision` (한 줄에 JSON 하나)
4. 멈춤: `docker compose -f compose.yaml down`

발행을 켜려면 compose.yaml 의 `PUBLISH` 를 "true" 로 바꾼다. 이 결정은 사용자가 한다.

## 이 노트북에서 다시 검증하는 법 (GPU 불필요)

```
# zone 시험 4개(스크립트로 실행. pytest 는 3개 파일을 수집하지 못한다)
for t in test_zone_evidence_msg test_pinky_evidence test_vision_answer test_marker_zone; do
  docker run --rm --network none --entrypoint python homelab-vision:20261110 -B /app/zone/$t.py
done

# 발행기 시험(무응답, 끊김, 반복 끊김, 묵은 메시지, 로그 줄. 약 1분. 마지막 줄 RESULT fails=0 이면 통과)
docker run --rm --network none --cpus 2 --memory 1g -v ~/homelab-vision/verify:/verify:ro \
  --entrypoint python homelab-vision:20261110 -B /verify/test_publisher.py

# 기준 사진 대조(사진은 읽기 전용으로만 붙인다. 숫자만 출력하고 파일을 쓰지 않는다)
docker run --rm --network none --cpus 4 --memory 4g --read-only --tmpfs /tmp \
  -v ~/yolo_edge/inbox/homelab-20261109-d-pinky:/g:ro \
  -v ~/homelab-vision/verify:/verify:ro \
  --entrypoint python homelab-vision:20261110 -B /verify/golden_check.py \
  --pinky-golden /g/golden-pinky-v2-final --boxes-golden /g/golden-kneg-d-final --device cpu --repeat 5
```

## 전부 지우는 법

```
# 1) 컨테이너가 남아 있으면 지운다(2a 에서는 남기지 않았다)
docker ps -a --filter ancestor=homelab-vision:20261110
docker rm -f homelab-vision 2>/dev/null

# 2) 이미지
docker rmi homelab-vision:20261110

# 3) 빌드 중간 이미지와 고치기 전 이미지(이 프로젝트 표시가 붙은 것만. 이름 없는 <none> 이미지가 여기 해당한다)
docker image prune -f --filter label=project=homelab-vision
docker images -a --filter label=project=homelab-vision   # 아무것도 안 나오면 끝

# 4) 폴더
rm -rf ~/homelab-vision
```

`docker builder prune` 이나 `docker system prune` 은 다른 작업의 캐시까지 지우므로 쓰지 않는다.
시험에 쓴 임시 브로커 이미지 `eclipse-mosquitto:latest` 는 기존 `mosquitto-broker` 컨테이너가
같은 이미지를 쓰고 있을 수 있으니 지우지 않는다.

## 한계 (측정하지 않은 것)

- GPU 추론 전부(속도, 메모리, cuda 동작). 이 노트북에는 NVIDIA GPU 가 없다.
- 실제 폰 카메라 스트림, 실제 브로커(1883), monitor_node 가 zones 메시지를 받아들이는지.
- 구역 좌표(zones-tray-px-20261108)는 11-08 카메라 자세 기준이다. 카메라가 움직였으면 맞지 않는다.
- paho 2.2.0 의 내부 함수 `_socketpair_compat` 를 바꿔 끼웠다(127.0.0.1 임시 listen 제거).
  paho 버전을 올리면 다시 확인해야 한다. 끊김 콜백 안에서 `loop_stop()` 을 부르는 것도 paho 2.2.0 동작에 기대고 있다.
- 로그의 `net_audit` 에 `bind ('', 0)` 이 나오는 것은 보내는 소켓의 임시 포트 지정이다. listen 은 없다.

## 현장 기동 기록 (2026-11-10)

이미지 `homelab-vision:20261110`(id 29b735fb)을 OMEN 두 대에 올려 폰 천장 영상(`/processed`, 1080x1440, 약 11.7 fps)으로 돌렸다.
설정은 compose 의 `PUBLISH` 를 "true", `MQTT_BROKER` 를 중계 현재 주소(192.168.0.8, DHCP 라 바뀔 수 있다)로 바꾼 것뿐이다.

| 항목 | 8-OMEN | team11 OMEN |
|---|---|---|
| 추론 | cuda:0, 10.0 fps, 평균 12.5 ms | cuda:0, 10.0 fps, 평균 9.7 ms |
| 마커 | 4개, OK | 4개, OK |
| 브로커 도착 | zones·boxes 각 초당 10건, status 초당 1건 | 같음 |
| CPU / 메모리 | 23%(1코어=100%) / 1.11 GiB | 23% / 1.10 GiB |

- 8-OMEN 은 23분 동안 대기열 버림 242건, 응답 없이 잃은 것 40건이 있었다(같은 시간에 12 GB 이미지 전송이 중계 유선을 채웠다. 원인은 추정).
- 실행 PC 조건: 실행 계정이 docker 그룹에 있고 `nvidia-container-toolkit` 이 설치돼 있어야 한다.
- 중계 감시 노드가 이 MQTT 증거를 받아 반영하는 것은 아직 확인하지 않았다.
- 재지 않은 것: 폰에서 추론 PC 까지 지연, 10분 이상 연속 손실률.
