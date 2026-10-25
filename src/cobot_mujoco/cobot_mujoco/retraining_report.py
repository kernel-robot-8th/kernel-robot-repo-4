"""Report collection-role comparisons without calling supplemental training data a final test."""

from collections import defaultdict
import html
import json
from pathlib import Path

import numpy as np

from .common import read_json, utc_now
from .training_details import (
    REASONS,
    simulation_evidence,
    simulation_html,
    step_record,
    step_summary,
    training_html,
)

REGIMES = {
    "basic_only": "기본 시연만",
    "correction_concat": "보완 시연 추가",
    "correction_balanced": "보완 시연 추가·두 수집군 50:50 샘플링",
}


def results_in(run, kind):
    """Load only completed job evidence from the requested run."""
    return [read_json(p) for p in sorted((Path(run) / kind).glob("*/result.json"))]


def aggregate_holdouts(evaluations, protocol):
    """Average seeds per unique correction recording before computing uncertainty."""
    grouped = defaultdict(lambda: defaultdict(list))
    base = defaultdict(list)
    for row in evaluations:
        key = (row["family"], row["regime"])
        for episode, value in row["metrics"]["per_episode"].items():
            episode = int(episode)
            if episode in protocol["correction_ids"]:
                grouped[key][episode].append(value["control_mae"])
            elif episode in protocol["basic_test_ids"]:
                base[key].append(value["control_mae"])
    output = []
    rng = np.random.default_rng(2718)
    for (family, regime), episodes in sorted(grouped.items()):
        values = np.array([np.mean(v) for v in episodes.values()])
        bootstrap = rng.choice(values, (2000, len(values)), replace=True).mean(1)
        output.append(
            {
                "family": family,
                "regime": regime,
                "unique_correction_recordings": len(values),
                "correction_mae": float(values.mean()),
                "correction_ci95": np.quantile(bootstrap, [0.025, 0.975]).tolist(),
                "per_correction_recording": {str(k): float(np.mean(v)) for k, v in episodes.items()},
                "basic_mae": float(np.mean(base[(family, regime)])),
                "unique_basic_test_recordings": len(protocol["basic_test_ids"]),
            }
        )
    return output


def write_retraining_report(run, destination):
    """Render progress, actual upstream training, split roles, and all-data refits."""
    run, destination = Path(run), Path(destination)
    protocol = read_json(run / "plan.json")
    state = read_json(run / "status.json") if (run / "status.json").exists() else {"status": "준비 중"}
    light, native = results_in(run, "trials"), results_in(run, "native")
    evaluations = (
        read_json(run / "heldout_evaluations.json") if (run / "heldout_evaluations.json").exists() else []
    )
    summary = aggregate_holdouts(evaluations, protocol) if evaluations else []
    final = results_in(run, "final")

    def esc(value):
        return html.escape(str(value))

    split_rows = []
    frozen = read_json(run / "frozen_trial_plan.json")
    examples = [
        r
        for r in frozen["lightweight"]
        if r["family"] == "act" and r["seed"] == 17 and r["regime"] == "correction_concat"
    ]
    for row in examples:
        split = row["split_plan"]
        split_rows.append(
            f"<tr><td>{row['fold']}</td><td>{esc(split['train'])}</td>"
            f"<td>{esc(split['validation'])}</td><td>{esc(split['test'])}</td></tr>"
        )
    job_rows = []
    for row in native + light:
        cfg = row["config"]
        score = row.get("best_validation_mae")
        selected = min(
            row.get("history", []),
            key=lambda h: abs(h["validation_mae"] - score),
            default={},
        )
        train_mae = selected.get("training_mae")
        gap = selected.get("gap")
        steps = step_record(row)
        job_rows.append(
            f"<tr><td>{esc(cfg['name'])}</td><td>{esc(REGIMES[cfg['regime']])}</td>"
            f"<td>{steps['target_steps']:,}</td><td>{row['steps']:,}</td>"
            f"<td>{steps['selected_step']:,}</td><td>{'도달' if steps['target_reached'] else '미도달'}</td>"
            f"<td>{esc(REASONS.get(steps['stop_reason'], steps['stop_reason']))}</td>"
            f"<td>{'—' if score is None else f'{score:.3f}'}</td>"
            f"<td>{'—' if train_mae is None else f'{train_mae:.3f}'}</td>"
            f"<td>{'—' if gap is None else f'{gap:.3f}'}</td>"
            f"<td>{row['elapsed_s'] / 60:.1f}분</td><td>{esc(row['status'])}</td></tr>"
        )
    summary_rows = []
    for row in summary:
        lo, hi = row["correction_ci95"]
        summary_rows.append(
            f"<tr><td>{esc(row['family'])}</td><td>{esc(REGIMES[row['regime']])}</td>"
            f"<td>{row['unique_correction_recordings']}</td><td>{row['correction_mae']:.3f}</td>"
            f"<td>{lo:.3f}–{hi:.3f}</td><td>{row['basic_mae']:.3f}</td></tr>"
        )
    refit_rows = []
    for row in final:
        steps = step_record(row)
        refit_rows.append(
            f"<tr><td>{esc(row['config']['name'])}</td><td>{esc(row['status'])}</td>"
            f"<td>{steps['target_steps']:,}</td><td>{row['steps']:,}</td><td>{esc(REASONS.get(steps['stop_reason'], steps['stop_reason']))}</td><td>{esc(row['checkpoint'])}</td></tr>"
        )
    detail = training_html(native + light + final)
    simulation = simulation_evidence(run, destination.parent)
    simulation_section = simulation_html(simulation)
    appearance_link = (
        '<p><a href="appearance_report.html">박스 외형·카메라 수정 전후 인식 정합·정책 반응·물리 비교</a></p>'
        if (destination.parent / "appearance_report.html").exists()
        else ""
    )
    native_provenance = (
        read_json(run / "native_provenance.json") if (run / "native_provenance.json").exists() else {}
    )
    audit = read_json(run / "lineage_audit.json") if (run / "lineage_audit.json").exists() else {}
    source = read_json(run / "data_source.json") if (run / "data_source.json").exists() else {}
    current = state.get("current_job")
    progress = {}
    if current:
        for kind in ["native", "trials", "final"]:
            output = run / kind / current
            if (output / "status.json").exists():
                progress = read_json(output / "status.json")
                checkpoints = list((output / "upstream/checkpoints").glob("*/pretrained_model"))
                saved = [int(p.parent.name) for p in checkpoints if p.parent.name.isdigit()]
                progress["last_saved_upstream_step"] = max(saved, default=0)
                break
    elapsed = state.get("elapsed_s")
    duration = f"{elapsed / 3600:.2f}시간" if elapsed is not None else "진행 중"
    raw = {
        "protocol": protocol,
        "state": state,
        "lineage_audit": audit,
        "native_provenance": native_provenance,
        "data_source": source,
        "current_job_evidence": progress,
        "lightweight_results": light,
        "native_results": native,
        "heldout_evaluations": evaluations,
        "summary": summary,
        "all_data_refits": final,
        "step_summary": step_summary(native + light + final),
        "mujoco_comparison": simulation,
    }
    payload = json.dumps(raw, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    refresh = (
        ""
        if state.get("status") in {"completed", "incomplete", "failed", "budget_reached", "stopped"}
        and simulation["status"]["status"] != "running"
        else '<meta http-equiv="refresh" content="60">'
    )
    content = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{refresh}
<title>데이터 수집 의도 반영 재학습 · 공식 LeRobot ACT</title><style>
body{{margin:0;background:#0b1120;color:#edf2fb;font:15px/1.75 system-ui,sans-serif}}
main{{max-width:1280px;margin:auto;padding:40px 24px}}h1{{font-size:34px;line-height:1.3}}h2{{margin-top:40px}}
a{{color:#55d7bd}}.muted{{color:#aebace}}.card,article,details{{background:#141e30;border:1px solid #2a3850;border-radius:12px;padding:18px;margin:14px 0}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.card strong{{display:block;font-size:28px}}
.warning{{background:#30271b;border-left:4px solid #efb454;padding:18px}}.scroll{{overflow:auto}}
table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{border-bottom:1px solid #2a3850;text-align:left;padding:10px;vertical-align:top}}th{{color:#aebace}}
code{{overflow-wrap:anywhere}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}}summary{{cursor:pointer}}
@media(max-width:800px){{.cards{{grid-template-columns:1fr 1fr}}main{{padding:20px 12px}}h1{{font-size:26px}}}}
</style></head><body><main><p class="muted">데이터 역할 정정 · 기본 시연 / 보완 시연 · 공식 학습기 비교</p>
<h1>보완 시연을 실제 학습에 넣고,<br>LeRobot 기본 ACT와 함께 다시 비교합니다.</h1>
{appearance_link}
<div class="warning"><strong>학습 상태: {esc(state.get("status"))} · 신규 MuJoCo 비교 상태: {esc(simulation["status"]["status"])}</strong><br>학습 완료는 시뮬레이션 검증 완료를 뜻하지 않습니다. <a href="simulation_report.html">MuJoCo 실제 실행·영상·결과로 이동</a> · <a href="#training-differences">학습 차이·스텝으로 이동</a></div>
<p>생성 {esc(utc_now())} · 상태 <strong>{esc(state.get("status"))}</strong><br>현재 작업 {esc(state.get("current_job") or "없음")}</p>
<p class="muted">현재 작업 상태 {esc(progress.get("status", "대기"))} · 마지막 저장 단계 {esc(progress.get("last_saved_upstream_step", progress.get("step", "—")))} · 공식 학습 PID {esc(progress.get("upstream_pid", "—"))}</p>
<div class="cards"><div class="card"><strong>{len(light)}/48</strong>경량 비교 학습</div>
<div class="card"><strong>{len(native)}/8</strong>공식 ACT 비교 학습</div>
<div class="card"><strong>{len(final)}/2</strong>전체 15개 시연 재학습</div><div class="card"><strong>{duration}</strong>실제 실행 · 최대 12시간</div></div>
<div class="warning"><strong>이전 데이터 역할 해석을 수정했습니다.</strong> 사용자 지정 기본 수집은 0~10번, 보완 수집은 11~14번입니다.
11~14번을 모두 최종 테스트로 두었던 1차 분리는 수집 의도를 반영하지 못했습니다. 보완 시연을 학습에 넣는 실험으로 다시 구성했습니다.
이 데이터는 이미 검토했던 수집 자료이므로 새로 수집한 독립 현장 테스트로 표현하지 않습니다.</div>
<h2>수집 역할과 물체 개수는 다른 정보입니다</h2><article>
<p>기본 시연: {esc(protocol["basic_ids"])}. 보완 시연: {esc(protocol["correction_ids"])}.
영상에서 관찰한 물체 개수는 0~9번 2개, 10~14번 1개입니다. 영상 10번은 사용자 지정에 따라 기본 수집으로 분류했습니다.
‘같은 에피소드’는 같은 태스크의 별도 반복 시연으로 우선 해석했습니다. 수집 시각과 움직이는 100프레임 구간 {audit.get("dynamic_100_frame_windows_checked", 0):,}개의
완전 중복을 검사했습니다. 한 번의 원본 녹화를 나눈 조각이라는 별도 정보가 확인되면 녹화 원본 단위로 다시 묶어야 합니다.</p>
<p>보완 데이터는 사용자가 DAgger 느낌으로 추가한 시연입니다. 정책 실행 중 전문가 개입·수정 라벨의 별도 기록은 없으므로
정식 DAgger 반복 수집을 수행했다고 주장하지 않습니다.</p></article>
<h2>비교 방법과 녹화 분리</h2><article><p>각 학습 모델에는 기본 시연 9개를 사용하고, 보완 수집 4개 중 2개를 추가하거나 제외합니다.
같은 회차에서 기본 8번과 보완 1개를 검증에, 기본 9번과 다른 보완 1개를 평가에 남깁니다.
4회 순환하여 보완 11~14번이 각각 한 번씩 평가용이 되게 합니다. 시드는 경량 17·42, 공식 학습기 17입니다.</p>
<p>비교: 기본 시연만 / 보완 시연 합치기 / 학습 샘플의 기본·보완 수집군을 50:50으로 뽑기.
50:50에서는 각 수집군 안에서도 녹화별 확률을 같게 합니다. 정규화 통계는 각 모델의 학습 녹화만 사용합니다.</p></article>
<div class="scroll"><table><thead><tr><th>회차</th><th>보완 결합 모델의 학습 ID</th><th>검증 ID</th><th>평가 ID</th></tr></thead><tbody>{"".join(split_rows)}</tbody></table></div>
<h2>공식 LeRobot 학습을 실제로 실행합니다</h2><article>
<p><code>python -m lerobot.scripts.lerobot_train</code>을 별도 프로세스로 실행합니다. 설치된 공식 학습 루프를 수정하지 않았습니다.
원본 640×480 영상, ACT 내부 512·중간 3,200·인코더 4층·행동 100스텝, 실제 학습 가중치 51,597,190개를 사용합니다.
배치 8, 기본 학습률 0.00001, 가중치 감쇠 0.0001, ImageNet ResNet18 초기값, 최대 10,000스텝입니다.
검증 통계 누출을 막기 위해 입력 데이터의 메타 통계만 해당 학습 ID로 다시 집계한 로컬 사본을 사용합니다.
영상·행동 데이터와 공식 학습 코드는 원본을 유지합니다. 각 작업의 명령·로그·원본 체크포인트 설정을 저장합니다.</p>
<p>경량 비교는 128×96 영상, CNN 또는 ACT 내부 128·중간 512·인코더 2층·행동 16스텝, 배치 24입니다.
CNN 학습률 0.0003, ACT 0.0001, dropout 0.1, 가중치 감쇠 0.0001, 증강·입력 노이즈 끔으로 고정했습니다.
250스텝마다 검증하고 개선 폭 0.005 초과가 10회 없으면 최소 1,500스텝 뒤 조기 종료합니다.
공식 학습은 원래 루프의 고정 단계 학습과 1,000스텝 체크포인트를 사용합니다. 두 방식의 구조·해상도·관측 표본 수·학습량이 달라
성능 차이를 모델 크기 하나의 영향으로 해석할 수 없습니다.</p></article>
{detail}
<h2>실제 학습 작업 · 전체 56건</h2><p>경량 모델은 선택 시점의 학습 MAE와 검증−학습 차이를 함께 기록합니다. 학습 오차가 내려가면서 검증 오차가 커지는지는 위 곡선과 원본 JSON의 단계별 history로 확인할 수 있습니다.
큰 차이는 과적합·수집 조건 차이의 신호이며 단독 원인 진단은 아닙니다. 공식 모델은 저장 단계별 검증 MAE를 기록하며, 학습 MAE를 별도로 측정하지 않은 칸은 비워 둡니다.</p>
<div class="scroll"><table><thead><tr><th>실험</th><th>데이터 방식</th><th>목표step</th><th>실제 종료step</th><th>평가에 선택한step</th><th>목표 도달</th><th>종료 이유</th><th>최고 검증 MAE</th><th>선택 시 학습 MAE</th><th>검증−학습</th><th>소요 시간</th><th>작업 상태</th></tr></thead><tbody>
{"".join(job_rows) or '<tr><td colspan="12">현재 작업의 학습 로그가 수집 중입니다.</td></tr>'}</tbody></table></div>
<h2>보완 시연 학습 효과와 기본 동작 유지</h2><p>같은 녹화의 시드 평균을 먼저 낸 뒤 보완 평가 녹화 4개를 평균합니다.
95% 구간도 고유 보완 녹화 단위 bootstrap입니다. 기본 평가 녹화는 9번 하나이므로 일반적인 기본 동작 성공률로 해석할 수 없습니다.
지표는 앞 10개 미래 관절 명령의 MAE이며 물체 이동 성공률과 다릅니다.</p>
<div class="scroll"><table><thead><tr><th>학습기</th><th>데이터 방식</th><th>고유 보완 평가 녹화 수</th><th>보완 MAE</th><th>95% 구간</th><th>기본 9번 MAE</th></tr></thead><tbody>
{"".join(summary_rows) or '<tr><td colspan="6">모든 비교 학습과 검증 기준 후보 확정 후 평가합니다.</td></tr>'}</tbody></table></div>
<h2>전체 시연을 반영한 마지막 모델</h2><article><p>비교 검증으로 설정을 정한 뒤, 별도의 경량 후보와 공식 ACT를 0~14번 전체로 다시 학습합니다.
이 모델에는 보완 11~14번 전부를 반영합니다. 학습에 모든 녹화를 사용하므로 독립 테스트 점수를 붙이지 않습니다.
표의 경로는 로컬 가중치이며 대용량 모델을 Git에 넣지 않습니다.</p></article>
<div class="scroll"><table><thead><tr><th>모델</th><th>상태</th><th>목표step</th><th>실제 종료step</th><th>종료 이유</th><th>실제 체크포인트 경로</th></tr></thead><tbody>{"".join(refit_rows) or '<tr><td colspan="6">비교 학습 완료 후 생성합니다.</td></tr>'}</tbody></table></div>
{simulation_section}
<p><a href="round1_report.html">1차 보고서와 박스 개수 정정 기록</a> · <a href="../../src/cobot_mujoco/docs/retraining.md">재학습 절차·파라미터 설명</a></p>
<details><summary>전체 설정·학습 결과·원본 실행 근거 JSON</summary><pre id="raw"></pre></details>
<script type="application/json" id="evidence">{payload}</script><script>document.getElementById('raw').textContent=JSON.stringify(JSON.parse(document.getElementById('evidence').textContent),null,2)</script>
<p class="muted">실행 중 60초마다 갱신 · 실제 완료 수와 중단·시간 제한 상태를 기록합니다.</p></main></body></html>"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(".tmp")
    tmp.write_text(content)
    tmp.replace(destination)
    styles = content.split("<style>", 1)[1].split("</style>", 1)[0]
    simulation_page = (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>재학습 모델 MuJoCo 실제 비교</title><style>" + styles + "</style></head><body><main>"
        '<h1>재학습 모델의 MuJoCo 실행·비교 분석</h1><p><a href="report.html">전체 학습 보고서로 이동</a></p>'
        + appearance_link
        + simulation_section
        + "</main></body></html>"
    )
    destination.with_name("simulation_report.html").write_text(simulation_page)
    return raw
