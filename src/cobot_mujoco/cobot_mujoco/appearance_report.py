"""Compare real-print scene appearance, frozen-policy responses, and paired physics runs."""

import argparse
from collections import defaultdict
import html
from pathlib import Path
import shutil

from .common import PACKAGE, read_json, utc_now, write_json

PROFILES = [
    ("before", "기존 장면", "mujoco_comparison"),
    ("visual", "외형·카메라만 수정", "mujoco_appearance_visual"),
    ("v2", "외형·카메라·뚜껑 충돌 수정", "mujoco_appearance_v2"),
]


def publish_appearance_report(training, experiment, destination):
    """Preserve before/after evidence and explicitly distinguish print visibility from grasping."""
    training, experiment, destination = map(Path, [training, experiment, destination])
    destination.mkdir(parents=True, exist_ok=True)
    evidence = destination / "appearance_v2"
    evidence.mkdir(exist_ok=True)
    probe = read_json(experiment / "probe/probe.json")
    for path in (experiment / "probe").glob("*"):
        shutil.copyfile(path, evidence / path.name)
    shutil.copyfile(PACKAGE / "config/textures/provenance.json", evidence / "texture_provenance.json")
    aggregates, rows, policy_rows, details = [], [], [], []
    for key, label, directory in PROFILES:
        state = read_json(training / directory / "status.json")
        values = [read_json(p) for p in (training / directory / "rollouts").glob("*/*/result.json")]
        replays = [read_json(p) for p in (training / directory / "replays").glob("*/result.json")]
        models = [r for r in values if r["kind"] != "hold"]
        rgb = [r for r in probe["image_cases"] if r["profile"] == key]
        row = {
            "profile": key,
            "status": state["status"],
            "policy_runs": len(models),
            "hold_runs": len(values) - len(models),
            "stable_placements": sum(r["ever_stable_placement"] for r in models),
            "finger_box_contact_frames": sum(r["finger_box_contact_frames"] for r in models),
            "lifted_runs": sum(r["lifted_boxes"] > 0 for r in models),
            "replays": len(replays),
            "replay_successes": sum(r["success_any_box"] for r in replays),
            "rgb_print_detections": sum(r["sim_rgb_detection"]["detected"] for r in rgb),
            "rgb_cases": len(rgb),
        }
        aggregates.append(row)
        rows.append(
            f"<tr><td>{label}</td><td>{row['rgb_print_detections']}/{row['rgb_cases']}</td><td>{row['stable_placements']}/{len(models)}</td><td>{row['finger_box_contact_frames']:,}</td><td>{row['lifted_runs']}/{len(models)}</td><td>{row['replay_successes']}/{len(replays)}</td></tr>"
        )
        grouped = defaultdict(list)
        for record in models:
            grouped[(record["model"], record["box_count"])].append(record)
        for (model, boxes), records in sorted(grouped.items()):
            root = f"retraining_20261025/{directory}/rollouts/{model}/boxes{boxes}_seed0"
            details.append(
                f'<tr><td>{label}</td><td>{html.escape(model)}</td><td>{boxes}</td><td>{sum(r["ever_stable_placement"] for r in records)}/{len(records)}</td><td>{sum(r["finger_box_contact_frames"] for r in records)}</td><td>{sum(r["command_tracking_mae"] for r in records) / len(records):.2f}</td><td><a href="{root}/rollout.mp4">영상</a> · <a href="{root}/montage.jpg">시점별 장면</a></td></tr>'
            )
        for family in ["cnn", "native"]:
            samples = [r for r in probe["policy_responses"] if r["profile"] == key and r["family"] == family]

            def mean(field):
                return sum(r[field] for r in samples) / len(samples)

            policy_rows.append(
                f"<tr><td>{label}</td><td>{'최종 CNN' if family == 'cnn' else '최종 공식 ACT'}</td><td>{mean('real_vs_sim_prediction_mae'):.3f}</td><td>{mean('sim_image_target_mae'):.3f}</td><td>{mean('real_image_target_mae'):.3f}</td></tr>"
            )
    cases = []
    for name in ["ep0_0s", "ep0_5s", "ep2_0s", "ep11_5s"]:
        cases.append(
            f'<article><h3>{name} · 같은 관절 상태에서의 상부 영상</h3><div class="images"><figure><img src="appearance_v2/{name}_real.jpg"><figcaption>실제 녹화 RGB</figcaption></figure><figure><img src="appearance_v2/{name}_before.jpg"><figcaption>기존 렌더</figcaption></figure><figure><img src="appearance_v2/{name}_v2.jpg"><figcaption>수정 렌더·진단용 검출 표시</figcaption></figure></div></article>'
        )
    real_count = sum(
        r["real_rgb_detection"]["detected"] for r in probe["image_cases"] if r["profile"] == "v2"
    )
    final_gallery = []
    for model in ["lightweight_final_all15", "native_act_final_all15"]:
        root = f"retraining_20261025/mujoco_appearance_v2/rollouts/{model}/boxes2_seed0"
        final_gallery.append(
            f'<article><h3>{model} · 수정된 박스 2개 장면</h3><img src="{root}/montage.jpg" style="width:100%"><video controls preload="none" src="{root}/rollout.mp4" style="width:100%;max-width:640px"></video></article>'
        )
    payload = {
        "generated_at": utc_now(),
        "summary": aggregates,
        "probe": probe,
        "policy_weights_changed": False,
        "detector_is_policy_input": False,
        "physical_calibration_certified": False,
    }
    write_json(evidence / "comparison.json", payload)
    content = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>박스 외형·카메라 인식 정합 개선</title><style>
body{{background:#0b1120;color:#edf2fb;margin:0;font:15px/1.8 system-ui,sans-serif}}main{{max-width:1320px;margin:auto;padding:32px 24px}}h1{{font-size:32px}}h2{{margin-top:38px}}a{{color:#55d7bd}}article{{background:#141e30;padding:18px;border-radius:10px;margin:16px 0}}.warning{{background:#30271b;border-left:4px solid #efb454;padding:18px}}.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{text-align:left;border-bottom:1px solid #2a3850;padding:10px}}.images{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}figure{{margin:0}}img{{width:100%}}figcaption{{color:#aebace}}@media(max-width:800px){{.images{{grid-template-columns:1fr}}main{{padding:16px}}}}</style></head><body><main>
<h1>실제 인쇄 박스가 보이도록 환경을 수정했습니다</h1><p>{utc_now()} · <a href="report.html">학습 보고서</a> · <a href="simulation_report.html">최초 MuJoCo 비교</a></p>
<div class="warning"><strong>외형 정합·진단용 검출·정책 반응·실제 집기는 서로 다른 확인 항목입니다.</strong>
실제 뚜껑 사진을 텍스처로 사용했으며, 검출 박스나 MuJoCo 정답 좌표를 ACT/CNN에 입력하지 않았습니다. 모델 가중치는 모두 이전과 같습니다. 안정 배치와 실제 로봇 성공을 보증하지 않습니다.</div>
<h2>무엇을 바꿨는가</h2><article><p>빨간 구체로 대신했던 무늬를 제거하고, 실제 2개 박스의 하트 9개와 1개 박스의 작은 하트 무늬를 투시 보정한 텍스처로 적용했습니다.
조명 과노출로 무늬가 사라지는 현상과 실제보다 강한 로봇 그림자를 줄였습니다. 상부·손목 카메라 투영을 관찰 영상의 뚜껑 모서리에 맞췄고, 화면에 찍히던 가상의 빨간 끝단 표시를 제거했습니다.</p>
<p>뚜껑은 얇은 평면 대신 전체 높이의 35%를 덮는 형태로 바꿨습니다. 외형만 수정한 비교에서는 원래 충돌체와 질량·제어를 그대로 유지했습니다.
두 번째 비교에서는 뚜껑 돌출부 1mm를 충돌 형상에 포함하고 본체·뚜껑 질량을 65:35로 나눴습니다. 합계 18g과 전체 높이·마찰은 유지했습니다.</p>
<p>상부 카메라 수직 시야각 50도와 기존 박스 크기를 가정한 평면 추정입니다. 녹화 0번·11번 뚜껑 모서리, 손목은 0번 5초를 사용했습니다.
렌즈 실측·다중 시점 물리 보정이 완료된 것은 아닙니다. 작은 평면 재투영 오차만으로 3차원 카메라 정확도를 주장하지 않습니다.</p></article>
<h2>실제 영상·수정 전·수정 후</h2>{"".join(cases)}
<h2>진단용 인쇄 무늬·색상 검출</h2><article><p>RGB의 SIFT 특징점과 RANSAC 호모그래피로 무늬를 맞추고, 작은 하트가 반복되는 분홍 뚜껑은 색상·모양·테두리 검사로 보완합니다.
단일 박스·다른 인쇄·가림이 있는 모든 상황에 일반화된 검출기는 아닙니다. 녹화 0·2·11번의 0·5·10초 총 9개 관찰 사례이며, 실제 영상 자체도 {real_count}/9개에서만 검출됐습니다.
보정에 쓴 사진·같은 무늬를 다시 보는 진단이므로 아래 숫자는 독립 데이터 인식 정확도가 아닙니다. 초록 표시는 검토용 이미지에만 그리며 정책 입력 RGB에는 그리지 않습니다.</p></article>
<div class="scroll"><table><thead><tr><th>환경</th><th>무늬·색상 정합 사례</th><th>학습 모델 안정 배치</th><th>손가락·박스 접촉 프레임 합계</th><th>25mm 이상 상승 실행</th><th>기록 명령 재생 성공</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<h2>영상만 바꿨을 때 같은 모델은 어떻게 반응하는가</h2><p>실제 관절값과 체크포인트를 같게 두고 두 카메라 RGB만 바꿉니다. 실제 이미지로 예측한 행동과의 차이, 기록된 행동 목표와의 차이를 앞 10스텝·6관절 평균 MAE로 표시합니다. 낮을수록 차이가 작습니다.</p>
<div class="scroll"><table><thead><tr><th>환경</th><th>모델</th><th>실제 영상 예측과의 차이</th><th>렌더 입력의 기록 목표 오차</th><th>실제 입력의 기록 목표 오차</th></tr></thead><tbody>{"".join(policy_rows)}</tbody></table></div>
<article><p><strong>CNN은 실제 영상 기준 출력과 가까워졌지만 공식 ACT에서는 개선되지 않았습니다.</strong> 무늬를 보기 좋게 바꾼 것과 두 정책의 관측 분포가 일치하는 것은 다릅니다.
로봇 표면·카메라·배경·가림·접촉 차이가 남아 있고, 이번 비교로 한 원인을 확정하지 않습니다. 무늬 검출 성공을 ACT의 의미적 인식 성공으로 바꿔 부르지 않습니다.</p></article>
<h2>동일 체크포인트·동일 조건의 물리 실행 비교</h2><p>각 환경에서 학습 모델 66회·정지 대조군 6회, 기록 명령 재생 6회를 비교합니다. 기준 장면·위치 이동 17/42, 박스 2개/1개, 실행당 50초·1,500 동작 프레임입니다.</p>
<div class="scroll"><table><thead><tr><th>환경</th><th>체크포인트</th><th>박스</th><th>안정 배치</th><th>손가락 접촉 프레임 합계</th><th>평균 명령 추종 MAE</th><th>증거</th></tr></thead><tbody>{"".join(details)}</tbody></table></div>
<h2>수정 환경의 최종 모델 영상</h2>{"".join(final_gallery)}
<p class="warning">기록된 성공 시연의 재생에서도 안정 배치를 재현하지 못하면 환경 오차와 학습 실패를 분리할 수 없습니다. 다음 과제는 실측 박스 치수·카메라·그리퍼 접촉의 검증과 다양한 외형·가림 조건의 독립 검출 확인입니다.</p>
<p><a href="appearance_v2/comparison.json">전체 진단 수치 JSON</a> · <a href="appearance_v2/texture_provenance.json">실제 텍스처 출처·모서리 주석</a></p></main></body></html>"""
    (destination / "appearance_report.html").write_text(content)
    return payload


def main():
    """Render the appearance comparison after both physical ablations have completed."""
    parser = argparse.ArgumentParser()
    for key in ["training", "experiment", "destination"]:
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    publish_appearance_report(args.training, args.experiment, args.destination)


if __name__ == "__main__":
    main()
