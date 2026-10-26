"""Protect checkpoint selection and non-actuating preview behavior of the real-robot launcher."""

import importlib.util
import json
from types import SimpleNamespace

import pytest

from cobot_mujoco.common import REPOSITORY


def launcher():
    """Load the standalone command builder without importing robot drivers."""
    spec = importlib.util.spec_from_file_location(
        "act044_launch", REPOSITORY / "scripts/manipulation/act044_launch.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_run(tmp_path):
    """Create metadata-only checkpoint fixtures; never allocate a model or open devices."""
    run = tmp_path / "training"
    run.mkdir()
    (run / "plan.json").write_text(json.dumps({"trials": [{"name": "trial", "architecture": "standard"}]}))
    (run / "provenance.json").write_text(json.dumps({"lerobot_version": "0.4.4"}))
    job = run / "jobs/trial"
    for step in [1000, 2000]:
        directory = job / "upstream/checkpoints" / f"{step:06d}" / "pretrained_model"
        directory.mkdir(parents=True)
        (directory / "model.safetensors").write_text("fixture-not-loaded")
        (directory / "norm.safetensors").write_text("fixture-not-loaded")
        config = {
            "type": "act",
            "chunk_size": 32,
            "input_features": {
                "observation.state": {"shape": [6]},
                "observation.images.top": {"shape": [3, 480, 640]},
                "observation.images.wrist": {"shape": [3, 480, 640]},
            },
        }
        (directory / "config.json").write_text(json.dumps(config))
        for name in ["policy_preprocessor.json", "policy_postprocessor.json"]:
            (directory / name).write_text(json.dumps({"steps": [{"state_file": "norm.safetensors"}]}))
    root = job / "upstream/checkpoints"
    (root / "last").symlink_to(root / "001000", target_is_directory=True)
    return run, job


def test_launcher_hides_not_yet_committed_saves_and_resolves_real_checkpoint_paths(tmp_path):
    """Respect the upstream last marker and accept an explicit checkpoint in the correct job."""
    module = launcher()
    run, job = fixture_run(tmp_path)
    assert [int(p.parent.name) for p in module.complete_checkpoints(job)] == [1000]
    path, _ = module.choose(run, "1")
    assert path.parents[3] == job
    assert module.choose(run, str(path))[0] == path
    with pytest.raises(ValueError, match="저장 완료"):
        module.choose(run, "1", step=2000)
    (job / "upstream/checkpoints/last").unlink()
    (job / "upstream/checkpoints/last").symlink_to(
        job / "upstream/checkpoints/002000", target_is_directory=True
    )
    assert module.choose(run, "1", latest=True)[0].parent.name == "002000"
    (run / "provenance.json").write_text(json.dumps({"lerobot_version": "0.6.1"}))
    with pytest.raises(ValueError, match="0.4.4"):
        module.choose(run, "1")


def test_launcher_uses_record_for_044_and_never_uploads_evaluation_recordings(tmp_path):
    """Keep motor normalization and real camera keys while disabling unrequested Hub uploads."""
    module = launcher()
    run, _ = fixture_run(tmp_path)
    path, _ = module.choose(run, "1")
    args = SimpleNamespace(
        top="/dev/top",
        wrist="/dev/wrist",
        top_fps=22,
        wrist_fps=30,
        device="cuda",
        action_steps=5,
        temporal_ensemble=False,
        temporal_ensemble_coeff=0.01,
        init_pose=False,
        init_pose_file=REPOSITORY / "scripts/manipulation/act044_init_pose.json",
        init_pose_duration=3,
        robot_id="omx_follower_arm",
        port="/dev/follower",
        max_relative_target=3,
        duration=10,
        display=False,
    )
    command, target = module.launch_command(args, path)
    assert command[2] == "lerobot.scripts.lerobot_record"
    assert "--dataset.push_to_hub=false" in command
    assert "--robot.use_degrees=false" in command
    assert "--policy.n_action_steps=5" in command
    assert "--policy.temporal_ensemble_coeff=null" in command
    args.action_steps = 1
    args.temporal_ensemble = True
    ensemble_command, _ = module.launch_command(args, path)
    assert "--policy.n_action_steps=1" in ensemble_command
    assert "--policy.temporal_ensemble_coeff=0.01" in ensemble_command
    args.max_relative_target = None
    unlimited_command, _ = module.launch_command(args, path)
    assert "--robot.max_relative_target=null" in unlimited_command
    args.init_pose = True
    init_command, _ = module.launch_command(args, path)
    assert init_command[1].endswith("act044_record.py")
    assert "--init-pose-duration=3" in init_command
    cameras = json.loads(next(a.split("=", 1)[1] for a in command if a.startswith("--robot.cameras=")))
    assert set(cameras) == {"top", "wrist"}
    assert isinstance(cameras["top"]["fps"], int)
    assert target.name.startswith("trial_s1000_")


def test_launcher_dry_run_never_executes_or_connects_to_hardware(tmp_path, monkeypatch, capsys):
    """Make the preview return before device checks and the real upstream command."""
    module = launcher()
    run, _ = fixture_run(tmp_path)
    monkeypatch.setattr(module, "version", lambda _: "0.4.4")
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "launcher",
            "run",
            "1",
            "--run-dir",
            str(run),
            "--dry-run",
            "--port",
            "/dev/missing",
            "--top",
            "/dev/missing_top",
            "--wrist",
            "/dev/missing_wrist",
        ],
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Dry run must not execute a robot command")

    monkeypatch.setattr(module.os, "execv", forbidden)
    module.main()
    assert "DRY RUN" in capsys.readouterr().out
