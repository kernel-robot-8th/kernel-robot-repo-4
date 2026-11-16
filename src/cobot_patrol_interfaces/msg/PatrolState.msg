# PatrolState.msg - 핑키 한 대의 순찰 상태 (규격 v2)
# 토픽: /pinkyN/patrol_state. 보내는 쪽: 순찰 노드. 상태가 바뀔 때 + 1초마다.
# v1 의 /pinkyN/patrol_status JSON 과 같은 값을 타입으로 낸다. 주기 발행이라 수신 간격으로
# 연결 여부를 알 수 있고, task_id 로 어느 명령의 진행·결과인지 짝짓는다.

# state 값 (v1 과 같은 14종)
string STATE_IDLE="IDLE"
string STATE_STARTING="STARTING"
string STATE_MOVING="MOVING"
string STATE_QUEUEING="QUEUEING"            # 구역 대기 슬롯에서 대기. detail = slot{k}
string STATE_ARRIVED="ARRIVED"
string STATE_HOLDING_ZONE="HOLDING_ZONE"    # 구역 토큰 보유 중. detail = 구역 이름
string STATE_LEAVING_ZONE="LEAVING_ZONE"
string STATE_RETREATING="RETREATING"        # stop 뒤 구역 EXIT 로 후퇴
string STATE_RETURNING="RETURNING"
string STATE_IDLE_WAIT="IDLE_WAIT"          # 유휴 복귀 대기. detail = 남은 초
string STATE_DONE="DONE"
string STATE_STOPPED="STOPPED"
string STATE_FAILED="FAILED"
string STATE_RETRY="RETRY"

std_msgs/Header header      # stamp = 로봇 시각
string robot_id             # 예: pinky1
string state                # 위 STATE_* 중 하나
int32 waypoint              # goto 경로 안 순번(0부터). 해당 없으면 -1
string detail               # 지점 이름, 구역 이름, 실패 이유 등 (v1 detail 과 같음)
string task_id              # 진행 중 작업, 없으면 마지막 작업의 ID. 관제가 안 보낸 작업(유휴 복귀)은 ""
bool task_finished          # task_id 작업이 끝났으면 true (DONE / FAILED / STOPPED 를 낸 뒤)
string held_zone            # 보유 중인 구역 (A/B/C). 없으면 ""
