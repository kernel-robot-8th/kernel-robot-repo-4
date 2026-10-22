# ReconcileItem.msg - Reconcile 대조 항목 1개 (ReconcileReport 응답의 원소, SR-14)
# 관제사는 APPROVE 때 항목마다 현장 관측값을 직접 입력한다 (attest, D5 추천안).

string target_id                   # 대조 대상 (예: pinky_1)
string expected                    # 원장이 기대하는 값
string observed                    # 현장에서 관측한 값
bool matched                       # expected 와 observed 가 같은가
string[] evidence_ids              # 근거 CompletionEvidence.evidence_id
