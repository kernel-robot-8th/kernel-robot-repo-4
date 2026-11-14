# homelab-vision MQTT 메시지 명세 (비전 어댑터·관제 연동 개발용)

작성 2026-11-14(16:10 관제 연동 8절 보충, 16:30 역할 분담·협의 항목 재구성). 대상: 이 메시지를 받아 관제 시나리오 단계에 답하는 **비전 어댑터**를 만드는 사람, 그리고 그 결과를 받는 관제(`src/cobot_navigation/cobot_fleet_control`, b554975 기준. 7f2b2e3 부터는 `src/cobot_fleet_control`)·`src/cobot_control_center` 개발자.
관제 노드가 이 MQTT 주제를 직접 구독하는 구조가 아니다. 관제는 설계상 MQTT 를 받지 않고, 장치 결과는 `/fleet/work_result` 로만 받는다(8절).
기준 코드: 이 폴더 `app/`, `zone/` (브랜치 `merge/submaster-20261112` 머리 b554975, 현장 이미지 `homelab-vision:20261110` 과 같은 앱).
시험 모드(5절)는 아직 커밋하지 않은 추가분(`~/kr4-vision-test` 작업본) 기준이다.

표기: **[사실]** 코드나 기록으로 확인, **[추정]** 확인하지 않은 판단, **[제안]** 수신 쪽에 권하는 규칙, **[계획]** 아직 없는 것.
예시 JSON 은 **(실제 수신)** 과 **(코드로 만든 예)** 를 구분한다. 운영 주제(`relay/evidence/*`, `relay/status/vision`)는 실제 수신 기록이 없어 코드로 만든 예만 있다.

---

## 0. 한 장 요약

| 주제 | 언제 | QoS | retain | 크기(UTF-8) | 용도 |
|---|---|---|---|---|---|
| `relay/status/vision` | 1초마다 (+ 끊김·종료 때 `"offline"`) | 0 (유언·종료 `"offline"` 은 1) | 없음 | 약 1.1~1.2 KB | 앱 살아 있음·영상·추론·발행 상태 |
| `relay/evidence/zones` | 추론한 프레임마다(시각 규칙으로 거절한 프레임 제외. 마커가 OK 가 아닌 프레임은 전부 NO_ROBOT 로 보낸다), 최대 `INFERENCE_FPS`(기본 10/초) | 1 | 없음 | 약 290 B | 작업 구역 ZA·ZB·ZC 의 핑키 상태. 감시 노드 적재 판정 입력(격리 시뮬에서만 켜짐, 3절) |
| `relay/evidence/boxes` | 추론한 프레임마다(거절·마커와 무관), 최대 `INFERENCE_FPS` | 1 | 없음 | 약 0.8 KB(검출 2개), 최대 약 11 KB [추정·계산] | 두 모델의 검출 상자 원본(신뢰도 0.5 이상) |
| `relay/test/status/vision` | 시험 모드에서만, 1초마다 | 0 (`"offline"` 은 1) | 없음 | 약 1.14 KB (실측) | 시험 앱 상태. **운영에 쓰지 말 것** |
| `relay/test/vision/detections` | 시험 모드에서만, 추론 프레임마다 | 0 | 없음 | 706~821 B (실측) | 핑키 검출만. **운영에 쓰지 말 것** |

근거: 주제 이름 `app/config.py:9`, QoS·retain `app/publisher.py:74,160,169,179`, 1초 주기 `app/main.py:181`, 프레임마다 발행 `app/main.py:229-244`. 시험 주제는 미커밋 작업본 `~/kr4-vision-test/.../app/config.py:28-33`, QoS 0 은 같은 작업본 `app/main.py:246-252`·`app/publisher.py:161`.
크기: zones 287 B·boxes 776 B 는 아래 예시를 같은 직렬화(`separators=(",",":")`)로 잰 값, 시험 주제는 `~/doc/logs/vision-test-20261114/mqtt_10min.log` 실측(status 1137~1145 B, detections 706~821 B).
11-10 현장 기동에서 zones·boxes 각 초당 10건, status 초당 1건이 브로커에 도착했다 [사실, `README.md:139`].

관제 시나리오 상태와 잇는 방법(요청·결과 계약, 단계별 필요한 값, 지금 답할 수 있는 단계)은 **8절**에 있다.

---

## 1. 연결

| 항목 | 값 | 근거 |
|---|---|---|
| 브로커 | 중계 노트북 `192.168.0.8:1883`. DHCP 라 바뀔 수 있다 | [사실] 11-10 현장 기동 때 `MQTT_BROKER` 로 준 값 `README.md:133`. 코드 기본값은 옛 주소 `192.168.0.3` (`app/config.py:28`, `compose.yaml:23`) |
| 인증 | 익명. TLS·ACL 없음 | [기록, 저장소 근거 없음] 중계 브로커가 익명 `eclipse-mosquitto` 컨테이너라는 것은 11-07 작업 기록에만 있다(저장소에는 `README.md:118-119` 에 `mosquitto-broker` 컨테이너 언급뿐). [사실] 앱은 계정·TLS 를 쓰지 않는다(`app/publisher.py:71-83` 에 `username_pw_set`·`tls_set` 없음) |
| 발행 여부 | `PUBLISH=true` 일 때만 접속. 기본은 `false` 라 연결 0 | `app/config.py:32`, `app/main.py:142-144` |
| 클라이언트 ID | `homelab-vision-{stream_epoch}` 예 `homelab-vision-1794631039-cf1d6015`. 앱을 다시 띄우면 바뀐다 | `app/main.py:117,144` |
| 세션 | `clean_session=True`, keepalive 5초 | `app/publisher.py:47,73` |
| 유언(LWT) | 주제 `relay/status/vision`(시험 모드는 `relay/test/status/vision`), 내용은 문자열 `offline`(JSON 아님), QoS 1, retain 없음 | `app/publisher.py:74` |
| 정상 종료 | SIGTERM/SIGINT 때 같은 주제로 `offline` 을 QoS 1 로 직접 보낸 뒤 끊는다 | `app/publisher.py:177-180` |
| 재접속 | 끊기면 paho 클라이언트를 버리고 같은 ID 로 새로 만든다(묵은 QoS 1 재전송 방지). 시도 간격 1→5초. 브로커 복구 뒤 최대 약 5초(측정 1.3~4.0초) | `app/publisher.py:77,103-133`, `README.md:29-33` |
| 폐기 규칙 | 근거 메시지(zones·boxes·시험 detections)는 `capture_time` 부터 2초가 넘으면 브로커에 넘기지 않고 버린다(`drops.stale`). 대기열(`PUBLISH_QUEUE_MAX`, 기본 20)을 넘으면 가장 오래된 것부터 버린다(`drops.overflow`). 응답 대기 20개 상한에 걸려 paho 가 거절하면 `drops.rc` 로 센다 | `app/publisher.py:36,47,75-76,135-142,157-165`, `app/config.py:36` |
| 끊긴 동안 | 응답(PUBACK) 못 받은 메시지는 다시 보내지 않는다(`publish_unacked_lost`). 즉 **끊김 구간 근거는 사라진다** | `app/publisher.py:124-128` |
| 최대 크기 | 직렬화 뒤 16000 바이트를 넘는 근거는 보내지 않고 `oversize_payload` 만 센다 | `app/config.py:13`, `app/main.py:191-197` |

[규격·미측정] 유언은 브로커가 연결 끊김을 알아챘을 때 보낸다. keepalive 5초면 MQTT 규격상 최대 약 7.5초(1.5배) 뒤다(현장 브로커에서 잰 적 없음). 그동안은 status 가 끊긴 것만 보인다.
[추정] 앱은 끊기면 **같은 클라이언트 ID** 로 새로 붙는다. 브로커가 옛 연결을 아직 살아 있다고 보던 중이면 새 접속이 옛 연결을 밀어내고, 이때 옛 연결의 유언 `offline` 이 새 연결의 status 와 거의 같이 도착할 수 있다. 2절 제안 2번(받은 뒤 3초 안에 status 가 오면 살아 있음)이 이 경우를 덮는다.

---

## 2. `relay/status/vision`

[사실] `app/main.py:153-175` 의 `status()` 가 만든 dict 를 `json.dumps(d, ensure_ascii=False)` 로(공백 있는 기본 구분자) 1초마다 보낸다(`app/main.py:181-184`). 연결돼 있을 때만 보낸다(`app/publisher.py:167-169`). 38개 필드.

| 이름 | 형식 | 의미 | 예 |
|---|---|---|---|
| status | 문자열 | 항상 `"online"` (끊김은 별도 문자열 `offline`) | `"online"` |
| ts | 실수(Unix 초) | 상태를 만든 시각. **추론 PC 시계** | `1794631056.004` |
| stream_id | 문자열 | 카메라 흐름 이름(6절) | `"ceiling"` |
| stream_epoch | 문자열 | 앱 시작마다 새로 만드는 식별자 `{시작 Unix 초}-{uuid 8자}` | `"1794631039-cf1d6015"` |
| model_id | 문자열 | 감시 노드와 맞추는 모델 계약 이름 | `"pinky-v1"` |
| calibration_id | 문자열 | 구역 좌표 판 | `"ceil-20261108"` |
| clock_error_sec | 실수 | 시계 오차 여유. **고정 상수이고 잰 값이 아니다** | `0.05` |
| weights_sha256 | 객체 {파일: sha256} | 실제 올라간 가중치 해시(시작 때 묶음 해시와 대조) | 6절 |
| device | 문자열 | 추론 장치 | `"cuda:0"`, `"cpu"` |
| publish | 참/거짓 | 발행 켜짐(받았다면 항상 true) | `true` |
| source_connected | 참/거짓 | 영상 연결돼 있고 마지막 프레임이 3초 이내 | `true` |
| source_connect_attempts | 정수 | 영상 접속 시도 누적 | `1` |
| source_connect_failures | 정수 | 영상 접속 실패 누적 | `0` |
| frames_received | 정수 | 받은 프레임 누적(추론 안 한 것 포함) | `157` |
| frames_inferred | 정수 | 추론한 프레임 누적 | `17` |
| frames_skipped_wrong_size | 정수 | 추론 차례에 고른 프레임 가운데 크기가 1080x1440(폭x높이)이 아니라 건너뛴 수. 받은 프레임 전부를 검사한 수가 아니다 | `0` |
| last_frame_size | [폭, 높이] 또는 null | 마지막 받은 프레임 크기 | `[1080, 1440]` |
| infer_fps_1s | 실수 | 직전 상태 이후 초당 추론 수 | `10.0` |
| infer_fps_avg | 실수 | 시작 이후 평균 추론 fps | `9.98` |
| infer_ms_last | 실수 | 마지막 프레임 추론 시간(마커 검사+두 모델) ms. 시험 모드는 마커 없이 두 모델만 | `12.4` |
| infer_ms_avg | 실수 | 평균 추론 시간 ms | `12.5` |
| zones_frames_emitted | 정수 | zones 프레임을 만든 수(발행 성공 수가 아님). 마커가 OK 가 아니라 전부 NO_ROBOT 로 만든 프레임도 센다 | `5980` |
| zones_frames_refused | 정수 | 시각 규칙(아래 `last_refusal` 네 가지)으로 zones 를 만들지 않은 수 | `0` |
| last_refusal | 문자열 또는 null | 마지막 거절 이유: `capture_time missing` / `capture_time not rising` / `capture_time in the future` / `frame older than 3 s` | `null` |
| marker_state | 문자열 또는 null | 마커 사각형 상태 `OK`/`FIXED`/`HOLD`/`CONFLICT`/`LOST` (3절). 시작 직후 첫 추론 전에는 `LOST`. 시험 모드는 null | `"OK"` |
| markers_seen | 정수 | 마지막 검사에서 읽은 마커 40~43 의 수(0~4, 같은 번호가 두 번 읽히면 둘 다 뺀다) | `4` |
| last_zones | 객체 또는 null | 마지막으로 만든 zones 프레임의 `zones` 값(발행 성공과 무관) | `{"ZA": "NO_ROBOT", ...}` |
| publish_queue_drops | 정수 | 버린 근거 합계(overflow+stale+rc) | `0` |
| publish_drops_detail | 객체 | `overflow`(대기열 넘침), `stale`(2초 초과), `rc`(paho 거절, 응답 대기 20개 상한 등) | `{"overflow": 0, "stale": 0, "rc": 0}` |
| publish_queue_len | 정수 | 지금 대기열 길이 | `0` |
| published | 정수 | 근거 메시지를 paho 에 넘긴 수(브로커 도착 수 아님). status 자신은 세지 않는다. 시험 모드는 QoS 0 detections 를 센다 | `11960` |
| published_acked | 정수 | 브로커가 PUBACK 한 수 | `11960` |
| publish_unacked_lost | 정수 | 응답 전에 끊겨 버린 수 | `0` |
| publish_inflight | 정수 | 응답 기다리는 수. `published = acked + unacked_lost + inflight` 가 성립하도록 센다. 단 발행 스레드가 바꾸는 값을 상태 스레드가 잠금 없이 읽으므로 한 메시지 안에서 1~2 어긋날 수 있다 [추정, 코드 구조]. 수신 쪽은 이 등식으로 경보를 내지 않는다 | `0` |
| mqtt_renewals | 정수 | 끊겨서 클라이언트를 새로 만든 횟수 | `0` |
| mqtt_connected | 참/거짓 | 발행 측 연결 상태. **받았다면 항상 true 라 수신 측 판단에는 쓸모없다** | `true` |
| oversize_payload | 정수 | 16000 B 초과로 안 보낸 수 | `0` |
| uptime_sec | 실수 | 앱 시작 후 초 | `16.7` |

근거: 필드 `app/main.py:156-175`, `source_connected` 3초 `app/source.py:26-28`, 크기 검사 `app/main.py:213-216`, 계수 관계 `README.md:34-39`·`app/publisher.py:117-133,160-163`, status 는 계수 밖 `app/publisher.py:167-169`, 시작 상태 `LOST` `zone/marker_zone.py:44`·`app/main.py:150`, 같은 번호 두 번 `zone/marker_zone.py:49-62`.
위 표의 예 가운데 `ts`·`frames_*`·`uptime_sec` 등은 시험 로그 첫 줄 값, `cuda:0`·`10.0`·`12.4`·`5980` 등은 설명용 값이다.

### 살아 있음 판단 [제안]

1. `stream_id` 별로 마지막 status 수신 시각을 둔다. **3초 동안 없으면 끊김**(QoS 0 이라 한두 개는 빠질 수 있다).
2. 문자열 `offline` 을 받으면 즉시 끊김. 단 `offline` 에는 `stream_id` 가 없다. 앱이 둘 이상이면 어느 것인지 모르므로, 받은 뒤 3초 안에 status 가 오는 흐름은 살아 있다고 다시 본다.
3. `offline` 은 JSON 이 아니다. 파싱 전에 바이트가 정확히 `offline` 인지 먼저 본다.
4. 받고 있어도 근거가 쓸 만한지는 따로 본다: `source_connected == true` 이고 `infer_fps_1s > 0` 이고 `marker_state == "OK"`. 하나라도 아니면 "앱은 살아 있으나 판정 불가"로 표시.
5. `stream_epoch` 가 바뀌거나 `uptime_sec` 가 줄면 앱이 다시 시작된 것이다(누적 계수도 0 부터 다시 센다).
6. `mqtt_connected` 는 판단에 쓰지 않는다(위 표).

### 예시 (실제 수신, 시험 모드 status 첫 줄을 축약)

시험 모드라 주제가 `relay/test/status/vision`, `stream_id` 가 `ceiling-test`, `marker_state` 가 null 이다. 운영 status 는 형식이 같다.

```json
{"status": "online", "ts": 1794631056.004, "stream_id": "ceiling-test", "stream_epoch": "1794631039-cf1d6015",
 "model_id": "pinky-v1", "calibration_id": "ceil-20261108", "clock_error_sec": 0.05,
 "weights_sha256": {"pinky_v2_final.pt": "58a8fe5f…533c0573", "kneg_d_final.pt": "f7991cdc…ab68595bd"},
 "device": "cpu", "publish": true, "source_connected": true, "source_connect_attempts": 1, "source_connect_failures": 0,
 "frames_received": 157, "frames_inferred": 17, "frames_skipped_wrong_size": 0, "last_frame_size": [1080, 1440],
 "infer_fps_1s": 1.0, "infer_fps_avg": 1.37, "infer_ms_last": 880.8, "infer_ms_avg": 726.8,
 "zones_frames_emitted": 0, "zones_frames_refused": 0, "last_refusal": null, "marker_state": null, "markers_seen": 0,
 "last_zones": null, "publish_queue_drops": 0, "publish_drops_detail": {"overflow": 0, "stale": 0, "rc": 0},
 "publish_queue_len": 0, "published": 17, "published_acked": 17, "publish_unacked_lost": 0, "publish_inflight": 0,
 "mqtt_renewals": 0, "mqtt_connected": true, "oversize_payload": 0, "uptime_sec": 16.7}
```

(해시는 가운데를 `…` 로 줄였다. 원문은 `mqtt_10min.log:1`.)

---

## 3. `relay/evidence/zones`

[사실] `zone/zone_evidence_msg.py:79-82` 가 만든 dict 를 키를 더하지 않고 그대로 보낸다(`app/main.py:236`). 10개 필드. 감시 노드 계약(`cobot_anomaly_monitor/load_evidence.py`)에 맞춘 형식이다.

| 이름 | 형식 | 의미 / 값 범위 |
|---|---|---|
| source_kind | 문자열 | 이 앱은 항상 `"model_output"`(`app/main.py:133-134` 가 기본값을 바꾸지 않음). `"sim_fixture"` 는 감시 노드 쪽 재생 도구가 내는 값이다(`cobot_anomaly_monitor/replay_evidence.py:89`) |
| stream_id | 문자열 | `"ceiling"` |
| stream_epoch | 문자열 | 앱 시작마다 새 값. 비어 있지 않다 |
| frame_seq | 정수 ≥0 | zones 프레임 번호, 0 부터. 같은 epoch 안에서 만든 프레임마다(마커 OK 아님 포함, 시각 거절 제외) 1씩 늘어난다. **boxes 의 `frame_seq` 와 다른 번호다**(4절) |
| capture_time | 실수(Unix 초) | 추론 PC 가 프레임을 **받은** 시각(폰 촬영 시각 아님). 같은 epoch 안에서 엄격히 증가 |
| clock_error_sec | 실수 0~0.25 | 지금 `0.05` 고정(`app/config.py:8`) |
| model_id | 문자열 | `"pinky-v1"` |
| calibration_id | 문자열 | `"ceil-20261108"` |
| marker_state | 문자열 | `OK` / `FIXED` / `HOLD` / `CONFLICT` / `LOST` (아래). 이 프레임 추론 때의 값을 그대로 싣는다 |
| zones | 객체 | 키 `ZA`, `ZB`, `ZC`. 값 `LOADED` / `EMPTY` / `NO_ROBOT` / `MULTI` |

근거: 필드 `zone/zone_evidence_msg.py:79-82`, capture_time 은 수신 시각 `app/source.py:56-61`, frame_seq 증가 `zone/zone_evidence_msg.py:77`(거절은 `:59-66` 에서 먼저 돌아가 번호를 쓰지 않음), 증가 검사 `zone/zone_evidence_msg.py:61-62`.

[사실] MQTT 에 실리는 구역 값은 위 네 가지뿐이다. `zone/pinky_evidence.py` 의 창 상태(`BOX`·`FILLING`·`MIXED`·`UNKNOWN`)와 `zone/vision_answer.py` 의 답은 이 앱이 불러오지 않으므로 메시지에 나오지 않는다(`README.md:52-53`, `app/*.py` 에 import 없음).

**구역 값** [사실, `zone/zone_evidence_msg.py:24-38`, `zone/tray_zones.py:36-40`]: 신뢰도 0.5 이상인 핑키 검출의 상자 중심이 구역 윤곽 안(또는 20 px 이내)에 있는 수로 정한다. 한 상자가 두 구역에 함께 들 수도 있다(`zone_of` 가 목록을 돌려줌).

| 값 | 뜻 |
|---|---|
| LOADED | 핑키 1대, 클래스 `pinky_loaded`(상자를 실음. 테두리에 걸친 상자도 적재로 본다) |
| EMPTY | 핑키 1대, 클래스 `pinky_empty` |
| NO_ROBOT | 핑키 없음. **"없다"가 아니라 "못 봤다"일 수 있다**. 마커가 OK 가 아니면 모든 구역이 NO_ROBOT 로 채워진다 |
| MULTI | 핑키 2대 이상 |

**marker_state** [사실, `zone/marker_zone.py:10-15`, 판단 `zone/marker_zone.py:81-111,121-126`, 판정 주기 1초 `app/main.py:135`]: 천장의 ArUco 마커 40~43 으로 카메라 자세를 확인한다. 마커는 약 1초에 한 번만 읽고 그 사이 프레임은 직전 판정을 그대로 쓴다(CPU 처럼 프레임 간격이 1초에 가까우면 약 1.7초에 한 번, `README.md:42-43`).

| 값 | 뜻 | zones 를 믿어도 되나 |
|---|---|---|
| OK | 마지막 검사에서 마커 4개를 모두 읽음 | 예 |
| FIXED | 2~3개만 읽고, 마지막 4개짜리 사각형을 닮음(2개)·아핀(3개) 변환으로 보정 | **아니오**. 앱은 OK 가 아니면 구역 판정을 하지 않고 전부 NO_ROBOT 로 보낸다(`zone/zone_evidence_msg.py:67,73-76`) |
| HOLD | 0~1개만 읽음, 마지막 사각형 유지(갱신 30초 이내) | 아니오(같은 이유) |
| CONFLICT | 사각형 검사 실패: 4개를 읽었으나 넓이·볼록 검사에 걸림, 또는 2~3개로 보정한 사각형이 검사(직전보다 120 px 넘게 움직임 등)에 걸림 | 아니오 |
| LOST | 사각형 없음(시작 직후 포함) 또는 30초 넘게 갱신 안 됨 | 아니오 |

[사실] 구역 판정 자체는 마커를 따라가지 않는다. 11-08 카메라 자세로 고정한 픽셀 윤곽(`zone/zones-tray-px-20261108.json`, `zone/tray_zones.py:3-7`)을 쓰고, 마커는 "카메라가 그대로인가"를 거르는 데만 쓴다.

**시각 규칙** [사실]: 앱은 `capture_time - clock_error_sec > now`(미래) 또는 `now - capture_time + clock_error_sec > 3`(3초 초과)인 프레임을 만들지 않는다(`zone/zone_evidence_msg.py:63-66`). 감시 노드도 같은 규칙으로 버린다(`load_evidence.py:98`). 추론 PC 와 수신 PC 의 시계가 0.05초 안으로 맞는지는 **확인하지 않았다** [추정 위험].

**감시 노드가 쓰는 방법** [사실, `src/cobot_anomaly_monitor/cobot_anomaly_monitor/`]

- `mqtt_evidence.py:28` 가 `relay/evidence/zones` 만 QoS 1 로 구독하고, retain 이거나 16384 B 를 넘으면 버린다(`:31`). JSON 파싱 실패는 경고 로그 후 버리고, JSON 이지만 객체(dict)가 아니면 로그 없이 버린다(`:33-38`). 남은 것을 ROS `/anomaly_monitor/zone_evidence` 로 옮긴다. 필드 검사는 여기서 하지 않고 아래 `observe()` 가 한다.
  - 이 수신기는 `ROS_DOMAIN_ID` 가 77/140 이고 `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` 일 때만 뜬다(`:16-18`). 브로커 기본값은 `127.0.0.1`(`:13`)이라 중계 브로커를 쓰려면 `--broker` 를 줘야 한다.
- `load_evidence.py:85-129` `observe()`: 대기 중(PENDING)인 작업 요청마다 프레임 하나를 넣는다(`manual_adapter.py:133-142`). `received` 는 그 요청이 저장된 시각(`created_at`)이다.
  - 다음 가운데 하나면 그 요청의 창을 비운다(`:87-102`): 호기 위치·정지·구역 귀속 검사 실패(`attribution()`, `:23-83`), `stream_id`·`model_id`·`calibration_id` 가 설정과 다름, `source_kind` 가 `model_output`/`sim_fixture` 가 아님, `clock_error_sec` 가 0~0.25 밖, 시각 규칙 위반, **요청을 받은 시각보다 먼저 찍힌 프레임**(`ts - error < received`), `frame_seq` 가 0 이상 정수가 아님.
  - `stream_epoch` 가 비었거나 문자열이 아니면 창을 비운다(`:104-108`).
  - `capture_time` 이 직전 프레임보다 늘지 않으면(epoch 와 무관) 또는 같은 epoch 에서 `frame_seq` 가 늘지 않으면 그 프레임만 무시한다. epoch 가 바뀌면 창을 비우고 새로 센다(`:109-115`).
  - `marker_state != "OK"` 이거나 요청의 상차 구역(`route.pickup`) 값이 `LOADED` 가 아니면 창을 비운다(`:117-121`). 상차 구역은 `ZA`·`ZB` 만 인정한다(`:35`). **ZC 값은 적재 판정에 쓰이지 않는다.**
  - 남은 프레임은 최근 3개, 3초 이내만 둔다(`:128`).
- `manual_adapter.py:153-174`: LOADED 프레임 3개 + 사람의 팔 퇴피 확인(요청 `timeout_sec`, 없으면 60초 안, `:8,160-164`)이 모이고, 그때 다시 본 귀속 검사와 프레임 나이(3초)도 통과하면 `load_present=True` 로 승인한다(`:165-174`).
- 제약: 이 결합(`verify_load_join`)은 기본값이 꺼짐(`monitor_node.py:60`)이고, 켜려면 `manual_adapter=True`, `camera_policy=sim`, `ROS_DOMAIN_ID` 77/140, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` 가 모두 맞아야 한다. 아니면 노드가 시작하지 않는다(`monitor_node.py:99-103`). 기본 `calibration_id` 는 `replay-v1` 이라(`monitor_node.py:61`) `ceil-20261108` 을 주지 않으면 모든 프레임을 거절한다(`README.md:47-50`). `stream_id`(`evidence_stream`)·`model_id`(`load_model`) 기본값은 `ceiling`·`pinky-v1` 로 앱과 같다(`monitor_node.py:61-62`). **현장에서 감시 노드가 이 메시지를 받아 쓴 기록은 없다.**

### 예시 (코드로 만든 예)

`ZoneEvidenceEmitter` 에 ZA 중심의 `pinky_loaded` 검출 1개를 넣어 만든 출력이다(287 B).

```json
{"source_kind":"model_output","stream_id":"ceiling","stream_epoch":"1794631039-cf1d6015","frame_seq":0,"capture_time":1794631117.805,"clock_error_sec":0.05,"model_id":"pinky-v1","calibration_id":"ceil-20261108","marker_state":"OK","zones":{"ZA":"LOADED","ZB":"NO_ROBOT","ZC":"NO_ROBOT"}}
```

같은 입력에서 마커가 HOLD 일 때(구역 값을 판정하지 않음):

```json
{"source_kind":"model_output","stream_id":"ceiling","stream_epoch":"1794631039-cf1d6015","frame_seq":1,"capture_time":1794631117.905,"clock_error_sec":0.05,"model_id":"pinky-v1","calibration_id":"ceil-20261108","marker_state":"HOLD","zones":{"ZA":"NO_ROBOT","ZB":"NO_ROBOT","ZC":"NO_ROBOT"}}
```

---

## 4. `relay/evidence/boxes`

[사실] `app/main.py:237-244` 에서 프레임마다 만든다. zones 를 거절한 프레임에도 보낸다. 19개 필드.

| 이름 | 형식 | 의미 |
|---|---|---|
| source_kind | 문자열 | `"model_output"` |
| stream_id, stream_epoch | 문자열 | zones 와 같다 |
| frame_seq | 정수 ≥0 | **추론한 프레임 번호**(`frames_inferred - 1`). zones 의 frame_seq 와 다르다 |
| zones_frame_seq | 정수 또는 null | 같은 프레임의 zones `frame_seq`. zones 를 거절했으면 null. 두 메시지를 잇는 열쇠 |
| capture_time | 실수 | zones 와 같은 규칙(프레임 받은 시각) |
| clock_error_sec, model_id, calibration_id | | zones 와 같다 |
| marker_state | 문자열 | 이 프레임의 마커 상태(OK 가 아니어도 그대로) |
| device | 문자열 | `"cuda:0"` 등 |
| weights_sha256 | 객체 | status 와 같다 |
| frame_size | [폭, 높이] | `[1080, 1440]` (세로 화면) |
| conf_min | 실수 | 보낸 검출의 최소 신뢰도 `0.5` |
| box_model | 문자열 | `"kneg-d-final"` |
| pinky_model | 문자열 | `"pinky-v2-final"` |
| boxes | 배열 | 상자 모델 검출. 항목 `cls`(정수), `name`, `confidence`(소수 4자리), `bbox` [x0, y0, x1, y1] 원본 프레임 픽셀(소수 1자리). 앱이 따로 정렬하지 않고 모델 출력 순서 그대로 담는다(ultralytics 는 보통 신뢰도 내림차순 [추정]) |
| pinky | 배열 | 핑키 모델 검출. 항목은 boxes 와 같고 `zones`(그 상자 중심이 든 구역 이름 배열, 예 `["ZA"]` 또는 `[]`)가 더 있다. **`zones` 는 마커 상태와 상관없이 11-08 픽셀 윤곽으로 계산한다.** `marker_state` 가 OK 가 아닌 프레임의 이 값은 구역 판정으로 쓰지 않는다 |
| truncated | 정수 | 배열마다 50개 상한으로 잘린 수의 합(0.5 이상 가운데 앞 50개만 담음) |

근거: 필드 `app/main.py:239-244`, 항목 형식·0.5 거름·50개 상한 `app/main.py:75-83`, 핑키 `zones` 는 마커 검사 없이 `zone_of` 호출 `app/main.py:132,237`, 검출 형식 `app/detector.py:22-23`.

**신뢰도** [사실, `app/config.py:6`]: 모델은 0.25 이상(`PREDICT_CONF`)을 내고, 메시지에는 0.5 이상(`EVIDENCE_CONF`)만 담는다. 구역 판정도 0.5 를 쓴다(`app/main.py:134`). 0.5 는 측정으로 정한 값이 아니다(`zone/pinky_evidence.py:19-20` "window, need and conf are not measured values"). 현장 영상으로 맞춘 기록도 없다.

**상자 모델 클래스 6종** [사실: 이름·번호는 `weights/kneg_d_final.pt` 의 `names`, 한국어 뜻은 `scripts/vision/edge_view/stream_page.html:33`, 이상 분류는 `scripts/vision/edge_view/edge_view.py:82`]

| cls | name | 뜻 | 구분 |
|---|---|---|---|
| 0 | box_on_floor | 바닥에 떨어진 상자 | 이상 |
| 1 | box_perched_on_rim | 적재판 턱에 걸친 상자 | 이상 |
| 2 | box_run_over | 로봇에 깔린 상자 | 이상 |
| 3 | lid_detached | 뚜껑 분리 | 이상 |
| 4 | box_on_tray | 적재판 위 정상 상자 | 정상 |
| 5 | box_stock | 재고 상자 | 정상 |

핑키 모델: 0 `pinky_loaded`, 1 `pinky_empty` (`weights/pinky_v2_final.pt` 의 `names`).
주의 [사실, `zone/pinky_evidence.py:3-4`]: 핑키 모델 정의에서는 테두리에 걸친 상자도 `pinky_loaded` 다. 걸침 이상은 상자 모델의 `box_perched_on_rim` 으로 따로 본다.

### 예시 (코드로 만든 예, 776 B)

```json
{"source_kind":"model_output","stream_id":"ceiling","stream_epoch":"1794631039-cf1d6015","frame_seq":12,"zones_frame_seq":12,"capture_time":1794631117.805,"clock_error_sec":0.05,"model_id":"pinky-v1","calibration_id":"ceil-20261108","marker_state":"OK","device":"cuda:0","weights_sha256":{"pinky_v2_final.pt":"58a8fe5fcd1fe5e020e32bbb845ea3fd6b33d40d3e614fad9d069f5a533c0573","kneg_d_final.pt":"f7991cdc2cebd052fb80b148bb126135c4a212890aa5a5359461d98ab68595bd"},"frame_size":[1080,1440],"conf_min":0.5,"box_model":"kneg-d-final","pinky_model":"pinky-v2-final","boxes":[{"cls":4,"name":"box_on_tray","confidence":0.9312,"bbox":[752.3,310.8,806.1,360.2]}],"pinky":[{"cls":0,"name":"pinky_loaded","confidence":0.91,"bbox":[740.0,301.0,820.0,371.0],"zones":["ZA"]}],"truncated":0}
```

크기 상한 [추정·계산]: 검출 1개가 약 95~110 B 라 두 배열 50개씩 꽉 차도 약 11 KB 로 16000 B 아래다.

---

## 5. 시험 주제 (DETECT_ONLY) — **운영에 쓰지 말 것**

[사실] 미커밋 시험 모드다(`~/kr4-vision-test/scripts/vision/homelab_vision/app/config.py:28-33`, `app/main.py:144-154,246-252`, `app/publisher.py:135-161`). 현장 이미지 `homelab-vision:20261110` 에는 없다. `DETECT_ONLY=true` 이면

- 구역 판정과 마커를 건너뛰고, 운영 주제(`relay/evidence/zones`, `relay/evidence/boxes`, `relay/status/vision`)에는 **쓰지 않는다**.
- `stream_id` 가 `ceiling-test`, 상태·유언 주제가 `relay/test/status/vision` 으로 바뀐다. 상태 형식은 2절과 같고 `marker_state`·`last_zones` 는 null, `markers_seen`·zones 계수는 0, `infer_ms_*` 는 두 모델만이다.
- `relay/test/vision/detections` 를 QoS 0 으로 프레임마다 보낸다(2초 폐기 규칙은 같다).
- `FRAME_SIZE=폭x높이` 로 입력 크기를 바꿀 수 있다(기본 1080x1440, `config.py:11-22`). **주의 [사실]**: 이 설정은 `DETECT_ONLY` 와 무관하게 먹는다. 운영 모드에서 크기를 바꾸면 1080x1440 기준 11-08 픽셀 윤곽으로 구역을 판정하게 되므로, 운영에서는 `FRAME_SIZE` 를 주지 않는다.

관제 수신 코드는 `relay/test/#` 를 운영 판단에 넣으면 안 된다. 내용은 구역·마커 검사를 거치지 않은 검출이다.

`relay/test/vision/detections` 필드(18개):

| 이름 | 형식 | 의미 |
|---|---|---|
| source_kind | 문자열 | `"model_output_test"` (운영 `model_output` 과 다르다) |
| stream_id, stream_epoch, frame_seq | | `ceiling-test`, 앱 시작 식별자, 추론 프레임 번호 |
| capture_time | 실수 | 프레임 받은 시각 |
| model_id, device, frame_size | | `pinky-v1`, 추론 장치, [폭, 높이] |
| infer_ms | 실수 | 이 프레임 추론 시간 ms |
| predict_conf / conf_min | 실수 | 0.25 / 0.5 |
| pinky_model / box_model | 문자열 | `pinky-v2-final` / `kneg-d-final` |
| pinky | 배열 | 핑키 검출 **0.25 이상 전부**, 신뢰도 높은 순, 최대 50. 항목 `cls`, `name`, `confidence`, `bbox_norm` [x0, y0, x1, y1] 0~1 정규화(운영은 픽셀) |
| pinky_truncated | 정수 | 50개 넘어 잘린 수 |
| pinky_counts_conf_ge_min | 객체 | 0.5 이상 클래스별 수 |
| boxes_count / boxes_count_all | 정수 | 상자 검출 수(0.5 이상 / 0.25 이상 전부). 상자 목록은 보내지 않는다 |

없는 필드 [사실, `app/main.py:247-252`]: `clock_error_sec`, `calibration_id`, `marker_state`, `zones_frame_seq`, `weights_sha256`. 그래서 감시 노드 규칙(3절)도 통과하지 못한다.

### 실제 수신 예 (`~/doc/logs/vision-test-20261114/mqtt_10min.log`, 2026-11-14 13:37~13:47, 루프백 시험 브로커 18883)

시험 브로커는 운영 브로커와 별개였다(`broker/mosquitto.conf`: `listener 18883 127.0.0.1`). 10분에 detections 904건, status 599건. CPU 추론이라 평균 1.5 fps 였다(마지막 status `infer_fps_avg`).

```json
{"source_kind":"model_output_test","stream_id":"ceiling-test","stream_epoch":"1794631039-cf1d6015","frame_seq":116,"capture_time":1794631117.8052702,"model_id":"pinky-v1","device":"cpu","frame_size":[1080,1440],"infer_ms":626.9,"predict_conf":0.25,"conf_min":0.5,"pinky_model":"pinky-v2-final","box_model":"kneg-d-final","pinky":[{"cls":1,"name":"pinky_empty","confidence":0.9443,"bbox_norm":[0.4826,0.2808,0.5461,0.3306]},{"cls":1,"name":"pinky_empty","confidence":0.9372,"bbox_norm":[0.487,0.3402,0.5338,0.3825]},{"cls":1,"name":"pinky_empty","confidence":0.8777,"bbox_norm":[0.4864,0.3993,0.5324,0.4509]}],"pinky_truncated":0,"pinky_counts_conf_ge_min":{"pinky_empty":3},"boxes_count":4,"boxes_count_all":4}
```

(`mqtt_10min.log:163` 원문 그대로, frame_seq 116. status 실제 예는 2절.)

---

## 6. 식별자 규칙

| 식별자 | 현재 값 | 규칙 | 근거 |
|---|---|---|---|
| stream_id | `ceiling` (시험 `ceiling-test`) | 카메라 흐름 하나에 하나. 앱 하나가 흐름 하나를 맡는다. 감시 노드 `evidence_stream` 기본값과 같다 | `app/config.py:8`, `monitor_node.py:61` |
| stream_id (다중 카메라) | **[계획]** 상하차 카메라용 이름은 **아직 없다**(계획 문서에도 코드에도 정한 이름이 없다). 정해지기 전에는 `ceiling` 이외의 값을 "모르는 흐름"으로 다룬다 | 주제는 그대로 두고 `stream_id` 로 나누는 안이 기본안. 상하차 흐름은 보정 파일이 없어 좌표 없이 상태만 내는 안 | `~/doc/VISION_DUAL_STREAM_AND_MODEL_ENHANCEMENT_PLAN_20261113.md:17,53` |
| stream_epoch | `{시작 Unix 초}-{uuid 8자}` | 앱 시작마다 새로. 순서·중복 판단은 (stream_id, stream_epoch, frame_seq) 로 | `app/main.py:117` |
| model_id | `pinky-v1` | 감시 노드 `load_model` 과 같아야 한다. 가중치 파일 이름(`pinky_v2_final`)과 별개인 계약 이름 | `app/config.py:8`, `monitor_node.py:62` |
| calibration_id | `ceil-20261108` | 구역 픽셀 윤곽 판. 카메라를 옮겨 구역을 다시 만들면 바꿔야 한다 | `app/config.py:8`, `app/config.py:11` |
| weights_sha256 | `pinky_v2_final.pt` 58a8fe5fcd1fe5e020e32bbb845ea3fd6b33d40d3e614fad9d069f5a533c0573 / `kneg_d_final.pt` f7991cdc2cebd052fb80b148bb126135c4a212890aa5a5359461d98ab68595bd | 시작 때 `PACKET_SHA256SUMS` 와 다르면 앱이 뜨지 않는다 | `app/main.py:92-97`, `README.md:13-14` |

---

## 7. 수신 쪽(비전 어댑터) 구현 체크리스트

- [ ] 구독: `relay/status/vision`(QoS 0 으로 충분), `relay/evidence/zones`·`relay/evidence/boxes`(QoS 1). `relay/test/#` 는 구독하지 않거나 운영 경로와 분리.
- [ ] 이 주제들에 **발행하지 않는다**(발행자는 비전 앱 하나뿐이어야 한다).
- [ ] 클라이언트 ID 는 `homelab-vision-` 로 시작하지 않게(겹치면 브로커가 앞 연결을 끊는다).
- [ ] status 주제는 먼저 바이트가 `offline` 인지 보고, 아니면 JSON 파싱.
- [ ] JSON 파싱 실패, dict 가 아님, 필수 키 없음 → 버리고 경고 로그만. (감시 노드 수신기 `mqtt_evidence.py:33-38` 는 파싱 실패만 경고하고, dict 아님은 조용히 버리며, 필수 키 검사는 `load_evidence.py:91-108` 에서 한다.)
- [ ] 16384 B 초과·retain 메시지 → 버린다(`mqtt_evidence.py:31`). 앱은 16000 B 넘는 것을 보내지 않는다.
- [ ] `stream_id` 로 흐름을 나누고, 흐름마다 (stream_epoch, frame_seq, capture_time) 최고값을 둔다. epoch 가 같고 seq 가 같거나 작으면 중복·역순으로 버린다. epoch 가 바뀌면 그 흐름 상태를 비운다. 감시 노드는 여기에 더해 `capture_time` 이 늘지 않으면 epoch 가 바뀌어도 버린다(`load_evidence.py:111`).
- [ ] boxes 의 `pinky[].zones` 는 마커 검사를 거치지 않은 값이다. 구역 판정은 zones 메시지(`marker_state == "OK"`)로만 한다.
- [ ] zones 와 boxes 의 `frame_seq` 는 별개 번호다. 같은 프레임은 boxes 의 `zones_frame_seq` 로 잇는다.
- [ ] 시각 검사: `capture_time - clock_error_sec > now` 또는 `now - capture_time + clock_error_sec > 3` 이면 버린다. 추론 PC 와 수신 PC 의 시계 동기(NTP)를 먼저 확인한다.
- [ ] `marker_state != "OK"` 인 zones 는 판정 불가(전부 NO_ROBOT 로 와도 "로봇 없음"이 아니다). status 의 `last_zones` 도 같은 이유로 `marker_state` 와 함께 본다.
- [ ] `NO_ROBOT`, `MULTI` 는 미정으로 다룬다. 적재 근거는 `LOADED` 뿐이다.
- [ ] 끊김 판정: status 3초 없음 또는 `offline` (2절 제안).
- [ ] retain 이 없다: **구독 시작 직후에는 상태를 모른다**. 첫 status 를 받기 전(최대 약 1초)과 첫 zones 를 받기 전은 "모름"으로 시작한다.
- [ ] 끊긴 동안의 근거는 다시 오지 않는다. 재접속 뒤 이전 창을 이어 붙이지 않는다.

### 확인 명령 (읽기만, 중계 브로커에서 구독)

```bash
# 상태 1초마다(5건만 받고 끝)
mosquitto_sub -h 192.168.0.8 -p 1883 -i cc-dev-$USER -v -t relay/status/vision -C 5

# 근거 두 주제(10건)
mosquitto_sub -h 192.168.0.8 -p 1883 -i cc-dev-$USER -v -t 'relay/evidence/#' -C 10

# 메시지 크기(바이트)만 보기
mosquitto_sub -h 192.168.0.8 -p 1883 -i cc-dev-$USER -t relay/evidence/boxes -C 50 | LC_ALL=C awk '{print length($0)}'

# 마커·구역만 보기(jq 있을 때)
mosquitto_sub -h 192.168.0.8 -p 1883 -i cc-dev-$USER -t relay/evidence/zones -C 20 | jq -c '{frame_seq, marker_state, zones}'
```

`-i` 를 주지 않으면 mosquitto_sub 가 임의 ID 를 쓴다. 브로커 주소가 바뀌었으면 중계 노트북 주소를 먼저 확인한다. 앱이 `PUBLISH=false` 로 떠 있으면 아무것도 오지 않는다.

---

## 8. 관제 시나리오와 잇기 (비전 어댑터)

이 절의 관제 코드 근거는 control-center **7f2b2e3**(`src/cobot_fleet_control/cobot_fleet_control/`, 아래 `FC/`)이다. b554975 는 같은 파일이 `src/cobot_navigation/cobot_fleet_control/` 에 있다.

### 8-1. 관제는 MQTT 를 받지 않는다 [사실]

- 허지혁 님이 97be6c7(11-05)에서 관제의 MQTT 접수를 일부러 뺐다. 커밋 메시지: "중복 MQTT 접수·브로커를 제거하고 웹 관제와 ROS 요청·결과 경계 분리".
- 시나리오 상태(단계 완료·보류·재시도)를 바꾸는 장치 쪽 입구는 `/fleet/work_request` → `/fleet/work_result` 하나다(`FC/fleet_control_node.py:40,102,146-152`).
- 그래서 비전 메시지를 관제 노드가 직접 구독하지 않는다. **비전 어댑터**가 MQTT 를 받아 두고, 관제가 `target: "vision"` 요청을 보내면 그 요청에 `work_result` 로 답한다.
- 비전 어댑터는 **아직 없다**(팀 원격·우리 원격 모두). **우리(중계 쪽)가 만든다** [결정 11-14]. 관제는 이미 있는 `/fleet/work_result` 수신을 그대로 쓴다. 역할 분담과 협의할 것은 8-7.

```
비전 앱 ──MQTT relay/evidence/zones·boxes, relay/status/vision──▶ 비전 어댑터(없음)
관제 fleet ──/fleet/work_request (target=vision)──▶ 비전 어댑터
비전 어댑터 ──/fleet/work_result (source=vision)──▶ 관제 fleet ──▶ SQLite 원장
```

### 8-2. 요청 `/fleet/work_request` [사실]

- 타입 `std_msgs/String`, 내용은 JSON 객체.
- 필드: `request_id`, `order_id`, `robot_id`, `stage`, `target`, `action`, `sku`, `quantity`, `attempt`, `route`(`pickup`·`dropoff`·`pickup_arm`·`dropoff_arm`·`lane`), `timeout_sec`(300) (`FC/scenario_runtime.py:84-88`).
- 관제가 덧붙이는 봉투: `session_id`, `seq`(대상별 순번), `issued_at`, `ttl_sec` (`FC/fleet_control_node.py:146-152`).
- 모든 대상이 한 주제를 같이 쓴다. 어댑터는 `target == "vision"` 인 것만 받는다.
- 관제의 정지 요청(`stage: "SAFETY"`, `action: "hold"`·`"release_hold"`)은 팔 대상에만 간다(`FC/fleet_control_node.py:138-144,177-181`). 비전 어댑터는 받을 일이 없다.
- 관제 주석: "장치 어댑터는 request_id로 중복을 제거하고 실측한 최종 결과를 반환한다"(`FC/fleet_control_node.py:147`).

### 8-3. 결과 `/fleet/work_result` [사실]

관제가 받아들이는 조건(`FC/scenario_runtime.py:173-196`):

| 항목 | 값 | 어기면 |
|---|---|---|
| `request_id`, `robot_id`, `stage` | 요청 값을 그대로 복사 | 조용히 버림 |
| `source` | 문자 그대로 `"vision"` (경로 설정에 vision 키가 없어서 기본값) | 조용히 버림 |
| `measured`, `finished` | 둘 다 `true` | 조용히 버림 |
| `success` | bool | 예외(요청 거절) |
| `data` | JSON 객체 | 예외(요청 거절) |
| 전체 크기 | JSON 객체, 16 KiB 이하 (`FC/fleet_control_node.py:183-189`) | 거절 |

- 받는 순간 로봇 신선도도 본다. 로봇 상태가 3초(`stale_sec`), 배터리가 10초(`battery_stale_sec`)를 넘게 끊겼거나 단계 마감(300초)이 지났으면 주문을 **UNKNOWN** 으로 보류한다(`FC/scenario_runtime.py:185-189`, `FC/scenario.py:103-108`, `config/scenario.yaml`).
- `success: false` 이면 `data.retry_safe: true` 일 때만 재시도한다(최대 3회, VERIFY_LOAD 는 LOAD 와 횟수를 같이 씀). 그 밖에는 UNKNOWN(`FC/scenario_nodes.py:132-137`, `FC/scenario_runtime.py:92-97`).
- `success: true` 인데 8-4 의 필드가 모자라면 단계를 끝내지 않고 다음 결과를 기다린다("완료 증거 부족"). 같은 `request_id` 로 다시 보낼 수 있다. 300초 안에 못 채우면 "단계 결과 시간 초과"로 UNKNOWN(`FC/scenario_nodes.py:94-96,138-140`).
- 관제는 11-09 이후 결과의 시각·TTL 을 비교하지 않는다. **오래된 근거를 거르는 일은 어댑터 몫이다**(8-5).
- 관제 원장에는 단계 완료만 남고 결과 `data` 는 남지 않는다(`FC/scenario_runtime.py:40-45`). 근거 기록은 어댑터가 따로 남겨야 한다.

예 (코드로 만든 예, VERIFY_LOAD 성공):

```json
{"request_id":"<요청 값>","robot_id":"pinky1","stage":"VERIFY_LOAD","source":"vision",
 "measured":true,"finished":true,"success":true,
 "data":{"load_present":true,"arm_safe":true,
         "evidence":{"stream_id":"ceiling","stream_epoch":"<값>","frame_seq":[1201,1202,1203],
                     "capture_time_max":1794631100.42,"zone":"ZA","state":"LOADED"}}}
```

`evidence` 안의 이름은 관제가 읽지 않는다. 어댑터가 정하는 기록용 값이다 [제안].

### 8-4. 비전 9단계와 지금 메시지로 답할 수 있는 것

관제 쪽 판정은 `FC/scenario_contracts.py:13-26`(단계·action), `FC/scenario_nodes.py:149-194`(필드) [사실].

| 단계 | action | 관제가 요구하는 `data` | 지금 비전 메시지로 | 비고 |
|---|---|---|---|---|
| PICKUP_EXIT, PATH_EXIT, RETURN_EXIT | `path_exit` | `clear: true` (이때 통로 `lane_main` 예약을 푼다) | **없음.** zones 는 작업 구역 ZA·ZB·ZC 만 본다. 통로는 보지 않는다 | [추정] "목표 구역 안에 로봇이 보임"을 통로 이탈 근거로 써도 되는지 허지혁 님 확인 필요 |
| DOCK_PICKUP, DOCK_DROPOFF | `dock_check` | `xy_m`, `yaw_deg` 숫자. 공차(0.01 m, 15도) 안이면 `stopped`·`base_hold` 도 `true` | **없음.** 정차 오차를 재지 않는다 | 공차 밖이면 `navigation` 의 `dock_correct` 로 넘어간다 |
| MARKER, QR | `marker`, `qr` | `sku` 가 주문 `sku` 와 같아야 함. 다르면 UNKNOWN(상품 불일치) | **없음** | boxes 의 상자 6종 이름을 sku 로 쓸 수 있는지는 미정 [추정]. 요청 `sku` 를 그대로 복사해 보내면 검사가 무의미해진다 |
| VERIFY_LOAD | `verify_load` | `load_present: true`, `arm_safe: true` | **`load_present` 만**: 상차 구역(ZA·ZB) `LOADED`. `arm_safe` 는 비전에 없다 | `arm_safe` 출처를 정해야 함(팔 어댑터 결과 결합 또는 운영자 확인) |
| VERIFY_UNLOAD | `verify_unload` | `placed`, `arm_safe`, `load_absent` 모두 `true` | **`load_absent` 후보만**: ZC 에서 `EMPTY`. `placed`·`arm_safe` 없음 | 감시 노드는 지금 ZC 를 쓰지 않는다(3절) |

정리: 지금 메시지만으로 온전히 답할 수 있는 비전 단계는 **없다**. VERIFY_LOAD·VERIFY_UNLOAD 는 일부, 나머지 7개는 비전 근거 자체가 없다.

### 8-5. 비전 어댑터 규칙 [제안]

1. **사람 승인은 보내지 않는다** [결정 11-14]: 관제에 보내는 결과는 카메라·팔 결과로만 만든다. `measured: true` 는 모델 추론 근거로 판정했을 때만 붙인다. 허지혁 님 원칙(c995902 문서 "measured=true 결과를 만들어 넣지 않는다")과 같다.
2. **요청 뒤 근거만**: 요청을 받은 시각 이후에 찍힌 프레임(`capture_time`)만 쓴다. 7절의 시각 검사(3초)와 `marker_state == "OK"` 를 지키고, 같은 판정이 연속 N 프레임(감시 노드 결합 시험은 3) 나올 때만 답한다.
3. **로봇 식별**: zones 에는 로봇 ID 가 없다. 요청의 `route.pickup`(VERIFY_LOAD) 또는 `route.dropoff`(VERIFY_UNLOAD) 구역 하나만 본다. 그 구역이 `MULTI`·`NO_ROBOT` 이면 판정하지 않는다.
4. **카메라가 끊겼을 때**(status 3초 없음 또는 `offline`): 8-7 협의 2번 **[미결]**. 주의: `retry_safe: true` 로 답하면 VERIFY_LOAD·VERIFY_UNLOAD 는 팔 단계(LOAD·UNLOAD)부터 다시 돈다. 두 단계가 한 재시도 묶음이기 때문이다(`FC/scenario_tree.py:70-73`, `FC/scenario_runtime.py:94`) [사실, 코드 읽기·미시험]. 그래서 "확인 못 함"에는 `retry_safe` 를 붙이지 않는 안을 권한다.
5. **발행자**: `work_result` 를 vision 대상으로 내는 노드는 하나만 둔다. 지금 우리 감시 노드의 수동 어댑터와 충돌한다(8-6).
6. **중복 제거**: 같은 `request_id` 에는 최종 결과를 한 번만 낸다(증거 부족으로 기다리는 경우는 예외, 8-3).
7. **기록은 중계 웹에서** [결정 11-14]: 관제 원장에는 단계 완료만 남는다. `stream_id`·`stream_epoch`·`frame_seq`·`capture_time`·신뢰도·판정 규칙은 어댑터가 남기고 중계 웹에서 보여 준다. 주문 번호·`request_id` 로 관제 기록과 잇는다. 같은 값을 `data.evidence` 에도 넣는다(관제는 읽지 않음).

### 8-6. 지금 있는 것과 없는 것 [사실]

- **비전 어댑터**: 없다.
- **우리 감시 노드 수동 어댑터**(b554975 `src/cobot_anomaly_monitor/cobot_anomaly_monitor/manual_adapter.py`):
  - 사람 승인으로 vision·navigation·omx1·omx2 단계에 대신 답한다. 승인 결과에 `measured: True` 를 붙인다(`manual_adapter.py:219`). 11-14 결정(사람 승인은 관제에 보내지 않음)에 따라 사람 승인 응답을 끈다 [계획].
  - 사람 승인을 끄면 카메라가 못 보는 단계를 넘길 우회로가 없어진다(8-7 협의 1번).
  - `work_result` 발행자가 2개 이상이면 스스로 꺼진다. 비전 어댑터를 띄우기 전에 이 검사를 대상별로 바꾸거나, 현장 `manual_targets` 에서 vision 을 빼야 한다.
- **비전 근거 결합 시험**(감시 노드 `verify_load_join`, 기본 꺼짐): VERIFY_LOAD 에 한해 zones `LOADED` 3프레임과 운영자의 팔 퇴피 확인을 묶어 `decision: "camera_and_operator"` 로 답한다(`manual_adapter.py:153-174`). 격리 시뮬 도메인 77·140 에서만 켜진다(`monitor_node.py:99-106`). 현장 경로가 아니다.
- **가짜 수신처**: 11-14 시험의 시험 브로커(127.0.0.1:18883)와 `relay/test/*` 주제는 우리 시험 도구다. 관제가 아니다. 관제와 잇는 시험은 격리 도메인에서 `work_request` 를 흉내 내야 한다.

### 8-7. 역할 분담과 협의할 것

**정한 것** [결정 11-14]

| 항목 | 내용 |
|---|---|
| 비전 어댑터 | 우리가 만든다. 카메라 컨테이너가 이미 내는 MQTT 결과를 읽어 `target: "vision"` 요청에 답한다. 새 추론은 하지 않는다 |
| 팔 어댑터 | 우리가 만든다(팀 sh 선택·호출). 같은 요청·결과 계약을 쓴다 |
| 관제 | 이미 있는 `/fleet/work_result` 수신을 그대로 쓴다. 기본 경로에는 관제 코드 변경이 없다 |
| 사람 승인 | 관제에 보내지 않는다 |
| 근거 기록 | 중계 웹에서 관리한다. 관제 원장에 남기지 않아도 된다 |
| 어댑터 실행 PC | [미정, 우리 쪽에서 정함] 관제 DDS(도메인 100)에 닿는 PC 여야 한다. 11-14 기준 중계 노트북의 감시 노드는 관제에 붙어 있지 않다 |

**협의할 것: 상태 처리만** (관제·시나리오 담당과)

1. **카메라가 아직 못 보는 단계의 상태 처리.** 통로 이탈(PICKUP_EXIT·PATH_EXIT·RETURN_EXIT), 정차 오차(DOCK_PICKUP·DOCK_DROPOFF), 상품 확인(MARKER·QR)이 해당한다. 사람 승인을 빼면 시나리오는 PICKUP_EXIT 에서 멈춘다(11-13 주행이 멈춘 자리). 선택지:
   - (가) 관제 시나리오에서 당분간 건너뛰는 설정을 둔다. 관제 코드 수정이 필요하다. 지금 `skip_stages` 는 복구 재개용뿐이다(`FC/scenario_tree.py:50`).
   - (나) 비전 어댑터가 대신 근거를 쓴다. 예: 통로 이탈 = "목표 구역 안에 로봇이 보임". 판정 기준을 합의해야 한다.
   - (다) 기능이 생길 때까지 그 단계에서 멈추는 것을 받아들인다.
2. **카메라·어댑터가 끊겼을 때 주문 상태.**
   - (가) 바로 `success: false`(`retry_safe` 없음)로 답한다. 주문이 즉시 UNKNOWN 이 되고 관리자 확인으로 간다. **[권장]**
   - (나) 답하지 않는다. 300초 뒤 UNKNOWN.
   - (다) `success: false` + `retry_safe: true`. 상하차 확인에서는 팔 단계부터 다시 돈다(8-5 4번). **위험**
3. **상하차 확인의 팔 항목.** VERIFY_LOAD 의 `arm_safe`, VERIFY_UNLOAD 의 `placed`·`arm_safe` 를 비전 어댑터가 같은 주문의 팔 결과(LOAD·UNLOAD 성공)로 채워도 되는지. 결과의 `source` 는 `vision` 하나여야 하므로 비전 어댑터가 묶어서 보내야 한다(`FC/scenario_runtime.py:182-184`).
4. **(선택) 어댑터 살아 있음을 관제가 받을지.** 지금 관제는 로봇 신호만 본다(`FC/scenario.py:103-108`). 어댑터가 꺼져 있어도 요청을 보낸 뒤 300초를 기다린다. 받기로 하면 이 수신만 관제에 구현하면 된다. 어댑터 쪽 신호 형식은 우리가 맞춘다.

---

## 9. 한계와 미정

- **관제 수신 미구현** [사실]: 관제는 설계상 MQTT 를 받지 않는다(8-1). 비전 결과를 관제로 넘길 비전 어댑터도 없다(8-6). `src/cobot_navigation/cobot_fleet_control`(b554975 기준. 7f2b2e3 부터는 `src/cobot_fleet_control`)·`src/cobot_control_center` 에 이 주제를 받는 코드는 없다(b554975 저장소 전체에서 이 폴더 밖의 `relay/evidence`·`relay/status/vision`·`relay/test/` 문자열은 `cobot_anomaly_monitor` 의 `mqtt_evidence.py`·`replay_evidence.py`·`docs/homelab_verify_load.md` 에만 있다). 감시 노드 결합도 격리 시뮬에서만 켜진다(3절).
- **카메라 분리 미구현** [사실·계획]: 지금은 천장 카메라 하나(`ceiling`)다. 상하차 카메라용 `stream_id` 와 그 흐름의 메시지(좌표 없이 상태만 낼지 등)는 계획 단계다.
- **구역 좌표** [사실]: ZA·ZB·ZC 윤곽은 11-08 카메라 자세의 픽셀 값이다(`zone/tray_zones.py:3-7`, `README.md:125`). 카메라 위치가 바뀌면 윤곽을 다시 만들고 `calibration_id` 를 바꿔야 한다. 마커 상태 OK 는 "마커 4개가 보인다"는 뜻이지 "11-08 자세와 같다"는 보장이 아니다 [추정 위험].
- **시각** [사실]: `capture_time` 은 추론 PC 가 프레임을 받은 시각이고, 폰에서 추론 PC 까지 지연은 재지 않았다(`README.md:145`). `clock_error_sec` 0.05 는 고정값이다.
- **status 의 `offline` 에 흐름 이름이 없다** [사실, `app/publisher.py:74`]: 앱이 여럿이면 어느 앱이 끊겼는지 이 메시지만으로는 모른다.
- **현장 운영 주제 수신 기록 없음**: 이 문서의 운영 주제 예시는 모두 코드로 만든 것이다. 11-10 현장 기동에서 도착 건수만 확인했다(`README.md:139`).
- 현장 적재 상태: 11-14 시험 10분(detections 904건) 동안 신뢰도 0.5 이상 `pinky_loaded` 는 1건(frame_seq 670, 0.5686)뿐이고, 0.25~0.45 짜리가 5건 더 있었다. 0.5 이상 나머지는 대기 줄의 빈 핑키(`pinky_empty`)였다(`~/doc/logs/vision-test-20261114/minute_summary.log` 마지막 줄, `mqtt_10min.log` 재집계). 실제 적재 장면에서 LOADED 가 안정적으로 나오는지는 아직 모른다.

---

## 10. 검증 기록

- 검증 일시: 2026-11-14 15:00~15:20 KST. 읽기와 이 파일 수정만 했다. 브로커·장비·로봇에는 붙지 않았고, 커밋·push 하지 않았다.
- 대조한 코드
  - `~/kr4-merge` `merge/submaster-20261112` 머리 **b554975**: `scripts/vision/homelab_vision/app/{config,main,publisher,source,detector}.py`, `zone/{zone_evidence_msg,marker_zone,tray_zones,pinky_evidence,vision_answer}.py`, `README.md`, `compose.yaml`
  - 시험 모드: `~/kr4-vision-test` (같은 b554975 위 미커밋 수정 3파일 `app/config.py`·`app/main.py`·`app/publisher.py`, +74/−25 줄)
  - 감시 노드: b554975 `src/cobot_anomaly_monitor/cobot_anomaly_monitor/{mqtt_evidence,load_evidence,manual_adapter,monitor_node,replay_evidence}.py`
  - 가중치 클래스 이름: `weights/*.pt` 의 `data.pkl` 을 `pickletools.genops` 로 읽기만(역직렬화·실행 안 함). sha256 두 개는 파일 실측과 일치
  - 실제 수신: `~/doc/logs/vision-test-20261114/mqtt_10min.log` 1503줄 재집계(status 599·detections 904, 크기 1137~1145 B·706~821 B), `broker/mosquitto.conf`, `minute_summary.log`
  - 예시 JSON 5개를 파싱해 필드 수(38·10·10·19·18)와 바이트 수(287·291·776·710)를 다시 쟀다. boxes 예의 핑키 상자는 `tray_zones.make_zone_of` 로 `["ZA"]` 가 나오는 것을 확인했다.
- 고친 것
  1. 대상 패키지 경로: `cobot_fleet_control` 은 `src/` 바로 아래가 아니라 `src/cobot_navigation/cobot_fleet_control`(b554975 기준. 7f2b2e3 부터는 `src/cobot_fleet_control`) 이다.
  2. 0절 zones 주기: "구역 판정을 거절한 프레임 제외"를 "시각 규칙으로 거절한 프레임 제외, 마커 OK 아님은 NO_ROBOT 로 보냄"으로 바로잡음. boxes 주기를 `INFERENCE_FPS` 로 통일.
  3. 인증: 익명 브로커를 [사실]로 쓴 것을 [기록, 저장소 근거 없음]으로 낮춤. 앱 쪽 근거 줄을 `publisher.py:71-83` 으로 고침.
  4. 폐기 규칙에 `drops.rc`(응답 대기 20개 상한) 추가, 대기열 길이가 `PUBLISH_QUEUE_MAX` 로 바뀔 수 있음을 적음.
  5. 유언 7.5초를 [사실]에서 [규격·미측정]으로 바꾸고, 같은 클라이언트 ID 재접속 때 묵은 `offline` 이 올 수 있다는 점을 [추정]으로 추가.
  6. status 표: `frames_skipped_wrong_size` 는 추론 차례 프레임만 검사, `infer_ms_*` 시험 모드는 마커 없음, `zones_frames_emitted` 는 NO_ROBOT 강제 프레임 포함, 시작 직후 `marker_state` 는 `LOST`, `markers_seen` 은 같은 번호 중복 제외, `published` 는 status 를 세지 않음, 계수 등식은 잠금 없이 읽어 순간 어긋날 수 있음.
  7. zones `source_kind`: "재생 시험은 sim_fixture" 를 "이 앱은 항상 model_output, sim_fixture 는 감시 노드 재생 도구 값"으로 바로잡음. `frame_seq` 가 0 부터이고 시각 거절은 번호를 쓰지 않음을 적음. `pinky_evidence`/`vision_answer` 상태가 MQTT 에 없음을 추가.
  8. marker_state 표: OK 는 "마지막 검사(약 1초마다)" 기준, FIXED 보정 방식, CONFLICT 정의(넓이·볼록·120 px 이동 검사 실패, "기존 사각형과 어긋남"만이 아님), LOST 에 시작 직후 포함.
  9. 감시 노드 규칙: 수신기의 `LOCALHOST` 조건·기본 브로커 127.0.0.1, dict 아님은 로그 없이 버림, `received` = 요청 저장 시각, 귀속 검사 실패·epoch 없음도 창을 비움, `capture_time` 역행은 epoch 와 무관하게 무시(원문은 "같은 epoch 에서"로 잘못 씀), 상차 구역은 ZA·ZB 만(ZC 미사용), 팔 확인 유효시간, `verify_load_join` 기본 꺼짐과 `camera_policy=sim`·`manual_adapter` 조건.
  10. boxes: `pinky[].zones` 는 마커와 무관한 픽셀 윤곽 값임을 경고, 배열 순서는 앱이 정렬하지 않음, `truncated` 정의 보강. 신뢰도 0.5 를 "홈랩 채점 조건"이라 한 근거 없는 주장을 지우고 `pinky_evidence.py:19-20`(측정값 아님)으로 바꿈(줄 번호 19-21 → 19-20). `box_stock` 뜻에서 근거 없는 "선반 등" 삭제.
  11. 시험 주제: 근거 줄 `config.py:27-33` → `28-33`, `FRAME_SIZE` 가 운영 모드에도 먹는 위험, detections 에 없는 필드, `boxes_count_all` 은 0.25 이상, status 의 `last_zones`·`markers_seen` 값 보강.
  12. 다중 카메라 `stream_id`: 계획 문서·코드 어디에도 없는 이름 `docking-note3`·`docking-webcam` 을 지움.
  13. 체크리스트: 감시 노드 JSON 처리 방식 오기 정정, `capture_time` 역행 규칙·`pinky[].zones` 주의 추가, 크기 확인 명령에 `LC_ALL=C`.
  14. 9절(당시 8절): `pinky_loaded` "1건"을 "0.5 이상 1건(frame_seq 670), 0.25~0.45 5건"으로 재집계해 고침. 저장소 검색 범위를 b554975 전체로 넓혀 다시 확인.
- 확인하지 못한 것: 운영 주제 실제 수신(기록 없음), 현장 브로커의 유언 지연, 추론 PC·수신 PC 시계 차이, ultralytics 출력 순서.
- 2차 보충 (2026-11-14 16:10 KST, 8절 신설). 읽기와 이 파일 수정만 했다. 커밋·push·장비 접속 없음.
  - 대조한 코드: control-center **7f2b2e3** `src/cobot_fleet_control/cobot_fleet_control/{scenario_contracts,scenario_nodes,scenario_runtime,scenario,fleet_control_node}.py`, `src/cobot_fleet_control/config/scenario.yaml`. 97be6c7 커밋 메시지, c995902 의 문서 문구. b554975 `src/cobot_anomaly_monitor/cobot_anomaly_monitor/{manual_adapter,monitor_node}.py`.
  - 바뀐 것: 제목·대상(관제 직접 구독이 아니라 비전 어댑터 경유), 0절 끝 안내, 7절 제목, 8절(관제 연동) 신설, 옛 8·9절을 9·10절로 옮김, 9절 첫 항목에 설계상 MQTT 미수신 추가.
  - 확인하지 못한 것: 관제가 결과를 거절할 때 남기는 로그 문구, 실제 관제와 비전 어댑터를 붙인 시험(어댑터가 없어 불가).
- 3차 수정 (2026-11-14 16:30 KST). 문서만 고침. 장비 접속 없음.
  - 11-14 사용자 결정 반영: 비전 어댑터는 우리가 만든다, 사람 승인은 관제에 보내지 않는다, 근거 기록은 중계 웹에서 관리한다.
  - 8-7 을 "역할 분담(정한 것)"과 "협의할 것: 상태 처리만" 으로 재구성. 8-1·8-5(1·4·7번)·8-6 문구 수정.
  - 추가 대조: 7f2b2e3 `scenario_tree.py:50,66-73`(공유 재시도·skip_stages 용도), `scenario_runtime.py:92-108`(재시도 소진 시 UNKNOWN·DOCK_PICKUP 만 안전 복귀).
