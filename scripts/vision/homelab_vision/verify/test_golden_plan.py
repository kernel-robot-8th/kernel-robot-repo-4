#!/usr/bin/env python3
"""golden_check.py 의 팔 모델 판단과 판정 배선 시험. 모델을 돌리지 않는다(torch·ultralytics import 는 필요).

  python -B verify/test_golden_plan.py --app-dir app

보는 것:
  1. 팔 가중치도 팔 골든도 없으면 팔 대조를 건너뛴다(기존 두 모델만)
  2. 둘 다 있으면 팔 대조를 한다
  3. 가중치만 있고 골든이 없으면 실행 오류(골든 없이 팔 모델이 나가지 못하게)
  4. 골든만 있고 가중치가 없으면 실행 오류(대조했다고 착각하지 않게)
  5. judge_models 가 실제로 팔 모델을 돌리고, 그 결과가 판정에 들어간다(팔이 실패하면 DIFF)
  6. 가중치의 이름표가 앱의 자리 이름표와 다르면 문제로 잡는다(컨테이너를 바꾸기 전에)
끝날 때 실패 수를 종료 코드로 낸다(0 이면 통과).
"""
import argparse
import os
import sys
import types

ap = argparse.ArgumentParser()
ap.add_argument("--app-dir", default="/app")
args = ap.parse_args()
sys.argv = sys.argv[:1]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import golden_check as gc  # noqa: E402

FAILS = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def setup_error(fn):
    try:
        fn()
    except gc.SetupError:
        return True
    return False


check("no arm weights, no arm golden -> skip", gc.arm_plan(False, None) is False)
check("arm weights and arm golden -> run", gc.arm_plan(True, "/g/golden-arm-v1") is True)
check("arm weights without golden -> setup error", setup_error(lambda: gc.arm_plan(True, None)))
check("arm golden without weights -> setup error", setup_error(lambda: gc.arm_plan(False, "/g/golden-arm-v1")))


def judge(arm_file, arm_golden, outcome):
    """가짜 run 으로 judge_models 를 돌린다. outcome: {모델: 통과 여부}. -> (결과 표, 돌린 모델 목록)."""
    a = types.SimpleNamespace(pinky_golden="/g/p", boxes_golden="/g/b", arm_golden=arm_golden, pinky_weights="/w/p.pt",
                              boxes_weights="/w/b.pt", arm_weights="/w/arm.pt", device="cpu", repeat=1, app_dir=args.app_dir)
    ran = []

    def fake_run(tag, weights, golden, device, repeat, app_dir):
        ran.append((tag, weights, golden))
        return outcome[tag]
    res = gc.judge_models(a, run_fn=fake_run, load_fn=lambda *x: {"names": {}, "images": [1]}, exists=lambda p: arm_file)
    return res, ran


ALL_OK = {"pinky_v2_final": True, "kneg_d_final": True, "arm_v1": True}
res, ran = judge(False, None, ALL_OK)
check("no arm: only the two models run", [t for t, _, _ in ran] == ["pinky_v2_final", "kneg_d_final"] and "arm_v1" not in res)
check("no arm: verdict SAME", gc.verdict(res, 0) is True)
res, ran = judge(True, "/g/a", ALL_OK)
check("arm shipped: the arm model is really run with its own weights and golden", ("arm_v1", "/w/arm.pt", "/g/a") in ran)
check("arm shipped: verdict SAME when all three pass", gc.verdict(res, 0) is True)
res, ran = judge(True, "/g/a", dict(ALL_OK, arm_v1=False))
check("arm shipped and arm fails -> verdict DIFF", res.get("arm_v1") is False and gc.verdict(res, 0) is False)
res, ran = judge(True, "/g/a", dict(ALL_OK, kneg_d_final=False))
check("boxes fail -> verdict DIFF", gc.verdict(res, 0) is False)
check("arm weights without golden -> judge_models raises", setup_error(lambda: judge(True, None, ALL_OK)))
check("verdict: network attempt -> DIFF", gc.verdict(ALL_OK, 1) is False)
check("verdict: a required model missing from the table -> DIFF", gc.verdict({"pinky_v2_final": True, "arm_v1": True}, 0) is False)
check("verdict: empty table -> DIFF", gc.verdict({}, 0) is False)

# 6. 자리 이름표 대조(앱의 model_slots 를 읽는다)
check("slot names: arm names fit arm slot", gc.slot_names_problem("arm_v1", {0: "arm_over_pinky"}, args.app_dir) is None)
check("slot names: arm names under the pinky file name -> problem",
      gc.slot_names_problem("pinky_v2_final", {0: "arm_over_pinky"}, args.app_dir) is not None)
check("slot names: unreadable app dir -> problem, not silence",
      "model_slots" in sys.modules or gc.slot_names_problem("arm_v1", {0: "arm_over_pinky"}, "/nonexistent-app") is not None)

print(f"{len(FAILS)} failed")
sys.exit(len(FAILS))
