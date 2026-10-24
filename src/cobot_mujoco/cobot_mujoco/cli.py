"""Command-line entry points for simulation, reports, and offline experiments."""

import argparse
from pathlib import Path

from .common import PACKAGE, read_json, utc_now, write_json


def main():
    """Dispatch simulation, data, experiment, and report commands."""
    parser = argparse.ArgumentParser(description="OMX MuJoCo validation; no hardware access")
    sub = parser.add_subparsers(dest="command", required=True)
    assets = sub.add_parser("fetch-robot")
    assets.add_argument("--assets", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source", required=True)
    prep.add_argument("--cache", required=True)
    for name in ["render", "view", "diagnose"]:
        p = sub.add_parser(name)
        p.add_argument("--assets", required=True)
        p.add_argument("--scene", default=str(PACKAGE / "config/scene.json"))
        if name == "render":
            p.add_argument("--output", required=True)
        if name == "diagnose":
            p.add_argument("--cache", required=True)
            p.add_argument("--output", required=True)
    run = sub.add_parser("run")
    for name in ["cache", "assets", "run", "report-dir"]:
        run.add_argument(f"--{name}", required=True)
    run.add_argument("--hours", type=float, default=12)
    run.add_argument("--push-report", action="store_true")
    run.add_argument("--sweep")
    report = sub.add_parser("report")
    report.add_argument("--run", required=True)
    report.add_argument("--output", required=True)
    stop = sub.add_parser("stop")
    stop.add_argument("--run", required=True)
    args = parser.parse_args()
    if args.command == "fetch-robot":
        from .assets import fetch_robot

        print(fetch_robot(args.assets))
    elif args.command == "prepare":
        from .data import prepare_dataset

        prepare_dataset(args.source, args.cache)
    elif args.command in {"render", "view"}:
        from .environment import OMXEnvironment

        env = OMXEnvironment(args.assets, read_json(args.scene))
        try:
            if args.command == "render":
                from PIL import Image

                path = Path(args.output)
                path.mkdir(parents=True, exist_ok=True)
                for camera in ["top", "wrist"]:
                    Image.fromarray(env.render(camera, 640, 480)).save(path / f"{camera}.png")
            else:
                import time
                import mujoco.viewer

                with mujoco.viewer.launch_passive(env.model, env.data) as viewer:
                    while viewer.is_running():
                        env.step(env.config["initial_state"])
                        viewer.sync()
                        time.sleep(1 / env.config["fps"])
        finally:
            env.close()
    elif args.command == "diagnose":
        from .evaluation import kinematic_check, replay_recording

        diagnostics = {
            "captured_at": utc_now(),
            "scene_config": read_json(args.scene),
            "kinematics": kinematic_check(args.cache, args.assets),
            "replay": [
                replay_recording(args.cache, args.assets, episode=n, config=read_json(args.scene))
                for n in [0, 1, 2]
            ],
        }
        write_json(args.output, diagnostics)
        print(diagnostics)
    elif args.command == "run":
        from .runner import run_sweep

        run_sweep(
            args.cache, args.assets, args.run, args.report_dir, args.hours, args.push_report, args.sweep
        )
    elif args.command == "report":
        from .report import make_report

        make_report(args.run, args.output, Path(args.run) / "evidence")
    elif args.command == "stop":
        (Path(args.run) / "STOP").write_text("User requested stop\n")
        print("Stop requested; supervisor will record the interrupted trial and finalize the report.")


if __name__ == "__main__":
    main()
