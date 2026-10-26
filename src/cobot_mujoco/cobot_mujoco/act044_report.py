"""Keep the version-correct ACT comparisons and their actual progress easy to inspect."""

from collections import defaultdict
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re

from .common import read_json, utc_now


def evidence(run):
    """Load only this explicitly versioned run, never mix it with the earlier 0.6.1 results."""
    run = Path(run)
    measurements = []
    jobs = []
    for directory in sorted((run / "jobs").glob("*")):
        if (directory / "result.json").exists():
            jobs.append(read_json(directory / "result.json"))
        if (directory / "measurements.json").exists():
            measurements.extend(read_json(directory / "measurements.json"))
    return {
        "plan": read_json(run / "plan.json"),
        "runtime": read_json(run / "provenance.json"),
        "state": read_json(run / "status.json") if (run / "status.json").exists() else {},
        "jobs": jobs,
        "measurements": measurements,
        "selected": read_json(run / "selected.json") if (run / "selected.json").exists() else {},
        "heldout": read_json(run / "heldout.json") if (run / "heldout.json").exists() else {},
    }


def current_progress(run, state):
    """Read a bounded tail rather than loading multi-hour progress logs."""
    name = state.get("current_job")
    if not name:
        return {}
    directory = Path(run) / "jobs" / name
    status = read_json(directory / "status.json") if (directory / "status.json").exists() else {}
    path = directory / "upstream.log"
    if path.exists():
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 20000))
            text = stream.read().decode(errors="replace")
        matches = re.findall(r"(\d+)/(\d+)\s*\[", text)
        if matches:
            status["step"], status["target"] = map(int, matches[-1])
    return status


def curves(measurements, architecture):
    """Draw original measured validation MAE at the saved comparison steps."""
    groups = defaultdict(list)
    for row in measurements:
        if row["config"]["architecture"] == architecture:
            groups[row["config"]["name"]].append(row)
    if not groups:
        return "<p>저장 체크포인트 검증 결과 수집 중</p>"
    maximum = max(r["validation"]["control_mae"] for rows in groups.values() for r in rows) * 1.1
    paths, legend = [], []
    colors = ["#55d7bd", "#efb454", "#8d9eff", "#f18fc5", "#79c6ff", "#b3dd6e"]
    for index, (name, rows) in enumerate(sorted(groups.items())):
        rows = sorted(rows, key=lambda row: row["step"])
        points = " ".join(
            f"{45 + 620 * r['step'] / 20000:.1f},{215 - 180 * r['validation']['control_mae'] / max(0.001, maximum):.1f}"
            for r in rows
        )
        color = colors[index % len(colors)]
        paths.append(f'<polyline points="{points}" stroke="{color}" fill="none" stroke-width="2.5"/>')
        legend.append(f'<span style="color:{color}">{html.escape(name)}</span>')
    return f'<svg viewBox="0 0 720 250" role="img" aria-label="{architecture} 검증 곡선"><path d="M45 20V215H690" fill="none" stroke="#aebace"/>{"".join(paths)}<text x="2" y="25" fill="#aebace">{maximum:.1f}</text><text x="590" y="245" fill="#aebace">20,000 step</text></svg><p>{" · ".join(legend)}</p>'


def render(run, destination):
    """Render configuration differences, stopping evidence, overfitting signals, and frozen selection."""
    run, destination = Path(run), Path(destination)
    data = evidence(run)
    plan, state = data["plan"], data["state"]
    live = current_progress(run, state)
    data["current_progress"] = live
    esc = html.escape
    rows = []
    for cfg in plan["trials"]:
        values = {r["step"]: r for r in data["measurements"] if r["config"]["name"] == cfg["name"]}
        job = next((j for j in data["jobs"] if j["config"]["name"] == cfg["name"]), {})
        cells = "".join(
            f"<td>{values[s]['validation']['control_mae']:.3f}</td>" if s in values else "<td>—</td>"
            for s in [2000, 5000, 10000, 20000]
        )
        rows.append(
            f"<tr><td>{esc(cfg['name'])}</td><td>{cfg['lr']:g}</td><td>{cfg['weight_decay']:g}</td>{cells}<td>{job.get('actual_steps', '진행·대기')}/{cfg['steps']}</td><td>{job.get('gpu_peak_device_mib', '—')}</td><td>{job.get('status', '진행' if state.get('current_job') == cfg['name'] else '대기')}</td></tr>"
        )
    detail = []
    for row in data["measurements"]:
        detail.append(
            f"<tr><td>{esc(row['config']['name'])}</td><td>{row['step']:,}</td><td>{row['training_probe']['control_mae']:.3f}</td><td>{row['validation']['control_mae']:.3f}</td><td>{row['gap']:.3f}</td><td>{row['validation']['per_episode'].get('8', {}).get('control_mae', 0):.3f}</td><td>{row['validation']['per_episode'].get('12', {}).get('control_mae', 0):.3f}</td></tr>"
        )
    selected = []
    for architecture, row in data["selected"].get("models", {}).items():
        heldout = data["heldout"].get(architecture, {})
        selected.append(
            f"<tr><td>{architecture}</td><td>{esc(row['config']['name'])}</td><td>{row['step']:,}</td><td>{row['validation']['control_mae']:.3f}</td><td>{heldout.get('control_mae', '대기')}</td><td><code>{esc(row['checkpoint'])}</code></td></tr>"
        )
    started = datetime.fromisoformat(plan["frozen_at"])
    finished = (
        datetime.fromisoformat(state["finished_at"])
        if state.get("finished_at")
        else datetime.now(timezone.utc)
    )
    duration = (finished - started).total_seconds() / 3600
    payload = json.dumps(data, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    refresh = '<meta http-equiv="refresh" content="60">' if state.get("status") == "running" else ""
    content = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{refresh}<title>LeRobot 0.4.4 ACT 일반형·경량형 학습 비교</title><style>
body{{margin:0;background:#0b1120;color:#edf2fb;font:15px/1.8 system-ui,sans-serif}}main{{max-width:1360px;margin:auto;padding:32px 24px}}h1{{font-size:32px}}h2{{margin-top:36px}}a{{color:#55d7bd}}article,.card,details{{background:#141e30;border:1px solid #2a3850;border-radius:10px;padding:18px;margin:16px 0}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.card strong{{display:block;font-size:26px}}.warning{{background:#30271b;border-left:4px solid #efb454;padding:18px}}.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{text-align:left;border-bottom:1px solid #2a3850;padding:10px;vertical-align:top}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}code{{overflow-wrap:anywhere}}svg{{width:100%;max-width:720px}}@media(max-width:800px){{main{{padding:16px}}.cards{{grid-template-columns:1fr 1fr}}}}</style></head><body><main>
<h1>LeRobot 0.4.4 · ACT 일반형/경량형 비교</h1><p>갱신 {utc_now()} · 상태 <strong>{esc(state.get("status", "준비"))}</strong> · 실제 경과 {duration:.2f}시간</p>
<div class="warning"><strong>이번 실행은 로컬 il_ws의 LeRobot 0.4.4입니다.</strong> 독립 CNN 학습·MuJoCo·실물 실행을 포함하지 않습니다. <a href="../report.html">이전 0.6.1 학습 보고서</a>와 구분합니다.</div>
<div class="cards"><div class="card"><strong>{len(data["jobs"])}/12</strong>종료한 학습 실행</div><div class="card"><strong>{len(data["measurements"])}/44</strong>학습·검증 비교 시점</div><div class="card"><strong>2종 구조</strong>일반형·경량형, 모두 ResNet18+Transformer</div><div class="card"><strong>0.4.4</strong>{esc(data["runtime"]["torch"])} · 원본 train 루프</div></div>
<p>현재 작업 <strong>{esc(state.get("current_job") or "없음")}</strong> · 단계 {live.get("step", "—")}/{live.get("target", "—")} · 작업 상태 {esc(live.get("status", "대기"))}</p>
<h2>한 번에 무엇을 비교하는가</h2><article><p>구조 2개 × chunk 16·32·64·100 = 기본 학습 8개를 최대 20,000스텝 실행합니다. 각 경로의 2,000·5,000·10,000·20,000 체크포인트를 비교합니다.
chunk 32에서는 일반형·경량형 각각 주 학습률 0.00003과 가중치 감쇠 0.001을 별도로 바꾼 4개 실행을 최대 10,000스텝 추가합니다. 기준은 학습률 0.00001·감쇠 0.0001입니다.
추가 실행은 같은 10,000스텝의 기준 모델과 비교해야 합니다. 스텝 비교는 같은 연속 학습 경로의 저장본이며 독립 재초기화 실험이 아닙니다.</p></article>
<div class="scroll"><table><thead><tr><th>항목</th><th>일반형</th><th>경량형</th><th>통제·해석</th></tr></thead><tbody>
<tr><td>영상 인코더·입력</td><td>ImageNet ResNet18·두 카메라 640×480</td><td>동일</td><td>둘 다 ResNet18을 함께 학습. 경량형도 영상 해상도 유지</td></tr>
<tr><td>Transformer 폭·중간 폭</td><td>512·3,200</td><td>128·512</td><td>구조 용량 차이</td></tr><tr><td>관측/VAE 인코더 깊이</td><td>4층·4층</td><td>2층·2층</td><td>디코더 1층·헤드 8개·잠재 32 동일</td></tr>
<tr><td>Chunk</td><td colspan="2">16 / 32 / 64 / 100</td><td>30Hz에서 미래 0.53 / 1.07 / 2.13 / 3.33초</td></tr>
<tr><td>Optimizer</td><td colspan="2">AdamW·배치 8·시드 17·dropout 0.1·KL 10</td><td>학습률 스케줄러·워밍업·영상 증강·관절 노이즈 없음</td></tr>
<tr><td>주 학습률</td><td colspan="2">기준 0.00001 / 추가 0.00003</td><td>ResNet18 별도 학습률은 0.00001로 고정. 주 학습률 변경은 backbone 그룹에 적용되지 않음</td></tr>
<tr><td>Weight decay</td><td colspan="2">기준 0.0001 / 추가 0.001</td><td>큰 가중치 억제. 강하면 과적합뿐 아니라 학습 부족도 가능</td></tr>
<tr><td>비교 지표</td><td colspan="2">앞 10개 미래 관절 목표의 녹화별 평균 MAE</td><td>chunk 길이가 달라도 같은 10스텝. 물체 배치 성공률 아님</td></tr></tbody></table></div>
<h2>데이터 역할과 누출 방지</h2><article><p>기본 시연 0~10번, 보완 시연 11~14번의 사용자 지정 역할을 유지합니다.
학습 {plan["split_plan"]["train"]} · 검증 {plan["split_plan"]["validation"]} · 평가 {plan["split_plan"]["test"]}입니다.
학습 11,136프레임·11개 녹화만으로 관절·행동 통계를 집계합니다. 0.4.4 원본 train에는 학습 ID만 전달하고, 별도 검증기가 저장 체크포인트를 읽습니다.
실제 영상 범위는 0~1 float이며 다시 255로 나누지 않습니다. 저장된 전처리기를 사용합니다.</p>
<p>검증에서 구조별 후보를 고른 뒤 학습·검증에 사용하지 않은 9번·11번을 평가합니다. 이미 관찰했던 원본 데이터이므로 새 현장 독립 테스트라고 표현하지 않습니다.
최종 선택 모델도 11개 녹화 학습 모델이며, 전체 15개 재학습 모델을 추가로 만들지는 않습니다.</p></article>
<h2>Chunk·step·추가 파라미터 비교표</h2><p>각 셀은 검증 MAE입니다. ‘—’는 아직 결과가 없거나 그 실험에서 계획하지 않은 시점입니다. 작업 완료와 목표 step 도달은 구분합니다. GPU 메모리는 학습 중 장치 전체 사용량 표본의 최댓값(MiB)으로 다른 GPU 프로세스도 포함할 수 있습니다.</p>
<div class="scroll"><table><thead><tr><th>실험</th><th>주 lr</th><th>감쇠</th><th>2,000</th><th>5,000</th><th>10,000</th><th>20,000</th><th>실제/목표 step</th><th>GPU 메모리</th><th>상태</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<h2>일반형 검증 곡선</h2>{curves(data["measurements"], "standard")}<h2>경량형 검증 곡선</h2>{curves(data["measurements"], "light")}
<h2>과적합 신호: 학습·검증 오차를 함께 확인</h2><p>학습 오차가 낮아지는데 검증 오차가 올라가면 과적합 또는 수집 조건 차이를 의심합니다. 학습·검증이 모두 높고 같이 감소하면 학습 부족 가능성도 있습니다. 단일 gap 숫자로 원인을 확정하지 않습니다.</p>
<div class="scroll"><table><thead><tr><th>실험</th><th>step</th><th>학습 표본 MAE</th><th>검증 MAE</th><th>검증−학습</th><th>기본 검증 8번</th><th>보완 검증 12번</th></tr></thead><tbody>{"".join(detail) or '<tr><td colspan="7">검증 결과 대기</td></tr>'}</tbody></table></div>
<h2>10만 스텝이 과한가</h2><article><p>100,000스텝을 무조건 과하다고 단정하지 않습니다. <a href="https://huggingface.co/docs/lerobot/act">공식 ACT 안내</a>에도 100k 학습 예시가 있습니다.
현재 학습 11,136프레임에서 배치 8×100,000은 약 800,000 표본, 관측 시작점 기준 약 71.8회 데이터 순회에 해당합니다. 끝 배치 등으로 달라지는 근삿값입니다.
인접 프레임·겹치는 행동 chunk는 독립 시연이 아닙니다. 20,000스텝은 같은 계산으로 약 14.4회입니다. 이번에는 최대 20,000까지만 실행하고 검증 추이로 판단하며 100,000스텝 결과를 만들어내지 않습니다.</p></article>
<h2>추가로 바꿀 수 있지만 이번에는 실행하지 않은 값</h2><article><p>Dropout은 특징 의존 억제, 밝기·대비·위치 증강은 외관 변화 대응, ResNet 별도 학습률은 영상 특징 적응 속도, 배치 크기는 갱신 안정성과 메모리, KL 가중치는 잠재 규제 강도를 바꿉니다.
시드를 늘리면 초기값에 따른 변동을 확인할 수 있습니다. 이번에는 비교 원인을 줄이기 위해 이 값들을 고정했습니다. 후보 설명을 실제 실행 내역과 섞지 않습니다.</p></article>
<h2>검증으로 선택한 두 후보와 별도 평가</h2><div class="scroll"><table><thead><tr><th>구조</th><th>선택 실험</th><th>step</th><th>검증 MAE</th><th>평가 MAE</th><th>실제 0.4.4 체크포인트 폴더</th></tr></thead><tbody>{"".join(selected) or '<tr><td colspan="6">모든 비교 완료 후 검증 기준으로 선택</td></tr>'}</tbody></table></div>
<details><summary>원본 실행 경로·소스 해시·전체 설정·결과</summary><pre id="raw"></pre></details><script type="application/json" id="evidence">{payload}</script><script>document.getElementById('raw').textContent=JSON.stringify(JSON.parse(document.getElementById('evidence').textContent),null,2)</script>
<p>실행 중 60초마다 화면 갱신 · 디스코드 30분 간격 진행 확인 · 종료 후 한국어 결과 커밋·푸시</p></main></body></html>"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(content)
    temporary.replace(destination)
    return data
