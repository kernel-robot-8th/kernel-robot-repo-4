"""Training through omx_train/<policy>/train.sh (Docker, lerobot 0.6.1).

train.sh is the single training entry point, shared with the command line: the dashboard only picks
its environment variables and override arguments, starts it with DETACH=1 and follows the container
with `docker logs -f`. The container outlives the dashboard, so closing the app does not stop training
and the next start attaches to it again.
"""

import json
import math
import queue
import re
import shlex
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment

POLICIES = {"act": "ACT", "smolvla": "SmolVLA"}  # policy -> folder under omx_train
TRAIN_KIND = "success"  # only successful demos are imitation targets
CONTAINER_PREFIX = "omx-train-"  # train.sh names its container omx-train-$JOB_NAME
# Values the dashboard shows and passes back as overrides; defaults are read from train.sh.
PARAMS = ["steps", "batch_size", "save_freq", "log_freq", "num_workers"]
DOCKER_TIMEOUT_S = 10

_STEP_RE = re.compile(r"\bstep:(\d+(?:\.\d+)?)([KMBTQ]?)(?=\s)")
_EPOCH_RE = re.compile(r"\bepch:(\d+(?:\.\d+)?)")
_LOSS_RE = re.compile(r"\bloss:(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)")
_SUFFIX = {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12, "Q": 1e15}
# lerobot's tqdm bar redraws with \r many times a second; show it as a status line, not in the log.
# The metrics log line is written right after the bar without a newline, so split it off.
_TQDM_RE = re.compile(r"^(Training:[^\]]*\])\s*(.*)$")
_IMAGE_RE = re.compile(r'^IMAGE="\$\{IMAGE:-([^}]+)\}"', re.M)


# ---------------------------------------------------------------- paths and names
def policy_dir(omx_dir: Path, policy: str) -> Path:
    return Path(omx_dir) / POLICIES[policy]


def train_script(omx_dir: Path, policy: str) -> Path:
    return policy_dir(omx_dir, policy) / "train.sh"


def outputs_dir(omx_dir: Path, policy: str) -> Path:
    """train.sh's default OUT_DIR/train, where every run lands (dashboard and command line alike)."""
    return policy_dir(omx_dir, policy) / "outputs" / "train"


def image_name(omx_dir: Path, policy: str) -> str:
    """The IMAGE default written in train.sh, e.g. omx-act:0.6.1."""
    m = _IMAGE_RE.search(train_script(omx_dir, policy).read_text())
    return m.group(1) if m else f"omx-{policy}:0.6.1"


def dataset_root(task_dir: Path) -> Path:
    """Default training data: the session's success dataset."""
    return Path(task_dir) / TRAIN_KIND


def job_name(task: str, policy: str, now: float | None = None) -> str:
    # Docker container names allow [a-zA-Z0-9_.-] only.
    task = re.sub(r"[^A-Za-z0-9_.-]", "_", task).strip("_.-") or "task"
    return f"{task}_{policy}_{time.strftime('%Y%m%d_%H%M%S', time.localtime(now))}"


def container_name(job: str) -> str:
    return CONTAINER_PREFIX + job


def run_meta_path(omx_dir: Path, policy: str, job: str) -> Path:
    # Next to the run folder: lerobot refuses to start when output_dir already exists.
    return outputs_dir(omx_dir, policy) / f"{job}.run.json"


def resume_config(run: Path) -> Path:
    return Path(run) / "checkpoints" / "last" / "pretrained_model" / "train_config.json"


def list_runs(omx_dir: Path, policy: str) -> list[Path]:
    """Runs that left a resumable checkpoint, newest first."""
    root = outputs_dir(omx_dir, policy)
    if not root.is_dir():
        return []
    runs = [p for p in root.iterdir() if p.is_dir() and resume_config(p).exists()]
    return sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)


def read_meta(omx_dir: Path, policy: str, job: str) -> dict:
    try:
        return json.loads(run_meta_path(omx_dir, policy, job).read_text())
    except (OSError, ValueError):
        return {}


def find_job(omx_dir: Path, job: str) -> str | None:
    """Policy whose outputs hold this job (run folder or dashboard metadata)."""
    for policy in POLICIES:
        if run_meta_path(omx_dir, policy, job).exists() or (outputs_dir(omx_dir, policy) / job).exists():
            return policy
    return None


# ---------------------------------------------------------------- train.sh defaults
def script_defaults(train_sh: Path) -> dict[str, int]:
    """Values train.sh actually passes (uncommented `--name=value` lines) for PARAMS."""
    out = {}
    for line in Path(train_sh).read_text().splitlines():
        m = re.match(r"\s*--([a-z_]+)=(\d+)\b", line)
        if m and m.group(1) in PARAMS:
            out.setdefault(m.group(1), int(m.group(2)))
    return out


# ---------------------------------------------------------------- dataset
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


def last_override(args: list[str], name: str) -> str | None:
    """Value of the last --name=value in args (later arguments win in lerobot)."""
    val = None
    for a in args:
        if a.startswith(f"--{name}="):
            val = a.split("=", 1)[1]
    return val


# ---------------------------------------------------------------- commands
def overrides(params: dict, image_aug: bool, wandb: bool) -> list[str]:
    out = [f"--{k}={int(params[k])}" for k in PARAMS if k in params]
    if image_aug:
        out.append("--dataset.image_transforms.enable=true")
    out.append(f"--wandb.enable={'true' if wandb else 'false'}")
    return out


def build_train(
    omx_dir: Path,
    policy: str,
    gpu: int,
    data_root: Path,
    job: str,
    episodes: list[int] | None,
    args: list[str],
) -> tuple[list[str], dict[str, str]]:
    """(argv, env) that start train.sh in the background. episodes None = every episode."""
    data_root = Path(data_root)
    env = {
        "DATA_DIR": str(data_root.parent),
        "DATASET": data_root.name,
        "JOB_NAME": job,
        "EPISODES": f"[{','.join(map(str, episodes))}]" if episodes is not None else "",
        # SmolVLA's train.sh prunes checkpoints to a fixed list by default; keep every one here.
        "KEEP_STEPS": "",
        "DETACH": "1",
    }
    return ["bash", str(train_script(omx_dir, policy)), str(int(gpu)), *args], env


def build_resume(omx_dir: Path, policy: str, gpu: int, run: Path, args: list[str]) -> tuple[list[str], dict[str, str]]:
    """Resume from run/checkpoints/last; the dataset mount must match the original run."""
    run = Path(run)
    meta = read_meta(omx_dir, policy, run.name)
    env = {"JOB_NAME": run.name, "KEEP_STEPS": "", "RESUME": "1", "DETACH": "1"}
    if meta.get("dataset_root"):
        root = Path(meta["dataset_root"])
        env.update(DATA_DIR=str(root.parent), DATASET=root.name)
    else:
        # A command-line run: train.sh's DATA_DIR default, dataset folder from the saved config.
        try:
            env["DATASET"] = Path(json.loads(resume_config(run).read_text())["dataset"]["root"]).name
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return ["bash", str(train_script(omx_dir, policy)), str(int(gpu)), *args], env


def shell_line(argv: list[str], env: dict[str, str], cwd: Path | None = None) -> str:
    """The same call as one command-line string, for the log and the run metadata."""
    envs = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items() if k != "DETACH")
    script = argv[1]
    if cwd is not None:
        try:
            script = str(Path(script).relative_to(cwd))
        except ValueError:
            pass
    return " ".join(filter(None, [envs, script, *map(shlex.quote, argv[2:])]))


# ---------------------------------------------------------------- log parsing
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


def parse_started_at(text: str) -> float | None:
    """docker inspect StartedAt (RFC 3339, nanoseconds) -> epoch seconds."""
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)", text.strip())
    if not m or text.startswith("0001-"):
        return None
    return datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc).timestamp()


# ---------------------------------------------------------------- docker
def _docker(*args: str, timeout: float = DOCKER_TIMEOUT_S) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def docker_status(image: str) -> tuple[bool, bool, str]:
    """(docker usable, image present, message)."""
    if shutil.which("docker") is None:
        return False, False, "Docker가 설치되어 있지 않습니다 (README의 Docker 설치 참고)"
    try:
        info = _docker("info", "--format", "{{.ServerVersion}}")
    except subprocess.TimeoutExpired:
        return False, False, "Docker 데몬이 응답하지 않습니다"
    if info.returncode != 0:
        err = info.stderr.strip().splitlines()[-1] if info.stderr.strip() else ""
        if "permission denied" in err:
            return False, False, "Docker 권한이 없습니다 (docker 그룹 추가 후 다시 로그인)"
        return False, False, f"Docker를 쓸 수 없습니다: {err}"
    try:
        has_image = _docker("image", "inspect", image).returncode == 0
    except subprocess.TimeoutExpired:
        has_image = False
    if not has_image:
        return True, False, f"Docker {info.stdout.strip()} · 이미지 {image} 없음 (이미지 빌드 필요)"
    return True, True, f"Docker {info.stdout.strip()} · 이미지 {image}"


def train_containers() -> list[tuple[str, str]]:
    """(container name, state) of every omx-train-* container, running first."""
    if shutil.which("docker") is None:
        return []
    try:
        r = _docker("ps", "-a", "--filter", f"name=^{CONTAINER_PREFIX}", "--format", "{{.Names}}\t{{.State}}")
    except subprocess.TimeoutExpired:
        return []
    rows = [tuple(line.split("\t", 1)) for line in r.stdout.splitlines() if "\t" in line]
    return sorted(rows, key=lambda r: r[1] != "running")


def container_state(name: str) -> tuple[str, int, float | None] | None:
    """(status, exit code, started at) or None when the container does not exist."""
    try:
        r = _docker("inspect", "-f", "{{.State.Status}}\t{{.State.ExitCode}}\t{{.State.StartedAt}}", name)
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    status, code, started = r.stdout.strip().split("\t")
    return status, int(code), parse_started_at(started)


class Trainer:
    """Starts train.sh and follows its container; the container keeps running without the dashboard."""

    def __init__(self, omx_dir: Path):
        self.omx_dir = Path(omx_dir)
        self.events: queue.Queue = queue.Queue()
        self.proc: QProcess | None = None
        self.phase = ""  # "launch" (train.sh), "follow" (docker logs -f), "build" (docker build)
        self.job = ""
        self.policy = ""
        self.out_dir: Path | None = None
        self.started_at = 0.0
        self.stop_requested = False
        self._buf = ""

    @property
    def running(self) -> bool:
        """A training run is being launched or followed."""
        return self.phase in ("launch", "follow")

    @property
    def busy(self) -> bool:
        return bool(self.phase)

    # -------------------------------------------------------------- control
    def start(self, argv: list[str], env: dict[str, str], policy: str) -> None:
        if self.busy:
            return
        self._set_run(policy, env["JOB_NAME"])
        state = container_state(container_name(self.job))
        if state and state[0] != "running":
            _docker("rm", container_name(self.job))  # left over from an earlier run of the same job
        self.events.put(("train_log", "$ " + shell_line(argv, env, self.omx_dir)))
        self.started_at = time.time()
        self._run("launch", argv, env)

    def attach(self, container: str) -> bool:
        """Follow an existing omx-train-* container (running, or finished while the app was closed)."""
        if self.busy:
            return False
        job = container[len(CONTAINER_PREFIX):]
        policy = find_job(self.omx_dir, job)
        if policy is None:
            return False
        self._set_run(policy, job)
        state = container_state(container)
        self.started_at = (state[2] if state else None) or time.time()
        self.events.put(("train_log", f"실행 중인 학습에 다시 연결: {container}"))
        self._follow()
        return True

    def stop(self) -> None:
        if self.phase == "follow":
            self.events.put(("train_log", "학습 중지 요청 (docker stop)"))
            self.stop_requested = True
            # docker stop waits up to 10 s for lerobot to exit; the log follower ends with the container.
            QProcess.startDetached("docker", ["stop", container_name(self.job)])
        elif self.phase == "build" and self.proc is not None:
            self.proc.terminate()

    def detach(self) -> None:
        """Stop following (app closing); the container keeps training."""
        if self.proc is not None and self.proc.state() != QProcess.NotRunning:
            self.phase = ""
            self.proc.kill()
            self.proc.waitForFinished(3000)

    def build_image(self, policy: str) -> None:
        if self.busy:
            return
        d = policy_dir(self.omx_dir, policy)
        argv = ["docker", "build", "-t", image_name(self.omx_dir, policy), str(d)]
        self.events.put(("train_log", "$ " + " ".join(argv)))
        self._run("build", argv, {})

    def elapsed(self) -> float:
        return max(0.0, time.time() - self.started_at) if self.running else 0.0

    # -------------------------------------------------------------- internals
    def _set_run(self, policy: str, job: str) -> None:
        self.policy, self.job = policy, job
        self.out_dir = outputs_dir(self.omx_dir, policy) / job
        self.stop_requested = False

    def _run(self, phase: str, argv: list[str], env: dict[str, str]) -> None:
        self._buf = ""
        proc = QProcess()
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.setWorkingDirectory(str(self.omx_dir))
        penv = QProcessEnvironment.systemEnvironment()
        for k, v in env.items():
            penv.insert(k, v)
        proc.setProcessEnvironment(penv)
        proc.readyReadStandardOutput.connect(self._on_output)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self.proc = proc
        self.phase = phase
        proc.start(argv[0], argv[1:])

    def _follow(self) -> None:
        self._run("follow", ["docker", "logs", "-f", container_name(self.job)], {})

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
        phase, self.phase = self.phase, ""
        crashed = status == QProcess.CrashExit
        if phase == "build":
            self.events.put(("build_done", -1 if crashed else code))
        elif phase == "launch":
            if code == 0 and not crashed:
                self._follow()  # train.sh returned once the container started
            else:
                self.events.put(("train_done", -1 if crashed else code))
        elif phase == "follow":
            self._finish_container()
        # phase "" = detach(): the container keeps running, nothing to report

    def _finish_container(self) -> None:
        name = container_name(self.job)
        state = container_state(name)
        if state is None:
            self.events.put(("train_log", f"컨테이너 {name}를 찾을 수 없습니다"))
            self.events.put(("train_done", -1))
            return
        status, code, _ = state
        if status == "running":
            # The log stream broke while training goes on (e.g. docker daemon restart): follow again.
            self.events.put(("train_log", "로그 연결이 끊겨 다시 연결합니다"))
            self._follow()
            return
        _docker("rm", name)
        self.events.put(("train_done", code))

    def _on_error(self, err) -> None:
        if err == QProcess.FailedToStart:
            phase, self.phase = self.phase, ""
            self.events.put(("train_log", "프로세스를 시작하지 못했습니다 (bash/docker 확인)."))
            self.events.put(("build_done" if phase == "build" else "train_done", -1))
