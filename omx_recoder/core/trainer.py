import json
import math
import queue
import re
import shlex
import sys
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer

POLICIES = ["act", "diffusion"]
DEVICES = ["cuda", "cpu"]
TRAIN_KIND = "success"  # only successful demos are imitation targets
STOP_GRACE_MS = 10_000
HOLDOUT_FILE = "omx_holdout.json"

_STEP_RE = re.compile(r"\bstep:(\d+(?:\.\d+)?)([KMBTQ]?)(?=\s)")
_EPOCH_RE = re.compile(r"\bepch:(\d+(?:\.\d+)?)")
_LOSS_RE = re.compile(r"\bloss:(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)")
_SUFFIX = {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12, "Q": 1e15}
# lerobot's tqdm bar redraws with \r many times a second; show it as a status line, not in the log.
# The metrics log line is written right after the bar without a newline, so split it off.
_TQDM_RE = re.compile(r"^(Training:[^\]]*\])\s*(.*)$")


def dataset_root(task_dir: Path) -> Path:
    """Default training data: the session's success dataset."""
    return Path(task_dir) / TRAIN_KIND


def episode_count(root: Path) -> int:
    info = Path(root) / "meta" / "info.json"
    if not info.exists():
        return 0
    try:
        return int(json.loads(info.read_text()).get("total_episodes", 0))
    except (ValueError, OSError):
        return 0


def episode_lengths(root: Path) -> dict[int, int]:
    """Frames per episode from meta/episodes; the recorder starts a new parquet file per episode."""
    import pyarrow.parquet as pq

    out = {}
    for f in sorted((Path(root) / "meta" / "episodes").glob("*/*.parquet")):
        t = pq.read_table(f, columns=["episode_index", "length"]).to_pydict()
        out.update(zip(map(int, t["episode_index"]), map(int, t["length"])))
    return out


def parse_episode_list(text: str, total: int) -> list[int]:
    """'5, 9' or '3-5' -> sorted unique indices; raises ValueError on bad syntax or out-of-range."""
    out = set()
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"에피소드 번호 형식 오류: '{part}' (예: 5,9 또는 3-5)")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a > b:
            raise ValueError(f"범위가 거꾸로 되어 있습니다: '{part}'")
        if b >= total:
            raise ValueError(f"에피소드 {b}이(가) 없습니다 (0~{total - 1})")
        out.update(range(a, b + 1))
    return sorted(out)


def steps_per_epoch(frames: int, batch: int) -> int:
    return math.ceil(frames / batch) if frames > 0 and batch > 0 else 0


def split_extra_args(text: str) -> list[str]:
    try:
        args = shlex.split(text)
    except ValueError as e:
        raise ValueError(f"추가 인자를 나눌 수 없습니다: {e}") from e
    bad = [a for a in args if not a.startswith("--")]
    if bad:
        raise ValueError(f"추가 인자는 --이름=값 형식이어야 합니다: {' '.join(bad)}")
    return args


def train_dir_for(data_root: Path) -> Path:
    """Runs sit next to the dataset, so the session default lands in <task_dir>/train."""
    return Path(data_root).parent / "train"


def run_dir(data_root: Path, policy: str) -> Path:
    return train_dir_for(data_root) / f"{policy}_{time.strftime('%Y%m%d_%H%M%S')}"


def default_repo_id(data_root: Path) -> str:
    # Only a label for a local root; lerobot reads the files from --dataset.root.
    root = Path(data_root)
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{root.parent.name}_{root.name}".strip("_")) or "dataset"
    return f"local/{name}"


def resume_config(run: Path) -> Path:
    return Path(run) / "checkpoints" / "last" / "pretrained_model" / "train_config.json"


def latest_run(data_root: Path) -> Path | None:
    """Most recent run that left a resumable checkpoint."""
    root = train_dir_for(data_root)
    if not root.is_dir():
        return None
    runs = [p for p in root.iterdir() if p.is_dir() and resume_config(p).exists()]
    return max(runs, key=lambda p: p.stat().st_mtime) if runs else None


def build_command(
    cfg_train: dict,
    root: Path,
    repo_id: str,
    out_dir: Path,
    resume_from: Path | None = None,
    episodes: list[int] | None = None,
    extra: list[str] | None = None,
) -> list[str]:
    base = [sys.executable, "-m", "lerobot.scripts.lerobot_train"]
    # Extra args go last so they override anything above, like options appended to omx_train's train.sh.
    extra = list(extra or [])
    if resume_from is not None:
        # Every other option is restored from the checkpoint's own train_config.json.
        return base + [f"--config_path={resume_config(resume_from)}", "--resume=true"] + extra
    c = cfg_train
    opt = []
    if episodes is not None:
        opt.append(f"--dataset.episodes=[{','.join(map(str, episodes))}]")
    if c.get("image_aug"):
        opt.append("--dataset.image_transforms.enable=true")
    return base + [
        f"--dataset.repo_id={repo_id}",
        f"--dataset.root={root}",
        f"--policy.type={c['policy']}",
        f"--policy.device={c['device']}",
        # No policy.repo_id is set, and lerobot refuses to train with push_to_hub on.
        "--policy.push_to_hub=false",
        f"--output_dir={out_dir}",
        f"--job_name={Path(out_dir).name}",
        f"--steps={int(c['steps'])}",
        f"--batch_size={int(c['batch_size'])}",
        f"--num_workers={int(c['num_workers'])}",
        f"--log_freq={int(c['log_freq'])}",
        f"--save_freq={int(c['save_freq'])}",
        f"--wandb.enable={'true' if c['wandb'] else 'false'}",
    ] + opt + extra


def parse_log_line(line: str) -> dict | None:
    """Extract progress from lerobot's MetricsTracker line (step:1K smpl:8K ep:20 epch:0.50 loss:0.123 ...)."""
    m = _STEP_RE.search(line + " ")
    loss = _LOSS_RE.search(line)
    if not m or not loss:
        return None
    out = {"step": int(round(float(m.group(1)) * _SUFFIX[m.group(2)])), "loss": float(loss.group(1))}
    ep = _EPOCH_RE.search(line)
    if ep:
        out["epoch"] = float(ep.group(1))
    return out


class Trainer:
    """Runs lerobot training in a child process so a crash or GPU load never stalls the control loop."""

    def __init__(self, cwd: Path):
        self.cwd = Path(cwd)
        self.events: queue.Queue = queue.Queue()
        self.proc: QProcess | None = None
        self.out_dir: Path | None = None
        self.started_at = 0.0
        self.stop_requested = False
        self._buf = ""

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.state() != QProcess.NotRunning

    def start(self, cmd: list[str], out_dir: Path) -> None:
        if self.running:
            return
        self.out_dir = Path(out_dir)
        self.stop_requested = False
        self._buf = ""
        proc = QProcess()
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.setWorkingDirectory(str(self.cwd))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        proc.setProcessEnvironment(env)
        proc.readyReadStandardOutput.connect(self._on_output)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self.proc = proc
        self.started_at = time.monotonic()
        self.events.put(("train_log", "$ " + " ".join(cmd)))
        proc.start(cmd[0], cmd[1:])

    def stop(self) -> None:
        if not self.running:
            return
        self.events.put(("train_log", "학습 중지 요청"))
        self.stop_requested = True
        self.proc.terminate()
        proc = self.proc
        QTimer.singleShot(STOP_GRACE_MS, lambda: proc.state() != QProcess.NotRunning and proc.kill())

    def stop_blocking(self) -> None:
        if not self.running:
            return
        self.stop_requested = True
        self.proc.terminate()
        if not self.proc.waitForFinished(STOP_GRACE_MS):
            self.proc.kill()
            self.proc.waitForFinished(3000)

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at if self.running else 0.0

    def _on_output(self) -> None:
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._buf += data.replace("\r", "\n")
        *lines, self._buf = self._buf.split("\n")
        for line in lines:
            self._emit_line(line)

    def _emit_line(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        tq = _TQDM_RE.match(line)
        if tq:
            self.events.put(("train_tqdm", tq.group(1)))
            line = tq.group(2)
            if not line:
                return
        self.events.put(("train_log", line))
        prog = parse_log_line(line)
        if prog:
            self.events.put(("train_progress", prog))

    def _on_finished(self, code: int, status) -> None:
        self._emit_line(self._buf)
        self._buf = ""
        crashed = status == QProcess.CrashExit
        self.events.put(("train_done", -1 if crashed else code))

    def _on_error(self, err) -> None:
        if err == QProcess.FailedToStart:
            self.events.put(("train_log", "학습 프로세스를 시작하지 못했습니다."))
            self.events.put(("train_done", -1))
