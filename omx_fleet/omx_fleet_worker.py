#!/usr/bin/env python3
"""관제(cobot_manipulation arm_adapter, backend=worker)용 팔 실행기 (lerobot 0.4.4).

omx_chain.py 의 함수(로봇 만들기·모델 불러오기·초기 자세 이동·단계 실행)를 그대로 쓰고,
사람 대신 어댑터가 stdin/stdout 으로 일을 시킨다. 같은 폴더의 omx_chain.py·success_judge.py 는
tool/omx-dashboard-v2 (a54637d) 의 omx_dashboard_v2/ 에서 고치지 않고 복사한 것이다.

왜 따로 두나: 작업마다 lerobot-record 를 새로 켜면 끝날 때·시작할 때 토크가 꺼져 팔이 떨어진다.
이 실행기는 켜질 때 한 번 연결하고 모든 모델을 미리 올린 뒤, 작업이 끝나도 토크를 유지한 채 다음 일을 기다린다.

대화 방식 (한 줄 = JSON 하나)
  stdin  {"cmd": "run", "id": "<request_id>", "action": "pick"}
         {"cmd": "hold"}   지금 단계를 멈추고 토크 유지 (안전 자세 이동도 하지 않음)
         {"cmd": "state"}  대기 중 관절 값 보고 (작업 중이면 작업이 끝난 뒤 답함)
         {"cmd": "release"} 쉬는 자세(rest_pose)에 있을 때만 연결을 끊고 끝냄. 아니면 거절 (팔을 옮기지 않음).
                            팔 설정 release_move: true 면 거절 대신 쉬는 자세로 옮긴 뒤 다시 재서 끈다
         {"cmd": "quit"}   무조건 연결을 끊고 끝냄 (토크가 꺼지므로 팔이 내려앉을 수 있음)
  stdout 기계용 줄은 "@fleet " 로 시작한다. 나머지 줄은 사람이 읽는 로그.
         @fleet {"event": "ready", "actions": [...], "joints": {...}, "models": {action: {...}},
                 "rest_pose": {관절: 값} | null, "safe_tol": N}      models 칸은 model_meta() 참고
         @fleet {"event": "state", "joints": {...}}
         @fleet {"event": "release_moving", "seconds": N, ...}       release_move: 쉬는 자세로 이동 시작 (약 N 초)
         @fleet {"event": "released", "pose_error": {...}}             이어서 연결을 끊고 끝냄
         @fleet {"event": "release_refused", "detail": "...", "pose_error": {...}, "joints": {...}}
         @fleet {"event": "started", "id": ...}
         @fleet {"event": "done", "id": ..., "success": bool, "success_basis": "judge"|"none",
                 "arm_safe": bool, "end_reason": "success"|"timeout"|"hold", "pose_error": {...}, "joints": {...},
                 "model": "<bundle>@<version>"}
         @fleet {"event": "rejected", "id": ..., "detail": "..."}   팔을 움직이지 않은 거절
         @fleet {"event": "fatal", "detail": "..."}                 이후 일을 하지 않고 끝냄

판단 규칙
  - success: 성공 판단(success.json 의 YOLO)이 성공을 낸 경우만 true. 판단기가 없으면 항상 false (success_basis=none).
  - arm_safe: 단계가 끝난 뒤 그 action 의 safe_pose 로 이동하고 (그리퍼는 그대로 둠 — 잡은 물건을 놓지 않게)
    관절을 다시 읽어 그리퍼 외 모든 관절 오차가 safe_tol 이하일 때만 true. hold 로 끝나면 이동하지 않으므로 false.

팔별 설정은 --arms-file (YAML) 에서 ARM_ID 환경변수로 고른다. 포트는 ROBOT_PORT 환경변수 (어댑터가 넘김).
모델은 action 마다 bundle·version (README "모델 번들 규격") 이나 model 경로로 적는다.

  ARM_ID=omx1 ROBOT_PORT=/dev/serial/by-id/... ~/venv/il/bin/python omx_fleet_worker.py --arms-file fleet_arms.yaml
"""

import argparse
import json
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import omx_chain  # noqa: E402

PREFIX = "@fleet "
GRIPPER = "gripper.pos"
DEFAULT_BUNDLES_DIR = "~/il_ws/bundles"
VERSION_RE = re.compile(r"^v\d+$")  # 번들 버전 폴더 이름 (HF 태그와 같게: v1, v2, ...)


def emit(**event):
    """기계용 한 줄. 사람용 로그와 섞여도 PREFIX 로 구분된다."""
    sys.stdout.write(PREFIX + json.dumps(event, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def load_arm_config(path, arm_id):
    """arms-file 에서 arm_id 칸을 읽는다. 틀리면 ValueError."""
    import yaml

    data = yaml.safe_load(Path(path).expanduser().read_text()) or {}
    arm = (data.get("arms") or {}).get(arm_id)
    if not isinstance(arm, dict):
        raise ValueError(f"{path} 에 arms.{arm_id} 가 없음")
    for key in ("top", "wrist", "actions"):
        if not arm.get(key):
            raise ValueError(f"arms.{arm_id}.{key} 가 비어 있음")
    bundles_dir = Path(data.get("bundles_dir") or DEFAULT_BUNDLES_DIR).expanduser()
    actions = {}
    for name, spec in arm["actions"].items():
        where = f"arms.{arm_id}.actions.{name}"
        if not isinstance(spec, dict) or not spec.get("seconds"):
            raise ValueError(f"{where} 에 seconds 필요")
        model = resolve_model(spec, bundles_dir, where)
        actions[name] = {
            "model": model,
            "seconds": float(spec["seconds"]),
            "safe_pose": spec.get("safe_pose"),
            "meta": model_meta(model),
        }
    arm["actions"] = actions
    # 쉬는 자세: 토크를 꺼도(release) 팔이 다치지 않는 자세. 없으면 release 는 늘 거절된다.
    arm["rest_pose"] = str(Path(arm["rest_pose"]).expanduser()) if arm.get("rest_pose") else None
    # 끄기 때 쉬는 자세로 옮긴 뒤 끌지 (녹화기 Servo OFF 방식). 기본 꺼짐: 관제는 팔 모션을
    # 시작하지 않는다는 팀 규칙(ArmCommand.msg)을 기본값에서는 지킨다. 현장 설정으로만 켠다.
    move = arm.get("release_move", False)
    if not isinstance(move, bool):
        raise ValueError(f"arms.{arm_id}.release_move 는 true/false ({move!r})")
    arm["release_move"] = move
    return arm


def resolve_model(spec, bundles_dir, where):
    """action 칸의 모델 폴더 경로. bundle·version 이면 <bundles_dir>/<bundle>/<version>/models/<모델>.

    model 을 안 적으면 models/ 아래 폴더가 하나일 때만 그것을 쓴다 (여럿이면 어느 것인지 모르므로 오류).
    bundle 없이 model 만 적으면 예전처럼 그 경로를 그대로 쓴다.
    """
    if spec.get("bundle") or spec.get("version"):
        bundle, version = str(spec.get("bundle") or ""), str(spec.get("version") or "")
        if not bundle or not version:
            raise ValueError(f"{where}: bundle 과 version 을 함께 적어야 함")
        models = bundles_dir / bundle / version / "models"
        if not models.is_dir():
            raise ValueError(f"{where}: 번들이 없음 ({models}). hf download --revision {version} 로 받으세요")
        if spec.get("model"):
            path = models / str(spec["model"])
        else:
            found = sorted(d for d in models.iterdir() if d.is_dir()) if models.is_dir() else []
            if len(found) != 1:
                names = ", ".join(d.name for d in found) or "없음"
                raise ValueError(f"{where}: {models} 아래 모델 폴더가 하나여야 함 ({names}). model 칸으로 고르세요")
            path = found[0]
        if not path.is_dir():
            raise ValueError(f"{where}: 모델 폴더가 없음 ({path})")
        return str(path)
    if not spec.get("model"):
        raise ValueError(f"{where} 에 bundle·version 또는 model 필요")
    return str(Path(spec["model"]).expanduser())


def model_meta(model_path):
    """관제에 보여 줄 모델 정보. 경로 모양에서 번들 이름·버전을 읽는다 (규격 밖 경로면 None)."""
    path = Path(model_path)
    meta = {"bundle": None, "version": None, "model_name": path.name, "path": str(path),
            "init_pose": False, "success_judge": False}
    if path.parent.name != "models":
        return meta
    bundle_dir = path.parent.parent  # <번들>/models/<모델> 또는 <번들>/<버전>/models/<모델>
    meta["init_pose"] = (bundle_dir / "init_pose.json").is_file()
    meta["success_judge"] = (bundle_dir / "success.json").is_file()
    if VERSION_RE.match(bundle_dir.name):
        meta["bundle"], meta["version"] = bundle_dir.parent.name, bundle_dir.name
    else:
        meta["bundle"] = bundle_dir.name
    return meta


def model_label(meta):
    """작업 결과에 싣는 짧은 모델 이름: omx_pick_za@v1 (버전을 모르면 번들 이름, 그것도 없으면 폴더 이름)."""
    if meta["bundle"] and meta["version"]:
        return f"{meta['bundle']}@{meta['version']}"
    return meta["bundle"] or meta["model_name"]


def plain_pose(pose):
    """{관절.pos: 값} → {관절: 값} (init_pose.json 형식, 관제 표시용)."""
    return {k[:-len(".pos")] if k.endswith(".pos") else k: v for k, v in pose.items()}


def chain_args(arm, port, extra):
    """omx_chain 함수들이 쓰는 args 를 만든다 (omx_chain 기본값 + 팔 설정 + 추가 인자)."""
    argv = ["--port", port, "--top", str(arm["top"]), "--wrist", str(arm["wrist"])]
    if arm.get("mjpg", True):
        argv.append("--mjpg")
    if arm.get("robot_id"):
        argv += ["--robot-id", str(arm["robot_id"])]
    return omx_chain.parse_args(argv + list(extra))


def safe_pose_for(spec):
    """action 의 안전 자세. safe_pose 가 없으면 그 모델 번들의 init_pose.json."""
    if spec["safe_pose"]:
        return omx_chain.read_pose(Path(spec["safe_pose"]).expanduser())
    return omx_chain.find_init_pose(spec["model"])


def read_joints(robot):
    now = robot.bus.sync_read("Present_Position")
    return {f"{k}.pos": round(float(v), 2) for k, v in now.items()}


def retreat(robot, pose, args, label, tol):
    """그리퍼를 뺀 관절만 pose 로 옮기고 실측 오차로 arm_safe 를 정한다."""
    body = {k: v for k, v in pose.items() if k != GRIPPER}
    target = dict(body)
    target[GRIPPER] = read_joints(robot)[GRIPPER]  # 그리퍼는 지금 값 유지 (omx_chain.move_to_pose 는 모든 관절을 받음)
    omx_chain.move_to_pose(robot, target, args, f"{label} 안전 자세")
    joints = read_joints(robot)
    error = body_error(joints, body)
    return all(abs(e) <= tol for e in error.values()), error, joints


def body_error(joints, pose):
    """그리퍼를 뺀 관절의 (지금 - 목표) 오차."""
    return {k: round(joints[k] - v, 2) for k, v in pose.items() if k != GRIPPER}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--arms-file", required=True)
    p.add_argument("--safe-tol", type=float, default=3.0, help="안전 자세 허용 오차 (관절 단위, 1 ≈ 1.8°)")
    mine, extra = p.parse_known_args(argv)
    arm_id, port = os.environ.get("ARM_ID", ""), os.environ.get("ROBOT_PORT", "")
    if not arm_id or not port:
        emit(event="fatal", detail="ARM_ID·ROBOT_PORT 환경변수가 필요함")
        return 2
    try:
        arm = load_arm_config(mine.arms_file, arm_id)
        args = chain_args(arm, port, extra)
    except (OSError, ValueError) as error:
        emit(event="fatal", detail=f"설정 오류: {error}")
        return 2
    if os.environ.get("ACT_ENSEMBLE_K"):
        import act_ensemble  # noqa: F401

    from lerobot.datasets.utils import hw_to_dataset_features

    stages, safe_poses = {}, {}
    try:  # 로봇에 연결하기 전 준비. 여기서 실패하면 팔은 건드리지 않았다.
        robot = omx_chain.make_robot(args)
        features = {
            **hw_to_dataset_features(robot.action_features, "action", True),
            **hw_to_dataset_features(robot.observation_features, "observation", True),
        }
        print(f"[{arm_id}] 모델 {len(arm['actions'])}개를 불러오는 중… (로봇 연결 전)", flush=True)
        for name, spec in arm["actions"].items():
            stages[name] = omx_chain.load_stage(spec["model"], spec["seconds"], args)
            omx_chain.check_inputs(stages[name], features)
            safe_poses[name] = safe_pose_for(spec)
            if not safe_poses[name]:
                raise ValueError(f"{name}: safe_pose 도 init_pose.json 도 없음")
        rest_pose = omx_chain.read_pose(arm["rest_pose"]) if arm["rest_pose"] else None
    except (Exception, SystemExit) as error:  # noqa: BLE001 — omx_chain 은 SystemExit 로 알린다
        emit(event="fatal", detail=f"준비 실패: {error}")
        return 2

    commands = queue.Queue()
    stop_evt = threading.Event()

    def read_stdin():
        for line in sys.stdin:
            try:
                msg = json.loads(line)
            except ValueError:
                print(f"[stdin] JSON 아님, 무시: {line.strip()[:80]}", flush=True)
                continue
            if msg.get("cmd") == "hold":
                # 실행 중인 단계를 바로 끊는다 (run_stage 가 매 스텝 확인). 지우는 건 메인 루프가
                # 이 hold 를 꺼냈을 때다. 그래야 앞서 줄 선 run 도 움직이지 않고 끝난다.
                stop_evt.set()
            commands.put(msg)
        commands.put({"cmd": "quit"})  # 어댑터가 사라지면 끝낸다

    threading.Thread(target=read_stdin, daemon=True).start()

    robot.connect()
    try:
        emit(event="ready", actions=sorted(stages), joints=read_joints(robot),
             models={name: spec["meta"] for name, spec in arm["actions"].items()},
             rest_pose=plain_pose(rest_pose) if rest_pose else None, safe_tol=mine.safe_tol)
        print(f"[{arm_id}] 준비 완료 — 토크 유지, 일을 기다림", flush=True)
        while True:
            msg = commands.get()
            cmd = msg.get("cmd")
            if cmd == "quit":
                break
            if cmd == "hold":
                stop_evt.clear()  # 이 hold 앞의 run 은 모두 멈춘 채 끝났다
                continue
            if cmd == "state":
                emit(event="state", joints=read_joints(robot))
                continue
            if cmd == "release":
                # 관제는 팔 모션을 시작하지 않는다. 그래서 옮기지 않고 지금 자세만 보고 판정한다.
                joints = read_joints(robot)
                if rest_pose is None:
                    emit(event="release_refused", detail=f"rest_pose 가 설정되지 않음 (arms.{arm_id}.rest_pose)",
                         pose_error={}, joints=joints)
                    continue
                error = body_error(joints, rest_pose)
                if all(abs(e) <= mine.safe_tol for e in error.values()):
                    emit(event="released", pose_error=error)
                    break
                worst = max(abs(e) for e in error.values())
                if not arm["release_move"]:
                    emit(event="release_refused", pose_error=error, joints=joints,
                         detail=f"쉬는 자세가 아님 (최대 오차 {worst:.1f} > {mine.safe_tol}): 현장에서 팔을 내려 주세요")
                    continue
                # release_move: 쉬는 자세로 옮긴 뒤 다시 잰다. 그리퍼는 그대로 (잡은 물건을 놓지 않게).
                # move_to_pose 는 멈춤 신호를 받지 않는다: 이동 중 hold 는 이동이 끝난 뒤에 처리된다.
                seconds = max(args.init_min_s, worst / args.init_speed) + 0.5  # +0.5: 도착 뒤 대기
                emit(event="release_moving", seconds=round(seconds, 1), pose_error=error, joints=joints)
                at_rest, error, joints = retreat(robot, rest_pose, args, "끄기 전 쉬는", mine.safe_tol)
                if at_rest:
                    emit(event="released", pose_error=error)
                    break
                worst = max(abs(e) for e in error.values())
                emit(event="release_refused", pose_error=error, joints=joints,
                     detail=f"쉬는 자세로 옮겼지만 도착 못 함 (최대 오차 {worst:.1f} > {mine.safe_tol}): "
                            "막힌 곳을 확인하세요. 토크 유지")
                continue
            if cmd != "run":
                continue
            job_id, action = msg.get("id"), msg.get("action")
            if action not in stages:
                emit(event="rejected", id=job_id, detail=f"{action} 모델이 설정되지 않음 (arms.{arm_id}.actions)")
                continue
            stage = stages[action]
            model = model_label(arm["actions"][action]["meta"])
            emit(event="started", id=job_id)
            if stage["init_pose"] and not stop_evt.is_set():
                omx_chain.move_to_pose(robot, stage["init_pose"], args, stage["name"])
            reason = "hold"
            if not stop_evt.is_set():
                reason = omx_chain.run_stage(robot, stage, features, args, stop_evt, ramp=True)
                reason = "hold" if reason == "next" else reason
            if reason == "hold":
                # 멈춤: 더 움직이지 않는다. 토크는 유지돼 서보가 마지막 목표를 붙잡는다.
                emit(event="done", id=job_id, success=False, end_reason="hold", arm_safe=False,
                     success_basis="judge" if stage.get("judge") else "none", pose_error={}, joints=read_joints(robot),
                     model=model)
                continue
            arm_safe, error, joints = retreat(robot, safe_poses[action], args, stage["name"], mine.safe_tol)
            emit(event="done", id=job_id, success=reason == "success", end_reason=reason, arm_safe=arm_safe,
                 success_basis="judge" if stage.get("judge") else "none", pose_error=error, joints=joints,
                 model=model)
    except Exception as error:  # noqa: BLE001 — 무슨 오류든 어댑터에 알리고 끝낸다
        emit(event="fatal", detail=f"{type(error).__name__}: {error}")
        raise
    finally:
        print(f"[{arm_id}] 연결 끊음 — 토크가 꺼지므로 팔이 내려앉을 수 있음", flush=True)
        if robot.is_connected:
            robot.disconnect()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
