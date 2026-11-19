"""omx_fleet_worker 가 쓰는 로봇 타입·박스 번호·동작 성공 판단·작업 실행 (lerobot 0.4.4).

omx_chain.py 는 대시보드에서 고치지 않고 복사한 파일이라 그대로 두고, 관제 실행기에만 필요한 것을 여기에 둔다.

- 로봇 타입: 기본 omx_follower. 그리퍼 전류(omx_follower_grip)·MoGe depth(omx_follower_grip_depth) 모델은
  그 모델 번들의 omx_grip_robot.py·omx_depth_robot.py 를 불러와 같은 로봇을 만든다 (robot_code_dir).
- depth: 실행기는 lerobot.utils.control_utils.predict_action 을 쓰므로 번들의 자동 갱신(install)이 걸리지 않는다.
  그래서 정책이 새로 예측하는 프레임에서만 여기서 depth 를 새로 만든다 (번들의 depth_sync 방식과 같다).
- 박스 번호: 모델 폴더 omx_info.json 의 box.mode 가 "state" 면 그 작업은 box(1..N) 가 있어야 하고,
  원핫 N 개를 observation.state 끝에 붙인다 (번들 omx_box.py 와 같은 값).
- 동작 성공 판단 (success_motion): 그리퍼 전류로 잡음 → 회전한 곳에서 놓음 → 처음 회전값으로 돌아옴 이 차례로
  나오면 성공. 학습 시연(omx_1031 2번)에서 잡는 동안 전류 약 -330 mA, 놓으면 ±20 mA, 회전은 -1.7 → 41 → -2.4.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np

PAN = "shoulder_pan.pos"
GRIP_CURRENT = "gripper_current.pos"  # omx_grip_robot.GRIP_KEY
ROBOT_TYPES = ("omx_follower", "omx_follower_grip", "omx_follower_grip_depth")
MOTION_DEFAULTS = {
    "grip_closed_ma": -150.0,   # 이 값 이하가 hold_s 동안 이어지면 잡음 (닫는 쪽 전류가 음수)
    "grip_open_ma": 80.0,       # |전류| 가 이 값 아래로 hold_s 동안 이어지면 놓음
    "pan_away": 20.0,           # 놓을 때 처음 회전값에서 이만큼 이상 돌아가 있어야 함 (관절 단위)
    "pan_home_tol": 5.0,        # 처음 회전값 ± 이 안으로 hold_s 동안 있으면 돌아옴
    "hold_s": 0.5,
}


def model_info(model_path):
    """모델 폴더의 omx_info.json (없으면 {})."""
    f = Path(model_path) / "omx_info.json"
    return json.loads(f.read_text()) if f.is_file() else {}


def box_count(model_path):
    """그 모델이 state 에 붙는 박스 원핫 수. 박스를 받지 않는 모델이면 0."""
    box = model_info(model_path).get("box") or {}
    if box.get("mode") != "state":
        return 0
    return len(box.get("tasks") or []) or 4


def box_one_hot(box, n_box):
    """box(1..n_box) → 원핫. 틀리면 ValueError (팔을 움직이기 전에 거절하려고)."""
    if isinstance(box, bool) or not isinstance(box, int) or not 1 <= box <= n_box:
        raise ValueError(f"박스 번호는 1..{n_box} 정수여야 함 ({box!r})")
    return np.eye(n_box, dtype=np.float32)[box - 1]


def motion_config(spec):
    """success_motion 칸 → 판단 설정 (없으면 None). 모르는 칸은 오타일 수 있으니 거절한다."""
    if spec in (None, False):
        return None
    if spec is True:
        spec = {}
    if not isinstance(spec, dict):
        raise ValueError(f"success_motion 은 true 또는 설정 칸 ({spec!r})")
    unknown = set(spec) - set(MOTION_DEFAULTS)
    if unknown:
        raise ValueError(f"success_motion 에 모르는 칸: {sorted(unknown)}")
    return {k: float(spec.get(k, v)) for k, v in MOTION_DEFAULTS.items()}


class MotionJudge:
    """잡음 → (돌아간 곳에서) 놓음 → 처음 회전값으로 돌아옴. 단계마다 begin() 으로 새로 시작한다."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.phase, self.pan0, self.since, self.at = "wait_grasp", None, None, {}

    def begin(self):
        self.phase, self.pan0, self.since, self.at = "wait_grasp", None, None, {}

    def _held(self, ok, now):
        if not ok:
            self.since = None
            return False
        if self.since is None:
            self.since = now
        return now - self.since >= self.cfg["hold_s"]

    def update(self, obs, now):
        """관측 한 번. 성공이면 True. 단계: wait_grasp → wait_release → wait_return → done."""
        pan, current = float(obs[PAN]), float(obs[GRIP_CURRENT])
        if self.pan0 is None:
            self.pan0 = pan
        cfg = self.cfg
        if self.phase == "wait_grasp" and self._held(current <= cfg["grip_closed_ma"], now):
            self.phase, self.since, self.at["grasp"] = "wait_release", None, now
        elif self.phase == "wait_release" and self._held(
                abs(current) < cfg["grip_open_ma"] and abs(pan - self.pan0) >= cfg["pan_away"], now):
            self.phase, self.since, self.at["release"] = "wait_return", None, now
        elif self.phase == "wait_return" and self._held(abs(pan - self.pan0) <= cfg["pan_home_tol"], now):
            self.phase, self.at["return"] = "done", now
        return self.phase == "done"

    def summary(self):
        return {"phase": self.phase, "pan_start": None if self.pan0 is None else round(self.pan0, 1)}


def make_robot(arm, args, depth_info=None):
    """팔 설정의 robot_type 으로 로봇을 만든다 (연결은 하지 않음)."""
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig

    kind = arm.get("robot_type") or "omx_follower"
    if kind not in ROBOT_TYPES:
        raise ValueError(f"모르는 robot_type: {kind} ({', '.join(ROBOT_TYPES)})")

    def cam(dev):
        return OpenCVCameraConfig(
            index_or_path=int(dev) if str(dev).isdigit() else Path(dev), width=640, height=480, fps=args.fps,
            **({"fourcc": "MJPG"} if args.mjpg else {}),
        )

    common = dict(port=args.port, id=args.robot_id, max_relative_target=args.max_relative_target,
                  cameras={"top": cam(args.top), "wrist": cam(args.wrist)})
    if kind == "omx_follower":
        from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig
        from lerobot.robots.omx_follower.omx_follower import OmxFollower

        return OmxFollower(OmxFollowerConfig(**common))
    code_dir = arm.get("robot_code_dir")
    if not code_dir or not (Path(code_dir).expanduser() / "omx_grip_robot.py").is_file():
        raise ValueError(f"{kind} 에는 robot_code_dir (omx_grip_robot.py·omx_depth_robot.py 가 있는 번들 폴더) 필요")
    sys.path.insert(0, str(Path(code_dir).expanduser()))
    if kind == "omx_follower_grip":
        from omx_grip_robot import OmxFollowerGrip, OmxFollowerGripConfig

        return OmxFollowerGrip(OmxFollowerGripConfig(**common))
    if not depth_info:
        raise ValueError(f"{kind}: 작업 모델 폴더에 depth_info.json 이 없음")
    from omx_depth_robot import OmxFollowerGripDepth, OmxFollowerGripDepthConfig

    return OmxFollowerGripDepth(OmxFollowerGripDepthConfig(
        **common, depth_info=str(depth_info), depth_device=args.device, gripper_current=True, depth_sync=True))


def find_depth_info(actions):
    """작업 모델 폴더에서 depth_info.json 을 찾는다. 작업마다 다르면 한 로봇으로 못 돌리므로 오류."""
    found = {}
    for name, spec in actions.items():
        if spec.get("noop"):
            continue
        f = Path(spec["model"]) / "depth_info.json"
        if f.is_file():
            found[name] = f
    texts = {f.read_text() for f in found.values()}
    if len(texts) > 1:
        raise ValueError(f"작업마다 depth_info.json 이 다름: {sorted(found)}")
    return next(iter(found.values()), None)


def check_state_size(stage, features, n_box):
    """모델 state 길이 == 로봇 state 길이 + 박스 원핫 수 (키 이름만 보는 omx_chain.check_inputs 를 보완)."""
    want = stage["policy"].config.input_features["observation.state"].shape[0]
    have = features["observation.state"]["shape"][0] + n_box
    if want != have:
        raise SystemExit(f"{stage['name']} state 길이가 다름: 모델 {want} / 로봇 {have - n_box} + 박스 {n_box}")


def warm_depth(robot):
    """MoGe 첫 추론이 느려서 연결 직후 빈 영상으로 한 번 돌려 둔다."""
    if hasattr(robot, "refresh_depth"):
        c = robot.config.cameras[robot.src_cam]
        robot.refresh_depth(np.zeros((c.height, c.width, 3), dtype=np.uint8))
        robot.depth = None


def run_job(robot, stage, features, args, stop_evt, one_hot=None, motion=None):
    """한 작업 실행 (omx_chain.run_stage 와 같은 제어 주기 + depth·박스·동작 판단).

    반환: 'timeout' | 'next'(멈춤) | 'success'.
    """
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
    depth = hasattr(robot, "refresh_depth") and robot.config.depth_sync
    will_predict = sys.modules[type(robot).__module__].will_predict if depth else None
    if motion:
        motion.begin()
    reason = "timeout"
    t0 = time.perf_counter()
    steps = slow = 0
    try:
        while (elapsed := time.perf_counter() - t0) < stage["seconds"]:
            if stop_evt.is_set():
                reason = "next"
                break
            start = time.perf_counter()
            robot.config.max_relative_target = limit if elapsed < args.ramp_s else normal_max
            obs = robot.get_observation()
            if motion and motion.update(obs, start):
                reason = "success"
                break
            frame = build_dataset_frame(features, obs, prefix=OBS_STR)
            if depth and will_predict(policy):
                frame[f"{OBS_STR}.images.{robot.depth_cam}"] = robot.refresh_depth(obs[robot.src_cam])
            if one_hot is not None:
                frame[f"{OBS_STR}.state"] = np.concatenate(
                    [np.asarray(frame[f"{OBS_STR}.state"], dtype=np.float32), one_hot])
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
    note = f", 동작 판단 {motion.summary()}" if motion else ""
    print(f"  {stage['name']}: {time.perf_counter() - t0:.1f}s, {steps} 스텝, 목표 주기 초과 {slow}회, "
          f"끝난 이유: {reason}{note}", flush=True)
    return reason
