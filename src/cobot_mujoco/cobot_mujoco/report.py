"""Generate a standalone HTML report directly from persisted experiment evidence."""

import base64
import html
import json
from pathlib import Path

from .analysis import summarize_results
from .common import read_json, utc_now


def escape(value):
    """Escape an untrusted evidence string for insertion into HTML text."""
    return html.escape(str(value))


def number(value, digits=3):
    """Format a measured value while keeping missing results visibly absent."""
    return "—" if value is None else f"{value:,.{digits}f}"


def line_chart(trial):
    """Render training and validation histories as an inline SVG chart."""
    rows = trial.get("history", [])
    if not rows:
        return "<p class='muted'>학습 곡선 대기 중</p>"
    width, height, pad = 660, 220, 34
    xmax = max(row["step"] for row in rows)
    ymax = max(max(r["training_mae"], r["validation_mae"]) for r in rows) * 1.1
    ymax = max(ymax, 0.1)
    lines = []
    for key, color in [("training_mae", "#47d7b1"), ("validation_mae", "#f6b65d")]:
        points = " ".join(
            f"{pad + (width - 2 * pad) * r['step'] / xmax:.1f},"
            f"{height - pad - (height - 2 * pad) * r[key] / ymax:.1f}"
            for r in rows
        )
        lines.append(f"<polyline points='{points}' fill='none' stroke='{color}' stroke-width='2.5'/>")
    return (
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Training and validation error'>"
        f"<path d='M{pad} 10 V{height - pad} H{width - pad}' stroke='#657387' fill='none'/>"
        f"<text x='4' y='22' fill='#aebace' font-size='11'>{ymax:.1f}</text>"
        f"<text x='{width - 85}' y='{height - 8}' fill='#aebace' font-size='11'>{xmax} steps</text>"
        + "".join(lines)
        + "</svg>"
        "<p class='legend'><span class='green'>● 학습</span> <span class='amber'>● 검증</span>"
        " · 녹화별 평균 관절 명령 MAE, 낮을수록 좋음</p>"
    )


def inline_image(path, label):
    """Embed a small evidence image into the standalone report."""
    path = Path(path)
    if not path.exists():
        return ""
    mime = "image/jpeg" if path.suffix in {".jpg", ".jpeg"} else "image/png"
    data = base64.b64encode(path.read_bytes()).decode()
    return f"<figure><img alt='{escape(label)}' src='data:{mime};base64,{data}'><figcaption>{escape(label)}</figcaption></figure>"


def make_report(run, destination, evidence=None):
    """Atomically render actual persisted results and explicit validation limits."""
    run, destination = Path(run), Path(destination)
    status = read_json(run / "status.json") if (run / "status.json").exists() else {"status": "preparing"}
    trials = []
    for path in sorted((run / "trials").glob("*/result.json")):
        trials.append(read_json(path))
    trials.sort(key=lambda x: x["best_validation_mae"])
    final = read_json(run / "final_evaluation.json") if (run / "final_evaluation.json").exists() else []
    diagnostics = read_json(run / "diagnostics.json") if (run / "diagnostics.json").exists() else {}
    source = read_json(run / "data_manifest.json") if (run / "data_manifest.json").exists() else {}
    findings = summarize_results(trials, final, diagnostics)
    findings_rows = []
    for comparison in findings["scarcity"]:
        value = comparison["mean_improvement_2_to_8"]
        direction = "개선" if value > 0 else "악화"
        findings_rows.append(
            f"<li>{comparison['family']}: 같은 {comparison['paired_seeds']}개 시드에서 "
            f"학습 녹화 2→8개 변경 시 검증 MAE가 평균 {abs(value):.3f} {direction}했습니다. "
            "추가 데이터의 효과를 확인하는 관찰이며 일반적인 데이터 충분성 판정은 아닙니다.</li>"
        )
    for comparison in findings["generalization"]:
        findings_rows.append(
            f"<li>{escape(comparison['trial'])}: 테스트−검증 MAE 차이 "
            f"{comparison['test_minus_validation']:+.3f}. "
            f"자세 유지 대조군보다 낮은 오차: {comparison['beats_hold_current_state']}.</li>"
        )
    if findings["replay_count"]:
        findings_rows.append(
            f"<li>실제 녹화 명령의 물리 재생: {findings['replay_successes']}/{findings['replay_count']}개 "
            "배치 성공. 이 결과와 실측 보정 조건이 해결되기 전에는 정책의 물리 성공률로 현장 성능을 판단할 수 없습니다.</li>"
        )
    pending = status.get("current_trial", "—")
    table_rows, curves = [], []
    for trial in trials:
        config = trial["config"]
        hist = trial.get("history", [])
        row = min(hist, key=lambda x: x["validation_mae"]) if hist else {}
        gap = row.get("validation_mae", 0) - row.get("training_mae", 0)
        table_rows.append(
            f"<tr data-family='{escape(config['family'])}'><td>{escape(config['name'])}</td>"
            f"<td>{config['family']}</td><td>{config['train_episodes']}</td><td>{config['seed']}</td>"
            f"<td>{trial['steps']:,}</td><td>{number(trial['elapsed_s'] / 60, 1)}분</td>"
            f"<td>{number(trial['best_validation_mae'])}</td><td>{number(gap)}</td>"
            f"<td>{escape(trial['stop_reason'])}</td></tr>"
        )
        curves.append(
            f"<details><summary>{escape(config['name'])} · val {trial['best_validation_mae']:.3f}</summary>"
            + line_chart(trial)
            + "</details>"
        )
    final_sections = []
    for candidate in final:
        test = candidate["test"]
        low, high = test["recording_bootstrap_ci95"]
        sims = candidate.get("simulation", [])
        sim_rows = []
        for scenario in sorted({s["scenario"] for s in sims}):
            for mode in sorted({s["mode"] for s in sims}):
                group = [
                    s
                    for s in sims
                    if s["scenario"] == scenario and s["mode"] == mode and s.get("completed_rollout", True)
                ]
                if not group:
                    continue
                successful = sum(int(s["success_any_box"]) for s in group)
                lifted = sum(int(s["lifted_boxes"] > 0) for s in group)
                sim_rows.append(
                    f"<tr><td>{scenario}</td><td>{mode}</td><td>{len(group)}</td>"
                    f"<td>{lifted}/{len(group)}</td><td>{successful}/{len(group)}</td>"
                    f"<td>{number(sum(s['force_saturation_fraction'] for s in group) / len(group))}</td></tr>"
                )
        ablations = candidate.get("camera_ablations", {})
        baseline = candidate.get("persistence_baseline", {})
        montage = (
            inline_image(
                Path(evidence) / candidate["rollout_montage"],
                "선택된 정책의 nominal 장면 · 시작, 25%, 50%, 75%, 종료",
            )
            if evidence and candidate.get("rollout_montage")
            else ""
        )
        final_sections.append(
            f"<article><h3>{escape(candidate['trial'])}</h3><p>나중 세션 5개 녹화의 관절 명령 MAE "
            f"<strong>{number(test.get('control_mae', test['point_mae']))}</strong> (앞 10스텝) · 녹화 단위 bootstrap 95% 구간 "
            f"[{number(low)}, {number(high)}]. 표본이 5개여서 불확실성이 큽니다.</p>"
            f"<p>현재 자세를 그대로 유지하는 무학습 대조군 MAE: "
            f"<strong>{number(baseline.get('control_mae'))}</strong>. "
            "이 값보다 낮은지와 실제 물체 이동을 함께 확인해야 합니다.</p>"
            f"<p>카메라 제거 MAE: wrist {number(ablations.get('wrist', {}).get('control_mae'))}, "
            f"top {number(ablations.get('top', {}).get('control_mae'))}. "
            "상태 전용 정책은 카메라 제거에 반응하지 않는 대조군입니다.</p>"
            "<div class='scroll'><table><thead><tr><th>장면 변화</th><th>제어</th><th>반복</th>"
            "<th>상자 들림</th><th>임시 배치 판정</th><th>힘 제한 도달 비율</th></tr></thead><tbody>"
            + "".join(sim_rows)
            + "</tbody></table></div>"
            + montage
            + "</article>"
        )
    scarcity = []
    for family in ["state", "act"]:
        for count in [2, 4, 8]:
            group = [
                t
                for t in trials
                if t["config"]["family"] == family
                and t["config"]["train_episodes"] == count
                and (
                    family == "state"
                    or t["config"]["name"].split("_seed")[0] in {"act_2", "act_4", "act_baseline_8"}
                )
            ]
            if group:
                values = [t["best_validation_mae"] for t in group]
                scarcity.append(
                    f"<tr><td>{family}</td><td>{count}</td><td>{len(group)}</td>"
                    f"<td>{number(sum(values) / len(values))}</td>"
                    f"<td>{number(min(values))}–{number(max(values))}</td></tr>"
                )
    evidence_html = ""
    if evidence:
        evidence = Path(evidence)
        evidence_html = (
            "<div class='images'>"
            + "".join(
                [
                    inline_image(evidence / "real_top.jpg", "실제 녹화 · top 카메라 · 에피소드 2 시작"),
                    inline_image(evidence / "sim_top.jpg", "MuJoCo · 같은 초기 관절 자세 · top"),
                    inline_image(evidence / "real_wrist.jpg", "실제 녹화 · wrist 카메라 · 에피소드 2 시작"),
                    inline_image(evidence / "sim_wrist.jpg", "MuJoCo · 같은 초기 관절 자세 · wrist"),
                ]
            )
            + "</div>"
        )
    raw = {
        "status": status,
        "analysis": findings,
        "diagnostics": diagnostics,
        "trials": trials,
        "final_evaluation": final,
        "source": source,
    }
    payload = json.dumps(raw, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    completed = status.get("status") in {"completed", "completed_with_failures", "budget_reached", "stopped"}
    refresh = "" if completed else "<meta http-equiv='refresh' content='60'>"
    content = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{refresh}<title>OMX 학습·MuJoCo 검증 보고서</title><style>
:root{{--bg:#0b1120;--panel:#141e30;--ink:#edf2fb;--muted:#aebace;--line:#2a3850;--green:#47d7b1;--amber:#f6b65d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.7 system-ui,sans-serif}}
main{{max-width:1240px;margin:auto;padding:48px 28px}}h1{{font-size:38px;line-height:1.25;margin:10px 0 18px}}
h2{{font-size:24px;margin:42px 0 18px}}h3{{font-size:18px}}a,.green{{color:var(--green)}}.amber{{color:var(--amber)}}
.muted,figcaption{{color:var(--muted)}}.eyebrow{{text-transform:uppercase;letter-spacing:.18em;color:var(--green);font-size:12px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.card,article,details{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px}}
.card strong{{display:block;font-size:28px}}.card span{{color:var(--muted);font-size:13px}}.warning{{border-left:4px solid var(--amber);background:#28241d;padding:18px 22px;border-radius:6px;margin:24px 0}}
.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;white-space:nowrap;font-size:13px}}th,td{{padding:12px;text-align:left;border-bottom:1px solid var(--line)}}th{{color:var(--muted)}}
details{{margin:10px 0;padding:14px 18px}}summary{{cursor:pointer}}svg{{max-width:760px;width:100%;display:block}}.legend{{font-size:12px;margin:0}}
.images{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}figure{{margin:0;background:var(--panel);border-radius:12px;overflow:hidden}}img{{width:100%;display:block}}figcaption{{padding:10px 16px}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}}select{{background:var(--panel);color:var(--ink);border:1px solid var(--line);padding:8px;margin-bottom:12px}}article{{margin:16px 0}}
footer{{margin-top:48px;border-top:1px solid var(--line);padding-top:18px;color:var(--muted);font-size:12px}}@media(max-width:800px){{.grid{{grid-template-columns:1fr 1fr}}.images{{grid-template-columns:1fr}}main{{padding:28px 16px}}h1{{font-size:28px}}}}
</style></head><body><main>
<div class="eyebrow">OMX • Recording-disjoint experiments • MuJoCo</div>
<h1>학습 방식과 데이터 수를 바꾸고,<br>같은 기준으로 검증합니다.</h1>
<p class="muted">생성: {escape(utc_now())} · 브랜치 feature/manipulation-mujoco-validation<br>
실행 상태: <strong>{escape(status.get("status", "preparing"))}</strong> · 현재 실험: {escape(pending)}</p>
<div class="grid"><div class="card"><strong>{len(trials)}</strong><span>완료된 학습 실험 / 계획 {status.get("planned_trials", 36)}개</span></div>
<div class="card"><strong>8 / 2 / 5</strong><span>학습 / 검증 / 잠금 테스트 녹화</span></div>
<div class="card"><strong>{source.get("total_frames", 14292):,}</strong><span>원본 프레임 · 카메라 2대 · 30Hz</span></div>
<div class="card"><strong>≤12시간</strong><span>전체 실행 상한 · 조기 종료·재개 지원</span></div></div>
<div class="warning"><strong>시뮬레이션은 아직 현장 검증을 통과하지 않았습니다.</strong><br>
상자·작업대·원형 수신 로봇 치수와 카메라 외부 파라미터는 영상 기반 추정입니다. 제조사 모델의 관절 기하와
실제 장면의 접촉·성공률 검증은 별개입니다. 아래 임시 물리 판정은 실물 성공률 또는 배포 승인으로 사용할 수 없습니다.</div>
<h2>실제 영상과 재현 장면</h2>{evidence_html}
<p class="muted">화면 공유 도구에 연결된 화면이 없어 저장된 카메라 영상을 확인했습니다. 초기 세션에는 쌓인 상자,
나중 세션에는 한 개 상자와 바뀐 초기 팔 자세가 관찰됩니다. 이는 테스트 세션의 분포 변화입니다.</p>
<h2>검증 설계</h2><article><p>학습 녹화 0–7, 검증 8–9, 잠금 테스트 10–14.
각 녹화 전체가 한쪽에만 속하며 미래 action chunk는 에피소드 끝에서 패딩합니다.
정규화 통계는 해당 실험의 학습 녹화에서만 계산합니다. 시드마다 같은 중첩 녹화 부분집합으로 2·4·8개를 비교합니다.</p>
<p>앞 10개 미래 제어 스텝의 검증 MAE로 각 모델 계열의 체크포인트를 고른 뒤 마지막에만 테스트를 엽니다.
지표는 녹화별 평균을 다시 평균하며 bootstrap도 녹화 단위입니다. 관절 명령 오차는 물체 이동 성공률과 다릅니다.
세 개 시드는 물체·실측 데이터 다양성을 추가하지 않습니다.</p></article>
<h2>학습 비교 결과</h2><select id="family" aria-label="모델 계열"><option value="all">전체 계열</option><option>state</option><option>cnn</option><option>act</option></select>
<div class="scroll"><table id="trials"><thead><tr><th>실험</th><th>계열</th><th>녹화 수</th><th>시드</th><th>스텝</th><th>시간</th><th>최저 검증 MAE</th><th>검증−학습 차이</th><th>종료 사유</th></tr></thead><tbody>
{"".join(table_rows) or '<tr><td colspan="9">아직 완료된 실험이 없습니다. 실행 중 결과가 여기에 추가됩니다.</td></tr>'}</tbody></table></div>
<h2>과적합 확인</h2><p>학습 오차가 내려가는 동안 검증 오차가 올라가는 구간, 최저 검증 지점 이후의 악화를 확인합니다.
양의 격차 하나만으로 과적합을 확정하지 않습니다. 최고 검증 체크포인트를 보존하고 개선이 멈추면 조기 종료합니다.</p>
{"".join(curves) or '<p class="muted">학습 곡선 수집 대기 중</p>'}
<h2>데이터 부족과 학습 곡선</h2><div class="scroll"><table><thead><tr><th>계열</th><th>학습 녹화 수</th><th>실험 수</th><th>평균 검증 MAE</th><th>최소–최대</th></tr></thead><tbody>
{"".join(scarcity) or '<tr><td colspan="5">2·4·8개 녹화 비교 대기 중</td></tr>'}</tbody></table></div>
<p class="muted">녹화 수가 늘 때 오차가 개선되는지와 시드 간 변동을 함께 확인해야 합니다.
성공 영상만 있으므로 실패 탐지기 정확도·재현율은 산출할 수 없습니다. 상자 위치·개수·조명·초기 자세가 다른 추가 성공·실패 녹화가 필요합니다.</p>
<h2>실험에서 확인된 점</h2><article>
<p>최저 검증 지점 이후 학습 MAE가 5% 이상 감소하면서 검증 MAE가 10%·0.1 이상 증가한
패턴: <strong>{findings["overfit_pattern_count"]}개 실험</strong>. 이 조건은 추세를 찾기 위한 명시적 기준이며 통계적 유의성 판정은 아닙니다.</p>
<ul>{"".join(findings_rows) or "<li>비교할 완료 실험을 기다리고 있습니다.</li>"}</ul>
<p>실패 예제가 없으므로 실패 탐지기 정확도·재현율은 산출하지 않았습니다. 다른 초기 배치·조명·상자 수·실패 시연을 추가하고,
시뮬레이터의 접촉·카메라 보정을 마친 뒤 독립 현장 시도로 확인해야 합니다.</p></article>
<h2>잠금 테스트와 물리 시뮬레이션</h2>
{"".join(final_sections) or '<p class="muted">학습·선택 완료 후 평가합니다. 현재 테스트 성능은 발표하지 않았습니다.</p>'}
<article><p>물리 판정: 원래 위치에서 25mm 이상 들린 상자가 원형 수신대 내부에 완전히 들어가,
손을 놓은 상태에서 속도 0.04m/s 미만으로 15프레임 유지되어야 합니다. 강제 부착·물체 텔레포트는 사용하지 않습니다.
일반 장면, 위치 변화, 낮은 마찰, 무거운 상자, 카메라 변화, 한 개 상자를 고정된 시드로 비교합니다.
초기 물체 배치가 결정적인 조건의 같은 시드 반복은 독립적인 현장 시도와 같지 않습니다.</p></article>
<h2>기하·접촉 재생 검증</h2><details open><summary>현재 진단 기록</summary><pre>{escape(json.dumps(diagnostics, ensure_ascii=False, indent=2))}</pre></details>
<h2>출처·재현·남은 조건</h2><article>
<p>원본 데이터 <a href="https://huggingface.co/datasets/{escape(source.get("source_repo", "Sungah/omx_1024_test_jihyeok_success"))}">Hugging Face</a> · Apache-2.0 ·
리비전 <code>{escape(source.get("source_revision", "pending"))}</code>.<br>
로봇 <a href="https://github.com/ROBOTIS-GIT/open_manipulator/tree/ee9a720bcc45acda9c0df8fe689b1182844307db/open_manipulator_description/mujoco/omx">ROBOTIS OMX-F 원본 MJCF</a> · Apache-2.0.</p>
<p>실행 방법은 저장소의 <code>src/cobot_mujoco/docs/validation.md</code>에 기록했습니다.
장시간 실행의 상태·오류·종료 이유와 체크포인트는 로컬 실행 폴더에 남습니다. 가중치와 원본 영상은 Git에 넣지 않습니다.
실측 치수·카메라 보정·접촉 파라미터 식별·시연 재생 성공·실물 교차 검증을 거쳐야 현장용 검증기로 승인할 수 있습니다.</p></article>
<details><summary>전체 수치와 실행 근거 JSON</summary><pre id="raw"></pre></details>
<script type="application/json" id="evidence">{payload}</script>
<script>document.getElementById('raw').textContent=JSON.stringify(JSON.parse(document.getElementById('evidence').textContent),null,2);
document.getElementById('family').onchange=function(){{document.querySelectorAll('#trials tbody tr[data-family]').forEach(r=>r.hidden=this.value!=='all'&&r.dataset.family!==this.value)}};</script>
<footer>자동 생성된 실험 기록 · 완성되지 않은 항목은 대기 또는 미검증으로 표시합니다. 실행 중 보고서는 60초마다 새로고침됩니다.</footer>
</main></body></html>"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(destination)
    return destination
