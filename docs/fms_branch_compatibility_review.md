# FMS 규칙 보완 뒤 기존 브랜치 호환성 검토

- 조회일: 2026-10-22. 대상 저장소: kernel-robot-8th/kernel-robot-repo-4.
- 범위: 작성자 rkd1rjs2의 FMS Draft PR #1~6을 기준 계약으로 삼아, main과 다른 작업 브랜치의 현재 소스·의미를 대조했다. 타인의 브랜치·main은 수정하지 않았다.
- 정본 SR: Confluence 5406727 SR_v2 version 13. 대조 내용은 `fms_sr_reconciliation.md`를 본다.

## 고정한 비교 대상

| 대상 | SHA | 관측 |
|---|---|---|
| main | 913eb15cd6f3006b8686ff90d9a178736f405946 | 기본 README·규칙, 주행 README, 비전 이미지 ZIP. FMS·인터페이스·녹화 앱은 아직 없다. |
| tool/omx-ai_record_dashboard | e78dd9a34a84fad98ccec266dc6577980dcd02d1 | main의 자손. sakim0128·JiHyeokHeo 등의 녹화 앱 커밋. 아직 main 통합 상태가 아니다. |
| feature/setup-fleet-msgs-structure | 1c2002aa999a562bafa8f5327e192685f036e7c3 | 옛 fleet_msgs와 맵의 이행 참고. rkd1rjs2 작성 커밋도 있어 '타인 소유 브랜치'로 단정하지 않는다. |

팀원 개인 저장소는 요청 범위에 없다. 저장소의 모든 원격 브랜치를 열거했으며, 위 외의 브랜치는 FMS PR #1~6의 작업 브랜치다.

## 소스 충돌과 의미 충돌

격리된 로컬 복제본에서 `git merge-tree --write-tree caae252 <대상SHA>`를 실행했다. tool/e78dd9a 및 setup/1c2002a 모두 종료코드 0으로 텍스트 병합 충돌이 없었다. 이는 아래 의미 충돌이 없다는 뜻이 아니다. 실제 병합·main 반영은 하지 않았다.

| 우선도 | 충돌 | 소스 근거와 영향 | 통합 전 조치 |
|---|---|---|---|
| P1 | 명령 번호가 같아도 뜻이 다름 | legacy `src/fleet_msgs/msg/FleetCommand.msg`의 STOP은 HOLD, HEARTBEAT=7은 워치독 갱신. S1 `cobot_interfaces`는 STOP을 PAUSED로, 옛 HEARTBEAT 번호를 미사용으로 다룬다. legacy에는 epoch·seq·TTL·map_hash·서명이 없다. | 발행자·가드 동시 이행과 상태 이행표를 시험한다. 옛 명령에 최신 권한을 자동으로 덧씌우는 브리지를 만들지 않는다. |
| P1 | 녹화 앱과 FMS가 동일 팔의 제어권을 가질 수 있음 | `e78dd9a:omx_recoder/core/robot_ctrl.py:94~115` 직접 포트 연결·토크 ON, 263·271·274행 Goal_Position 쓰기. FMS와 공유하는 프로세스 간 소유권 잠금·exclusive 상태 계약이 없다. | D7·D12에서 공식 도구와 운영 모드를 정한다. 장치 제어는 담당 노드로 분리하거나 승인된 배타 실행 계약을 구현한다. FMS 화면의 토큰만으로 시리얼 단일 소유권을 증명하지 않는다. |
| P1 | Servo OFF는 관제 정지가 아님 | `e78dd9a:robot_ctrl.py:399~412`는 녹화 중 OFF를 거부하고 평시에는 Rest/Init으로 이동한다. | 정상 종료와 긴급 정지 경로를 분리한다. 원격 정지 미구현 동안 가능한 것처럼 표시하지 않는다. |
| P2 | 상태·작업 타입은 이름 변경 호환이 아님 | legacy RobotStatus는 핑키/팔 혼용, v2는 별도 ArmStatus·부팅 ID·측정 상태를 둔다. HandoverTask의 station_id→waypoint_id, item_type→sku, 증거 ID도 다르다. | 생산자·소비자 쌍을 함께 이전한다. 미계측을 0/성공으로 채우지 않는다. yaw rad와 정렬 오차 mm/deg를 일괄 변환하지 않는다. |
| P1 | 같은 waypoint ID가 다른 좌표·경기장 크기 | legacy flat의 WP_GATE와 1021_gate67·approach_poses의 작업점/정차점이 다르다. | ID만 맞추지 않고 map_hash·접근 자세·Nav2 로드 맵을 함께 전환한다. 현재 맵 2.5×2.4 m와 SR-22의 실제 경기장 2.4×2.4 m 차이도 D3에서 해소한다. 고정대가 반영되지 않은 점유맵을 고정대 포함 물리 검증으로 보고하지 않는다. |
| P2 | 녹화 앱의 실행·패키징 환경이 다름 | main은 Ubuntu24.04/Jazzy/Python3.12, 앱 안내는 Ubuntu22.04/별도 LeRobot venv이며 루트 omx_recoder는 ament 패키지가 아니다. | D18에서 Station PC 환경을 확인하고 D12에서 패키징·UI·장치 제어 경계를 정한다. 기존 앱을 이번 규칙으로 소급 삭제하지 않는다. |

`main:src/cobot_vision/pinky_camera.zip`도 읽기 전용으로 검사했다. 엔트리 214개 중 폴더 2개와 JPG 212개뿐이며 Python·ROS 소스는 없다. 따라서 이 ZIP을 카메라 노드 구현으로 판단하지 않았다. ZIP을 실행하거나 이미지의 현장 성능을 검증하지 않았다.

main과 setup의 공통 조상은 eb4014c다. setup은 현재 main의 자손이 아니므로, 단순 diff에 보이는 CLAUDE 삭제를 최신 규칙의 의도적 삭제로 판단하지 않는다.

## 판정과 다음 단위

- 규칙·카탈로그 보완은 FMS Draft PR에서만 진행한다. main·타인 브랜치·장치 실행은 별도다.
- 기존 앱은 D12 미결 자산이고, 새 계약도 proposed다. 따라서 위 표는 확정 규칙 위반 판정이 아니라 FMS 채택 전 해결할 이행 조건이다.
- 다음 순서: D7·D12·D18 결정 → 배타 제어와 정상 종료/정지 계약 → 메시지·맵 동시 이행 → 통합 빌드·가짜 장치 부정 시험 → 별도 승인된 실물 검증.
- 문서 규칙·SR 카탈로그 시험은 ROS·Nav2·실물 시리얼·물리 시뮬레이션 시험을 대체하지 않는다.
