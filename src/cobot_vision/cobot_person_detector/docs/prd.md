# cobot_person_detector PRD

## 1. 목적
핑키 정면 카메라 영상에서 YOLO(ultralytics)로 사람을 찾아 bbox 를 발행한다.
`cobot_obstacle_avoidance` 가 이 결과를 라이다와 이어 붙여, 사람 앞에서는 피하지 않고 정지 후 재출발한다.

## 2. 실행 위치
- 핑키와 연결된 PC(관제 PC, 도메인 100)에서 실행한다. 라즈베리파이에서는 추론이 느리다.
- 영상은 도메인 브릿지로 로봇 → PC, 결과는 PC → 로봇으로 넘어간다 (`cobot_domain_bridge/config/pinky_bridge_pinkyN.yaml`).

## 3. 토픽
| 방향 | 토픽(기본) | 타입 | 비고 |
|---|---|---|---|
| 입력 | `camera/image_raw` | `sensor_msgs/Image` | `use_compressed: true` 면 `sensor_msgs/CompressedImage` |
| 출력 | `person_detections` | `vision_msgs/Detection2DArray` | header 는 입력 영상 그대로. bbox 는 픽셀, `class_id: person`, score |

## 4. 파라미터 (`config/person_detector.yaml`)
| 이름 | 기본값 | 설명 |
|---|---|---|
| `model_path` | (필수) | YOLO `.pt` 경로 |
| `image_topic` | `camera/image_raw` | |
| `use_compressed` | false | |
| `output_topic` | `person_detections` | |
| `person_class` | 0 | 모델의 사람 클래스 번호 (`best.pt` 는 `{0: 'human'}`) |
| `min_confidence` | 0.5 | |
| `min_box_height` | 20 px | 너무 작은(먼) 사람 무시 |
| `imgsz` | 640 | |
| `device` | `cpu` | GPU 면 `'0'` |
| `max_rate` | 5 Hz | 최신 프레임만 이 주기로 처리 |

## 5. 설치
- ROS: `sudo apt install ros-jazzy-vision-msgs ros-jazzy-cv-bridge`
- Python (rosdep 키 없음, venv 권장): `python3 -m venv --system-site-packages .venv && .venv/bin/pip install ultralytics "numpy<2"`
  - ROS Jazzy 의 `cv_bridge` 는 numpy 1.x 로 빌드되어 있어 numpy 2 가 깔리면 깨진다.
- 모델 파일은 커밋하지 않는다. 현재 모델: `kernel-robot-8th/kernel-robot-repo-4` 의 `feature/vision` 브랜치 `human/best.pt`
  ```bash
  git -C <kernel-robot-repo-4 경로> show origin/feature/vision:human/best.pt > ~/models/best.pt
  ```

## 6. 실행
```bash
ros2 launch cobot_person_detector person_detector.launch.xml model_path:=$HOME/models/best.pt \
  image_topic:=/pinky1/camera/image_raw/compressed use_compressed:=true output_topic:=/pinky1/person_detections
```
확인: `ros2 topic hz /pinky1/person_detections`, `ros2 topic echo /pinky1/person_detections`

## 7. 확인 필요
- 실물 핑키의 카메라 발행 토픽 이름·형식. `pinky_pro` GitHub(모든 브랜치)에는 실물 카메라 노드가 없고 시뮬만 `camera/image_raw` 를 발행한다.
  브릿지 설정은 `/camera/image_raw/compressed` 로 가정했다.
