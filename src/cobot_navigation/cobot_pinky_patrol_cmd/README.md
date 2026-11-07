> 실행 방법은 [`cobot_pinky_patrol/README.md`](../cobot_pinky_patrol/README.md)를 참고하세요. 이 문서는 `pinky_control_client.py` 코드 해설입니다.

> **명령 (v1.2)** — `python3 pinky_control_client.py <pinky1|pinky2|pinky3> <동작> [포인트]`
>
> | 동작 | 보내는 문자열 | 설명 |
> |---|---|---|
> | `goto P1 P2` | `goto:P1,P2` | 구역 밖 지점으로 이동. 도착 후 홈으로 가지 않는다 |
> | `zone ZA` | `zone:ZA` | 구역 지점 1개로 이동. 토큰을 받은 뒤 출발하고 도착 후 유지한다 |
> | `leave` | `leave` | 구역 EXIT 로 나가 도착한 뒤 토큰 반납 |
> | `home` | `home` | 초기 위치(I1/I2/I3)로 복귀. 구역 안이면 EXIT 로 나와 토큰 반납한 뒤 이동한다 |
> | `stop` / `emergency_stop` | 그대로 | 중지 (stop = EXIT 로 나와 반납, emergency_stop = 토큰 유지) |
> | `monitor` | - | 상태 출력 |
>
> 마지막 명령 뒤 `idle_return_sec`(기본 120초) 동안 새 명령이 없으면 로봇이 스스로 홈으로 복귀한다.
> 아래 코드 해설은 초기 버전(`start/stop`) 기준이라 `zone`/`leave` 분기는 `build_command` 함수에 있다.
