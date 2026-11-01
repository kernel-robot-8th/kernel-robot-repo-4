# PatrolCommand.msg - 관제가 핑키 한 대에 보내는 순찰 명령 (규격 v2)
# 토픽: /pinkyN/patrol_command (관제 PC 쪽 이름). 받는 쪽: 순찰 노드 (지금은 가짜 핑키 cobot_mock).
# v1 의 /pinkyN/patrol_cmd 문자열("goto:P1,P2")과 같은 일을 하되, 작업 ID 를 붙여
# 결과(PatrolCommandAck, PatrolState)와 짝지을 수 있게 한다.

string OP_GOTO="goto"                      # points: 구역 밖 일반 지점·자기 홈 1개 이상
string OP_ZONE="zone"                      # points: 구역 지점 정확히 1개
string OP_LEAVE="leave"                    # points: 비움. 보유 구역 EXIT 로 나가 토큰 반납
string OP_HOME="home"                      # points: 비움. 자기 홈으로
string OP_STOP="stop"                      # points: 비움. 작업 중단 (구역 안이면 EXIT 로 후퇴)
string OP_EMERGENCY_STOP="emergency_stop"  # points: 비움. 그 자리 정지, 토큰 유지

string task_id      # 관제가 정한 작업 ID. 비어 있으면 거절. stop 계열은 멈출 작업과 무관한 새 ID
string operation    # 위 OP_* 중 하나
string[] points     # 지점 이름 (pinkyN.yaml 의 points 키). 예: ["P1", "P2"]
