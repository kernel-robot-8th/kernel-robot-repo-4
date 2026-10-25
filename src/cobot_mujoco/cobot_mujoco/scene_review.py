"""Render a prominent correction for the visually verified box-count mismatch."""

import html


def review_html(review):
    """Separate historical mismatched-scene rollouts from matched-scene evidence."""
    if not review:
        return ""
    counts = review.get("original_policy_rollout_counts", {})
    count_note = (
        f"<p>기존 모델 평가 구성: 박스 3개 조건 {counts.get('three_box_conditions', '미확인')}회, "
        f"박스 1개 조건 {counts.get('one_box_conditions', '미확인')}회, "
        f"학습과 같은 박스 2개 조건 {counts.get('two_box_conditions', '미확인')}회입니다.</p>"
    )
    names = {
        "original_3_boxes": "기존 오류 장면: 3개 / 작업대 0.12m",
        "two_boxes_same_table": "개수만 정정: 2개 / 작업대 0.12m",
        "two_boxes_preserved_upper_heights": "높이 비교: 2개 / 작업대 0.16m",
    }
    rows = []
    for variant in review["variants"]:
        records = variant["replays"]
        lifted = sum(int(r["lifted_boxes"] > 0) for r in records)
        placed = sum(int(r["success_any_box"]) for r in records)
        maximum = max(r["max_lift_m"] for r in records) * 1000
        rows.append(
            f"<tr><td>{html.escape(names[variant['name']])}</td><td>{len(records)}</td>"
            f"<td>{lifted}/{len(records)}</td><td>{placed}/{len(records)}</td>"
            f"<td>{maximum:.1f}mm</td></tr>"
        )
    return (
        "<h2 id='scene-correction'>정정: 실제 박스 개수와 시뮬레이션 불일치</h2>"
        "<div class='warning'><strong>학습·검증 영상은 박스 2개인데 기존 기본 장면을 3개로 잘못 구성했습니다.</strong>"
        "<br>기존 0/108회는 같은 장면에서 검증한 모델 성공률이 아닙니다. 이 수치로 학습이 실패했다고 "
        "단정할 수 없습니다. 아래 원래 결과는 오류를 추적하기 위한 기록으로 보존합니다.</div>"
        "<article><p>원본 15개 녹화의 시작 영상을 다시 확인했습니다. 0–9번은 박스 2개, 10–14번은 1개입니다. "
        "2번 녹화는 시작 시 2개이고 첫 이동 뒤 20초에는 1개만 남아 있습니다. 원래 장면의 세 번째 박스는 "
        "데이터에 없던 추가 물체였습니다.</p>"
        + count_note
        + "<p>학습 모델을 다시 조정하기 전에 <strong>실제 성공 시연의 기록된 명령</strong>을 같은 0·1·2번 녹화로 "
        "재생했습니다. 박스 개수만 2개로 바꾸어도 배치는 0/3회였습니다. 따라서 개수 불일치는 확인된 문제이며, "
        "그것만 고치면 모든 실패가 해결된다고 입증되지는 않았습니다.</p></article>"
        "<div class='scroll'><table><thead><tr><th>시연 재생 조건</th><th>녹화 수</th><th>25mm 이상 들림</th>"
        "<th>안정적 배치</th><th>최대 들림 높이</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div><p class='muted'>0.16m 조건은 원래 장면의 위쪽 두 박스 높이를 유지하도록 "
        "아래 박스 1개를 4cm 높은 받침으로 대체한 비교입니다. 실측 높이를 확인했다는 뜻이 아닙니다. "
        "새 기본 설정의 박스는 2개로 정정했지만 치수·카메라·접촉 보정은 남아 있습니다.</p>"
        "<article><p><strong>테스트 해석도 구분해야 합니다.</strong> 이번 오프라인 최종 테스트는 "
        "2개 박스 녹화로 학습한 모델을 나중의 1개 박스·다른 상자 외관·다른 초기 자세에 적용한 세션 변화 테스트입니다. "
        "동일한 2개 박스 조건에서의 최종 성능을 측정한 것은 아닙니다. 박스 개수만의 영향을 분리하려면 "
        "다른 조건을 고정한 독립 녹화와, 성공 시연의 재생을 통과한 시뮬레이터가 먼저 필요합니다.</p></article>"
    )
