#!/usr/bin/env python3
"""ACT 모델 여러 개를 로봇 연결을 끊지 않고 이어서 실행 (lerobot 0.4.4).

왜 lerobot-record를 두 번 부르지 않나: 끝날 때 disconnect가 토크를 끄고, 다음 connect의 configure()가
또 토크를 끄므로 그 사이 팔이 떨어지고 잡은 물건을 놓침. 여기서는 모델을 미리 모두 올려 두고 connect/disconnect를
처음과 끝에 한 번씩만 함. 단계가 끝나면 (시간 초과든 버튼이든) 명령을 보내지 않고 토크를 유지한 채 멈춰서
(서보가 마지막 목표 위치를 유지) 다음 "next" 를 기다림. 시간이 지났다고 다음 모델이 저절로 시작하지는 않음.

전환 직후에는 다음 모델의 첫 동작이 현재 자세와 멀 수 있어서 --ramp-s 동안 한 스텝 이동량을 --ramp-max 로 더 제한함.
각 단계 시작 전에는 그 모델 번들 폴더의 init_pose.json (학습 데이터 첫 프레임 자세) 로 천천히 이동한 뒤 추론 시작.
(--no-init-pose 로 끔. 파일이 없는 모델은 이동 없이 바로 시작)
--prepare <init_pose.json>: 모델 없이 먼저 연결해서 그 자세로 이동한 뒤 토크를 유지한 채 대기하다가,
stdin 으로 'run {"stages": [[모델폴더, 초], ...]}' 가 오면 그때 모델을 불러와서 이어서 실행 (대시보드 '초기 자세로 이동 후 대기').
자동 넘김 (--auto, stdin "auto on" / "auto off", run JSON 의 "auto"): 켜져 있으면 단계가 끝난 뒤 --min-hold-s 만큼만
멈췄다가 다음 단계로 넘어감 (실행 중에도 바꿀 수 있음).
stdin 의 "next": 실행 중이면 그 단계를 끝내고 대기, 대기 중이면 다음 단계 시작 (대시보드 버튼). 정지는 SIGINT.
성공 판단 (success_judge.py): 모델 번들 폴더에 success.json 이 있고 model 이 들어 있으면, 그 단계는 top 카메라를
YOLO 로 보고 성공(예: closed_box 5초 유지)이 나오면 시간 전에 끝냄. 시간 안에 성공이 안 나오면 자동 넘김이 켜져 있어도
넘기지 않고 버튼을 기다림. success.json 이 없거나 model 이 비어 있으면 지금처럼 시간 기준. --no-success 로 끔.
마지막 단계가 끝나면 lerobot-record 와 같이 토크를 끄므로 팔이 내려앉을 수 있음.

  python omx_chain.py --port /dev/ttyACM0 --top /dev/video6 --wrist /dev/video4 --mjpg \
      --stage <모델폴더> 90 --stage <모델폴더> 90
"""

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # act_ensemble.py
sys.path.insert(0, str(Path(__file__).resolve().parent))  # success_judge.py


def parse_args(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("--stage", nargs=2, action="append", default=[], metavar=("MODEL", "SECONDS"))
    a.add_argument("--prepare", default=None, help="이 init_pose.json 자세로 먼저 이동해서 대기, 실행할 모델은 stdin 'run' 으로 받음")
    a.add_argument("--port", required=True)
    a.add_argument("--top", required=True)
    a.add_argument("--wrist", required=True)
    a.add_argument("--mjpg", action="store_true")
    a.add_argument("--robot-id", default="omx_follower")
    a.add_argument("--max-relative-target", type=float, default=10.0)
    a.add_argument("--device", default="cuda")
    a.add_argument("--n-action-steps", type=int, default=50)
    a.add_argument("--temporal-ensemble-coeff", type=float, default=None)
    a.add_argument("--use-amp", action="store_true")
    a.add_argument("--fps", type=int, default=30)
    a.add_argument("--min-hold-s", type=float, default=1.0, help="대기에 들어간 뒤 이 시간 동안은 next 무시 (버튼 두 번 눌림 방지)")
    a.add_argument("--ramp-s", type=float, default=2.0, help="전환 직후 이동량을 더 제한할 시간")
    a.add_argument("--ramp-max", type=float, default=2.0, help="전환 직후 한 스텝 최대 이동량")
    a.add_argument("--task", default="")
    a.add_argument("--auto", action="store_true", help="자동 넘김: 단계가 끝나면 버튼 없이 다음 단계로")
    a.add_argument("--no-init-pose", action="store_true", help="단계 시작 전 초기 자세 이동 끄기")
    a.add_argument("--init-speed", type=float, default=10.0, help="초기 자세 이동 속도 (단위/초, 관절 1 ≈ 1.8°)")
    a.add_argument("--init-min-s", type=float, default=2.0, help="초기 자세 이동 최소 시간")
    a.add_argument("--no-success", action="store_true", help="번들의 success.json 성공 판단을 쓰지 않음 (시간 기준)")
    return a.parse_args(argv)


def make_robot(args):
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
    from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig
    from lerobot.robots.omx_follower.omx_follower import OmxFollower

    def cam(dev):
        return OpenCVCameraConfig(
            index_or_path=int(dev) if str(dev).isdigit() else Path(dev), width=640, height=480, fps=args.fps,
            **({"fourcc": "MJPG"} if args.mjpg else {}),
        )

    return OmxFollower(OmxFollowerConfig(
        port=args.port, id=args.robot_id, max_relative_target=args.max_relative_target,
        cameras={"top": cam(args.top), "wrist": cam(args.wrist)},
    ))


def load_stage(path, seconds, args):
    import torch
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    cfg = PreTrainedConfig.from_pretrained(path)
    if cfg.type != "act":
        raise SystemExit(f"ACT 모델만 이어서 실행할 수 있음: {path} ({cfg.type})")
    cfg.device = args.device
    cfg.use_amp = args.use_amp
    cfg.pretrained_backbone_weights = None  # 어차피 체크포인트 가중치로 덮어씀
    if args.temporal_ensemble_coeff is not None:
        cfg.temporal_ensemble_coeff = args.temporal_ensemble_coeff
        cfg.n_action_steps = 1
    else:
        cfg.n_action_steps = min(args.n_action_steps, cfg.chunk_size)
    policy = ACTPolicy.from_pretrained(path, config=cfg).to(args.device).eval()
    pre, post = make_pre_post_processors(
        policy_cfg=cfg, pretrained_path=path, preprocessor_overrides={"device_processor": {"device": args.device}},
    )
    # 첫 추론이 수백 ms 걸려서 전환 때 끊기므로 미리 한 번 돌림
    batch = {k: torch.zeros(1, *v.shape, device=args.device) for k, v in cfg.input_features.items()}
    with torch.inference_mode():
        policy.predict_action_chunk(batch)
    return {"name": Path(path).name, "seconds": seconds, "policy": policy, "pre": pre, "post": post,
            "init_pose": None if args.no_init_pose else find_init_pose(path),
            "judge": None if args.no_success else make_judge(path, args)}


def make_judge(model_path, args):
    """<번들>/success.json 이 있고 model 이 들어 있으면 성공 판단기, 아니면 None (= 시간 기준)."""
    from success_judge import Detector, SuccessJudge, load_config

    name = Path(model_path).name
    try:
        cfg = load_config(Path(model_path).resolve().parent.parent)
    except ValueError as e:  # success.json 문법 오류
        raise SystemExit(f"[성공 판단] {name}: success.json 을 못 읽음 ({e})")
    if cfg is None:
        return None
    if not cfg["model"]:
        print(f"[성공 판단] {name}: success.json 의 model 이 비어 있음 — 시간 기준으로 실행", flush=True)
        return None
    try:
        det = Detector(cfg, args.device)
    except RuntimeError as e:  # 판단기가 있다고 믿고 돌렸는데 시간 기준으로 넘어가면 위험하니 시작 전에 멈춤
        raise SystemExit(f"[성공 판단] {name}: {e} — success.json 의 model 을 고치거나 비워줘 ({cfg['file']})")
    print(f"[성공 판단] {name}: 판단 모델 불러옴 ({cfg['model']})", flush=True)
    return SuccessJudge(cfg, det, log=lambda s: print(s, flush=True))


def find_init_pose(model_path):
    """<번들>/models/<모델> → <번들>/init_pose.json 의 pose (없으면 None)."""
    f = Path(model_path).resolve().parent.parent / "init_pose.json"
    return read_pose(f) if f.is_file() else None


def read_pose(f):
    import json

    pose = json.loads(Path(f).read_text())["pose"]
    return {f"{k}.pos": float(v) for k, v in pose.items()}


def move_to_pose(robot, pose, args, label):
    """현재 자세에서 pose 까지 부드럽게(코사인) 보간해서 이동. 끝나면 도달 오차 출력."""
    import math

    from lerobot.utils.robot_utils import precise_sleep

    start = robot.bus.sync_read("Present_Position")
    start = {f"{k}.pos": float(v) for k, v in start.items()}
    far = max(abs(pose[k] - start[k]) for k in pose)
    if far < 1.0:
        print(f"[초기 자세] {label}: 이미 그 자세 (차이 {far:.1f}) — 이동 생략", flush=True)
        return
    dur = max(args.init_min_s, far / args.init_speed)
    print(f"[초기 자세] {label} 로 이동 ({dur:.1f}s, 가장 큰 차이 {far:.1f})", flush=True)
    t0 = time.perf_counter()
    while (t := time.perf_counter() - t0) < dur:
        s = 0.5 - 0.5 * math.cos(math.pi * t / dur)
        robot.send_action({k: start[k] + (pose[k] - start[k]) * s for k in pose})
        precise_sleep(1 / args.fps)
    robot.send_action(dict(pose))
    time.sleep(0.5)
    now = robot.bus.sync_read("Present_Position")
    err = {k: round(float(now[k.removesuffix(".pos")]) - pose[k], 1) for k in pose}
    worst = max(abs(v) for v in err.values())
    print(f"[초기 자세] 도착 — 오차 최대 {worst:.1f} {err}" + ("  (!) 오차가 큼: 막힌 곳이 없는지 확인" if worst > 5 else ""), flush=True)


def check_inputs(stage, features):
    want = set(stage["policy"].config.input_features)
    have = {k for k in features if k.startswith("observation.")}
    if want != have:
        raise SystemExit(f"{stage['name']} 입력이 로봇과 다름: 모델 {sorted(want)} / 로봇 {sorted(have)}")
    judge = stage.get("judge")
    if judge and f"observation.images.{judge.cfg['camera']}" not in have:
        raise SystemExit(f"[성공 판단] {stage['name']}: 로봇에 '{judge.cfg['camera']}' 카메라가 없음")


def run_stage(robot, stage, features, args, next_evt, ramp):
    """한 단계 실행. 반환: 끝난 이유 'timeout' | 'next' | 'success'."""
    from lerobot.datasets.utils import build_dataset_frame
    from lerobot.policies.utils import make_robot_action
    from lerobot.utils.constants import OBS_STR
    from lerobot.utils.control_utils import predict_action
    from lerobot.utils.robot_utils import precise_sleep
    from lerobot.utils.utils import get_safe_torch_device

    policy, pre, post = stage["policy"], stage["pre"], stage["post"]
    policy.reset(), pre.reset(), post.reset()
    device = get_safe_torch_device(args.device)
    normal_max = args.max_relative_target
    limit = min(args.ramp_max, normal_max)
    judge = stage.get("judge")
    reason = "timeout"
    t0 = time.perf_counter()
    steps = slow = 0
    if judge:
        judge.begin()
    try:
        while (elapsed := time.perf_counter() - t0) < stage["seconds"]:
            if next_evt.is_set():
                reason = "next"
                break
            if judge and judge.succeeded.is_set():
                reason = "success"
                break
            start = time.perf_counter()
            robot.config.max_relative_target = limit if ramp and elapsed < args.ramp_s else normal_max
            obs = robot.get_observation()
            if judge:
                judge.feed(obs[judge.cfg["camera"]])  # 검출은 판단기 스레드가 함 (제어 주기에 영향 없음)
            frame = build_dataset_frame(features, obs, prefix=OBS_STR)
            values = predict_action(
                observation=frame, policy=policy, device=device, preprocessor=pre, postprocessor=post,
                use_amp=args.use_amp, task=args.task, robot_type=robot.robot_type,
            )
            robot.send_action(make_robot_action(values, features))
            steps += 1
            left = 1 / args.fps - (time.perf_counter() - start)
            slow += left < 0
            precise_sleep(max(left, 0.0))
    finally:
        robot.config.max_relative_target = normal_max
        if judge:
            judge.end(reason)
    why = {"timeout": "시간", "next": "버튼", "success": "성공 판단"}[reason]
    print(f"  {stage['name']}: {time.perf_counter() - t0:.1f}s, {steps} 스텝, 목표 주기 초과 {slow}회, 끝난 이유: {why}", flush=True)
    return reason


def wait_for_next(next_evt, min_hold_s, next_name, auto_evt, manual=False):
    """토크를 유지한 채 멈춰서 next 를 기다림 (자동 넘김이 켜져 있으면 min_hold_s 뒤 바로 진행).
    manual=True (성공 판단이 안 나온 채 시간이 끝남) 이면 자동 넘김이 켜져 있어도 버튼만 기다림.
    모터에는 아무 명령도 보내지 않음."""
    if manual:
        how = "성공 판단이 안 나와서 자동 넘김 안 함 · 버튼을 누르면"
    else:
        how = f"자동 넘김 켜짐 — {min_hold_s:.0f}s 뒤" if auto_evt.is_set() else "버튼을 누르면"
    print(f"[대기] 토크 유지, 멈춰 있음 — {how} {next_name} 시작", flush=True)
    time.sleep(min_hold_s)
    next_evt.clear()
    while not next_evt.wait(0.1):  # 타임아웃을 둬야 Ctrl+C 가 바로 먹음
        if auto_evt.is_set() and not manual:
            print("[자동 넘김] 다음 단계로", flush=True)
            return


def run_stages(robot, stages, features, args, next_evt, auto_evt):
    manual = False
    for i, st in enumerate(stages):
        if i:
            wait_for_next(next_evt, args.min_hold_s, st["name"], auto_evt, manual=manual)
        if st["init_pose"]:
            move_to_pose(robot, st["init_pose"], args, st["name"])
        else:
            print(f"[초기 자세] {st['name']}: init_pose.json 없음 — 이동 없이 시작", flush=True)
        next_evt.clear()
        print(f"[단계 {i + 1}/{len(stages)}] {st['name']} 시작 (최대 {st['seconds']:.0f}s)", flush=True)
        reason = run_stage(robot, st, features, args, next_evt, ramp=i > 0)
        manual = bool(st.get("judge")) and reason == "timeout"
    print("[완료] 모든 단계 끝 — 토크를 끄므로 팔이 내려앉을 수 있음", flush=True)


def load_all(specs, features, args, note):
    print(f"모델 {len(specs)}개를 불러오는 중… ({note})", flush=True)
    stages = [load_stage(p, float(s), args) for p, s in specs]
    for st in stages:
        check_inputs(st, features)
    return stages


def main(argv=None):
    import json
    import queue

    args = parse_args(argv)
    if not args.stage and not args.prepare:
        raise SystemExit("--stage 나 --prepare 가 필요함")
    logging.basicConfig(level=logging.INFO)
    if os.environ.get("ACT_ENSEMBLE_K"):
        import act_ensemble  # noqa: F401  (ACTPolicy.select_action 교체)

    from lerobot.datasets.utils import hw_to_dataset_features

    robot = make_robot(args)
    features = {
        **hw_to_dataset_features(robot.action_features, "action", True),
        **hw_to_dataset_features(robot.observation_features, "observation", True),
    }
    prep_pose = read_pose(args.prepare) if args.prepare else None
    stages = None if args.prepare else load_all(args.stage, features, args, "로봇 연결 전")

    next_evt = threading.Event()
    auto_evt = threading.Event()
    if args.auto:
        auto_evt.set()
    runs = queue.Queue()

    def set_auto(on):
        (auto_evt.set if on else auto_evt.clear)()
        print(f"[자동 넘김] {'켜짐' if on else '꺼짐'}", flush=True)

    def read_stdin():
        for line in sys.stdin:
            line = line.strip()
            if line == "next":
                next_evt.set()
            elif line in ("auto on", "auto off"):
                set_auto(line == "auto on")
            elif line.startswith("run "):
                msg = json.loads(line[4:])
                if "auto" in msg:
                    set_auto(bool(msg["auto"]))
                runs.put(msg["stages"])

    threading.Thread(target=read_stdin, daemon=True).start()

    robot.connect()
    try:
        if prep_pose:
            move_to_pose(robot, prep_pose, args, "준비")
            print("[준비 완료] 초기 자세에서 토크 유지, 대기 — 실행 버튼을 누르면 시작", flush=True)
            while True:  # 타임아웃을 둬야 Ctrl+C 가 바로 먹음
                try:
                    specs = runs.get(timeout=0.1)
                    break
                except queue.Empty:
                    pass
            stages = load_all(specs, features, args, "토크 유지, 초기 자세에서 대기 중")
        run_stages(robot, stages, features, args, next_evt, auto_evt)
    finally:
        if robot.is_connected:
            robot.disconnect()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[정지] Ctrl+C", flush=True)
        sys.exit(130)
