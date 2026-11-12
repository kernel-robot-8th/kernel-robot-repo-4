# 스트림 관리자 (관측 전용)

여러 카메라의 영상 입력, 추론 순서, 자원 사용을 한 프로세스에서 관리합니다. 모델 B 패킷의 뷰어를 복사해 확장했고, 패킷 원본은 그대로입니다.

```text
카메라 A -> 수신 스레드 --+
카메라 B -> 수신 스레드 --+--> 추론 스케줄러 (모델 하나) -> 카메라별 화면
                                  |
                          자원 측정 스레드
```

경보, MQTT, ROS, 관제 연결은 없습니다. 프레임은 디스크에 쓰지 않고, 127.0.0.1에만 엽니다.

## 파일

| 파일 | 내용 |
|---|---|
| `stream_manager.py` | 카메라 등록, 시작·정지, 추론 스케줄러, 웹 |
| `resources.py` | `/proc`에서 스레드별 CPU, 메모리, 온도, 클럭을 읽습니다 |
| `stream_page.html` | 카메라 전체를 보는 화면 |
| `cameras.json` | 카메라 목록 |
| `edge_view.py` | 패킷 뷰어 복사본. 허용 장치를 넣었고, 단독 실행은 막았습니다 |
| `test_stream_manager.py` | 관리자 시험. 모델과 장치가 없어도 돕니다 |

## 실행과 끄기

```bash
cd ~/yolo_edge/view
XDG_RUNTIME_DIR=/run/user/1000 systemd-run --user --collect --unit=yolo-edge-streams --property=RuntimeMaxSec=28800 --nice=10 --working-directory="$PWD" ~/yolo-edge-venv/bin/python -B stream_manager.py --config cameras.json
```

```bash
XDG_RUNTIME_DIR=/run/user/1000 systemctl --user stop yolo-edge-streams
```

화면은 `http://127.0.0.1:8893/`입니다. 8시간 뒤 스스로 끝납니다.

## 카메라 추가

1. `cameras.json`의 `cameras`에 항목을 넣습니다.
2. 화면의 "설정 다시 읽기"를 누릅니다.

바뀌지 않은 카메라는 그대로 돌고, 파일이 틀리면 아무것도 바뀌지 않습니다.

"설정 다시 읽기"는 카메라 항목만 반영합니다. `model`, `threads`, `conf`, `alarm_conf`, `iou`, `debounce`, `cooldown`, `view_width` 등은 재시작해야 적용되고, 화면이 바뀐 값의 이름을 알려 줍니다.

```json
{"id": "new", "name": "새 카메라", "source": "http://주소:18086/processed",
 "stream_id": "CAM_NEW_01", "max_fps": 5, "event_log": false, "enabled": true}
```

`id`는 영문 소문자, 숫자, `-`, `_`입니다. `source`는 http, rtsp 주소, 파일, 폴더입니다. 폰 주소는 바뀔 수 있습니다.

USB 장치는 `edge_view.py`의 `ALLOWED_DEVICES`에 있는 것만 열립니다. 내장 카메라는 넣지 않습니다.

## 화면 읽는 법

| 값 | 뜻 |
|---|---|
| 요청 합 | 켜진 카메라 `max_fps`의 합 |
| 처리 능력 | 지금 한 프레임 걸리는 시간으로 낸 초당 처리 수 |
| 점유율 | 추론 스케줄러가 일하는 시간의 비율 |
| 지연 | 프레임이 계획보다 늦게 처리된 평균 시간 |
| `capture-<id>` | 그 카메라 수신 스레드의 CPU |
| `inference`, `openvino` | 추론에 쓰는 CPU |

요청 합이 처리 능력을 넘으면 빨간 경고가 뜨고, 카메라가 처리량을 똑같이 나눠 가집니다. 이때 각 카메라의 `max_fps`를 낮추거나 `threads`를 올립니다. `threads`를 올리면 CPU 온도가 오릅니다.

브라우저는 호스트당 연결이 6개입니다. 영상이 이를 다 쓰면 상태 요청과 정지 버튼이 멈추므로, 한 화면의 영상은 4개까지 열고 숨은 탭은 영상을 끊습니다. 창을 여러 개 띄워 연결이 차면 "상태를 읽지 못합니다" 경고가 뜨니 창을 줄입니다.

입력 JPEG는 약 3,350만 화소까지 받습니다. 넘으면 깨진 프레임으로 셉니다.

표시는 관측값이고 사고 판정이 아닙니다. 경보가 없다고 정상이 아닙니다.

## 시험

```bash
cd ~/yolo_edge/view
~/yolo-edge-venv/bin/python -B test_stream_manager.py
~/yolo-edge-venv/bin/python -B test_edge_view.py
```

## 맵 영역 자르기와 웹 창구 (2026-11-10)

- 카메라 항목에 `"map_crop": true` 를 주면 마커 40~43 네 개가 통째로 들어가는 영역만 내보낸다. 경계는 마커 중심이 아니라 마커 바깥 귀를 이은 선이고, 테두리가 잘리지 않게 2 화소 더 밖으로 잡는다. 그 밖 화소는 검게 지운다. 구역 판정 좌표는 그대로 마커 중심 기준이다.
  마커를 놓치면 10초 동안 직전 사각형을 쓰고, 그 뒤에는 전체 화면이 아니라 `MARKER LOST` 안내 화면을 낸다.
  맵 밖 검출은 판정·집계·표시에서 빠진다(`map.dropped_outside` 누계). 가려진 동안은 판정도 하지 않는다.
- 마커 코드는 `marker_zone.py` (`~/homelab-vision/zone/marker_zone.py` 사본, 수정 없음).
- 설정에 `"bridge_bind": "172.17.0.1"` 을 주면 같은 포트로 웹 창구가 하나 더 열린다. docker0 주소만 받는다.
  창구는 GET 만 받고, `/api/state` (맵 영역 카메라만) 와 맵 영역 카메라의 `stream.mjpg` 만 내준다. 시작·정지·reload 는 403 이다.
  중계 웹(5173)의 `/api/mapview/` 프록시가 이 창구로 온다. 화면은 `/debug/camera`.
- 시험: `python test_map_crop.py` (끝 줄 `[map_test] 34/34 PASS`).
- 되돌리기: `cameras.json` 에서 `bridge_bind` 줄과 `map_crop` 을 지우고 다시 시작하면 전과 같다.
