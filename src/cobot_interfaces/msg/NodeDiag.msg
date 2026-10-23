# NodeDiag.msg - 노드 1개의 생존·서비스 왕복 진단 (DiagSnapshot.nodes 의 원소)

string name                        # 노드 이름 (예: /control_center/fms_core)
bool alive                         # 그래프에 보이는가
float32 srv_rtt_ms                 # [ms] 진단 서비스 왕복 시간. NaN = 미측정
