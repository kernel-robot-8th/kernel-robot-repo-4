"""Explain effective training settings from completed trial records."""

import html
import json


EXPLANATIONS = {
    "family": (
        "모델 종류",
        "state는 관절값만, cnn·act는 관절값과 두 카메라 영상을 사용합니다.",
        "모델 입력·구조",
        "상태 모델은 물체 개수나 위치를 영상으로 볼 수 없습니다.",
    ),
    "train_episodes": (
        "학습 시연 수",
        "학습에 쓰는 독립 녹화 수입니다. 박스 개수와 다릅니다.",
        "데이터",
        "2·4·8건을 비교했습니다. 각 학습 영상은 박스 2개 조건입니다.",
    ),
    "lr": (
        "학습률",
        "AdamW가 가중치를 갱신할 때 사용하는 기본 이동 크기입니다.",
        "모든 학습 가중치",
        "크면 빠르게 변하지만 불안정할 수 있고, 작으면 더 많은 학습이 필요할 수 있습니다.",
    ),
    "weight_decay": (
        "가중치 감쇠",
        "AdamW가 큰 가중치를 억제하는 정도입니다.",
        "모든 학습 가중치",
        "값을 키우면 과적합 완화를 기대할 수 있지만 학습 부족을 만들 수도 있습니다.",
    ),
    "dropout": (
        "무작위 활성값 제외 비율",
        "학습 중 일부 활성값을 무작위로 제외해 특정 특징 의존을 줄입니다.",
        "MLP·CNN 출력부 / ACT 변환기",
        "0.1은 10%, 0.25는 25%입니다. 평가할 때는 꺼집니다.",
    ),
    "horizon": (
        "미래 행동 예측 길이",
        "한 번에 예측하는 미래 관절 목표값의 개수입니다. ACT의 chunk_size에 대응합니다.",
        "예측 출력·학습 목표",
        "30Hz에서 16·32·64스텝은 약 0.53·1.07·2.13초입니다.",
    ),
    "action_steps": (
        "재예측 전 실행 길이",
        "예측한 행동을 몇 스텝 실행한 뒤 새 관측으로 다시 예측할지 정합니다.",
        "시뮬레이션 제어",
        "5·10스텝은 약 0.17·0.33초입니다. 학습 손실이나 가중치 갱신에는 직접 쓰지 않습니다.",
    ),
    "dim_model": (
        "ACT 내부 특징 크기",
        "ACT가 관측과 행동을 표현하는 벡터의 폭입니다.",
        "ACT만 사용",
        "128·256을 비교했습니다. 상태 MLP·CNN 설정에 남아 있는 값은 실제 구조에 적용되지 않습니다.",
    ),
    "dim_feedforward": (
        "ACT 중간 신경망 크기",
        "변환기 내부 순방향 신경망의 중간 폭입니다.",
        "ACT만 사용",
        "512·1,024를 비교했습니다. 증가하면 용량·계산량이 커집니다.",
    ),
    "augmentation": (
        "영상 증강",
        "학습 영상의 밝기·대비·위치를 무작위로 바꿉니다.",
        "학습 관측만",
        "밝기·대비 배율 0.8~1.2, 가로·세로 이동 각 -3~3픽셀입니다. 이동 시 가장자리는 반대편으로 돌아옵니다.",
    ),
    "state_noise": (
        "관절 관측 노이즈",
        "정규화한 관절 입력에 평균 0인 정규분포 노이즈를 더합니다.",
        "학습 관측만",
        "0 또는 표준편차 0.03입니다. 0.03도나 원래 관절 단위 0.03을 뜻하지 않습니다.",
    ),
    "batch_size": (
        "한 번의 갱신에 쓰는 표본 수",
        "관측 프레임과 해당 미래 행동 묶음을 모아 한 번에 학습합니다.",
        "학습",
        "모든 실험에서 24로 고정했습니다. 에피소드 끝의 마지막 작은 배치도 사용했습니다.",
    ),
    "max_steps": (
        "최대 가중치 갱신 횟수",
        "한 실험에서 허용하는 최댓값입니다. 실제 실행 횟수와 다릅니다.",
        "학습 종료 조건",
        "30,000으로 고정했고, 실제 종료 단계는 각 실험 기록에서 확인합니다.",
    ),
    "min_steps": (
        "조기 종료 전 최소 단계",
        "개선이 없더라도 이 단계 전에는 조기 종료하지 않습니다.",
        "학습 종료 조건",
        "1,000으로 고정했습니다. 전체 시간 상한은 별도로 적용됩니다.",
    ),
    "validation_every": (
        "검증 간격",
        "몇 번 가중치를 갱신한 뒤 학습·검증 오차를 기록할지 정합니다.",
        "검증",
        "250스텝마다 확인합니다. 시작·재개 직후 1스텝에서도 한 번 확인했습니다.",
    ),
    "patience": (
        "개선 대기 횟수",
        "최고 검증 오차가 충분히 개선되지 않은 검증 횟수입니다.",
        "조기 종료",
        "10회로 고정했습니다. 개선 인정 기준은 기존 최고값보다 0.005를 초과해 낮아지는 것입니다.",
    ),
    "seed": (
        "난수 시드",
        "초기 가중치·표본 순서·증강·학습 녹화 부분집합을 재현하기 위한 번호입니다.",
        "학습 반복",
        "17·42·97입니다. 새로운 실물 녹화나 독립 현장 시도 3건을 추가한 것은 아닙니다.",
    ),
    "name": (
        "실험 식별자",
        "실험 종류와 시드를 구분하는 기록 이름입니다.",
        "기록",
        "가중치의 학습 방식 자체를 바꾸는 값은 아닙니다.",
    ),
}

FIXED = [
    (
        "최적화 방식",
        "AdamW",
        "모든 학습 가중치를 같은 lr·weight_decay로 갱신했습니다. "
        "ACT 기본 최적화 설정의 별도 이미지 인코더 학습률은 사용하지 않았습니다.",
    ),
    (
        "AdamW 기본 계수",
        "β1=0.9 / β2=0.999 / ε=0.00000001",
        "갱신 방향과 크기의 이동 평균·수치 안정성 계수이며 바꾸지 않았습니다.",
    ),
    (
        "학습률 변화 방식",
        "실험 안에서는 고정",
        "학습률 스케줄러·워밍업·자동 학습률 탐색을 사용하지 않았습니다. "
        "실험 사이에서만 사전 지정한 lr 값을 바꿨습니다.",
    ),
    ("MLP·CNN 출력부 폭", "256 → 256", "상태 모델과 CNN 모델의 출력 신경망 중간 폭은 고정했습니다."),
    (
        "CNN 영상 인코더",
        "합성곱 4개, 채널 24·48·64·64",
        "두 카메라가 인코더를 공유하고 각 128차원 특징을 얻습니다. "
        "이 CNN은 ImageNet 사전학습 모델이 아닙니다.",
    ),
    (
        "ACT 영상 인코더",
        "ResNet18 / ImageNet 초기값",
        "이미지 인코더는 사전학습 가중치로 시작했고 학습 중 함께 갱신했습니다.",
    ),
    ("ACT 변환기 층·헤드", "인코더 2층·디코더 1층·헤드 8개", "전체 ACT 실험에서 고정했습니다."),
    (
        "ACT 잠재 변수",
        "VAE 사용 / 잠재 크기 32 / 인코더 2층",
        "학습할 때 시연의 잠재 표현을 사용합니다. 검증·추론은 잠재값 0으로 수행했습니다.",
    ),
    (
        "ACT KL 가중치",
        "10",
        "행동 예측 오차와 잠재 분포 규제 항의 균형입니다. 이번 실험에서는 바꾸지 않았습니다.",
    ),
    (
        "손실 함수",
        "유효 미래 행동의 L1 / ACT는 KL 항 추가",
        "에피소드 끝을 넘는 패딩은 행동 손실에서 제외합니다.",
    ),
    ("그래디언트 제한", "전체 노름 10", "급격히 큰 가중치 갱신을 줄이도록 역전파 뒤에 적용했습니다."),
    (
        "입력 영상",
        "카메라 2대 / RGB 128×96",
        "원본 640×480을 축소했습니다. 기존 현장용 640×480 모델과 입력 조건이 다릅니다.",
    ),
    (
        "관절 입력·출력",
        "현재 관절값 6개 → 목표 관절값 6개",
        "팔 관절 5개와 그리퍼 1개입니다. 전류·속도·EE 포즈 보조 항목은 이번 정책 입력에 사용하지 않았습니다.",
    ),
    (
        "관절·행동 정규화",
        "각 실험의 학습 녹화 평균·표준편차",
        "검증·테스트의 통계는 섞지 않았고 표준편차는 최소 1로 제한했습니다.",
    ),
    ("영상 정규화", "ImageNet 평균·표준편차 고정", "카메라 입력에 같은 정규화 기준을 적용했습니다."),
    (
        "관측 표본 간격",
        "학습 3 / 학습 오차 확인 24 / 검증 12 / 테스트 6프레임",
        "이는 관측 시작점의 간격입니다. 미래 행동 목표는 원래 30Hz 간격을 유지합니다.",
    ),
    ("수치 연산", "FP32 / 행렬곱 정밀도 high / AMP 미사용", "혼합 정밀도 학습은 사용하지 않았습니다."),
    (
        "체크포인트 선택",
        "앞 10개 미래 행동의 녹화별 평균 MAE",
        "chunk 길이가 달라도 같은 10스텝으로 비교했습니다. "
        "검증이 가장 좋은 체크포인트와 마지막 체크포인트는 다릅니다.",
    ),
    (
        "시간 상한",
        "실험당 1,500초 / 전체 최대 12시간 / 마무리 30분 확보",
        "12시간을 반드시 채우는 방식이 아닙니다. 각 실험의 실제 종료 사유와 단계는 기록에서 확인합니다.",
    ),
    (
        "시뮬레이션 비교",
        "제어 30Hz / 회당 50초 / 조건 6개 / 시드 3개 / 제어 방식 2개",
        "학습 설정과 별도입니다. 기존 기본 장면의 박스 3개 설정 오류는 정정 절을 확인하세요.",
    ),
]


def setting_text(value):
    """Display saved settings without requiring scientific-notation knowledge."""
    if isinstance(value, bool):
        return "켬" if value else "끔"
    if isinstance(value, float):
        return f"{value:.7f}".rstrip("0").rstrip(".")
    return str(value)


def parameter_data(trials, sweep):
    """Read actual setting ranges and checkpoint steps without altering models."""
    keys = sorted({key for trial in trials for key in trial["config"]})
    missing = set(keys) - set(EXPLANATIONS)
    if missing:
        raise ValueError(f"Undocumented effective settings: {sorted(missing)}")
    definitions = []
    for key in keys:
        if key == "name":
            continue
        name, meaning, scope, effect = EXPLANATIONS[key]
        values = sorted({json.dumps(t["config"][key], ensure_ascii=False) for t in trials})
        definitions.append(
            {
                "key": key,
                "name": name,
                "values": values,
                "function": meaning,
                "scope": scope,
                "reading_note": effect,
            }
        )
    rows = []
    for trial in sorted(trials, key=lambda t: (t["config"]["seed"], t["config"]["name"])):
        config = trial["config"]
        best = min(
            trial["history"], key=lambda row: abs(row["validation_mae"] - trial["best_validation_mae"])
        )
        differences = {
            key: value
            for key, value in config.items()
            if key not in {"name", "seed"} and value != sweep["base"].get(key)
        }
        rows.append(
            {
                "name": config["name"],
                "config": config,
                "changes_from_act_reference": differences,
                "training_recordings": trial["training_episodes"],
                "best_step": best["step"],
                "end_step": trial["steps"],
                "validation_mae": trial["best_validation_mae"],
                "stop_reason": trial["stop_reason"],
            }
        )
    return {
        "definitions": definitions,
        "fixed_settings": FIXED,
        "trials": rows,
        "reference": sweep["base"],
        "search_method": "12 predefined configurations × 3 seeds; no adaptive search",
    }


def parameter_html(trials, sweep):
    """Build a readable Korean guide and trial-by-trial change table."""
    data = parameter_data(trials, sweep)

    def esc(value):
        return html.escape(str(value))

    display = setting_text

    definitions = "".join(
        f"<tr><td>{esc(r['name'])}<br><code>{esc(r['key'])}</code></td>"
        f"<td>{esc(', '.join(display(json.loads(v)) for v in r['values']))}</td><td>{esc(r['function'])}<br>"
        f"<span class='muted'>적용: {esc(r['scope'])}</span></td><td>{esc(r['reading_note'])}</td></tr>"
        for r in data["definitions"]
    )
    fixed = "".join(
        f"<tr><td>{esc(name)}</td><td>{esc(value)}</td><td>{esc(note)}</td></tr>"
        for name, value, note in FIXED
    )
    experiments = []
    for variation in sweep["experiments"]:
        name = variation["name"]
        group = [r for r in data["trials"] if r["name"].split("_seed")[0] == name]
        changes = {k: v for k, v in variation.items() if k != "name" and v != sweep["base"].get(k)}
        text = "; ".join(f"{k}={display(v)}" for k, v in changes.items()) or "ACT 기준 설정 유지"
        value = sum(r["validation_mae"] for r in group) / len(group) if group else None
        score = "미완료" if value is None else f"{value:.3f}"
        experiments.append(
            f"<tr><td>{esc(name)}</td><td>{esc(text)}</td><td>{len(group)}</td><td>{score}</td></tr>"
        )
    actual = "".join(
        f"<tr><td>{esc(r['name'])}</td><td>{r['config']['seed']}</td>"
        f"<td>{esc(r['training_recordings'])}</td>"
        f"<td>{esc('; '.join(f'{k}={display(v)}' for k, v in r['changes_from_act_reference'].items()) or '기준 설정 유지')}</td>"
        f"<td>{r['best_step']:,} / {r['end_step']:,}</td><td>{r['validation_mae']:.3f}</td></tr>"
        for r in data["trials"]
    )
    return (
        "<h2 id='parameter-guide'>학습 파라미터 설명서</h2><article>"
        "<p><strong>학습으로 자동 갱신된 값은 신경망 가중치입니다.</strong> 아래 학습률·정규화·구조 설정은 "
        "실험 전에 정한 12가지 조합이며, 시드 3개씩 총 36번 학습했습니다. 결과에 따라 설정을 자동으로 "
        "추천·변경하는 탐색이나 실행 중 학습률 감소는 하지 않았습니다.</p>"
        "<p>학습은 원본 실제 시연으로 수행했고 MuJoCo는 평가에 사용했습니다.</p>"
        "<p><strong>학습 시연 2·4·8건과 박스 2개는 서로 다른 뜻입니다.</strong> 학습·검증 녹화의 실제 박스는 "
        "2개이며, 나중 테스트 녹화는 1개입니다. box_count는 MuJoCo 장면 설정으로 학습 시연 수가 아닙니다.</p>"
        "<p>ACT 기준: 시연 8건, lr=0.0001, weight_decay=0.0001, dropout=0.1, "
        "예측 32스텝·실행 10스텝, dim_model=128, dim_feedforward=512, 증강·관절 노이즈 끔.</p>"
        "</article><div class='scroll'><table class='guide'><thead><tr>"
        "<th>파라미터</th><th>실제로 사용한 값</th><th>기능·적용 범위</th><th>값을 읽는 방법</th>"
        "</tr></thead><tbody>" + definitions + "</tbody></table></div>"
        "<h3>실험 안에서 고정한 설정</h3><div class='scroll'><table class='guide'><thead><tr>"
        "<th>항목</th><th>실제 설정</th><th>설명</th></tr></thead><tbody>" + fixed + "</tbody></table></div>"
        "<h3>12가지 비교 조건과 실제 결과</h3><p>아래 변경점은 ACT 기준 설정과 비교한 것입니다. "
        "모델 종류가 다른 행은 구조도 다릅니다. regularized는 학습률·감쇠·dropout을 함께, "
        "long_chunk는 예측 길이·내부 폭을 함께 바꾸었으므로 한 파라미터만의 효과로 해석할 수 없습니다.</p>"
        "<div class='scroll'><table class='guide'><thead><tr><th>조건</th><th>기준에서 바꾼 값</th>"
        "<th>완료 시드 수</th><th>평균 검증 MAE</th></tr></thead><tbody>"
        + "".join(experiments)
        + "</tbody></table></div><details><summary>실제 36개 실험의 변경값·학습 녹화·선택 단계</summary>"
        "<div class='scroll'><table class='guide'><thead><tr><th>실험</th><th>시드</th><th>학습 녹화 ID</th>"
        "<th>ACT 기준에서 바꾼 값</th><th>선택 / 종료 단계</th><th>검증 MAE</th></tr></thead><tbody>"
        + actual
        + "</tbody></table></div></details><p class='muted'>선택 단계는 best.pt에 보존한 검증 기준 단계이며 "
        "종료 단계와 다릅니다. 설정에만 남아 있는 ACT 차원 값은 state·cnn에서는 사용하지 않습니다.</p>"
        "<p>실제 구현: <code>learning.py</code>·<code>train.py</code>·<code>data.py</code>. 추가 참고: "
        "<a href='https://docs.pytorch.org/docs/stable/generated/torch.optim.AdamW'>PyTorch AdamW</a>, "
        "<a href='https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/policies/act/configuration_act.py'>"
        "LeRobot 0.6.1 ACT 설정</a>. 이번 실험의 실제 값은 이 보고서와 실행 코드가 기준입니다.</p>"
    ), data


def compare_checkpoints(selected):
    """Measure actual best-to-last learned tensor changes without further training."""
    from pathlib import Path
    import torch

    from .learning import make_policy

    torch.set_num_threads(4)
    output = []
    for trial in selected:
        path = Path(trial["checkpoint"])
        best = torch.load(path, map_location="cpu", weights_only=False)
        best.pop("optimizer", None)
        last = torch.load(path.with_name("last.pt"), map_location="cpu", weights_only=False)
        last.pop("optimizer", None)
        model = make_policy(best["config"], pretrained_backbone=False)
        groups = {}
        for name, parameter in model.named_parameters():
            if name.startswith("model.backbone"):
                label = "ACT 영상 인코더"
            elif name.startswith("model.vae"):
                label = "ACT 잠재 변수 인코더"
            elif name.startswith("model.encoder"):
                label = "ACT 관측 변환기"
            elif name.startswith("model.decoder"):
                label = "ACT 행동 변환기"
            elif name.startswith("encoder"):
                label = "CNN 영상 인코더"
            elif name.startswith("head"):
                label = "관절 행동 출력 신경망"
            else:
                label = "ACT 입력·출력 투영 및 나머지 학습 가중치"
            first, second = best["model"][name].double(), last["model"][name].double()
            difference = second - first
            group = groups.setdefault(
                label, {"scalars": 0, "change_square": 0.0, "best_square": 0.0, "change_abs": 0.0}
            )
            group["scalars"] += parameter.numel()
            group["change_square"] += difference.square().sum().item()
            group["best_square"] += first.square().sum().item()
            group["change_abs"] += difference.abs().sum().item()
        records = []
        for label, group in groups.items():
            records.append(
                {
                    "group": label,
                    "learned_scalars": group["scalars"],
                    "mean_absolute_change": group["change_abs"] / group["scalars"],
                    "relative_l2_change_percent": 100
                    * (group["change_square"] / max(group["best_square"], 1e-30)) ** 0.5,
                }
            )
        output.append(
            {
                "trial": trial["config"]["name"],
                "training_config": best["config"],
                "best_step": best["step"],
                "last_saved_step": last["step"],
                "groups": records,
                "comparison": "Actual best.pt versus last.pt learned parameters; optimizer and buffers excluded",
            }
        )
        del model, best, last
    return {
        "models": output,
        "initial_snapshot_available": False,
        "limitation": "Initial weights were not saved. These are best-to-last changes, not initial-to-final changes. Magnitude is not a performance improvement measure.",
    }


def checkpoint_html(data):
    """Explain stored learned-weight changes separately from fixed hyperparameters."""
    if not data:
        return ""
    rows = []
    selected = []
    for model in data["models"]:
        config = model.get("training_config")
        if config:
            width = (
                f"{config['dim_model']} / {config['dim_feedforward']}"
                if config["family"] == "act"
                else "ACT 차원 미사용"
            )
            selected.append(
                f"<tr><td>{html.escape(model['trial'])}</td>"
                f"<td>{config['train_episodes']}</td><td>{config['lr']:.5f}</td>"
                f"<td>{config['weight_decay']:.4f}</td><td>{config['dropout']}</td>"
                f"<td>{config['horizon']} / {config['action_steps']}</td><td>{width}</td></tr>"
            )
        for group in model["groups"]:
            rows.append(
                f"<tr><td>{html.escape(model['trial'])}</td>"
                f"<td>{model['best_step']:,} → {model['last_saved_step']:,}</td>"
                f"<td>{html.escape(group['group'])}</td><td>{group['learned_scalars']:,}</td>"
                f"<td>{group['mean_absolute_change']:.6f}</td>"
                f"<td>{group['relative_l2_change_percent']:.3f}%</td></tr>"
            )
    return (
        "<h3>최종 평가에 선정한 후보 설정</h3><p>각 계열의 검증 MAE가 가장 낮은 후보입니다. "
        "현장 성능을 승인했다는 뜻은 아닙니다.</p><div class='scroll'><table class='guide'><thead><tr>"
        "<th>후보</th><th>학습 시연 수</th><th>학습률</th><th>가중치 감쇠</th><th>dropout</th>"
        "<th>예측 / 실행 스텝</th><th>ACT 내부 / 중간 폭</th></tr></thead><tbody>"
        + "".join(selected)
        + "</tbody></table></div><h3>실제 학습 가중치는 얼마나 바뀌었나</h3><p>최종 평가에 선정한 3개 모델의 실제 "
        "<code>best.pt</code>와 <code>last.pt</code>를 비교했습니다. 최적화기 내부 상태와 평균·분산 버퍼를 제외한 "
        "학습 가중치만 집계했습니다. 초기 가중치 스냅샷은 저장하지 않았으므로 초기값→최종값 변화로 표현하지 않습니다.</p>"
        "<div class='scroll'><table class='guide'><thead><tr><th>선정 모델</th><th>최고 검증 → 마지막 저장 단계</th>"
        "<th>가중치 묶음</th><th>학습 숫자 수</th><th>숫자당 평균 절대 변화</th><th>상대 L2 변화</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
        "<p class='muted'>상대 L2 변화는 ‖마지막−최고검증‖₂ / ‖최고검증‖₂ × 100입니다. "
        "변화량이 크다고 성능이 개선됐다는 뜻은 아닙니다. 배포 후보는 마지막 단계가 아니라 검증으로 선정한 단계입니다.</p>"
    )


def parameter_markdown(data, weights=None):
    """Export the same parameter definitions as repository documentation."""
    lines = [
        "# 학습 파라미터 설명서",
        "",
        "이 문서는 완료된 실험 설정과 실제 실행 코드를 기준으로 생성했습니다.",
        "",
        "- 시연 2·4·8건은 녹화 수이며 박스 개수가 아닙니다. 학습·검증 영상의 박스는 2개입니다.",
        "- 12가지 설정 × 시드 3개 = 36개 실험이며 자동 설정 탐색은 사용하지 않았습니다.",
        "- 실험 안에서 lr은 고정했고, 가중치는 AdamW로 갱신했습니다.",
        "",
        "## 실제 변경 파라미터",
        "",
        "| 키 | 이름 | 실제 값 | 기능 | 적용·해석 |",
        "|---|---|---|---|---|",
    ]
    for row in data["definitions"]:
        values = ", ".join(setting_text(json.loads(value)) for value in row["values"])
        lines.append(
            f"| `{row['key']}` | {row['name']} | {values} | "
            f"{row['function']} | {row['scope']}. {row['reading_note']} |"
        )
    lines += ["", "## 고정 설정", "", "| 항목 | 실제 값 | 설명 |", "|---|---|---|"]
    lines += [f"| {name} | {value} | {note} |" for name, value, note in data["fixed_settings"]]
    lines += [
        "",
        "## 실제 36개 실험",
        "",
        "| 실험 | 학습 녹화 ID | ACT 기준에서 바꾼 값 | 선택/종료 단계 | 검증 MAE |",
        "|---|---|---|---|---|",
    ]
    for row in data["trials"]:
        changes = "; ".join(
            f"{key}={setting_text(value)}" for key, value in row["changes_from_act_reference"].items()
        )
        lines.append(
            f"| {row['name']} | {row['training_recordings']} | {changes or '기준 유지'} | "
            f"{row['best_step']}/{row['end_step']} | {row['validation_mae']:.3f} |"
        )
    lines += [
        "",
        "## 해석 시 주의",
        "",
        "regularized는 학습률·감쇠·dropout을 함께 바꾸었고 long_chunk는 "
        "예측 길이·모델 폭을 함께 바꾸었습니다. 한 파라미터의 독립적 효과로 해석할 수 없습니다.",
        "",
        "초기 가중치 스냅샷은 없습니다. HTML 보고서는 실제 최고 검증·마지막 저장 체크포인트의 변화량을 별도로 보여줍니다.",
        "",
        "자세한 수치·장면 정정은 [HTML 보고서](../../../docs/mujoco_validation/report.html)를 확인하세요.",
    ]
    if weights:
        lines += [
            "",
            "## 실제 체크포인트 가중치 변화",
            "",
            "| 모델 | 단계 | 가중치 묶음 | 학습 숫자 수 | 평균 절대 변화 | 상대 L2 변화 |",
            "|---|---|---|---|---|---|",
        ]
        for model in weights["models"]:
            for group in model["groups"]:
                lines.append(
                    f"| {model['trial']} | {model['best_step']}→{model['last_saved_step']} | "
                    f"{group['group']} | {group['learned_scalars']} | "
                    f"{group['mean_absolute_change']:.6f} | {group['relative_l2_change_percent']:.3f}% |"
                )
    return "\n".join(lines) + "\n"
