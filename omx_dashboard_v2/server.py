#!/usr/bin/env python3
"""OMX 추론 대시보드 서버 (표준 라이브러리만 사용).

실행:  python ~/il_ws/omx_act_1027/dashboard/server.py
접속:  http://127.0.0.1:8765  (자동으로 브라우저가 열림)

- 모델 폴더(config.json이 있는 폴더)를 스캔해서 태스크 / 모델 / 학습 스텝으로 묶음
  ~/il_ws/models (직접 학습) + ~/il_ws/<번들>/models (inference.sh 가 있는 HF 번들, 예: omx_act_1029_r50)
- 모델 버튼을 켜면 그 번들의 inference.sh 를 MODEL=<폴더> 로 실행, 끄면 Ctrl+C(SIGINT)로 정상 종료
- 추론 파라미터(PARAMS)는 inference.sh 뒤에 붙는 인자로 넘겨서 기본값을 덮어씀
- 한 번에 하나만 실행 (로봇이 하나라서)

환경변수로 바꿀 수 있는 값:
  OMX_MODEL_DIRS   모델 폴더 목록(:로 구분). 기본은 위 자동 탐색
  OMX_IL_WS        자동 탐색 위치. 기본 ~/il_ws
  OMX_INFER_SH     직접 학습한 모델에 쓸 실행 스크립트. 기본 이 폴더의 상위 inference.sh
  OMX_VENV         가상환경. 기본 ~/venv/il
  OMX_DASH_PORT    웹 포트. 기본 8765
"""

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
HOME = Path.home()

IL_WS = Path(os.environ.get("OMX_IL_WS", HOME / "il_ws")).expanduser()
INFER_SH = Path(os.environ.get("OMX_INFER_SH", HERE.parent / "inference.sh")).expanduser()
DATASETS_DIR = Path(os.environ.get("OMX_DATASETS", IL_WS / "datasets")).expanduser()  # 녹화한 데이터셋 저장 위치
REC_SCRIPT = Path(os.environ.get("OMX_REC_SCRIPT", HERE / "record_ctl.py")).expanduser()
CHAIN_SCRIPT = Path(os.environ.get("OMX_CHAIN_SCRIPT", HERE / "omx_chain.py")).expanduser()
VENV = Path(os.environ.get("OMX_VENV", HOME / "venv" / "il")).expanduser()
PORT = int(os.environ.get("OMX_DASH_PORT", "8765"))

# 태스크 이름 표시용. 없는 태스크는 폴더 이름을 그대로 씀
TASK_LABELS = {
    "vertical": "Vertical",
    "task_success": "Task success",
    "omx_act_1027": "상자 → 흰 바구니 (1027)",
    "omx_act_1029_r50": "상자 → 흰 바구니 · R50 (1029)",
    "omx_shoebox_act": "신발 → 상자 (shoebox)",
}

POLICY_LABELS = {"act": "ACT", "smolvla": "SmolVLA", "diffusion": "Diffusion", "pi0": "π0", "pi05": "π0.5"}
STEP_RE = re.compile(r"^(?P<fam>.+?)_(?P<n>\d+)(?P<unit>k|step)$")
DEV_RE = re.compile(r"^(/dev/[\w./-]+|\d+)$")


def model_dirs() -> list:
    """~/il_ws/models (직접 학습) + ~/il_ws/<번들>/models (옆에 inference.sh 가 있는 HF 번들) 자동 탐색."""
    if os.environ.get("OMX_MODEL_DIRS"):
        return [Path(p).expanduser() for p in os.environ["OMX_MODEL_DIRS"].split(":") if p]
    dirs = [IL_WS / "models"]
    dirs += sorted(p for p in IL_WS.glob("*/models") if (p.parent / "inference.sh").is_file())
    return dirs


# ---------------------------------------------------------------- 모델 스캔
def bundle_descriptions(bundle_dir: Path) -> dict:
    """번들 infer.sh 의 MODELS=( "폴더|설명" ... ) 에서 설명을 읽음 (없으면 빈 dict)."""
    try:
        text = (bundle_dir / "infer.sh").read_text(encoding="utf-8")
    except OSError:
        return {}
    descs = dict(re.findall(r'^\s*"([^"|]+)\|([^"]*)"\s*$', text, flags=re.M))
    # omx_shoebox_act 형식: add <변형> <마지막 스텝> "<설명>" → 폴더 act_..._<변형>_<n>step 에 같은 설명
    variants = re.findall(r'^\s*add\s+(\S+)\s+\d+\s+["\']([^"\']*)["\']', text, flags=re.M)
    folders = sorted(p.name for p in (bundle_dir / "models").glob("*") if p.is_dir())
    for v, desc in variants:  # infer.sh 에 적힌 변형 순서대로 (화면 정렬에 쓰임)
        pat = re.compile(rf"_{re.escape(v)}_\d+(k|step)$")
        for name in folders:
            if pat.search(name):
                descs.setdefault(name, desc)
    return descs


def bundle_infer_default(bundle_dir: Path, flag: str):
    """번들 infer.sh 가 넘기는 --<flag>=값 (예: dataset.single_task). 없으면 None."""
    try:
        text = (bundle_dir / "infer.sh").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(rf'--{re.escape(flag)}=(?:"([^"]*)"|\'([^\']*)\'|(\S+))', text)
    return next((g for g in m.groups() if g is not None), None) if m else None


def read_config(path: Path) -> dict:
    try:
        cfg = json.loads((path / "config.json").read_text())
    except (OSError, ValueError):
        return {}
    state = cfg.get("input_features", {}).get("observation.state", {}).get("shape", [None])
    cams = [k.split(".")[-1] for k in cfg.get("input_features", {}) if k.startswith("observation.images.")]
    return {
        "type": cfg.get("type", "?"),
        "chunk": cfg.get("chunk_size"),
        "state_dim": state[0] if state else None,
        "cameras": cams,
        "backbone": cfg.get("vision_backbone"),
        "depth": (path / "depth_info.json").is_file(),
    }


def auto_desc(info: dict) -> str:
    parts = []
    bb = info.get("backbone") or ""
    if bb:
        parts.append(bb.replace("resnet", "ResNet"))
    parts.append("MoGe-2 깊이 입력 (top)" if info.get("depth") else f"카메라 {len(info.get('cameras') or [])}대")
    return " · ".join(parts)


def scan_models() -> list:
    """[{id, label, families:[{id, label, desc, checkpoints:[{key, steps, label, bundle, depth_info, info}]}]}]"""
    tasks: dict = {}
    order: dict = {}
    for root in model_dirs():
        if not root.is_dir():
            continue
        # 번들 폴더(…/omx_act_1027/models 처럼 옆에 inference.sh가 있는 곳)는 폴더 이름을 태스크로 씀
        bundle_dir = root.parent if (root.parent / "inference.sh").is_file() else None
        bundle = bundle_dir.name if bundle_dir else None
        descs = bundle_descriptions(bundle_dir) if bundle_dir else {}
        for i, name in enumerate(descs):
            order.setdefault(name, i)
        for d in sorted(root.iterdir()):
            if not (d / "config.json").is_file():
                continue
            m = STEP_RE.match(d.name)
            if m:
                fam = m["fam"]
                steps = int(m["n"]) * (1000 if m["unit"] == "k" else 1)
            else:
                fam, steps = d.name, None

            if bundle:  # 다른 사람 번들: 태스크 하나에 변형 모델들
                task_id = bundle
                fam_label = re.sub(r"^act_(\d+|shoebox)_", "", fam)
            else:  # 직접 학습한 모델: <정책>_<태스크>_<스텝>k (act_vertical_20k, smolvla_vertical_20k …)
                task_id = re.sub(r"^(act|smolvla|diffusion|pi0|pi05)_", "", fam)

            info = read_config(d)
            if not bundle:
                fam_label = POLICY_LABELS.get(info.get("type"), info.get("type") or "?")
            task = tasks.setdefault(
                task_id,
                {"id": task_id, "label": TASK_LABELS.get(task_id, task_id), "families": {}},
            )
            family = task["families"].setdefault(
                fam,
                {
                    "id": f"{task_id}/{fam}",
                    "label": fam_label,
                    "desc": descs.get(d.name, "") or (auto_desc(info) if bundle else f"직접 학습한 {fam_label} 모델"),
                    "checkpoints": [],
                },
            )
            if descs.get(d.name) and family["desc"] == auto_desc(info):
                family["desc"] = descs[d.name]
            family["checkpoints"].append(
                {
                    "key": str(d),
                    "name": d.name,
                    "steps": steps,
                    "label": step_label(steps),
                    "bundle": str(bundle_dir) if bundle_dir else None,
                    "depth_info": str(d / "depth_info.json") if info.get("depth") else None,
                    "info": info,
                }
            )

    out = []  # 번들은 infer.sh(README) 순서대로
    for task in tasks.values():
        fams = []
        for fam in task["families"].values():
            fam["checkpoints"].sort(key=lambda c: (c["steps"] is None, c["steps"] or 0))
            fams.append(fam)
        fams.sort(key=lambda f: order.get(f["checkpoints"][0]["name"], len(order)))
        task["families"] = fams
        bundle = fams[0]["checkpoints"][0]["bundle"] if fams else None
        pose_file = Path(bundle) / "init_pose.json" if bundle else None
        task["init_pose_file"] = str(pose_file) if pose_file and pose_file.is_file() else None
        try:
            task["init_pose"] = json.loads(pose_file.read_text())["pose"] if task["init_pose_file"] else None
        except (OSError, ValueError, KeyError):
            task["init_pose"], task["init_pose_file"] = None, None
        task["success"] = success_info(bundle)
        out.append(task)
    return out


def success_info(bundle):
    """<번들>/success.json 요약 (연속 실행 화면 표시용). 없으면 None."""
    if not bundle:
        return None
    try:
        import success_judge

        cfg = success_judge.load_config(bundle)
    except Exception as e:  # noqa: BLE001  설정 파일이 깨져 있어도 목록은 보여야 함
        return {"desc": f"success.json 을 못 읽음: {e}", "model": "", "model_ok": False, "error": True}
    if cfg is None:
        return None
    return {"desc": success_judge.describe(cfg), "model": cfg["model"],
            "model_ok": bool(cfg["model"]) and Path(cfg["model"]).is_file(), "error": False}


def step_label(steps):
    if steps is None:
        return "-"
    if steps >= 1000 and steps % 1000 == 0:
        return f"{steps // 1000}k"
    if steps >= 1000:
        return f"{steps / 1000:.1f}k"
    return str(steps)


def all_checkpoints() -> dict:
    return {
        c["key"]: c
        for t in scan_models()
        for f in t["families"]
        for c in f["checkpoints"]
    }


# ---------------------------------------------------------------- 실행 관리
BUSY_CHECK = None  # app.py 가 넣어줌: 녹화 탭(팀 수집 대시보드)이 로봇을 잡고 있으면 True

REC_PATTERNS = [
    (re.compile(r"Recording episode (\d+)"), "rec"),
    (re.compile(r"Reset the environment"), "reset"),
    (re.compile(r"Re-record episode"), "rerecord"),
    (re.compile(r"Stop recording"), "finishing"),
    (re.compile(r"^\[저장 완료\]"), "saved"),
    (re.compile(r"^\[버림\]"), "discarded"),
]


class Runner:
    """추론(lerobot-record + policy)과 녹화(lerobot-record + 리더암) 중 한 번에 하나만 실행."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.kind = None  # "infer" | "record"
        self.ckpt = None
        self.rec = None
        self.chain = None  # 연속 실행: [{name, seconds}, ...]
        self.prep = None  # 초기 자세 준비: {task, label, used}
        self.auto = False  # 연속 실행 자동 넘김 (실행 중인 프로세스에 보낸 마지막 값)
        self.phases = []  # 연속 실행 구간: [{kind: init|stage|wait, stage, t0, t1}]
        self.started = None
        self.ended = None
        self.exit_code = None
        self.stopping = False
        self.log = deque(maxlen=3000)
        self.run_id = 0
        self.partial = ""

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _launch(self, kind, args, env_extra, notes, cwd, stdin_pipe=False):
        if self.running():
            raise RuntimeError("이미 실행 중인 작업이 있어 (추론 또는 녹화). 먼저 끄고 다시 눌러줘.")
        if BUSY_CHECK is not None and BUSY_CHECK():
            raise RuntimeError("녹화 탭에서 로봇을 쓰고 있어 (BringUp 상태). 녹화 탭에서 Servo OFF 하고 다시 눌러줘.")
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)  # ROS 경로가 섞이지 않게
        env.update(env_extra)
        env["PYTHONUNBUFFERED"] = "1"
        if (VENV / "bin").is_dir():
            env["VIRTUAL_ENV"] = str(VENV)
            env["PATH"] = f"{VENV / 'bin'}:{env.get('PATH', '')}"
        self.log.clear()
        self.phases = []
        self.partial = ""
        self.log.extend(notes)
        self.log.append("$ " + " ".join([*(f"{k}={shlex.quote(v)}" for k, v in env_extra.items()), shlex.join(args)]))
        self.proc = subprocess.Popen(
            args,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE if stdin_pipe else subprocess.DEVNULL,
            start_new_session=True,
            # 대시보드를 백그라운드로 띄웠을 때 SIGINT가 '무시'로 물려받아지면 정지 버튼이 안 먹으므로 기본값으로 되돌림
            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
        )
        self.kind = kind
        self.started = time.time()
        self.run_id += 1
        self.ended = None
        self.exit_code = None
        self.stopping = False
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()

    def start(self, ckpt: dict, params: dict):
        with self.lock:
            infer_sh, args, env_extra, notes = build_command(ckpt, params)
            self._launch("infer", args, env_extra, notes, infer_sh.parent)
            self.ckpt = ckpt
            self.rec = None
            self.chain = None
            self.prep = None

    def start_prepare(self, task: dict, params: dict):
        """선택한 태스크의 초기 자세로 이동해서 토크 유지한 채 대기 (모델은 실행 버튼을 누를 때 보냄)."""
        with self.lock:
            pose = task.get("init_pose_file")
            if not pose:
                raise ValueError(f"{task['label']}: 초기 자세 파일(init_pose.json)이 없어.")
            a, env = chain_base(params)
            notes = [f"[알림] 초기 자세 준비: {task['label']} 시작 자세로 천천히 이동한 뒤 토크를 유지한 채 대기. "
                     "03 모델 실행이나 04 연속 실행을 누르면 이 연결 그대로 이어서 실행해 (실행 설정은 지금 값 기준, "
                     "실행 시간만 누를 때 값). 정지를 누르면 토크가 꺼져 팔이 내려앉을 수 있어."]
            self.prep = {"task": task["id"], "label": task["label"], "used": False}
            self.chain = None
            try:
                self._launch("infer", [*a, "--prepare", pose], env, notes, HERE, stdin_pipe=True)
            except Exception:
                self.prep = None
                raise
            self.ckpt = {"key": "prep", "name": f"초기 자세 준비: {task['label']}"}
            self.rec = None

    def prep_ready(self) -> bool:
        return bool(self.running() and self.prep and not self.prep["used"]
                    and any(l.startswith("[준비 완료]") for l in self.log))

    def run_prepared(self, stages: list, single: bool, auto: bool = False):
        """준비해 둔 프로세스에 실행할 모델을 보냄 (연결·토크 유지)."""
        with self.lock:
            if not self.prep_ready():
                raise RuntimeError("초기 자세 준비가 끝나지 않았어. 잠깐 기다렸다가 다시 눌러줘.")
            for st in stages:
                check_chain_model(st["ckpt"])
            msg = "run " + json.dumps({"stages": [[st["ckpt"]["key"], st["seconds"]] for st in stages], "auto": bool(auto)})
            self.log.extend(success_notes(stages))
            self.auto = bool(auto)
            try:
                self.proc.stdin.write(msg.encode() + b"\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                raise RuntimeError("실행 프로세스에 명령을 못 보냈어.")
            self.prep["used"] = True
            self.chain = [{"name": st["ckpt"]["name"], "seconds": st["seconds"]} for st in stages]
            names = " → ".join(st["ckpt"]["name"] for st in stages)
            self.ckpt = stages[0]["ckpt"] if single else {"key": "chain", "name": f"연속 실행: {names}"}
            self.log.append(f"[버튼] 실행: {names}")

    def set_auto(self, on: bool):
        """자동 넘김 켜기/끄기. 연속 실행·초기 자세 대기 중이면 실행 중인 프로세스에 바로 반영."""
        with self.lock:
            self.auto = bool(on)
            if self.running() and (self.chain or self.prep):
                try:
                    self.proc.stdin.write(f"auto {'on' if on else 'off'}\n".encode())
                    self.proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    raise RuntimeError("실행 프로세스에 명령을 못 보냈어.")

    def start_chain(self, stages: list, params: dict, auto: bool = False):
        with self.lock:
            args, env_extra, notes = build_chain_command(stages, params)
            if auto:
                args.append("--auto")
            self.auto = bool(auto)
            self._launch("infer", args, env_extra, notes, HERE, stdin_pipe=True)
            names = " → ".join(st["ckpt"]["name"] for st in stages)
            self.ckpt = {"key": "chain", "name": f"연속 실행: {names}"}
            self.rec = None
            self.prep = None
            self.chain = [{"name": st["ckpt"]["name"], "seconds": st["seconds"]} for st in stages]

    def next_stage(self):
        """연속 실행: 실행 중이면 지금 단계를 끝내고 대기, 대기 중이면 다음 단계 시작."""
        with self.lock:
            if not self.running() or not self.chain:
                raise RuntimeError("연속 실행이 돌고 있지 않아.")
            try:
                self.proc.stdin.write(b"next\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                raise RuntimeError("실행 프로세스에 명령을 못 보냈어.")
            self.log.append("[버튼] 다음 요청")

    def start_record(self, site: dict, params: dict):
        with self.lock:
            args, notes, info = build_record_command(site, params)
            self._launch("record", args, {}, notes, HERE, stdin_pipe=True)
            self.ckpt = None
            self.chain = None
            self.prep = None
            self.rec = {
                **info,
                "phase": "starting",  # starting → rec ↔ reset → finishing → done
                "phase_t0": time.time(),
                "episode": None,  # 데이터셋 기준 에피소드 번호 (0부터)
                "saved": 0,
                "discarded": 0,
                "last_cmd": None,
            }

    def send(self, cmd: str):
        """녹화 중 버튼 명령 (next / rerecord / stop / discard_stop)."""
        with self.lock:
            if not self.running() or self.kind != "record":
                raise RuntimeError("녹화가 돌고 있지 않아.")
            if cmd not in ("next", "rerecord", "stop", "discard_stop"):
                raise ValueError(f"모르는 명령: {cmd}")
            try:
                self.proc.stdin.write(f"{cmd}\n".encode())
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                raise RuntimeError("녹화 프로세스에 명령을 못 보냈어.")
            self.rec["last_cmd"] = cmd
            if cmd in ("stop", "discard_stop"):
                self.stopping = True

    def _phase(self, line: str):
        """연속 실행 로그에서 구간(초기 자세 이동 / 단계 / 대기) 시작 시각을 기록 (런타임 표시용)."""
        if not self.chain and not self.prep:
            return
        now = time.time()
        m = re.match(r"\[단계 (\d+)/\d+\]", line)
        if m:
            new = ("stage", int(m[1]))
        elif line.startswith("[초기 자세] 준비 로 이동"):
            new = ("prep", 0)
        elif line.startswith("[준비 완료]"):
            new = ("ready", 0)
        elif self.prep and line.startswith("모델 ") and "불러오는 중" in line:
            new = ("load", 0)
        elif line.startswith("[초기 자세]") and "이동 (" in line:
            new = ("init", sum(p["kind"] == "stage" for p in self.phases) + 1)
        elif line.startswith("[대기]"):
            new = ("wait", sum(p["kind"] == "stage" for p in self.phases))
        elif line.startswith(("[완료]", "[정지]")):
            new = None
        else:
            return
        if self.phases and self.phases[-1]["t1"] is None:
            self.phases[-1]["t1"] = now
        if new:
            self.phases.append({"kind": new[0], "stage": new[1], "t0": now, "t1": None})

    def _phases_out(self, run: bool):
        end = time.time() if run else (self.ended or time.time())
        return [{"kind": p["kind"], "stage": p["stage"], "done": p["t1"] is not None or not run,
                 "elapsed": round((p["t1"] or end) - p["t0"], 1)} for p in self.phases]

    def _track(self, line: str):
        self._phase(line)
        if self.kind != "record" or not self.rec:
            return
        for rx, what in REC_PATTERNS:
            m = rx.search(line)
            if not m:
                continue
            r = self.rec
            if what == "rec":
                r["episode"] = int(m.group(1))
                r["phase"], r["phase_t0"] = "rec", time.time()
            elif what == "reset":
                r["phase"], r["phase_t0"] = "reset", time.time()
            elif what == "rerecord":
                r["phase_t0"] = time.time()
            elif what == "finishing":
                r["phase"], r["phase_t0"] = "finishing", time.time()
            elif what == "saved":
                r["saved"] += 1
            elif what == "discarded":
                r["discarded"] += 1
            return

    def _pump(self, proc):
        fd = proc.stdout.fileno()
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            text = self.partial + chunk.decode("utf-8", "replace")
            parts = re.split(r"\r\n|\n|\r", text)
            self.partial = parts.pop()
            for line in parts:
                if line.strip():
                    self.log.append(line)
                    self._track(line)
        if self.partial.strip():
            self.log.append(self.partial)
            self._track(self.partial)
        self.partial = ""
        code = proc.wait()
        with self.lock:
            if proc is self.proc:
                self.exit_code = code
                self.ended = time.time()
                if self.rec:
                    self.rec["phase"] = "done"
                self.log.append(f"[종료] exit code {code}")

    def stop(self):
        with self.lock:
            if not self.running():
                return False
            proc = self.proc
            self.stopping = True
            self.log.append("[정지 요청] Ctrl+C 전송 — 로봇 연결을 정리하는 중…")
        try:
            os.killpg(proc.pid, signal.SIGINT)
        except ProcessLookupError:
            return True

        def escalate():
            # 녹화는 끝날 때 영상 인코딩·저장이 길 수 있어서 더 기다림
            waits = ((signal.SIGTERM, 60), (signal.SIGKILL, 10)) if self.kind == "record" else ((signal.SIGTERM, 10), (signal.SIGKILL, 5))
            for sig, wait in waits:
                try:
                    proc.wait(timeout=wait)
                    return
                except subprocess.TimeoutExpired:
                    self.log.append(f"[정지] 응답이 없어 {sig.name} 전송")
                    try:
                        os.killpg(proc.pid, sig)
                    except ProcessLookupError:
                        return

        threading.Thread(target=escalate, daemon=True).start()
        return True

    def full_log(self) -> str:
        """클립보드 복사용 전체 로그 (한 번 실행분)."""
        with self.lock:
            lines = list(self.log) + ([self.partial] if self.partial.strip() else [])
            if self.kind == "record" and self.rec:
                head = (f"[OMX 녹화 로그] {self.rec['dataset']} · 저장 {self.rec['saved']}개 · "
                        f"버림 {self.rec['discarded']}개 · exit code {self.exit_code}")
            else:
                name = self.ckpt["name"] if self.ckpt else "-"
                head = f"[OMX 추론 로그] {name} · exit code {self.exit_code}"
        return head + "\n" + "\n".join(lines)

    def _chain_current(self):
        for line in reversed(self.log):
            m = re.match(r"\[단계 (\d+)/\d+\]", line)
            if m:
                return int(m[1])
        return None

    def _success(self):
        """지금(또는 방금 끝난) 단계의 성공 판단 상태 — omx_chain.py 의 '[성공 판단]' 로그에서 읽음."""
        if not self.chain:
            return None
        found = None
        for line in reversed(self.log):
            if line.startswith("[단계 "):
                break
            if found is None and line.startswith("[성공 판단]"):
                found = line
        else:
            return None  # 아직 단계가 시작 안 됨
        if found is None:
            return None
        text = found[len("[성공 판단]"):].strip()
        out = {"state": "arming", "text": text, "progress": None, "need": None}
        m = re.search(r"진행 ([\d.]+)/([\d.]+)s", text)
        if m:
            out.update(state="counting", progress=float(m[1]), need=float(m[2]))
        if text.startswith("성공 —"):
            out["state"] = "success"
        elif text.startswith("성공 안 남"):
            out["state"] = "fail"
        elif text.startswith("버튼으로"):
            out["state"] = "stopped"
        elif text.startswith("검출 오류"):
            out["state"] = "error"
        elif "판단 시작" in text or "다시 셈" in text:
            out["state"] = "armed"
        elif "셈 시작" in text:
            out.update(state="counting", progress=0.0)
        return out

    def _chain_waiting(self):
        for line in reversed(self.log):
            if line.startswith("[대기]"):
                return True
            if line.startswith(("[단계 ", "[초기 자세]", "[자동 넘김] 다음")):
                return False
        return False

    def status(self) -> dict:
        with self.lock:
            run = self.running()
            elapsed = None
            if self.started:
                end = self.ended if (not run and self.ended) else time.time()
                elapsed = round(end - self.started, 1)
            rec = None
            if self.rec:
                rec = {k: v for k, v in self.rec.items() if k != "phase_t0"}
                rec["phase_elapsed"] = round(time.time() - self.rec["phase_t0"], 1) if run else None
            return {
                "running": run,
                "kind": self.kind,
                "stopping": run and self.stopping,
                "ckpt_key": self.ckpt["key"] if self.ckpt else None,
                "ckpt_name": self.ckpt["name"] if self.ckpt else None,
                "rec": rec,
                "chain": {"stages": self.chain, "current": self._chain_current(), "waiting": self._chain_waiting(), "phases": self._phases_out(run)} if self.chain else None,
                "success": self._success(),
                "prep": {**self.prep, "ready": self.prep_ready()} if self.prep else None,
                "auto": self.auto,
                "phases": self._phases_out(run),
                "elapsed": elapsed,
                "exit_code": self.exit_code,
                "run_id": self.run_id,
                "log": list(self.log)[-250:] + ([self.partial] if self.partial.strip() else []),
            }


RUNNER = Runner()

TORQUE_OFF_CODE = r"""
import sys, dynamixel_sdk as dxl
port = dxl.PortHandler(sys.argv[1]); ph = dxl.PacketHandler(2.0)
if not port.openPort() or not port.setBaudRate(1000000):
    sys.exit("포트를 열 수 없음: " + sys.argv[1])
for i in range(11, 17):
    res, err = ph.write1ByteTxRx(port, i, 64, 0)
    print(f"ID {i}: " + ("OK" if res == dxl.COMM_SUCCESS and err == 0 else ph.getTxRxResult(res)))
port.closePort()
"""


def torque_off(port: str) -> str:
    if RUNNER.running():
        raise RuntimeError("추론이 돌고 있을 때는 포트가 겹쳐서 못 해. 먼저 정지해줘.")
    py = VENV / "bin" / "python"
    exe = str(py) if py.is_file() else sys.executable
    out = subprocess.run([exe, "-c", TORQUE_OFF_CODE, port], capture_output=True, text=True, timeout=15)
    return (out.stdout + out.stderr).strip() or f"exit code {out.returncode}"


# ---------------------------------------------------------------- 추론 파라미터
# inference.sh(Sungah/omx_act_1027, omx_act_1029_r50)에서 바꿀 수 있는 값들.
# 화면은 이 목록으로 자동으로 그려지고, 값은 inference.sh 뒤에 붙는 인자/환경변수로 넘어가서 기본값을 덮어씀.
ID_RE = re.compile(r"^[\w.-]{1,64}$")
# NVIDIA GPU가 있는 PC(nvidia-smi 있음)면 기본 연산 장치를 GPU로. 화면에서 바꾼 값은 그 PC에 따로 저장됨
DEFAULT_DEVICE = "cuda" if shutil.which("nvidia-smi") else "cpu"
PARAMS = [
    # ---- 현장 설정
    {"group": "현장 설정", "key": "port", "label": "팔로워 포트", "type": "dev", "default": "/dev/ttyACM0"},
    {"group": "현장 설정", "key": "top", "label": "top 카메라", "type": "dev", "default": "/dev/video6"},
    {"group": "현장 설정", "key": "wrist", "label": "wrist 카메라", "type": "dev", "default": "/dev/video4"},
    {"group": "현장 설정", "key": "mjpg", "label": "카메라 MJPG", "type": "bool", "default": True,
     "help": "카메라 두 대를 같은 허브에 꽂으면 끊기는 문제 방지"},
    {"group": "현장 설정", "key": "robot_id", "label": "캘리브레이션 이름", "type": "id", "default": "omx_follower",
     "help": "--robot.id"},
    # ---- 정책
    {"group": "정책", "key": "device", "label": "연산 장치", "type": "select", "default": DEFAULT_DEVICE,
     "options": [["cpu", "CPU"], ["cuda", "GPU (cuda)"]],
     "help": "기본값: NVIDIA GPU가 있으면 GPU, 없으면 CPU"},
    {"group": "정책", "key": "ensemble", "label": "동작 섞기 방식", "type": "select", "default": "off",
     "options": [["off", "끔 (chunk 단위)"], ["builtin", "lerobot 내장"], ["kstep", "k스텝 앙상블"]],
     "help": "ACT 전용 — SmolVLA 등 다른 모델은 자동으로 '끔'. 끔: 한 번 예측하고 n스텝 실행 · 내장: 매 스텝 예측 후 가중 평균 · k스텝: k스텝마다 예측해 겹치는 예측 평균"},
    {"group": "정책", "key": "n_action_steps", "label": "n_action_steps", "type": "int", "default": 50,
     "min": 1, "max": 100, "show_if": ["ensemble", ["off"]],
     "help": "한 번 예측 후 실행할 스텝 수. CPU 50 권장, GPU면 10까지. 모델 chunk보다 크면 chunk로 맞춤"},
    {"group": "정책", "key": "te_coeff", "label": "앙상블 계수", "type": "float", "default": 0.01,
     "min": -1, "max": 1, "step": 0.001, "show_if": ["ensemble", ["builtin"]],
     "help": "--policy.temporal_ensemble_coeff (n_action_steps는 자동으로 1)"},
    {"group": "정책", "key": "ens_k", "label": "k (재예측 간격)", "type": "int", "default": 5,
     "min": 1, "max": 100, "show_if": ["ensemble", ["kstep"]], "help": "ACT_ENSEMBLE_K · 1 = 매 스텝 예측"},
    {"group": "정책", "key": "ens_m", "label": "m (가중치 계수)", "type": "float", "default": 0.01,
     "min": -1, "max": 1, "step": 0.001, "show_if": ["ensemble", ["kstep"]],
     "help": "ACT_ENSEMBLE_M · exp(-m·i), 음수면 새 예측에 무게"},
    {"group": "정책", "key": "use_amp", "label": "혼합 정밀도 (AMP)", "type": "bool", "default": False,
     "show_if": ["device", ["cuda"]], "help": "--policy.use_amp (GPU일 때만)"},
    # ---- 로봇
    {"group": "로봇", "key": "max_relative_target", "label": "한 스텝 최대 이동량", "type": "float", "default": 10,
     "min": 1, "max": 50, "step": 0.5, "help": "안전장치. 관절 1 ≈ 1.8°. 작을수록 천천히"},
    {"group": "로봇", "key": "depth_device", "label": "깊이 모델 장치", "type": "select", "default": DEFAULT_DEVICE,
     "options": [["cpu", "CPU"], ["cuda", "GPU (cuda)"]], "help": "MoGe-2 깊이 모델에만 적용 (CPU는 매우 느림)"},
    # ---- 실행 · 기록
    {"group": "실행 · 기록", "key": "episode_time", "label": "실행 시간 (초)", "type": "int", "default": 30,
     "min": 5, "max": 600},
    {"group": "실행 · 기록", "key": "num_episodes", "label": "반복 횟수", "type": "int", "default": 1, "min": 1, "max": 50},
    {"group": "실행 · 기록", "key": "reset_time", "label": "에피소드 사이 정리 (초)", "type": "int", "default": 10,
     "min": 0, "max": 120, "show_if": ["num_episodes", "gt1"]},
    {"group": "실행 · 기록", "key": "task", "label": "작업 문장", "type": "text", "default": "",
     "placeholder": "비우면 스크립트 기본 문장 (ACT는 안 씀)"},
    {"group": "실행 · 기록", "key": "display_data", "label": "rerun 화면 표시", "type": "bool", "default": False},
    {"group": "실행 · 기록", "key": "vcodec", "label": "영상 코덱", "type": "select", "default": "libsvtav1",
     "options": [["libsvtav1", "AV1"], ["h264", "H.264"], ["hevc", "HEVC"], ["auto", "auto"]],
     "help": "저장이 느리면 H.264"},
    {"group": "실행 · 기록", "key": "streaming_encoding", "label": "녹화하면서 인코딩", "type": "bool", "default": False,
     "help": "끝난 뒤 저장이 빨라짐"},
    # ---- 리더암
    {"group": "리더암 리셋", "key": "teleop", "label": "리더암으로 리셋", "type": "bool", "default": False,
     "help": "에피소드 사이 정리 시간에 리더암으로 팔로워 자세를 되돌림"},
    {"group": "리더암 리셋", "key": "teleop_port", "label": "리더 포트", "type": "dev", "default": "/dev/ttyACM1",
     "show_if": ["teleop", [True]]},
    {"group": "리더암 리셋", "key": "teleop_id", "label": "리더 캘리브레이션 이름", "type": "id", "default": "omx_leader",
     "show_if": ["teleop", [True]]},
]
PARAM_BY_KEY = {p["key"]: p for p in PARAMS}


def clean_params(body: dict, schema: list = None) -> dict:
    """화면에서 온 값을 검사해서 정리. 빠진 값은 기본값."""
    out = {}
    for p in schema or PARAMS:
        k, t = p["key"], p["type"]
        v = body.get(k, p["default"])
        if t in ("dev", "id", "idopt", "text"):
            v = str(v).strip()
            if t == "idopt" and v and not ID_RE.match(v):
                raise ValueError(f"{p['label']} 값이 이상해: {v!r} (영문·숫자·_.-)")
            if t == "dev" and not DEV_RE.match(v):
                raise ValueError(f"{p['label']} 값이 이상해: {v!r} (/dev/... 형식)")
            if t == "id" and not ID_RE.match(v):
                raise ValueError(f"{p['label']} 값이 이상해: {v!r} (영문·숫자·_.-)")
            if t == "text" and len(v) > 200:
                raise ValueError(f"{p['label']}이 너무 길어")
        elif t == "bool":
            v = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "on", "yes")
        elif t in ("int", "float"):
            try:
                v = int(v) if t == "int" else float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{p['label']}은 숫자여야 해")
            if not p["min"] <= v <= p["max"]:
                raise ValueError(f"{p['label']}은 {p['min']}~{p['max']} 사이로 해줘")
        elif t == "select":
            if v not in [o[0] for o in p["options"]]:
                raise ValueError(f"{p['label']} 값이 이상해: {v!r}")
        out[k] = v
    return out


def build_command(ckpt: dict, p: dict):
    """(실행할 inference.sh, argv, 추가 환경변수, 알림) — 뒤에 붙인 인자가 inference.sh 기본값을 덮어씀."""
    bundle = Path(ckpt["bundle"]) if ckpt.get("bundle") else None
    infer_sh = bundle / "inference.sh" if bundle else INFER_SH
    if not infer_sh.is_file():
        raise RuntimeError(f"실행 스크립트가 없음: {infer_sh}")
    chunk = ckpt["info"].get("chunk") or 100
    ptype = ckpt["info"].get("type") or "act"
    notes = []
    b = lambda x: "true" if x else "false"  # noqa: E731
    if ptype != "act" and p["ensemble"] != "off":  # 내장/k스텝 앙상블은 ACT 전용
        notes.append(f"[알림] {ptype} 모델이라 ACT 전용 '동작 섞기'는 끄고 n_action_steps={min(p['n_action_steps'], chunk)}로 실행")
        p = {**p, "ensemble": "off"}
    if ptype == "smolvla" and not p["task"]:
        notes.append("[알림] SmolVLA는 작업 문장을 보고 움직여. 학습 때 문장을 '작업 문장'에 넣는 걸 추천 (지금은 스크립트 기본 문장)")
    env = {"MODEL": ckpt["key"], "ROBOT_PORT": p["port"], "TOP_CAM": p["top"], "WRIST_CAM": p["wrist"]}
    # omx_shoebox_act 처럼 omx_run.py 가 있는 번들: 모든 모델을 omx_run.py 로 실행 (번들 infer.sh 와 같은 처리).
    # 이 번들에는 omx_record.py 가 없어서 inference.sh 기본값으로는 실행이 안 됨
    run_py = bundle / "omx_run.py" if bundle else None
    use_run_py = bool(run_py and run_py.is_file())
    if use_run_py:
        env["OMX_RECORD"] = str(run_py)
    a = [f"--policy.device={p['device']}"]

    if p["ensemble"] == "builtin":
        a += [f"--policy.temporal_ensemble_coeff={p['te_coeff']}", "--policy.n_action_steps=1"]
    else:
        a.append(f"--policy.n_action_steps={min(p['n_action_steps'], chunk)}")
        if p["ensemble"] == "kstep":  # act_ensemble.py 가 select_action 을 바꿔서 n_action_steps 는 무시됨
            env["ACT_ENSEMBLE_K"] = str(min(p["ens_k"], chunk))
            env["ACT_ENSEMBLE_M"] = str(p["ens_m"])
    if p["use_amp"] and p["device"] != "cpu":
        a.append("--policy.use_amp=true")

    fc = ", fourcc: MJPG" if p["mjpg"] else ""
    a.append(
        f"--robot.cameras={{top: {{type: opencv, index_or_path: {p['top']}, width: 640, height: 480, fps: 30{fc}}}, "
        f"wrist: {{type: opencv, index_or_path: {p['wrist']}, width: 640, height: 480, fps: 30{fc}}}}}"
    )
    a += [f"--robot.max_relative_target={p['max_relative_target']}", f"--robot.id={p['robot_id']}"]

    if ckpt.get("depth_info"):  # MoGe-2 깊이 모델 (r50 / shoebox 번들 infer.sh 와 같은 처리)
        env["ROBOT_TYPE"] = "omx_follower_grip_depth"
        if use_run_py:  # shoebox: omx_run.py 가 깊이 로봇 타입도 등록, 그리퍼 전류는 안 씀
            a.append("--robot.gripper_current=false")
        elif bundle and (bundle / "omx_depth_robot.py").is_file():
            env["OMX_RECORD"] = str(bundle / "omx_depth_robot.py")
        else:
            raise RuntimeError("깊이 모델인데 번들에 omx_depth_robot.py / omx_run.py 가 없어")
        a += [f"--robot.depth_info={ckpt['depth_info']}", f"--robot.depth_device={p['depth_device']}"]

    a += [f"--dataset.episode_time_s={p['episode_time']}", f"--dataset.num_episodes={p['num_episodes']}"]
    if p["num_episodes"] > 1:
        a.append(f"--dataset.reset_time_s={p['reset_time']}")
    task = p["task"] or (bundle_infer_default(bundle, "dataset.single_task") if use_run_py else None)
    if task:
        a.append(f"--dataset.single_task={task}")
    if use_run_py:
        bt = bundle_infer_default(bundle, "dataset.episode_time_s")
        if bt and bt.isdigit() and int(bt) > p["episode_time"]:
            notes.append(f"[알림] 이 번들 기본 실행 시간은 {bt}초인데 지금 {p['episode_time']}초로 설정돼 있어 (짧으면 '실행 시간'을 늘려줘)")
    a += [f"--display_data={b(p['display_data'])}", f"--dataset.vcodec={p['vcodec']}",
          f"--dataset.streaming_encoding={b(p['streaming_encoding'])}"]
    if p["teleop"]:
        a += ["--teleop.type=omx_leader", f"--teleop.port={p['teleop_port']}", f"--teleop.id={p['teleop_id']}"]
    return infer_sh, ["bash", str(infer_sh), *a], env, notes


def check_chain_model(c: dict):
    info = c["info"]
    if info.get("type") != "act" or info.get("depth") or info.get("state_dim") != 6 or set(info.get("cameras") or []) != {"top", "wrist"}:
        raise ValueError(f"{c['name']}: 이 실행 방식은 관절 6개 + top/wrist 카메라를 쓰는 ACT 모델만 돼.")


def build_chain_command(stages: list, p: dict):
    """연속 실행 명령. 로봇 연결을 끊지 않아야 해서 inference.sh 대신 omx_chain.py 하나로 실행."""
    if len(stages) != 2:
        raise ValueError("연속 실행은 모델 두 개를 골라줘.")
    a, env = chain_base(p)
    for st in stages:
        check_chain_model(st["ckpt"])
        a += ["--stage", st["ckpt"]["key"], str(st["seconds"])]
    notes = ["[알림] 연속 실행: 각 단계 시작 전에 번들의 init_pose.json 자세로 천천히 이동 (2단계 전에는 그리퍼가 열림). 1단계가 끝나면 토크를 유지한 채 멈춰 있고 버튼을 눌러야 2단계가 시작돼 (자동 넘김을 켜면 1초 뒤 자동으로 2단계). 전부 끝나거나 정지하면 토크가 꺼져 팔이 내려앉을 수 있어. 이 실행은 평가 데이터셋을 저장하지 않아."]
    notes += success_notes(stages)
    return a, env, notes


def success_notes(stages: list) -> list:
    out = []
    for i, st in enumerate(stages, 1):
        info = success_info(st["ckpt"].get("bundle"))
        if not info:
            continue
        if info["error"]:
            out.append(f"[알림] {i}단계 {info['desc']} — 이대로면 시작 전에 멈춤. success.json 을 고쳐줘.")
        elif info["model_ok"]:
            out.append(f"[알림] {i}단계 성공 판단: {info['desc']}. 성공하면 시간 전에 끝나고, 시간 안에 성공이 안 나오면 자동 넘김이 켜져 있어도 버튼을 기다려.")
        elif info["model"]:
            out.append(f"[알림] {i}단계 성공 판단 모델 파일이 없음: {info['model']} — 이대로면 시작 전에 멈춤. success.json 을 고쳐줘.")
        else:
            out.append(f"[알림] {i}단계 success.json 은 있지만 model 이 비어 있어서 시간 기준으로 실행.")
    return out


def chain_base(p: dict):
    """omx_chain.py 공통 인자 (현장 설정 + 정책 옵션)."""
    if not CHAIN_SCRIPT.is_file():
        raise RuntimeError(f"실행 스크립트가 없음: {CHAIN_SCRIPT}")
    py = VENV / "bin" / "python"
    a = [str(py) if py.is_file() else sys.executable, "-u", str(CHAIN_SCRIPT),
         "--port", p["port"], "--top", p["top"], "--wrist", p["wrist"], "--robot-id", p["robot_id"],
         "--max-relative-target", str(p["max_relative_target"]), "--device", p["device"]]
    if p["mjpg"]:
        a.append("--mjpg")
    if p["use_amp"] and p["device"] != "cpu":
        a.append("--use-amp")
    env = {}
    if p["ensemble"] == "builtin":
        a += ["--temporal-ensemble-coeff", str(p["te_coeff"])]
    else:
        a += ["--n-action-steps", str(p["n_action_steps"])]
        if p["ensemble"] == "kstep":
            env = {"ACT_ENSEMBLE_K": str(p["ens_k"]), "ACT_ENSEMBLE_M": str(p["ens_m"])}
    if p["task"]:
        a += ["--task", p["task"]]
    return a, env


# ---------------------------------------------------------------- 녹화 (리더암 원격조종으로 학습 에피소드 촬영)
# 현장 설정(포트·카메라·캘리브레이션 이름)은 추론 탭의 PARAMS 값을 같이 씀
REC_PARAMS = [
    {"group": "리더암", "key": "leader_port", "label": "리더 포트", "type": "dev", "default": "/dev/ttyACM1"},
    {"group": "리더암", "key": "leader_id", "label": "리더 캘리브레이션 이름", "type": "id", "default": "omx_leader"},
    {"group": "데이터셋", "key": "dataset_name", "label": "데이터셋 이름", "type": "id", "default": "omx_task",
     "help": "~/il_ws/datasets/<이름> 에 저장. 이미 있으면 이어서 녹화"},
    {"group": "데이터셋", "key": "task", "label": "작업 문장", "type": "text", "default": "",
     "placeholder": "예: Pick up the box and put it in the white basket",
     "help": "에피소드에 같이 저장됨 (SmolVLA 학습 때 사용). 꼭 넣어야 해"},
    {"group": "데이터셋", "key": "hf_user", "label": "HF 아이디", "type": "idopt", "default": "",
     "help": "HF 업로드할 때만 필요. 비우면 local/<이름>"},
    {"group": "녹화", "key": "num_episodes", "label": "에피소드 수", "type": "int", "default": 20, "min": 1, "max": 200},
    {"group": "녹화", "key": "episode_time", "label": "에피소드 길이 (초)", "type": "int", "default": 30, "min": 5,
     "max": 600, "help": "다 하면 '다음'을 눌러 일찍 끝낼 수 있음"},
    {"group": "녹화", "key": "reset_time", "label": "정리 시간 (초)", "type": "int", "default": 15, "min": 0, "max": 120,
     "help": "에피소드 사이에 물체를 제자리에 놓는 시간. '다음'으로 건너뛰기 가능"},
    {"group": "녹화", "key": "display_data", "label": "rerun 화면 표시", "type": "bool", "default": False},
    {"group": "녹화", "key": "vcodec", "label": "영상 코덱", "type": "select", "default": "libsvtav1",
     "options": [["libsvtav1", "AV1"], ["h264", "H.264"], ["hevc", "HEVC"], ["auto", "auto"]],
     "help": "에피소드 저장이 느리면 H.264"},
    {"group": "녹화", "key": "streaming_encoding", "label": "녹화하면서 인코딩", "type": "bool", "default": False,
     "help": "에피소드 저장 대기 시간이 줄어듦"},
    {"group": "업로드", "key": "push_to_hub", "label": "끝나면 HF에 업로드", "type": "bool", "default": False},
    {"group": "업로드", "key": "private", "label": "비공개 저장소", "type": "bool", "default": True,
     "show_if": ["push_to_hub", [True]]},
]


def list_datasets() -> list:
    out = []
    if not DATASETS_DIR.is_dir():
        return out
    for d in sorted(DATASETS_DIR.iterdir()):
        info_path = d / "meta" / "info.json"
        if not info_path.is_file():
            continue
        try:
            info = json.loads(info_path.read_text())
        except (OSError, ValueError):
            continue
        feats = info.get("features", {})
        out.append({
            "name": d.name,
            "episodes": info.get("total_episodes", 0),
            "frames": info.get("total_frames", 0),
            "fps": info.get("fps"),
            "robot_type": info.get("robot_type"),
            "cameras": [k.split(".")[-1] for k in feats if k.startswith("observation.images.")],
            "modified": int(info_path.stat().st_mtime),
        })
    out.sort(key=lambda x: -x["modified"])
    return out


def build_record_command(site: dict, r: dict):
    """(argv, 알림, 상태 정보) — record_ctl.py(= 버튼으로 조종하는 lerobot-record) 실행 인자."""
    if not REC_SCRIPT.is_file():
        raise RuntimeError(f"녹화 스크립트가 없음: {REC_SCRIPT}")
    if not r["task"]:
        raise ValueError("작업 문장을 넣어줘 (예: Pick up the box and put it in the white basket)")
    if r["push_to_hub"] and not r["hf_user"]:
        raise ValueError("HF에 올리려면 HF 아이디를 넣어줘")
    root = DATASETS_DIR / r["dataset_name"]
    resume = (root / "meta" / "info.json").is_file()
    if root.exists() and not resume:
        raise ValueError(f"{root} 폴더가 이미 있는데 데이터셋이 아니야. 다른 이름을 쓰거나 폴더를 정리해줘")
    existing = 0
    if resume:
        try:
            existing = json.loads((root / "meta" / "info.json").read_text()).get("total_episodes", 0)
        except (OSError, ValueError):
            pass
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    repo_id = f"{r['hf_user'] or 'local'}/{r['dataset_name']}"
    b = lambda x: "true" if x else "false"  # noqa: E731
    fc = ", fourcc: MJPG" if site["mjpg"] else ""
    py = VENV / "bin" / "python"
    args = [
        str(py) if py.is_file() else sys.executable, str(REC_SCRIPT),
        "--robot.type=omx_follower", f"--robot.port={site['port']}", f"--robot.id={site['robot_id']}",
        f"--robot.cameras={{top: {{type: opencv, index_or_path: {site['top']}, width: 640, height: 480, fps: 30{fc}}}, "
        f"wrist: {{type: opencv, index_or_path: {site['wrist']}, width: 640, height: 480, fps: 30{fc}}}}}",
        "--teleop.type=omx_leader", f"--teleop.port={r['leader_port']}", f"--teleop.id={r['leader_id']}",
        f"--dataset.repo_id={repo_id}", f"--dataset.root={root}", f"--dataset.single_task={r['task']}",
        f"--dataset.num_episodes={r['num_episodes']}", f"--dataset.episode_time_s={r['episode_time']}",
        f"--dataset.reset_time_s={r['reset_time']}", "--dataset.fps=30",
        f"--dataset.push_to_hub={b(r['push_to_hub'])}", f"--dataset.private={b(r['private'])}",
        f"--dataset.vcodec={r['vcodec']}", f"--dataset.streaming_encoding={b(r['streaming_encoding'])}",
        f"--display_data={b(r['display_data'])}", "--play_sounds=false", f"--resume={b(resume)}",
    ]
    notes = [f"[알림] 기존 데이터셋 {r['dataset_name']}({existing}개)에 이어서 녹화"] if resume else []
    info = {
        "dataset": r["dataset_name"], "root": str(root), "repo_id": repo_id, "resume": resume,
        "existing": existing, "num_episodes": r["num_episodes"],
        "episode_time": r["episode_time"], "reset_time": r["reset_time"],
    }
    return args, notes, info


# ---------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 터미널을 조용하게
        pass

    def _json(self, code: int, data) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        self.path = urlsplit(self.path).path  # ?app=1 같은 쿼리는 무시
        if self.path in ("/", "/index.html"):
            body = (HERE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/models":
            self._json(200, {"tasks": scan_models(), "dirs": [str(p) for p in model_dirs()], "infer_sh": str(INFER_SH)})
        elif self.path == "/api/params":
            self._json(200, {"params": PARAMS})
        elif self.path == "/api/rec_params":
            self._json(200, {"params": REC_PARAMS})
        elif self.path == "/api/datasets":
            self._json(200, {"root": str(DATASETS_DIR), "datasets": list_datasets()})
        elif self.path == "/api/log":
            self._json(200, {"text": RUNNER.full_log()})
        elif self.path == "/api/status":
            self._json(200, RUNNER.status())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        self.path = urlsplit(self.path).path
        try:
            body = self._body()
            if self.path == "/api/start":
                ckpt = all_checkpoints().get(body.get("key"))
                if not ckpt:
                    raise ValueError("모델을 찾을 수 없어. 목록을 새로고침해줘.")
                params = clean_params(body.get("params", {}))
                if RUNNER.prep_ready():  # 초기 자세에서 대기 중이면 그 연결로 이어서 실행
                    RUNNER.run_prepared([{"ckpt": ckpt, "seconds": params["episode_time"]}], single=True)
                else:
                    RUNNER.start(ckpt, params)
                self._json(200, RUNNER.status())
            elif self.path == "/api/prepare":
                task = next((t for t in scan_models() if t["id"] == body.get("task")), None)
                if not task:
                    raise ValueError("태스크를 찾을 수 없어. 목록을 새로고침해줘.")
                RUNNER.start_prepare(task, clean_params(body.get("params", {})))
                self._json(200, RUNNER.status())
            elif self.path == "/api/chain/start":
                ckpts = all_checkpoints()
                stages = []
                for st in body.get("stages", []):
                    ckpt = ckpts.get(st.get("key"))
                    if not ckpt:
                        raise ValueError("모델을 찾을 수 없어. 목록을 새로고침해줘.")
                    try:
                        seconds = int(st.get("seconds"))
                    except (TypeError, ValueError):
                        raise ValueError("실행 시간은 숫자여야 해")
                    if not 5 <= seconds <= 600:
                        raise ValueError("실행 시간은 5~600초 사이로 해줘")
                    stages.append({"ckpt": ckpt, "seconds": seconds})
                if RUNNER.prep_ready():
                    if len(stages) != 2:
                        raise ValueError("연속 실행은 모델 두 개를 골라줘.")
                    RUNNER.run_prepared(stages, single=False, auto=bool(body.get("auto")))
                else:
                    RUNNER.start_chain(stages, clean_params(body.get("params", {})), auto=bool(body.get("auto")))
                self._json(200, RUNNER.status())
            elif self.path == "/api/chain/auto":
                RUNNER.set_auto(bool(body.get("on")))
                self._json(200, RUNNER.status())
            elif self.path == "/api/chain/next":
                RUNNER.next_stage()
                self._json(200, RUNNER.status())
            elif self.path == "/api/record/start":
                site = clean_params(body.get("site", {}), PARAMS)
                RUNNER.start_record(site, clean_params(body.get("params", {}), REC_PARAMS))
                self._json(200, RUNNER.status())
            elif self.path == "/api/record/cmd":
                RUNNER.send(str(body.get("cmd", "")))
                self._json(200, RUNNER.status())
            elif self.path == "/api/stop":
                RUNNER.stop()
                self._json(200, RUNNER.status())
            elif self.path == "/api/torque_off":
                port = clean_params(body.get("params", {}))["port"]
                self._json(200, {"output": torque_off(port)})
            else:
                self._json(404, {"error": "not found"})
        except (ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
            self._json(400, {"error": str(e)})


def make_server(port: int = PORT) -> ThreadingHTTPServer:
    """port=0 이면 비어 있는 포트를 자동으로 고름 (app.py 창 모드에서 사용)."""
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def stop_running(timeout: float = 20) -> None:
    """프로그램을 끌 때 돌고 있는 추론을 정상 종료."""
    if RUNNER.running():
        RUNNER.stop()
        try:
            RUNNER.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass


def main():
    srv = make_server(PORT)
    url = f"http://127.0.0.1:{PORT}"
    print(f"OMX 추론 대시보드: {url}")
    print(f"  모델 폴더: {', '.join(map(str, model_dirs()))}")
    print(f"  실행 스크립트: {INFER_SH}")
    print("  끄려면 이 터미널에서 Ctrl+C")
    if os.environ.get("OMX_NO_BROWSER") != "1":
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if RUNNER.running():
            print("\n실행 중인 추론을 정지하는 중…")
        stop_running()
        srv.server_close()


if __name__ == "__main__":
    main()
