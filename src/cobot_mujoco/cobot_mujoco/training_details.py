"""Expose actual optimizer steps, checkpoint choices, learning curves, and simulation evidence."""

from collections import Counter, defaultdict
import html
from pathlib import Path

from .common import read_json

NAMES = {"cnn": "경량 CNN", "act": "경량 ACT", "native_act": "공식 ACT"}
REASONS = {
    "maximum_steps": "목표 스텝 도달",
    "validation_early_stopping": "검증 개선 정체로 조기 종료",
    "budget_exhausted": "작업 시간 상한",
    "time_limited_checkpoint": "시간 제한·저장 단계 사용",
    "completed": "목표 스텝 도달",
    "failed_with_checkpoint": "오류 종료·체크포인트 존재",
}


def step_record(row):
    """Separate the last optimizer update from the validation-selected checkpoint step."""
    cfg = row["config"]
    history = row.get("history", [])
    score = row.get("best_validation_mae")
    selected = (
        min(history, key=lambda h: abs(h.get("validation_mae", 1e30) - score), default={})
        if score is not None
        else {}
    )
    final = not cfg["split_plan"]["validation"]
    target = row.get("requested_steps", cfg.get("max_steps"))
    reason = row.get("stop_reason", row["status"])
    return {
        "name": cfg["name"],
        "family": cfg["family"],
        "regime": cfg["regime"],
        "target_steps": target,
        "actual_steps": row["steps"],
        "selected_step": row.get("selected_step", row["steps"] if final else selected.get("step")),
        "target_reached": target is not None and row["steps"] >= target,
        "stop_reason": reason,
        "training_mae": selected.get("training_mae"),
        "validation_mae": score,
        "gap": selected.get("gap"),
        "is_all_data_refit": final,
    }


def step_summary(rows):
    """Count actual step limits and stopping reasons rather than treating every result as max steps."""
    groups = defaultdict(list)
    for row in rows:
        value = step_record(row)
        groups[(value["family"], value["is_all_data_refit"])].append(value)
    return [
        {
            "family": family,
            "all_data_refit": final,
            "jobs": len(values),
            "actual_min": min(v["actual_steps"] for v in values),
            "actual_max": max(v["actual_steps"] for v in values),
            "selected_min": min(v["selected_step"] for v in values if v["selected_step"] is not None),
            "selected_max": max(v["selected_step"] for v in values if v["selected_step"] is not None),
            "total_optimizer_updates": sum(v["actual_steps"] for v in values),
            "target_reached_count": sum(v["target_reached"] for v in values),
            "stop_reasons": dict(Counter(v["stop_reason"] for v in values)),
        }
        for (family, final), values in sorted(groups.items())
    ]


def curve_html(row):
    """Draw actual same-unit MAE histories with shared axes and no smoothed or invented points."""
    history = row.get("history", [])
    series = []
    if history and "validation_mae" in history[0]:
        series = [
            ("학습", "#55d7bd", [(v["step"], v["training_mae"]) for v in history]),
            ("검증", "#efb454", [(v["step"], v["validation_mae"]) for v in history]),
        ]
    elif row.get("validation_checkpoints"):
        series = [
            ("검증", "#efb454", [(v["steps"], v["control_mae"]) for v in row["validation_checkpoints"]])
        ]
    if not series:
        return ""
    maximum_x = max(x for _, _, points in series for x, _ in points)
    maximum_y = max(y for _, _, points in series for _, y in points) * 1.05
    paths = []
    for name, color, points in series:
        xy = " ".join(
            f"{50 + 650 * x / max(1, maximum_x):.1f},{210 - 180 * y / max(0.001, maximum_y):.1f}"
            for x, y in points
        )
        paths.append(
            f'<polyline points="{xy}" fill="none" stroke="{color}" stroke-width="2"><title>{name}</title></polyline>'
        )
    name = html.escape(row["config"]["name"])
    return f'<details><summary>{name} · 실제 단계별 MAE 곡선</summary><p>가로: 가중치 갱신 step, 세로: 같은 관절 명령 MAE. 초록: 학습 / 노랑: 검증. 공식 ACT는 저장 단계별 검증 곡선만 있습니다.</p><svg role="img" aria-label="{name} 학습 곡선" viewBox="0 0 740 250" style="max-width:740px;width:100%"><path d="M50 25V210H710" fill="none" stroke="#aebace"/>{"".join(paths)}<text x="10" y="30" fill="#aebace" font-size="12">{maximum_y:.1f}</text><text x="30" y="215" fill="#aebace" font-size="12">0</text><text x="600" y="240" fill="#aebace" font-size="12">{maximum_x:,} step</text></svg></details>'


def training_html(rows):
    """Summarize training differences and exact stopping behavior in Korean."""
    groups = step_summary(rows)
    summary = []
    for group in groups:
        reasons = " · ".join(f"{REASONS.get(k, k)} {v}건" for k, v in group["stop_reasons"].items())
        summary.append(
            f"<tr><td>{NAMES[group['family']]}{' · 전체 데이터 최종' if group['all_data_refit'] else ' · 비교'}</td><td>{group['jobs']}</td><td>{group['actual_min']:,}–{group['actual_max']:,}</td><td>{group['selected_min']:,}–{group['selected_max']:,}</td><td>{group['target_reached_count']}/{group['jobs']}</td><td>{reasons}</td></tr>"
        )
    curves = "".join(curve_html(row) for row in rows if not step_record(row)["is_all_data_refit"])
    return f"""<h2 id="training-differences">각 학습의 차이와 실제 스텝</h2>
<article><p><strong>step은 가중치를 한 번 갱신한 횟수</strong>입니다. 에피소드 개수·영상 프레임·MuJoCo 동작 스텝과 다릅니다.
배치도 공식 8, 경량 24로 다르므로 같은 step이 같은 데이터 노출량·계산량을 뜻하지 않습니다.</p>
<p><strong>실행 완료</strong>는 설정한 종료 규칙에 따라 작업이 끝났다는 뜻입니다. 경량 학습의 최대 20,000스텝을 전부 채웠다는 뜻은 아닙니다.
실제 종료 step은 마지막 가중치 갱신, 선택 step은 검증 점수가 가장 좋다고 저장해 평가에 사용한 시점입니다. 두 숫자가 다른 것은 정상입니다.</p></article>
<div class="scroll"><table><thead><tr><th>학습 종류</th><th>건수</th><th>실제 종료 step 범위</th><th>평가용 선택 step 범위</th><th>목표 도달</th><th>실제 종료 이유</th></tr></thead><tbody>{"".join(summary)}</tbody></table></div>
<div class="scroll"><table><thead><tr><th>차이</th><th>경량 CNN</th><th>경량 ACT</th><th>공식 ACT</th></tr></thead><tbody>
<tr><td>학습 코드</td><td>자체 CNN 모방학습 루프</td><td>LeRobot ACT 모델을 경량 설정으로 구성한 자체 루프</td><td>설치된 원본 lerobot_train 루프</td></tr>
<tr><td>입력·예측</td><td>128×96 두 영상+관절, CNN+MLP, 16스텝</td><td>128×96 두 영상+관절, Transformer 128/512·2층, 16스텝</td><td>640×480 두 영상+관절, Transformer 512/3200·4층, 100스텝</td></tr>
<tr><td>손실·초기값</td><td>L1, 무작위 초기값</td><td>L1+KL×10, ImageNet ResNet18</td><td>공식 L1+KL×10, ImageNet ResNet18</td></tr>
<tr><td>학습률·배치</td><td>0.0003 · 24</td><td>0.0001 · 24</td><td>0.00001 · 8</td></tr>
<tr><td>데이터 방식</td><td colspan="2">기본만 / 보완 단순 결합 / 보완군 50:50 샘플링, 각각 4회 분리×시드 2개</td><td>기본만 / 보완 단순 결합, 각각 4회 분리×시드 1개</td></tr>
<tr><td>종료 규칙</td><td colspan="2">최대 20,000 또는 검증 개선 정체 또는 작업 600초 상한</td><td>10,000 고정 단계, 작업 2,400초 상한</td></tr></tbody></table></div>
<article><p>기본 9개와 보완 포함 11개 비교는 수집 데이터의 양과 내용이 함께 바뀝니다. 데이터 부족 하나의 인과 효과로 단정하지 않습니다.
50:50 샘플링은 보완 데이터를 더 자주 보게 하지만 새 데이터를 추가하지 않습니다. 과적합은 학습 오차 감소와 검증 오차 정체·증가를 함께 확인합니다.
이번 결과만으로 대형 공식 ACT 구조가 열등하다고 결론 내릴 수 없습니다. 해상도·학습률·표본 수·학습량도 동시에 다릅니다.</p></article>
<h3>학습별 실제 곡선</h3><p>모든 비교 실험의 원본 기록을 펼쳐 볼 수 있습니다. 학습 점수와 검증 점수의 간격은 수집 조건 차이의 영향도 받습니다.</p>{curves}"""


def simulation_evidence(training, report_root):
    """Keep prior trials, recorded-action replay, and newly trained policy runs distinct."""
    training, report_root = Path(training), Path(report_root)
    review = read_json(report_root / "scene_count_review.json")
    run = training / "mujoco_comparison"
    status = read_json(run / "status.json") if (run / "status.json").exists() else {"status": "not_started"}
    plan = read_json(run / "plan.json") if (run / "plan.json").exists() else {}
    results = [read_json(p) for p in sorted((run / "rollouts").glob("*/*/result.json"))]
    replays = [read_json(p) for p in sorted((run / "replays").glob("*/result.json"))]
    return {
        "historical_scene_review": review,
        "status": status,
        "plan": plan,
        "new_rollouts": results,
        "new_replays": replays,
    }


def simulation_html(evidence):
    """Render actual MuJoCo counts and side-by-side measurements without a validation claim."""
    state = evidence["status"]
    results = evidence["new_rollouts"]
    grouped = defaultdict(list)
    for row in results:
        grouped[(row["model"], row["box_count"])].append(row)
    rows = []
    for (name, boxes), values in sorted(grouped.items()):
        n = len(values)

        def average(key):
            return sum(v[key] for v in values) / n

        success = sum(v["ever_stable_placement"] for v in values)
        lifts = sum(v["lifted_boxes"] > 0 for v in values)
        image = next((v for v in values if v["seed"] == 0), None)
        links = ""
        if image:
            root = f"retraining_20261025/mujoco_comparison/rollouts/{name}/{image['case']}"
            links = f'<a href="{root}/rollout.mp4">영상</a> · <a href="{root}/montage.jpg">장면</a>'
        rows.append(
            f"<tr><td>{html.escape(name)}</td><td>{boxes}</td><td>{n}</td><td>{success}/{n}</td><td>{lifts}/{n}</td><td>{average('max_lift_m') * 1000:.1f}</td><td>{average('finger_box_contact_frames'):.0f}</td><td>{average('command_tracking_mae'):.2f}</td><td>{average('target_limit_fraction'):.1%}</td><td>{links}</td></tr>"
        )
    replay_rows = "".join(
        f"<tr><td>{r['episode']}</td><td>{r['box_count']}</td><td>{int(r['success_any_box'])}</td><td>{r['max_lift_m'] * 1000:.1f}</td><td>{r['ee_tracking_rmse_m'] * 1000:.1f}</td></tr>"
        for r in evidence["new_replays"]
    )
    counts = evidence["historical_scene_review"]["original_policy_rollout_counts"]
    historical = sum(counts.values())
    learned = [r for r in results if r["kind"] != "hold"]
    placed = sum(r["ever_stable_placement"] for r in learned)
    high_without_fingers = sum(
        r["max_lift_m"] > 0.025 and r["finger_box_contact_frames"] == 0 for r in learned
    )
    replay_success = sum(r["success_any_box"] for r in evidence["new_replays"])
    final_cnn = [r for r in learned if r["model"] == "lightweight_final_all15"]
    cnn_limit = sum(r["target_limit_fraction"] for r in final_cnn) / max(1, len(final_cnn))
    final_native = [r for r in learned if r["model"] == "native_act_final_all15"]
    default_native = [r for r in learned if r["model"] == "native_act_final_all15_interval100"]
    interval_comparison = ""
    if final_native and default_native:
        first = sum(r["command_tracking_mae"] for r in final_native) / len(final_native)
        second = sum(r["command_tracking_mae"] for r in default_native) / len(default_native)
        interval_comparison = f"공식 최종 모델은 재예측 간격 5/100스텝에서 평균 명령 추종 MAE가 {first:.3f}/{second:.3f}였습니다. 간격에 따라 궤적이 달라졌지만 배치 성공을 확인한 것은 아닙니다."
    analysis = f"""<article><h3>이번 실행에서 확인한 것</h3><p>학습 모델 실행 {len(learned)}회 중 안정 배치 도달은 {placed}회입니다.
25mm 이상 상승했지만 손가락 접촉이 없는 실행도 {high_without_fingers}회입니다. 높이 상승만으로 잡기 성공이라고 판단하지 않습니다.
실제 기록 명령 재생은 {len(evidence["new_replays"])}회 중 배치 성공 {replay_success}회입니다.</p>
<p>녹화 데이터에서의 예측 오차 개선이 이 시뮬레이션의 물체 배치 성공으로 이어졌는지를 별도로 확인했습니다.
모든 모델이 같은 배치 실패를 보이면 이 지표만으로 우열을 정할 수 없습니다. 손가락 접촉·명령 추종·목표 제한 개입은 실패 과정을 비교하는 진단 지표입니다.
보충 데이터 효과와 환경의 외관·접촉 불일치를 분리하려면 성공 시연 재생과 카메라·접촉 보정을 먼저 통과해야 합니다.</p></article>"""
    analysis += f"""<article><h3>모델·제어 방식별 차이</h3><p>전체 데이터 최종 CNN에서는 목표 제한이 평균 {cnn_limit:.1%}의 프레임에 개입했습니다.
원래 예측 목표가 현재 관절에서 멀어 환경의 10단위 제한이 동작을 크게 바꾼 경우가 많았습니다. 예측 명령과 실제 관절 추종 오차를 함께 확인해야 합니다.</p>
<p>{interval_comparison}</p><p>새 비교는 고정 회차·시드의 모델 일부와 전체 데이터 최종 후보를 평가한 것입니다.
48개 경량·8개 공식 학습 체크포인트 전부를 시뮬레이션에 넣었다는 뜻은 아닙니다. 녹화 MAE가 작은 모델도 시뮬레이션 영상·상태를 받으면 다른 궤적을 만들 수 있으며,
현재 기록만으로 시각 외관 차이·관측 분포 변화·동역학 불일치 중 한 원인으로 확정하지 않습니다.</p></article>"""
    gallery = []
    for result in learned:
        if result["model"] in {"lightweight_final_all15", "native_act_final_all15"} and result["seed"] == 0:
            root = f"retraining_20261025/mujoco_comparison/rollouts/{result['model']}/{result['case']}"
            gallery.append(
                f'<article><h3>{html.escape(result["model"])} · 박스 {result["box_count"]}개</h3><img src="{root}/montage.jpg" alt="시작·12.5초·25초·37.5초·종료 장면" style="width:100%"><video controls preload="none" src="{root}/rollout.mp4" style="width:100%;max-width:640px">실행 영상</video></article>'
            )
    return f"""<h2 id="mujoco-actual">MuJoCo를 실제로 무엇까지 실행했는가</h2>
<div class="warning"><strong>학습 완료와 MuJoCo 검증 완료는 별개입니다.</strong> 현재 새 비교 상태: {html.escape(state["status"])}.
새 정책·정지 대조군 실행 {len(results)}/{evidence["plan"].get("expected_policy_rollouts", 0)}회, 새 시연 재생 {len(evidence["new_replays"])}/{evidence["plan"].get("expected_replays", 0)}회입니다.
보정되지 않은 환경에서의 탐색적 비교이며, 실제 로봇의 성공률로 해석하지 않습니다.</div>
<div class="scroll"><table><thead><tr><th>구분</th><th>실제로 실행한 것</th><th>해석</th></tr></thead><tbody>
<tr><td>1차 모델 평가</td><td>{historical}회: 박스 3개 {counts["three_box_conditions"]}회, 1개 {counts["one_box_conditions"]}회, 2개 {counts["two_box_conditions"]}회</td><td>과거 모델·장면 오류가 포함된 기록. 이번 모델의 성능이 아님</td></tr>
<tr><td>개수 정정 뒤 과거 시연 재생</td><td>0·1·2번 기록 명령을 3조건에서 9회 재생</td><td>학습 모델의 추론 없이 성공 시연 명령을 그대로 실행. 배치 성공 0/9회</td></tr>
<tr><td>이번 재학습 모델 비교</td><td>이 표 아래 신규 실행 {len(results)}회</td><td>실제 저장 체크포인트를 로드해 시뮬레이션 영상·관절을 보고 다음 명령을 예측</td></tr></tbody></table></div>
<p>회차 0·시드 17의 CNN/경량 ACT 각 3개 데이터 방식, 공식 ACT 2개 데이터 방식, 전체 데이터 최종 모델 2개를 고정해 비교합니다.
공통 재예측 간격은 5스텝입니다. 공식 최종 ACT의 기본 100스텝 간격과 현재 관절 유지 대조군도 별도 실행합니다.
박스 2개·1개 각각 기준 장면 1개와 동일한 위치 이동 시드 17·42, 각 50초·30Hz입니다. 1개 조건은 시작 관절도 달라 개수만의 효과는 아닙니다.
조건·모델을 시뮬레이션 성적에 맞춰 선택하지 않았습니다. 같은 환경 시드의 비교이며 물리 실측 검증은 남아 있습니다.</p>
<div class="scroll"><table><thead><tr><th>모델·제어 방식</th><th>박스 수</th><th>실행</th><th>안정 배치 도달</th><th>25mm 이상 들림</th><th>평균 최대 들림 mm</th><th>손가락·박스 접촉 프레임</th><th>명령 추종 MAE</th><th>목표 제한 개입</th><th>실행 증거</th></tr></thead><tbody>{"".join(rows) or '<tr><td colspan="10">신규 실행 결과 수집 중</td></tr>'}</tbody></table></div>
{analysis}
<p>접촉 프레임은 손가락 link6·link7과 박스 사이 실제 접촉만 집계합니다. 바닥 접촉을 잡기 성공으로 세지 않습니다.
목표 제한 개입은 예측 명령이 현재 관절 대비 10 단위를 넘어 환경에서 제한된 프레임 비율입니다.
명령 추종 MAE는 원래 예측 목표와 시뮬레이터 관절의 차이이므로 목표 제한·동역학 오차도 포함합니다. 안정 배치는 들림·놓기·수신대 지지·저속 유지 15프레임을 모두 만족한 경우입니다.</p>
<h3>같은 장면의 실제 시연 명령 재생 대조</h3><div class="scroll"><table><thead><tr><th>녹화</th><th>박스</th><th>배치 성공</th><th>최대 들림 mm</th><th>끝단 궤적 RMSE mm</th></tr></thead><tbody>{replay_rows or '<tr><td colspan="5">정책 비교 뒤 실행</td></tr>'}</tbody></table></div>
<h3>전체 데이터 최종 모델의 실제 영상</h3>{"".join(gallery)}
<p>시연 재생이 실패하면 모델 실패와 환경 불일치를 분리할 수 없습니다. 영상 렌더링·카메라·접촉·모터 보정을 다음 검증 과제로 남깁니다.</p>"""
