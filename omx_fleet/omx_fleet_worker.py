#!/usr/bin/env python3
"""관제(cobot_manipulation arm_adapter, backend=worker)용 팔 실행기 (lerobot 0.4.4).

omx_chain.py 의 함수(로봇 만들기·모델 불러오기·초기 자세 이동·단계 실행)를 그대로 쓰고,
사람 대신 어댑터가 stdin/stdout 으로 일을 시킨다. 같은 폴더의 omx_chain.py·success_judge.py 는
대시보드 v2 (2026-11-17 팔 멈춤 판단 반영본) 에서 고치지 않고 복사한 것이다 (README "파일").

왜 따로 두나: 작업마다 lerobot-record 를 새로 켜면 끝날 때·시작할 때 토크가 꺼져 팔이 떨어진다.
이 실행기는 켜질 때 한 번 연결하고 모든 모델을 미리 올린 뒤, 작업이 끝나도 토크를 유지한 채 다음 일을 기다린다.

대화 방식 (한 줄 = JSON 하나)
  stdin  {"cmd": "run", "id": "<request_id>", "action": "pick", "box": 3}
                           box: 박스 원핫을 받는 모델(omx_info.json box.mode=state)만 필요 (1..N). 다른 작업은 무시
         {"cmd": "hold"}   지금 단계를 멈추고 토크 유지 (안전 자세 이동도 하지 않음)
         {"cmd": "state"}  대기 중 관절 값 보고 (작업 중이면 작업이 끝난 뒤 답함)
         {"cmd": "release"} 쉬는 자세(rest_pose)에 있을 때만 연결을 끊고 끝냄. 아니면 거절 (팔을 옮기지 않음).
                            팔 설정 release_move: true 면 거절 대신 쉬는 자세로 옮긴 뒤 다시 재서 끈다
                            --release-without-rest 로 띄우면 rest_pose 가 없는 팔은 거절 대신 바로 끈다
                            (토크가 꺼지므로 팔이 내려앉을 수 있음. 현장에서 팔을 받친 뒤 누른다)
         {"cmd": "quit"}   무조건 연결을 끊고 끝냄 (토크가 꺼지므로 팔이 내려앉을 수 있음)
  stdout 기계용 줄은 "@fleet " 로 시작한다. 나머지 줄은 사람이 읽는 로그.
         @fleet {"event": "ready", "actions": [...], "joints": {...}, "models": {action: {...}},
                 "rest_pose": {관절: 값} | null, "safe_tol": N, "robot_type": "..."}
                 models 칸은 model_meta() 참고 (+ box_required, success_motion, noop)
         @fleet {"event": "state", "joints": {...}}
         @fleet {"event": "release_moving", "seconds": N, ...}       release_move: 쉬는 자세로 이동 시작 (약 N 초)
         @fleet {"event": "released", "pose_error": {...}}             이어서 연결을 끊고 끝냄
         @fleet {"event": "release_refused", "detail": "...", "pose_error": {...}, "joints": {...}}
         @fleet {"event": "started", "id": ...}
         @fleet {"event": "done", "id": ..., "success": bool, "success_basis": "judge"|"none",
                 "arm_safe": bool, "end_reason": "success"|"timeout"|"hold", "pose_error": {...}, "joints": {...},
                 "model": "<bundle>@<version>", "box": N | null,
                 "stages": [{"name", "end_reason", "judge", "seconds"}, ...]}   stages 는 단계가 여럿일 때만
         @fleet {"event": "progress", "id": ..., "stage": 1, "stages": 2, "label": "신발 정리",
                 "state": "running"|"success"|"timeout"|"hold", "text": "신발 정리 성공 (YOLO) → 신발 상차 진행",
                 "seconds": N (끝났을 때만)}                          단계가 여럿일 때만, 단계 시작·끝마다
         @fleet {"event": "rejected", "id": ..., "detail": "..."}   팔을 움직이지 않은 거절
         @fleet {"event": "fatal", "detail": "..."}                 이후 일을 하지 않고 끝냄

판단 규칙
  - success: 성공 판단이 성공을 낸 경우만 true. 판단기가 없으면 항상 false (success_basis=none).
    판단기: success.json 의 YOLO (success_basis=judge) 또는 단계 설정 success_motion (success_basis=motion,
    그리퍼 전류로 잡음 → 돌아간 곳에서 놓음 → 처음 회전값으로 돌아옴. fleet_runtime.py). 둘 다 쓰면 judge+motion.
    박스 번호·동작 판단·depth 를 쓰는 단계는 fleet_runtime.run_job 으로 돌고, 거기서는 YOLO 판단을 하지 않는다.
  - 이어서 실행 (action 의 stages): 단계마다 init_pose 이동 → 정책 실행, 사이에 --min-hold-s 멈춤.
    판단기가 있는 단계가 성공을 못 내면 다음 단계로 가지 않는다. success 는 모든 단계를 끝까지 가고
    판단기가 있는 단계가 모두 성공일 때만 true. 안전 자세 기본값은 마지막 단계 번들의 init_pose.json.
  - noop 작업: 팔을 움직이지 않고 바로 success=true (success_basis=noop). arm_safe 는 지금 자세를 그 작업
    safe_pose (없으면 다른 작업의 안전 자세) 와 비교해 정한다.
  - arm_safe: 단계가 끝난 뒤 그 action 의 safe_pose 로 이동하고 (그리퍼는 그대로 둠 — 잡은 물건을 놓지 않게)
    관절을 다시 읽어 그리퍼 외 모든 관절 오차가 safe_tol 이하일 때만 true. hold 로 끝나면 이동하지 않으므로 false.

팔별 설정은 --arms-file (YAML) 에서 ARM_ID 환경변수로 고른다. 포트는 ROBOT_PORT 환경변수 (어댑터가 넘김).
모델은 action 마다 bundle·version (README "모델 지정과 번들") 이나 model 경로로 적는다.

  ARM_ID=omx1 ROBOT_PORT=/dev/serial/by-id/... ~/venv/il/bin/python omx_fleet_worker.py --arms-file fleet_arms.yaml
  ARM_ID=omx1 ~/venv/il/bin/python omx_fleet_worker.py --arms-file fleet_arms.yaml --check   # 연결 없이 준비만 확인
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
import cam_preview  # noqa: E402
import fleet_runtime  # noqa: E402
import omx_chain  # noqa: E402
import usb_cams  # noqa: E402

PREFIX = "@fleet "
CAMERA_ROLES = ("top", "wrist")
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
    if not arm.get("actions"):
        raise ValueError(f"arms.{arm_id}.actions 가 비어 있음")
    # 카메라: 경로(top) 또는 모델 ID(top_model, 보드 허브에서 찾음) 중 하나만 적는다
    for role in CAMERA_ROLES:
        path, model = arm.get(role), arm.get(f"{role}_model")
        if bool(path) == bool(model):
            raise ValueError(f"arms.{arm_id}: {role} 와 {role}_model 중 하나만 적는다")
        if model and not usb_cams.MODEL_PATTERN.match(str(model)):
            raise ValueError(f"arms.{arm_id}.{role}_model 은 'vid:pid' 16진수 ({model!r})")
    bundles_dir = Path(data.get("bundles_dir") or DEFAULT_BUNDLES_DIR).expanduser()
    actions = {}
    for name, spec in arm["actions"].items():
        where = f"arms.{arm_id}.actions.{name}"
        if isinstance(spec, dict) and spec.get("noop") is True:
            # 팔을 움직이지 않는 작업 (예: 앞 작업 모델이 싣기까지 하는 경우의 load)
            actions[name] = {"noop": True, "safe_pose": spec.get("safe_pose"),
                             "meta": {"noop": True, "model_name": "noop", "bundle": None, "version": None}}
            continue
        if not isinstance(spec, dict):
            raise ValueError(f"{where} 형식이 틀림")
        # stages: 명령 하나로 모델 여러 개를 이어서 실행 (대시보드 v2 연속 실행과 같은 순서).
        # 없으면 예전처럼 단계 하나 (action 칸 자체가 그 단계).
        raw = spec.get("stages")
        if raw is None:
            raw = [spec]
        elif not isinstance(raw, list) or not raw:
            raise ValueError(f"{where}.stages 는 단계 목록이어야 함")
        parts = []
        for i, st in enumerate(raw):
            w = f"{where}.stages[{i}]" if spec.get("stages") else where
            if not isinstance(st, dict) or not st.get("seconds"):
                raise ValueError(f"{w} 에 seconds 필요 (팔을 안 움직이는 작업이면 noop: true)")
            model = resolve_model(st, bundles_dir, w)
            judge = st.get("judge")
            if judge is not None and judge is not False and not isinstance(judge, dict):
                raise ValueError(f"{w}.judge 는 false 또는 success.json 키를 덮어쓸 칸 ({judge!r})")
            try:
                motion = fleet_runtime.motion_config(st.get("success_motion"))
            except ValueError as error:
                raise ValueError(f"{w}: {error}") from None
            if motion and (arm.get("robot_type") or "omx_follower") == "omx_follower":
                raise ValueError(f"{w}: success_motion 은 그리퍼 전류가 있는 robot_type 에서만 쓸 수 있음")
            meta = model_meta(model)
            n_box = fleet_runtime.box_count(model)
            meta.update(box_required=n_box > 0, success_motion=bool(motion))
            # label: 관제 화면에 보일 단계 이름 (예: 신발 정리). 없으면 모델 폴더 이름
            parts.append({"model": model, "seconds": float(st["seconds"]), "meta": meta,
                          "label": str(st.get("label") or Path(model).name), "judge": judge,
                          "motion": motion, "n_box": n_box})
        meta = dict(parts[0]["meta"])  # 관제 표시용 모양은 예전과 같게 (첫 단계 기준) + 단계 목록
        if len(parts) > 1:
            meta["success_judge"] = any(p["meta"]["success_judge"] for p in parts)
            meta["box_required"] = any(p["n_box"] for p in parts)
            meta["success_motion"] = any(p["motion"] for p in parts)
            meta["stages"] = [p["meta"] for p in parts]
        actions[name] = {
            "stages": parts,
            "model": parts[-1]["model"],  # 안전 자세 기본값은 마지막 단계 번들의 init_pose.json
            "safe_pose": spec.get("safe_pose"),
            "meta": meta,
        }
    if all(spec.get("noop") for spec in actions.values()):
        raise ValueError(f"arms.{arm_id}.actions 에 모델 작업이 하나도 없음")
    arm["actions"] = actions
    # 쉬는 자세: 토크를 꺼도(release) 팔이 다치지 않는 자세. 없으면 release 는 늘 거절된다.
    arm["rest_pose"] = str(Path(arm["rest_pose"]).expanduser()) if arm.get("rest_pose") else None
    # 끄기 때 쉬는 자세로 옮긴 뒤 끌지 (녹화기 Servo OFF 방식). 기본 꺼짐: 관제는 팔 모션을
    # 시작하지 않는다는 팀 규칙(ArmCommand.msg)을 기본값에서는 지킨다. 현장 설정으로만 켠다.
    move = arm.get("release_move", False)
    if not isinstance(move, bool):
        raise ValueError(f"arms.{arm_id}.release_move 는 true/false ({move!r})")
    arm["release_move"] = move
    # 켤 때 자세: 연결 직후 이 자세로 천천히 옮긴 뒤 ready (그리퍼는 파일에 값이 있을 때만). 없으면 지금 자세 유지 (기본).
    # 경로(init_pose.json 모양) 또는 action 이름(그 action 첫 단계 번들의 init_pose.json).
    start = arm.get("start_pose")
    if start and str(start) in actions:
        if actions[str(start)].get("noop"):
            raise ValueError(f"arms.{arm_id}.start_pose: {start} 는 noop 작업이라 시작 자세가 없음")
        first = actions[str(start)]["stages"][0]["model"]
        start = Path(first).resolve().parent.parent / "init_pose.json"
        if not start.is_file():
            raise ValueError(f"arms.{arm_id}.start_pose: {arm.get('start_pose')} 의 init_pose.json 이 없음 ({start})")
    arm["start_pose"] = str(Path(str(start)).expanduser()) if start else None
    arm["preview"] = preview_config(arm.get("preview"), arm_id)
    return arm


def preview_config(value, arm_id):
    """
    팔 설정 preview 칸 → {port, bind} 또는 None (칸이 없으면 미리보기를 켜지 않음).

    관제 팔 상세화면이 카메라 영상을 보려면 켠다 (cam_preview.py). 팔 동작과는 상관없다.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"arms.{arm_id}.preview 는 {{port, bind}} ({value!r})")
    port = value.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"arms.{arm_id}.preview.port 는 1~65535 ({port!r})")
    bind = value.get("bind", "127.0.0.1")
    if not isinstance(bind, str) or not bind:
        raise ValueError(f"arms.{arm_id}.preview.bind 는 주소 문자열 ({bind!r})")
    return {"port": port, "bind": bind}


def start_preview(robot, arm_id, preview):
    """카메라 미리보기 서버를 켠다. 포트를 못 열어도 팔 일은 계속한다 (로그만)."""
    if not preview:
        return None
    try:
        server = cam_preview.PreviewServer(cam_preview.lerobot_frame_getter(robot), preview["port"],
                                           preview["bind"], roles=CAMERA_ROLES).start()
    except OSError as error:
        print(f"[{arm_id}] 카메라 미리보기 못 켬 ({preview['bind']}:{preview['port']}): {error}", flush=True)
        return None
    print(f"[{arm_id}] 카메라 미리보기 http://{preview['bind']}:{preview['port']}/top · /wrist", flush=True)
    return server


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
    """작업 결과에 싣는 짧은 모델 이름: omx_pick_za@v1 (버전을 모르면 번들 이름, 그것도 없으면 폴더 이름).
    단계가 여러 개면 + 로 잇는다: omx_arrange_shoe_zc@v1+omx_load_zc@v1"""
    if meta.get("stages"):
        return "+".join(model_label(m) for m in meta["stages"])
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


JOINT_ORDER = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def judge_override(model_path, override, args, where):
    """번들 success.json 에 팔별 값(fleet_arms.yaml 의 judge 칸)을 덮어쓴 성공 판단기. model 이 비면 None.

    success_judge.py 는 대시보드와 같은 파일을 쓰므로 고치지 않고, 여기서 설정만 바꿔 넣는다.
    rest_pose 는 숫자 목록 대신 init_pose.json 모양 파일 경로도 된다 (arm_console.py saverest 결과).
    model 을 상대 경로로 적으면 번들 폴더 기준.
    """
    from success_judge import DEFAULTS, Detector, SuccessJudge, load_config

    bundle = Path(model_path).resolve().parent.parent
    unknown = sorted(set(override) - set(DEFAULTS))
    if unknown:
        raise ValueError(f"{where}.judge: 모르는 키 {unknown} (가능: {sorted(DEFAULTS)})")
    base = load_config(bundle)
    if base is None:  # 번들에 success.json 이 없으면 신발 상자 기본값(inside_box 등)을 물려받지 않게 비운다
        base = {**DEFAULTS, "arm_class": "", "target": "", "forbid": {},
                "file": f"{where}.judge (번들에 success.json 없음)"}
    cfg = {**base, **override}
    cfg["forbid"] = {str(k): float(v) for k, v in (cfg.get("forbid") or {}).items()}
    if "model" in override and cfg["model"]:
        m = Path(str(cfg["model"])).expanduser()
        cfg["model"] = str(m if m.is_absolute() else (bundle / m).resolve())
    if isinstance(cfg.get("rest_pose"), str):
        pose = json.loads(Path(cfg["rest_pose"]).expanduser().read_text())["pose"]
        cfg["rest_pose"] = [float(pose[k]) for k in JOINT_ORDER]
    if not cfg["model"]:
        return None
    if not cfg["target"]:
        raise ValueError(f"{where}.judge: target(성공으로 볼 클래스) 이 비어 있음")
    try:
        det = Detector(cfg, args.device)
    except RuntimeError as error:
        raise ValueError(f"{where}.judge: {error}") from error
    print(f"[성공 판단] {Path(model_path).name}: 팔별 설정 덮어씀 {sorted(override)} ({cfg['model']})", flush=True)
    return SuccessJudge(cfg, det, log=lambda line: print(line, flush=True))


def load_part(part, args, where):
    """단계 하나 불러오기. judge 칸이 없으면 번들 success.json 그대로 (예전과 같음)."""
    override = part.get("judge")
    if override is None:
        return omx_chain.load_stage(part["model"], part["seconds"], args)
    plain = argparse.Namespace(**{**vars(args), "no_success": True})  # 번들 판단기는 만들지 않음
    stage = omx_chain.load_stage(part["model"], part["seconds"], plain)
    if override is not False and not args.no_success:
        stage["judge"] = judge_override(part["model"], override, args, where)
    return stage


def judge_line(stage):
    """사람용 한 줄: 이 단계가 무엇으로 끝나는지."""
    judge = stage.get("judge")
    if not judge:
        return "시간 기준 (성공 판단 없음)"
    import success_judge

    return f"YOLO {Path(judge.cfg['model']).name} — {success_judge.describe(judge.cfg)}"


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


def needs_run_job(robot, part):
    """이 단계를 fleet_runtime.run_job 으로 돌려야 하나 (박스 원핫·동작 판단·depth). 아니면 omx_chain.run_stage."""
    return bool(part["n_box"] or part["motion"] or hasattr(robot, "refresh_depth"))


def progress_text(labels, i, reason, judged, how="YOLO"):
    """단계 i 가 끝났을 때 관제에 보일 한 줄. 예: '신발 정리 성공 (YOLO) → 신발 상차 진행'."""
    word = {"success": "성공", "timeout": "시간 초과", "hold": "멈춤"}.get(reason, reason)
    if reason == "timeout" and not judged:
        word = "완료"  # 판단기가 없는 단계는 정해진 시간을 다 도는 게 정상
    head = f"{labels[i]} {word}" + (f" ({how})" if judged and reason == "success" else "")
    if reason == "hold":
        return head
    if i + 1 < len(labels):
        if judged and reason != "success":
            return f"{head} → {labels[i + 1]} 안 함"
        return f"{head} → {labels[i + 1]} 진행"
    return f"{head} → 안전 자세로 이동"


def run_chain(robot, chain, features, args, stop_evt, multi, job_id=None, labels=None, runners=None):
    """단계들을 이어서 실행 (대시보드 v2 omx_chain.run_stages 와 같은 순서).

    단계마다: init_pose.json 으로 천천히 이동 → 정책 실행. 단계 사이에는 args.min_hold_s 만큼 토크를 유지한 채
    멈췄다가 다음 단계로 넘어간다 (대시보드 자동 넘김). 판단기가 있는 단계가 시간 안에 성공을 못 내면
    다음 단계로 넘어가지 않고 끝낸다 (대시보드에서는 여기서 버튼을 기다렸다).
    단계가 여럿이면 단계 시작·끝마다 @fleet {"event": "progress", ...} 를 낸다 (관제 화면 진행 표시용).
    runners[i]: None 이면 omx_chain.run_stage (YOLO 판단), {"one_hot", "motion"} 이면 fleet_runtime.run_job
    (박스 원핫·동작 판단·depth. 이때 YOLO 판단은 쓰지 않음).
    반환: (마지막 끝난 이유 'success'|'timeout'|'hold', 단계별 결과 목록)
    """
    labels = labels or [st["name"] for st in chain]
    runners = runners or [None] * len(chain)
    results = []
    reason = "hold"

    def progress(i, state, text, **extra):
        if multi:
            emit(event="progress", id=job_id, stage=i + 1, stages=len(chain), label=labels[i],
                 state=state, text=text, **extra)

    for i, st in enumerate(chain):
        if stop_evt.is_set():
            reason = "hold"
            break
        if i:
            print(f"[단계 사이] {args.min_hold_s:.1f}s 멈춤 (토크 유지) 뒤 {st['name']}", flush=True)
            time.sleep(args.min_hold_s)
            if stop_evt.is_set():
                reason = "hold"
                break
        if st["init_pose"]:
            omx_chain.move_to_pose(robot, st["init_pose"], args, st["name"])
        if stop_evt.is_set():
            reason = "hold"
            break
        if multi:
            print(f"[단계 {i + 1}/{len(chain)}] {st['name']} 시작 (최대 {st['seconds']:.0f}s)", flush=True)
        progress(i, "running", f"{labels[i]} 진행 중 ({i + 1}/{len(chain)})")
        t0 = time.perf_counter()
        runner = runners[i]
        if runner:
            # run_job 은 ramp 인자가 없고 늘 처음 ramp_s 동안 완화한다
            judged, how = bool(runner["motion"]), "동작 판단"
            reason = fleet_runtime.run_job(robot, st, features, args, stop_evt,
                                           one_hot=runner["one_hot"], motion=runner["motion"])
        else:
            judged, how = bool(st.get("judge")), "YOLO"
            # 단계가 여럿이면 대시보드처럼 2단계부터만 전환 완화(ramp). 단계 하나는 예전처럼 늘 완화.
            reason = omx_chain.run_stage(robot, st, features, args, stop_evt, ramp=(i > 0) if multi else True,
                                         index=i + 1)
        reason = "hold" if reason == "next" else reason
        results.append({"name": st["name"], "label": labels[i], "end_reason": reason, "judge": judged,
                        "seconds": round(time.perf_counter() - t0, 1)})
        progress(i, reason, progress_text(labels, i, reason, judged, how),
                 seconds=results[-1]["seconds"])
        if reason == "hold":
            break
        if judged and reason != "success" and i < len(chain) - 1:
            print(f"[단계 {i + 1}] 성공 판단이 안 나옴 — 다음 단계({chain[i + 1]['name']})로 넘어가지 않고 끝냄",
                  flush=True)
            break
    return reason, results


def print_check(arm_id, arm, stages, safe_poses, rest_pose, tol):
    """--check 결과 요약 (사람용). 여기까지 왔으면 켜기 전 준비는 모두 통과한 것."""
    out = ["", f"[확인] {arm_id} — 켜기 전 준비 통과 (로봇에는 연결하지 않았음)"]
    out.append(f"  카메라 top={arm['top']} wrist={arm['wrist']} · 캘리브레이션 {arm.get('robot_id') or 'omx_follower'}")
    for name, chain in stages.items():
        spec = arm["actions"][name]
        if spec.get("noop"):
            out.append(f"  ▸ {name}  (noop: 팔을 움직이지 않고 바로 성공)")
            continue
        out.append(f"  ▸ {name}  ({model_label(spec['meta'])})")
        for i, (st, part) in enumerate(zip(chain, spec["stages"]), 1):
            pose = "있음" if st["init_pose"] else "없음 (이동 없이 시작)"
            out.append(f"     {i}. {part['label']}: {st['name']} 최대 {st['seconds']:.0f}s · 시작 자세 {pose}"
                       + (f" · 박스 원핫 {part['n_box']}" if part["n_box"] else ""))
            end = "동작 판단 (success_motion)" if part["motion"] else judge_line(st)
            out.append(f"        끝: {end}")
        if len(chain) > 1:
            out.append("     → 판단 있는 단계가 성공해야 다음 단계로 감")
        where = spec["safe_pose"] or "마지막 단계 번들 init_pose.json"
        note = ""
        if rest_pose:
            worst = max(abs(safe_poses[name][k] - v) for k, v in rest_pose.items() if k != GRIPPER)
            note = " = 쉬는 자세 (끝나면 관제 '끄기' 됨)" if worst <= tol else (
                f" ≠ 쉬는 자세 (최대 차이 {worst:.1f} > {tol:g}: 끝난 뒤 관제 '끄기'가 거절됨)")
        out.append(f"     끝난 뒤 안전 자세: {where}{note}")
    out.append(f"  쉬는 자세(rest_pose): {arm['rest_pose'] or '없음 — 관제 끄기가 늘 거절됨'}"
               + (" · 끄기 때 쉬는 자세로 옮긴 뒤 끔" if arm["release_move"] else ""))
    out.append(f"  켤 때 자세(start_pose): {arm['start_pose'] or '없음 (지금 자세 유지)'}")
    print("\n".join(out), flush=True)
    emit(event="checked", actions=sorted(stages),
         models={name: spec["meta"] for name, spec in arm["actions"].items()})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--arms-file", required=True)
    p.add_argument("--safe-tol", type=float, default=3.0, help="안전 자세 허용 오차 (관절 단위, 1 ≈ 1.8°)")
    p.add_argument("--check", action="store_true",
                   help="로봇에 연결하지 않고 설정·번들·모델·YOLO 판단기만 확인한 뒤 끝냄 (팔이 움직이지 않음, 사람용 요약)")
    p.add_argument("--dry-check", action="store_true",
                   help="설정·모델·입력 모양만 확인하고 JSON 한 줄로 끝냄 (팔·카메라에 연결하지 않음)")
    # 쉬는 자세를 아직 재지 못한 팔도 관제 끄기로 토크를 풀 수 있게 한다. 없으면 끄기가 늘 거절돼
    # 노드를 강제로 끄게 되고, 그러면 토크가 켜진 채 남는다 (2026-11-21 omx2).
    p.add_argument("--release-without-rest", action="store_true",
                   help="rest_pose 가 없는 팔은 끄기(release)를 거절하지 않고 바로 연결을 끊음 (팔이 내려앉을 수 있음)")
    mine, extra = p.parse_known_args(argv)
    arm_id, port = os.environ.get("ARM_ID", ""), os.environ.get("ROBOT_PORT", "")
    if (mine.check or mine.dry_check) and not port:
        port = "/dev/null"  # 확인 모드는 연결하지 않으므로 포트가 없어도 됨
    if not arm_id or not port:
        emit(event="fatal", detail="ARM_ID·ROBOT_PORT 환경변수가 필요함")
        return 2
    try:
        arm = load_arm_config(mine.arms_file, arm_id)
    except (OSError, ValueError) as error:
        emit(event="fatal", detail=f"설정 오류: {error}")
        return 2
    wants = {role: arm[f"{role}_model"] for role in CAMERA_ROLES if arm.get(f"{role}_model")}
    try:  # 팔에 연결하기 전. 실패해도 팔은 건드리지 않았다
        arm.update(usb_cams.find_cameras(port, wants) if wants else {})
    except usb_cams.CameraError as error:
        emit(event="fatal", detail=f"카메라 찾기 실패: {error}")
        return 2
    for role in CAMERA_ROLES:
        print(f"[{arm_id}] {role} = {arm[role]}" + (f" ({wants[role]})" if role in wants else ""), flush=True)
    try:
        args = chain_args(arm, port, extra)
    except (OSError, ValueError) as error:
        emit(event="fatal", detail=f"설정 오류: {error}")
        return 2
    if os.environ.get("ACT_ENSEMBLE_K"):
        import act_ensemble  # noqa: F401

    from lerobot.datasets.utils import hw_to_dataset_features

    stages, safe_poses = {}, {}
    try:  # 로봇에 연결하기 전 준비. 여기서 실패하면 팔은 건드리지 않았다.
        # depth_info.json 은 모든 단계 모델에서 찾는다 (find_depth_info 는 칸마다 model 하나를 본다)
        every = {f"{name}[{i}]": {"model": p["model"]} for name, spec in arm["actions"].items()
                 for i, p in enumerate(spec.get("stages") or [])}
        robot = fleet_runtime.make_robot(arm, args, fleet_runtime.find_depth_info(every))
        robot_type = arm.get("robot_type") or "omx_follower"  # robot.robot_type 은 캘리브레이션 이름이라 늘 omx_follower
        features = {
            **hw_to_dataset_features(robot.action_features, "action", True),
            **hw_to_dataset_features(robot.observation_features, "observation", True),
        }
        loaded = {}  # (모델, 초, 판단 설정) → 단계. 같은 것을 여러 action 이 쓰면 한 번만 올린다

        def key_of(p):
            return p["model"], p["seconds"], json.dumps(p.get("judge"), sort_keys=True, ensure_ascii=False)

        models = {name: spec for name, spec in arm["actions"].items() if not spec.get("noop")}
        wanted = {key_of(p) for spec in models.values() for p in spec["stages"]}
        print(f"[{arm_id}] 모델 {len(wanted)}개를 불러오는 중… (로봇 연결 전, {robot_type})", flush=True)
        for name, spec in models.items():
            stages[name] = []
            for i, p in enumerate(spec["stages"]):
                key = key_of(p)
                if key not in loaded:
                    loaded[key] = load_part(p, args, f"arms.{arm_id}.actions.{name}.stages[{i}]")
                    omx_chain.check_inputs(loaded[key], features)
                fleet_runtime.check_state_size(loaded[key], features, p["n_box"])
                if loaded[key].get("judge") and needs_run_job(robot, p):
                    print(f"[{arm_id}] 주의: {name} {i + 1}단계는 박스·동작 판단·depth 로 돌아 YOLO 판단을 쓰지 않음",
                          flush=True)
                stages[name].append(loaded[key])
            # 관제 표시의 '성공 판단 있음' 은 실제로 쓰는 판단기 기준 (팔별 judge 칸 반영)
            has = [bool(st.get("judge")) and not needs_run_job(robot, p) for st, p in zip(stages[name], spec["stages"])]
            spec["meta"]["success_judge"] = any(has)
            for m, h in zip(spec["meta"].get("stages") or [], has):
                m["success_judge"] = h
            safe_poses[name] = safe_pose_for(spec)
            if not safe_poses[name]:
                raise ValueError(f"{name}: safe_pose 도 init_pose.json 도 없음")
        for name, spec in arm["actions"].items():
            if spec.get("noop"):
                stages[name] = {"noop": True, "name": name}
                safe_poses[name] = (omx_chain.read_pose(Path(spec["safe_pose"]).expanduser())
                                    if spec["safe_pose"] else next(iter(safe_poses.values())))
        rest_pose = omx_chain.read_pose(arm["rest_pose"]) if arm["rest_pose"] else None
        start_pose = omx_chain.read_pose(arm["start_pose"]) if arm["start_pose"] else None
    except (Exception, SystemExit) as error:  # noqa: BLE001 — omx_chain 은 SystemExit 로 알린다
        emit(event="fatal", detail=f"준비 실패: {error}")
        return 2

    if mine.dry_check:
        summary = {name: {"noop": True} if spec.get("noop") else {
            "model": model_label(spec["meta"]), "box": max(p["n_box"] for p in spec["stages"]),
            "success_motion": any(p["motion"] for p in spec["stages"]), "stages": len(spec["stages"]),
            "init_pose": stages[name][0]["init_pose"] is not None} for name, spec in arm["actions"].items()}
        print(json.dumps({"dry_check": "ok", "robot_type": robot_type,
                          "cameras": {role: arm[role] for role in CAMERA_ROLES}, "preview": arm["preview"],
                          "state": features["observation.state"]["shape"][0],
                          "inputs": sorted(k for k in features if k.startswith("observation.")),
                          "actions": summary, "start_pose": start_pose is not None}, ensure_ascii=False), flush=True)
        return 0
    if mine.check:
        print_check(arm_id, arm, stages, safe_poses, rest_pose, mine.safe_tol)
        return 0

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
    preview = None
    try:
        preview = start_preview(robot, arm_id, arm["preview"])
        fleet_runtime.warm_depth(robot)
        if start_pose:
            # 켤 때 학습 데이터 첫 자세로 옮겨 둔다. 그리퍼는 자세 파일에 값이 있을 때만 옮기고,
            # 없으면 지금 값 그대로 둔다. 이 이동 중 온 hold 는 이동이 끝난 뒤 처리된다.
            target = dict(start_pose)
            if GRIPPER not in target:
                target[GRIPPER] = read_joints(robot)[GRIPPER]
            print(f"[{arm_id}] 켤 때 그리퍼 {'옮김' if GRIPPER in start_pose else '그대로 (자세 파일에 gripper 없음)'}",
                  flush=True)
            omx_chain.move_to_pose(robot, target, args, "켜기 시작 자세")
            error = body_error(read_joints(robot), start_pose)
            ok = all(abs(e) <= mine.safe_tol for e in error.values())
            print(f"[{arm_id}] 켤 때 시작 자세 {'도착' if ok else '도착 못 함'} ({arm['start_pose']}) 오차 {error}", flush=True)
        emit(event="ready", actions=sorted(stages), joints=read_joints(robot),
             models={name: spec["meta"] for name, spec in arm["actions"].items()},
             rest_pose=plain_pose(rest_pose) if rest_pose else None, safe_tol=mine.safe_tol,
             robot_type=robot_type)
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
                if rest_pose is None and mine.release_without_rest:
                    print(f"[{arm_id}] 쉬는 자세 없이 끔 (--release-without-rest): "
                          "팔이 내려앉을 수 있음", flush=True)
                    emit(event="released", pose_error={}, joints=joints, detail="rest_pose 없이 끔")
                    break
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
            spec = arm["actions"][action]
            model = model_label(spec["meta"])
            if spec.get("noop"):
                # 팔을 움직이지 않는다. 지금 자세가 안전 자세인지만 재서 알린다.
                emit(event="started", id=job_id)
                joints = read_joints(robot)
                error = body_error(joints, safe_poses[action])
                emit(event="done", id=job_id, success=True, end_reason="success", success_basis="noop",
                     arm_safe=all(abs(e) <= mine.safe_tol for e in error.values()), pose_error=error,
                     joints=joints, model=model, box=None)
                continue
            chain, parts = stages[action], spec["stages"]
            # 박스 번호: 박스 원핫을 받는 단계가 하나라도 있으면 box 가 있어야 한다 (움직이기 전에 거절)
            box, runners = msg.get("box"), []
            try:
                for p in parts:
                    if not needs_run_job(robot, p):
                        runners.append(None)
                        continue
                    one_hot = fleet_runtime.box_one_hot(box, p["n_box"]) if p["n_box"] else None
                    runners.append({"one_hot": one_hot,
                                    "motion": fleet_runtime.MotionJudge(p["motion"]) if p["motion"] else None})
            except ValueError as error:
                emit(event="rejected", id=job_id, detail=f"{action}: {error}")
                continue
            if not any(p["n_box"] for p in parts):
                box = None
            # 이 단계는 무엇으로 성공을 판단하나: run_job 단계는 동작 판단만, run_stage 단계는 YOLO 만
            judged = [bool(r["motion"]) if r else bool(st.get("judge")) for st, r in zip(chain, runners)]
            kinds = {("motion" if r else "judge") for r, j in zip(runners, judged) if j}
            basis = "+".join(sorted(kinds)) if kinds else "none"
            emit(event="started", id=job_id)
            reason, results = run_chain(robot, chain, features, args, stop_evt, len(chain) > 1, job_id,
                                        [p["label"] for p in parts], runners)
            # 성공: 모든 단계를 끝까지 갔고, 판단기가 있는 단계는 모두 '성공 판단'으로 끝남.
            # 판단기가 하나도 없으면 예전처럼 늘 false (success_basis=none).
            success = (bool(kinds) and len(results) == len(chain)
                       and all(r["end_reason"] == "success" for r, j in zip(results, judged) if j)
                       and all(r["end_reason"] != "hold" for r in results))
            end_reason = "success" if success else reason
            extra = {"stages": results} if len(chain) > 1 else {}
            if reason == "hold":
                # 멈춤: 더 움직이지 않는다. 토크는 유지돼 서보가 마지막 목표를 붙잡는다.
                emit(event="done", id=job_id, success=False, end_reason="hold", arm_safe=False,
                     success_basis=basis, pose_error={}, joints=read_joints(robot), model=model, box=box, **extra)
                continue
            arm_safe, error, joints = retreat(robot, safe_poses[action], args, chain[-1]["name"], mine.safe_tol)
            emit(event="done", id=job_id, success=success, end_reason=end_reason, arm_safe=arm_safe,
                 success_basis=basis, pose_error=error, joints=joints, model=model, box=box, **extra)
    except Exception as error:  # noqa: BLE001 — 무슨 오류든 어댑터에 알리고 끝낸다
        emit(event="fatal", detail=f"{type(error).__name__}: {error}")
        raise
    finally:
        if preview is not None:
            preview.stop()
        print(f"[{arm_id}] 연결 끊음 — 토크가 꺼지므로 팔이 내려앉을 수 있음", flush=True)
        if robot.is_connected:
            robot.disconnect()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
