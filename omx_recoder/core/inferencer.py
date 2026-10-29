"""Robot inference through omx_train/<policy>/inference.sh (lerobot-rollout, lerobot 0.6.1).

inference.sh is the single inference entry point, shared with the command line: the dashboard only
picks its environment variables and override arguments. It runs with this app's Python (the same
venv), so the dashboard must release the follower port and the cameras before starting it.
"""

import os
import queue
import re
import shlex
import signal
import sys
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer

from .trainer import outputs_dir, policy_dir

STOP_TIMEOUT_MS = 10_000  # lerobot gets this long after Ctrl+C to release the motors before SIGKILL
_ARG_RE = re.compile(r'^\s*--([a-z_.]+)=("[^"]*"|\S+)')


def inference_script(omx_dir: Path, policy: str) -> Path:
    return policy_dir(omx_dir, policy) / "inference.sh"


def script_defaults(script: Path) -> dict[str, str]:
    """Values inference.sh actually passes (uncommented `--name=value` lines), quotes stripped."""
    out = {}
    for line in Path(script).read_text().splitlines():
        m = _ARG_RE.match(line)
        if m:
            out.setdefault(m.group(1), m.group(2).strip('"'))
    return out


def list_models(omx_dir: Path, policy: str) -> list[Path]:
    """pretrained_model folders of every training run (last first, then by step), newest run first."""
    root = outputs_dir(omx_dir, policy)
    if not root.is_dir():
        return []
    runs = sorted((p for p in root.iterdir() if (p / "checkpoints").is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for run in runs:
        ckpts = [c for c in (run / "checkpoints").iterdir() if (c / "pretrained_model").is_dir()]
        ckpts.sort(key=lambda c: (c.name != "last", -int(c.name) if c.name.isdigit() else 0))
        out += [c / "pretrained_model" for c in ckpts]
    return out


def model_label(omx_dir: Path, policy: str, model: Path) -> str:
    try:
        return str(Path(model).relative_to(outputs_dir(omx_dir, policy)))
    except ValueError:
        return str(model)


def build_rollout(
    omx_dir: Path,
    policy: str,
    model: Path,
    port: str,
    cameras: dict[str, str],
    robot_id: str,
    task: str,
    duration: int,
    device: str,
    ensemble: tuple[int, float] | None,
    extra: list[str],
) -> tuple[list[str], dict[str, str]]:
    """(argv, env) that run inference.sh. cameras = {'top': path, 'wrist': path}; ensemble ACT only.

    An empty task keeps the sentence written in inference.sh.
    """
    env = {
        "MODEL": str(model),
        "ROBOT_PORT": port,
        "TOP_CAM": cameras["top"],
        "WRIST_CAM": cameras["wrist"],
        # inference.sh calls `python`: make it this app's venv, which has lerobot 0.6.1.
        "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    if ensemble and policy == "act":
        env["ACT_ENSEMBLE_K"], env["ACT_ENSEMBLE_M"] = str(int(ensemble[0])), f"{ensemble[1]:g}"
    args = [f"--robot.id={robot_id}", f"--duration={int(duration)}", f"--policy.device={device}"]
    if task:
        args.append(f"--task={task}")
    return ["bash", str(inference_script(omx_dir, policy)), *args, *extra], env


def shell_line(argv: list[str], env: dict[str, str], cwd: Path | None = None) -> str:
    """The same call as one command-line string, for the log."""
    envs = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items() if k != "PATH")
    script = argv[1]
    if cwd is not None:
        try:
            script = str(Path(script).relative_to(cwd))
        except ValueError:
            pass
    return " ".join(filter(None, [envs, script, *map(shlex.quote, argv[2:])]))


class Inferencer:
    """Runs inference.sh in its own process group so Stop reaches lerobot itself, not just bash."""

    def __init__(self, omx_dir: Path):
        self.omx_dir = Path(omx_dir)
        self.events: queue.Queue = queue.Queue()
        self.proc: QProcess | None = None
        self.started_at = 0.0
        self.stop_requested = False
        self._buf = ""
        self._kill_timer = QTimer()
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._kill)

    @property
    def running(self) -> bool:
        return self.proc is not None

    def elapsed(self) -> float:
        return max(0.0, time.time() - self.started_at) if self.running else 0.0

    def start(self, argv: list[str], env: dict[str, str]) -> None:
        if self.running:
            return
        self.stop_requested = False
        self._buf = ""
        self.events.put(("infer_log", "$ " + shell_line(argv, env, self.omx_dir)))
        proc = QProcess()
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.setWorkingDirectory(str(Path(argv[1]).parent))
        penv = QProcessEnvironment.systemEnvironment()
        penv.insert("PYTHONUNBUFFERED", "1")
        for k, v in env.items():
            penv.insert(k, v)
        proc.setProcessEnvironment(penv)
        proc.readyReadStandardOutput.connect(self._on_output)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self.proc = proc
        self.started_at = time.time()
        # setsid: bash and the python it starts share a new process group that stop() signals as a whole.
        proc.start("setsid", argv)

    def stop(self) -> None:
        """Ctrl+C for the whole group (lerobot disconnects the robot), SIGKILL if it hangs."""
        if not self.running or self.stop_requested:
            return
        self.stop_requested = True
        self.events.put(("infer_log", "추론 중지 요청 (Ctrl+C)"))
        self._signal(signal.SIGINT)
        self._kill_timer.start(STOP_TIMEOUT_MS)

    def shutdown(self, timeout_ms: int = STOP_TIMEOUT_MS + 3000) -> None:
        """Stop and wait (app closing)."""
        if self.proc is None:
            return
        self.stop()
        if not self.proc.waitForFinished(timeout_ms):
            self._kill()
            self.proc.waitForFinished(3000)

    # -------------------------------------------------------------- internals
    def _signal(self, sig: int) -> None:
        pid = self.proc.processId() if self.proc is not None else 0
        if pid > 0:
            try:
                os.killpg(pid, sig)
            except ProcessLookupError:
                pass

    def _kill(self) -> None:
        if self.running:
            self.events.put(("infer_log", "응답이 없어 강제 종료합니다 (SIGKILL)"))
            self._signal(signal.SIGKILL)

    def _on_output(self) -> None:
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._buf += data.replace("\r", "\n")
        *lines, self._buf = self._buf.split("\n")
        for line in lines:
            if line.strip():
                self.events.put(("infer_log", line.rstrip()))

    def _on_finished(self, code: int, status) -> None:
        if self._buf.strip():
            self.events.put(("infer_log", self._buf.rstrip()))
        self._buf = ""
        self._kill_timer.stop()
        self.proc = None
        self.events.put(("infer_done", -1 if status == QProcess.CrashExit else code))

    def _on_error(self, err) -> None:
        if err == QProcess.FailedToStart:
            self._kill_timer.stop()
            self.proc = None
            self.events.put(("infer_log", "프로세스를 시작하지 못했습니다 (setsid/bash 확인)."))
            self.events.put(("infer_done", -1))
