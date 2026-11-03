# pinky_interfaces (시뮬용 대체)

폴더 이름은 `pinky_interfaces_stub`, 패키지 이름은 `pinky_interfaces` 입니다.

- 순찰 노드(`cobot_pinky_patrol`)는 `from pinky_interfaces.srv import SetLed` 를 합니다. 실물 `pinky_interfaces` 는 로봇에만 설치되어 있어서, 시뮬 PC 에서는 이 패키지가 대신합니다.
- `SetLed.srv` 는 순찰 노드가 채우는 필드(`command`, `r`, `g`, `b`)만 둡니다. 실물 정의와 완전히 같지 않을 수 있습니다.
- **실물 로봇 워크스페이스에서는 빌드하지 않습니다.** 로봇은 `--packages-select cobot_zone_traffic_control cobot_pinky_patrol` 로만 빌드하므로 평소에는 섞이지 않습니다. 실수로 함께 빌드하면 로봇에 설치된 진짜 `pinky_interfaces` 를 가립니다.
- 이 패키지를 쓰는 곳은 `cobot_gazebo` 하나입니다. 시뮬을 빼면 폴더째 지워도 됩니다.
