# PatrolCommandAck.msg - PatrolCommand 를 받았는지 거절했는지 (규격 v2)
# 토픽: /pinkyN/patrol_command_ack. 보내는 쪽: 순찰 노드. 명령 하나에 한 번.
# v1 에는 없다 (바쁠 때 온 명령은 아무 응답 없이 무시됐다).
# 받음(accepted)은 '작업을 시작했다' 는 뜻일 뿐 성공이 아니다. 결과는 PatrolState 로 온다.

string REASON_BUSY="busy"                  # 다른 작업 중
string REASON_NOT_RUNNING="not running"    # stop 계열인데 멈출 작업이 없음
string REASON_BAD_TASK_ID="bad task_id"    # task_id 가 비었음
string REASON_UNKNOWN_OPERATION="unknown operation"
# 그 밖의 거절 이유는 v1 의 FAILED detail 과 같은 문구다.
# 예: "unknown point: ['P99']", "use zone: ['ZA']", "no zone held", "start disabled"

std_msgs/Header header
string robot_id     # 예: pinky1
string task_id      # 받은 PatrolCommand.task_id 그대로
bool accepted
string reason       # accepted=false 일 때 이유. true 면 빈 문자열
