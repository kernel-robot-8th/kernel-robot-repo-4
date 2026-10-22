# TopicDiag.msg - 토픽 1개의 발행자·유량 진단 (DiagSnapshot.topics 의 원소)
# 명령 토픽 발행자 수: 0 = NO_PUBLISHER, 1 = OK, 2 이상 = VIOLATION (SR-19 단일 기록자)

string SINGLE_WRITER_NO_PUBLISHER="NO_PUBLISHER"
string SINGLE_WRITER_OK="OK"
string SINGLE_WRITER_VIOLATION="VIOLATION"

string name                        # 토픽 이름 (예: /control_center/pinky_1/command)
uint16 publishers                  # [개] 발행자 수
float32 measured_hz                # [Hz] 실측 유량
string single_writer_state         # 위 SINGLE_WRITER_* 중 하나
