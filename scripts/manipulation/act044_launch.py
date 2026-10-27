# Copyright 2026 HeoJiHyeok
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Select the user's ACT 0.4.4 checkpoints and explicitly launch upstream real-robot inference."""

import argparse
from datetime import datetime
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import shlex
import sys


def read(path):
    """Read saved local metadata without importing or connecting to any hardware."""
    return json.loads(Path(path).read_text())


def complete_checkpoints(job):
    """Exclude incomplete checkpoints while the training process is still writing files."""
    root = Path(job) / "upstream/checkpoints"
    last = root / "last"
    if not last.exists() or not last.resolve().name.isdigit():
        return []
    maximum = int(last.resolve().name)
    ready = []
    for path in root.glob("*/pretrained_model"):
        if not path.parent.name.isdigit() or int(path.parent.name) > maximum:
            continue
        required = [
            "model.safetensors",
            "config.json",
            "policy_preprocessor.json",
            "policy_postprocessor.json",
        ]
        if not all((path / name).is_file() and (path / name).stat().st_size > 0 for name in required):
            continue
        for name in ["policy_preprocessor.json", "policy_postprocessor.json"]:
            required += [step["state_file"] for step in read(path / name)["steps"] if step.get("state_file")]
        if all((path / name).exists() for name in required):
            ready.append(path)
    return sorted(ready, key=lambda path: int(path.parent.name))


def choose(run, selector, step=None, latest=False):
    """Choose a fixed experiment ID, architecture candidate, or explicit versioned checkpoint."""
    plan = read(run / "plan.json")
    if read(run / "provenance.json")["lerobot_version"] != "0.4.4":
        raise ValueError("이 실행 폴더는 LeRobot 0.4.4 학습 결과가 아닙니다.")
    if selector.isdigit() and int(selector) > len(plan["trials"]) and (run / "previous_run.json").exists():
        previous_index = int(selector) - len(plan["trials"])
        if not 1 <= previous_index <= 3:
            raise ValueError("기존 40k 비교 모델 번호는 26~28입니다.")
        previous = Path(read(run / "previous_run.json")["run"])
        return choose(previous, str(previous_index), step, latest)
    if selector in {"standard", "light"}:
        measurements = []
        for job in plan["trials"]:
            path = run / "jobs" / job["name"] / "measurements.json"
            if job["architecture"] == selector and path.exists():
                measurements.extend(read(path))
        if not measurements:
            raise ValueError("이 구조의 검증 결과가 아직 없습니다. list의 번호를 직접 고르세요.")
        value = min(measurements, key=lambda row: row["validation"]["control_mae"])
        selector = value["config"]["name"]
    if selector.isdigit():
        index = int(selector) - 1
        if not 0 <= index < len(plan["trials"]):
            raise ValueError("모델 번호는 list에 표시된 번호를 사용하세요.")
        selector = plan["trials"][index]["name"]
    names = {row["name"] for row in plan["trials"]}
    if selector not in names:
        path = Path(selector).expanduser().resolve()
        if not path.is_relative_to(run.resolve() / "jobs") or path.name != "pretrained_model":
            raise ValueError("이번 0.4.4 모델 번호·이름·pretrained_model 경로를 지정하세요.")
        selector = path.parents[3].name
        step = int(path.parent.name)
    job = run / "jobs" / selector
    ready = complete_checkpoints(job)
    if not ready:
        raise ValueError("이 모델에는 아직 완전히 저장된 체크포인트가 없습니다.")
    if step is not None:
        candidates = [path for path in ready if int(path.parent.name) == step]
        if not candidates:
            raise ValueError(f"저장 완료된 step {step}이 없습니다. checkpoints 명령으로 확인하세요.")
        return candidates[0], "직접 지정한 저장 단계"
    path = job / "measurements.json"
    if path.exists() and not latest:
        values = [row for row in read(path) if Path(row["checkpoint"]) in ready]
        if values:
            best = min(values, key=lambda row: row["validation"]["control_mae"])
            return Path(best["checkpoint"]), f"현재 검증 최저 MAE {best['validation']['control_mae']:.3f}"
    return ready[-1], "최신 저장본 (검증 선택이 완료되지 않았을 수 있음)"


def list_models(run):
    """List stable plan IDs without changing the user's model or device configuration."""
    for index, cfg in enumerate(read(run / "plan.json")["trials"], 1):
        job = run / "jobs" / cfg["name"]
        ready = complete_checkpoints(job)
        stage = f"최신 {int(ready[-1].parent.name):,} step" if ready else "저장본 대기"
        architecture = "일반형" if cfg["architecture"] == "standard" else "경량형"
        current = "전류 포함" if cfg.get("current", False) else "전류 없음"
        print(
            f"{index:2d}) {architecture} | {current} | 배치 {cfg.get('batch_size', 8)} | "
            f"chunk {cfg['chunk']:3d} | lr {cfg['lr']:g} | "
            f"감쇠 {cfg['weight_decay']:g} | {stage}\n    {cfg['name']}"
        )
    print("\n모델 폴더:", run / "jobs")
    if (run / "previous_run.json").exists():
        previous = Path(read(run / "previous_run.json")["run"])
        for offset, cfg in enumerate(read(previous / "plan.json")["trials"][:3], 1):
            print(
                f"{len(read(run / 'plan.json')['trials']) + offset:2d}) 기존 40k 일반형 · 전류 없음 · "
                f"배치 {cfg['batch_size']} · chunk {cfg['chunk']}\n    {cfg['name']}"
            )
    print("번호는 고정입니다. --step 생략 시 해당 모델의 검증 최저 MAE 저장본을 선택합니다.")


def check_model(checkpoint):
    """Load actual model and processors on CPU, never open a robot or camera device."""
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    cfg = PreTrainedConfig.from_pretrained(checkpoint)
    cfg.device = "cpu"
    policy = ACTPolicy.from_pretrained(checkpoint, config=cfg)
    make_pre_post_processors(
        cfg,
        pretrained_path=checkpoint,
        preprocessor_overrides={"device_processor": {"device": "cpu"}},
    )
    print("모델·전처리·후처리 로딩 정상 (CPU 확인만, 장치 연결 없음)")
    print(
        "ResNet:",
        cfg.vision_backbone,
        "/ Transformer:",
        cfg.dim_model,
        "/ chunk:",
        cfg.chunk_size,
    )
    print("학습 파라미터:", sum(p.numel() for p in policy.parameters()))


def launch_command(args, checkpoint):
    """Build 0.4.4 lerobot-record policy inference with local evaluation recording only."""
    cfg = read(checkpoint / "config.json")
    features = cfg["input_features"]
    state_shape = features["observation.state"]["shape"]
    if cfg["type"] != "act" or state_shape not in ([6], [7]):
        raise ValueError("ACT의 관절 6개 또는 관절6+그리퍼전류 입력만 지원합니다.")
    current = state_shape == [7]
    cameras = {}
    for name, device, fps, fourcc in [
        ("top", args.top, args.top_fps, os.environ.get("FRONT_CAM_FOURCC", "")),
        ("wrist", args.wrist, args.wrist_fps, os.environ.get("WRIST_CAM_FOURCC", "")),
    ]:
        _, height, width = features[f"observation.images.{name}"]["shape"]
        cameras[name] = {
            "type": "opencv",
            "index_or_path": device,
            "width": width,
            "height": height,
            "fps": fps,
            "warmup_s": 3,
        }
        if fourcc:
            cameras[name]["fourcc"] = fourcc
    tag = checkpoint.parents[3].name + "_s" + str(int(checkpoint.parent.name))
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{os.getpid()}"
    target = Path.home() / "il_ws/outputs/act044_real_eval" / f"{tag}_{suffix}"
    command = [
        sys.executable,
        "-m",
        "lerobot.scripts.lerobot_record",
        f"--policy.path={checkpoint}",
        f"--policy.device={args.device}",
        f"--policy.n_action_steps={args.action_steps}",
        "--policy.temporal_ensemble_coeff="
        + (str(args.temporal_ensemble_coeff) if args.temporal_ensemble else "null"),
        "--robot.type=" + ("omx_follower_current" if current else "omx_follower"),
        f"--robot.id={args.robot_id}",
        f"--robot.port={args.port}",
        "--robot.use_degrees=false",
        "--robot.max_relative_target="
        + ("null" if args.max_relative_target is None else str(args.max_relative_target)),
        "--robot.cameras=" + json.dumps(cameras),
        f"--dataset.repo_id=local/eval_{tag}_{suffix}",
        f"--dataset.root={target}",
        "--dataset.single_task=" + os.environ.get("TASK", "상자를 집어 수신대에 놓는다."),
        "--dataset.fps=30",
        "--dataset.num_episodes=1",
        f"--dataset.episode_time_s={args.duration}",
        "--dataset.reset_time_s=0",
        "--dataset.push_to_hub=false",
        "--dataset.vcodec=h264",
        "--play_sounds=false",
        f"--display_data={str(args.display).lower()}",
    ]
    if args.init_pose or current:
        extra = []
        if args.init_pose:
            extra = [
                f"--init-pose-file={args.init_pose_file}",
                f"--init-pose-duration={args.init_pose_duration}",
            ]
        command[1:3] = [
            str(Path(__file__).with_name("act044_record.py")),
            *extra,
        ]
    return command, target


def main():
    """List/check safely, print a dry run, or explicitly run the chosen real-robot policy."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["list", "checkpoints", "check", "run"],
        default="list",
    )
    parser.add_argument("model", nargs="?", help="list의 번호·이름 또는 standard/light")
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=Path(
            os.environ.get("ACT044_RUN_DIR", str(Path.home() / "omx_sim_runs/retraining_044_20261026"))
        ),
    )
    parser.add_argument("--step", type=int)
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--init-pose",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("ACT044_INIT_POSE", "false").lower() in {"true", "1", "yes"},
    )
    parser.add_argument(
        "--init-pose-file",
        type=Path,
        default=Path(
            os.environ.get("ACT044_INIT_POSE_FILE", str(Path(__file__).with_name("act044_init_pose.json")))
        ),
    )
    parser.add_argument(
        "--init-pose-duration", type=float, default=float(os.environ.get("ACT044_INIT_POSE_DURATION", "3"))
    )
    parser.add_argument("--duration", type=float, default=float(os.environ.get("ACT044_DURATION", "10")))
    parser.add_argument("--action-steps", type=int, default=int(os.environ.get("ACT044_ACTION_STEPS", "5")))
    parser.add_argument(
        "--temporal-ensemble",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("ACT044_TEMPORAL_ENSEMBLE", "false").lower() in {"true", "1", "yes"},
        help="ACT temporal ensembling을 켭니다. action-steps=1이 필요합니다.",
    )
    parser.add_argument(
        "--temporal-ensemble-coeff",
        type=float,
        default=float(os.environ.get("ACT044_TEMPORAL_ENSEMBLE_COEFF", "0.01")),
    )
    parser.add_argument(
        "--max-relative-target", type=float, default=float(os.environ.get("ACT044_MAX_RELATIVE_TARGET", "3"))
    )
    parser.add_argument(
        "--no-relative-target",
        action="store_const",
        const=None,
        dest="max_relative_target",
        help="이번 실행에서 관절 목표 변화량 제한을 해제합니다.",
    )
    parser.add_argument("--device", choices=["cuda", "cpu"], default=os.environ.get("ACT044_DEVICE", "cuda"))
    parser.add_argument("--port", default=os.environ.get("ROBOT_PORT", ""))
    parser.add_argument("--robot-id", default=os.environ.get("ROBOT_ID", "omx_follower_arm"))
    parser.add_argument("--top", default=os.environ.get("FRONT_CAM", ""))
    parser.add_argument("--wrist", default=os.environ.get("WRIST_CAM", ""))
    parser.add_argument("--top-fps", type=int, default=int(os.environ.get("FRONT_CAM_FPS", "22")))
    parser.add_argument("--wrist-fps", type=int, default=int(os.environ.get("WRIST_CAM_FPS", "30")))
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--display", action="store_true", dest="display")
    display.add_argument("--no-display", action="store_false", dest="display")
    parser.set_defaults(display=os.environ.get("ACT044_DISPLAY", "false").lower() in {"true", "1", "yes"})
    args = parser.parse_args()
    if version("lerobot") != "0.4.4":
        raise ValueError("반드시 ~/venv/il의 LeRobot 0.4.4를 사용하세요.")
    if args.mode == "list":
        list_models(args.run_dir)
        return
    if not args.model:
        parser.error("모델 번호·이름·standard/light를 지정하세요.")
    checkpoint, reason = choose(args.run_dir, args.model, args.step, args.latest)
    print("선택 모델:", checkpoint, "\n선택 기준:", reason, flush=True)
    if args.mode == "checkpoints":
        for path in complete_checkpoints(checkpoint.parents[3]):
            print(int(path.parent.name), path)
        return
    if args.mode == "check":
        check_model(checkpoint)
        return
    cfg = read(checkpoint / "config.json")
    if not 1 <= args.action_steps <= cfg["chunk_size"]:
        raise ValueError("action-steps는 1 이상이며 모델 chunk 이하여야 합니다.")
    if args.temporal_ensemble and args.action_steps != 1:
        raise ValueError("Temporal ensembling은 --action-steps 1과 함께 사용하세요.")
    if not math.isfinite(args.temporal_ensemble_coeff):
        raise ValueError("temporal-ensemble-coeff는 유한한 숫자여야 합니다.")
    if args.duration <= 0 or (
        args.max_relative_target is not None
        and (not math.isfinite(args.max_relative_target) or args.max_relative_target <= 0)
    ):
        raise ValueError("duration과 max-relative-target은 양수여야 합니다.")
    if not args.port or not args.top or not args.wrist:
        raise ValueError("팔로워 포트와 top/wrist 카메라 경로를 설정하세요.")
    if args.init_pose:
        # The local helper uses only the standard library; validation never opens hardware.
        sys.path.insert(0, str(Path(__file__).parent))
        from act044_init import load_pose

        pose = load_pose(args.init_pose_file)
        if not math.isfinite(args.init_pose_duration) or args.init_pose_duration <= 0:
            raise ValueError("Init 이동 시간은 유한한 양수여야 합니다.")
        print("추론 전 Init 이동:", pose, f"/ {args.init_pose_duration}초", flush=True)
    command, target = launch_command(args, checkpoint)
    print("실행 명령:\n" + shlex.join(command), flush=True)
    print("실물 평가 기록:", target, flush=True)
    if args.dry_run:
        print("DRY RUN: 로봇·카메라 연결과 모터 명령 전송을 실행하지 않았습니다.")
        return
    from lerobot.utils.constants import HF_LEROBOT_CALIBRATION

    calibration = HF_LEROBOT_CALIBRATION / "robots/omx_follower" / f"{args.robot_id}.json"
    if not calibration.exists():
        raise ValueError(f"기존 캘리브레이션이 없습니다. 자동 덮어쓰기를 피하려고 종료합니다: {calibration}")
    for name, path in [("팔로워", args.port), ("top", args.top), ("wrist", args.wrist)]:
        if not Path(path).exists():
            raise ValueError(f"{name} 장치 경로가 없습니다: {path}")
    print(
        "실물 구동 시작: 학습 당시 초기 자세·물체 배치에서 사용하세요. 종료 시 토크가 해제됩니다.",
        flush=True,
    )
    os.execv(sys.executable, command)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, KeyError) as error:
        print("실행 준비 오류:", error, file=sys.stderr)
        sys.exit(2)
