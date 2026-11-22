"""화면(top 카메라)을 보고 단계 성공을 판단 — omx_chain.py 연속 실행의 자동 넘김용.

번들 폴더(예: ~/il_ws/omx_shoebox_d)에 success.json 이 있으면 그 단계는 성공 판단을 씀. 없으면 지금처럼 시간 기준.

판단 순서 (기본값은 shoebox_d 기준):
  1. 시작 확인: arm_class(inside_box = 상자 안쪽 빨간 면)가 합쳐서 arm_s(1초) 이상 보여야 판단을 시작 (시작 직후 오검출로 넘어가는 것 방지)
  2. 성공: target(closed_box)이 처음 보인 뒤로 hold_s(5초) 이상 이어지고, 최근 hold_s 동안
       target 이 보인 비율 >= min_ratio(0.8), forbid 의 각 클래스(inside_box, shoe)가 보인 비율 <= 그 값(0.1)
     target 이 gap_s(1초) 넘게 안 보이면 처음부터 다시 셈 (팔이 잠깐 가리는 정도는 봐줌)
  3. 팔 멈춤 (still_speed > 0 일 때만): 위 2 가 채워져도, 관절이 still_s(1초) 동안 거의 안 움직여야 성공.
     화면은 '닫혔다'를, 관절은 '팔 동작이 끝났다'를 본다. 관절 값은 feed_state() 로 넣는다 (제어 루프에서 매번).
     속도 = 최근 still_win_s(0.3초) 동안 가장 많이 변한 관절의 변화량 / 시간 (observation.state 단위/초).
     rest_pose 를 주면 '멈춤'은 그 자세 근처(모든 관절이 rest_tol 안)에 있을 때만 센다.
     (뚜껑을 누르며 잠깐 멈추는 것과, 동작을 끝내고 물러나 멈춘 것을 가르기 위함)
     관절 값이 한 번도 안 들어오면 성공이 안 뜬다 (시간 초과로 넘어감).

구성:
  SuccessRule  — 판단 규칙만 (시간, 보인 클래스 목록) → 상태. 모델 없이 시험 가능
  Detector     — Ultralytics YOLO(.pt) 로 한 장 검출 → {클래스: 최고 신뢰도}
  SuccessJudge — 별도 스레드에서 최신 프레임을 hz 번/초 검출해서 규칙에 넣음. 성공하면 succeeded 이벤트
"""

import json
import threading
import time
from collections import deque
from pathlib import Path

DEFAULTS = {
    "model": "",  # YOLO 세그멘테이션 가중치 (.pt). 번들 폴더 기준 상대 경로도 됨. 비우면 성공 판단 끔
    "camera": "top",
    "conf": 0.5,  # 이 신뢰도 이상만 '보임'으로 침
    "imgsz": 640,
    "hz": 10.0,  # 초당 검출 횟수
    "arm_class": "inside_box",
    "arm_s": 1.0,
    "target": "closed_box",
    "hold_s": 5.0,
    "min_ratio": 0.8,
    "forbid": {"inside_box": 0.1, "shoe": 0.1},
    "gap_s": 1.0,
    "still_speed": 0.0,  # 관절 속도가 이 값 미만이어야 '멈춤' (observation.state 단위/초). 0 이면 팔 멈춤 조건 끔
    "still_s": 1.0,  # 멈춤이 이만큼 이어져야 함
    "still_win_s": 0.3,  # 속도를 재는 구간
    "rest_pose": [],  # 동작을 끝낸 뒤의 팔 자세 (observation.state 순서). 비우면 자세는 안 봄
    "rest_tol": 18.0,  # rest_pose 에서 관절마다 이만큼 안이면 '근처'
}


def load_config(bundle_dir):
    """<번들>/success.json → 설정 dict (없으면 None). model 은 절대 경로로 바꿔 둠."""
    f = Path(bundle_dir) / "success.json"
    if not f.is_file():
        return None
    cfg = {**DEFAULTS, **json.loads(f.read_text(encoding="utf-8"))}
    cfg["forbid"] = {str(k): float(v) for k, v in (cfg.get("forbid") or {}).items()}
    if cfg["model"]:
        p = Path(cfg["model"]).expanduser()
        cfg["model"] = str(p if p.is_absolute() else (Path(bundle_dir) / p).resolve())
    cfg["file"] = str(f)
    return cfg


def describe(cfg) -> str:
    forbid = ", ".join(f"{k} ≤{v:.0%}" for k, v in cfg["forbid"].items())
    still = ""
    if cfg.get("still_speed", 0) > 0:
        pose = f", 끝 자세에서 {cfg['rest_tol']:g} 안" if cfg.get("rest_pose") else ""
        still = f" + 팔 멈춤 {cfg['still_s']:g}초 (속도 <{cfg['still_speed']:g}{pose})"
    return (f"{cfg['camera']} 카메라 · {cfg['arm_class']} 확인 후 {cfg['target']} {cfg['hold_s']:g}초 유지 "
            f"(≥{cfg['min_ratio']:.0%}" + (f", {forbid}" if forbid else "") + ")" + still)


class SuccessRule:
    def __init__(self, cfg):
        self.c = cfg
        self.reset()

    def reset(self):
        self.armed = not self.c["arm_class"]
        self.arm_acc = 0.0
        self.last_t = None
        self.streak_start = None
        self.last_target_t = None
        self.samples = deque()  # (t, 보인 클래스 set)
        self.done = False
        self.states = deque()  # (t, 관절 값 tuple) — 최근 still_win_s 만
        self.speed = None  # 최근 관절 속도 (단위/초). 관절 값이 아직 없으면 None
        self.still_since = None  # 멈춤이 시작된 시각
        self.rest_dist = None  # rest_pose 까지 거리 (가장 먼 관절)
        self.last_state_t = None

    def feed_state(self, t, q):
        """관절 값(observation.state)을 넣음. 제어 루프에서 매번 불러도 됨 (가벼움)."""
        c = self.c
        if c.get("still_speed", 0) <= 0:
            return
        q = tuple(float(x) for x in q)
        self.states.append((t, q))
        while len(self.states) > 2 and self.states[1][0] <= t - c["still_win_s"]:
            self.states.popleft()
        t0, q0 = self.states[0]
        self.last_state_t = t
        if t - t0 < 0.5 * c["still_win_s"]:
            return  # 아직 구간이 덜 참
        self.speed = max(abs(a - b) for a, b in zip(q, q0)) / (t - t0)
        rest = c.get("rest_pose") or []
        self.rest_dist = max(abs(a - b) for a, b in zip(q, rest)) if rest else None
        if self.speed < c["still_speed"] and (self.rest_dist is None or self.rest_dist <= c["rest_tol"]):
            if self.still_since is None:
                self.still_since = t0
        else:
            self.still_since = None

    def still_for(self) -> float:
        """팔이 멈춘 지 몇 초 (안 멈췄거나 관절 값이 없으면 0)."""
        if self.still_since is None or self.last_state_t is None:
            return 0.0
        return self.last_state_t - self.still_since

    def still_ok(self) -> bool:
        c = self.c
        return c.get("still_speed", 0) <= 0 or self.still_for() >= c["still_s"]

    def update(self, t, present):
        """한 번 검출한 결과를 넣음. 반환: 이번에 생긴 일 ('armed' | 'start' | 'lost' | 'success' | None)."""
        c = self.c
        dt = 0.0 if self.last_t is None else min(max(t - self.last_t, 0.0), 2.0 / c["hz"])
        self.last_t = t
        if self.done:
            return None
        if not self.armed:
            if c["arm_class"] in present:
                self.arm_acc += dt if dt else 1.0 / c["hz"]
                if self.arm_acc >= c["arm_s"]:
                    self.armed = True
                    return "armed"
            return None

        self.samples.append((t, set(present)))
        while self.samples and self.samples[0][0] < t - c["hold_s"] - 1.0:
            self.samples.popleft()

        event = None
        if c["target"] in present:
            if self.streak_start is None:
                self.streak_start = t
                event = "start"
            self.last_target_t = t
        elif self.streak_start is not None and t - self.last_target_t > c["gap_s"]:
            self.streak_start = None
            return "lost"

        if self.streak_start is not None and self.progress() >= c["hold_s"]:
            r = self.ratios()
            if (r[c["target"]] >= c["min_ratio"] and all(r[k] <= v for k, v in c["forbid"].items())
                    and self.still_ok()):
                self.done = True
                return "success"
        return event

    def progress(self) -> float:
        if self.streak_start is None or self.last_t is None:
            return 0.0
        return self.last_t - self.streak_start

    def ratios(self) -> dict:
        """최근 hold_s 동안 (target 이 보이기 시작한 뒤로만) 각 클래스가 보인 비율."""
        c = self.c
        names = [c["target"], *c["forbid"]]
        if self.streak_start is None or self.last_t is None:
            return {k: 0.0 for k in names}
        lo = max(self.streak_start, self.last_t - c["hold_s"])
        win = [s for t, s in self.samples if t >= lo]
        n = len(win) or 1
        return {k: sum(k in s for s in win) / n for k in names}

    def summary(self) -> str:
        c = self.c
        r = self.ratios()
        parts = [f"{k} {v:.0%}" for k, v in r.items()]
        if c.get("still_speed", 0) > 0:
            sp = "관절 값 없음" if self.speed is None else f"속도 {self.speed:.0f}"
            if self.rest_dist is not None:
                sp += f", 자세 거리 {self.rest_dist:.0f}"
            parts.append(f"팔 멈춤 {min(self.still_for(), c['still_s']):.1f}/{c['still_s']:g}s ({sp})")
        return f"진행 {min(self.progress(), c['hold_s']):.1f}/{c['hold_s']:g}s · " + " · ".join(parts)


class Detector:
    """Ultralytics YOLO (.pt). 프레임은 RGB(lerobot 카메라 출력) 로 받아서 BGR 로 바꿔 넣음."""

    def __init__(self, cfg, device="cuda"):
        if not Path(cfg["model"]).is_file():
            raise RuntimeError(f"모델 파일이 없음: {cfg['model']}")
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise RuntimeError(f"ultralytics 가 설치돼 있지 않음 ({e})") from e
        self.model = YOLO(cfg["model"])
        self.conf, self.imgsz = float(cfg["conf"]), int(cfg["imgsz"])
        self.device = "cpu" if str(device).startswith("cpu") else 0
        names = set(self.model.names.values())
        want = {cfg["target"], cfg["arm_class"], *cfg["forbid"]} - {""}
        if want - names:
            raise RuntimeError(f"모델에 없는 클래스: {sorted(want - names)} (모델 클래스: {sorted(names)})")
        import numpy as np

        self.detect(np.zeros((480, 640, 3), dtype=np.uint8))  # 첫 검출이 느려서 미리 한 번

    def detect(self, rgb, return_result=False):
        import numpy as np

        bgr = np.ascontiguousarray(rgb[..., ::-1])
        res = self.model.predict(bgr, conf=self.conf, imgsz=self.imgsz, device=self.device, verbose=False)[0]
        found = {}
        names = self.model.names
        if res.boxes is not None:
            for k, p in zip(res.boxes.cls.tolist(), res.boxes.conf.tolist()):
                n = names[int(k)]
                found[n] = max(found.get(n, 0.0), float(p))
        return (found, res) if return_result else found


class SuccessJudge:
    """run_stage 루프가 feed() 로 최신 프레임을 넘기면, 별도 스레드가 검출·판단. 루프는 succeeded 만 확인."""

    def __init__(self, cfg, detector, log=print):
        self.cfg, self.det, self.log = cfg, detector, log
        self.rule = SuccessRule(cfg)
        self.succeeded = threading.Event()
        self._frame = None  # (프레임, 받은 시각)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.t0 = None

    def feed(self, frame):
        with self._lock:
            self._frame = (frame, time.perf_counter())

    def feed_state(self, q):
        """관절 값(observation.state, 숫자 목록)을 넣음. 제어 루프에서 feed() 와 같이 부름. still_speed 가 0 이면 아무 일도 안 함."""
        if self.t0 is not None:
            self.rule.feed_state(time.perf_counter() - self.t0, q)

    def begin(self):
        self.rule.reset()
        self.succeeded.clear()
        self._stop.clear()
        self._frame = None
        self.t0 = time.perf_counter()
        self.log(f"[성공 판단] 사용 — {describe(self.cfg)}")
        self.log(f"[성공 판단] {self.cfg['arm_class']} 확인 대기")
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def end(self, reason="timeout"):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if reason == "next" and not self.succeeded.is_set():
            self.log("[성공 판단] 버튼으로 단계를 끝냄 — 판단 중단")
        elif not self.succeeded.is_set():
            r = self.rule
            if not r.armed:
                why = f"{self.cfg['arm_class']}를 확인하지 못함"
            elif r.streak_start is None:
                why = f"{self.cfg['target']}가 (이어서) 보이지 않음"
            else:
                why = f"{self.cfg['target']} 유지 조건을 못 채움 ({r.summary()})"
            self.log(f"[성공 판단] 성공 안 남 — {why}")

    def _loop(self):
        period = 1.0 / float(self.cfg["hz"])
        last_id = None
        last_print = 0.0
        while not self._stop.is_set():
            start = time.perf_counter()
            with self._lock:
                item = self._frame
            if item is None or id(item[0]) == last_id:
                time.sleep(0.01)
                continue
            last_id = id(item[0])
            try:
                found = self.det.detect(item[0])
            except Exception as e:  # noqa: BLE001  검출이 죽어도 로봇 제어는 계속
                self.log(f"[성공 판단] 검출 오류 — 이 단계는 시간 기준으로 진행: {type(e).__name__}: {e}")
                return
            ev = self.rule.update(item[1] - self.t0, set(found))
            now = time.perf_counter()
            if ev == "armed":
                self.log(f"[성공 판단] {self.cfg['arm_class']} 확인 — 판단 시작")
            elif ev == "start":
                self.log(f"[성공 판단] {self.cfg['target']} 보임 — 셈 시작")
            elif ev == "lost":
                self.log(f"[성공 판단] {self.cfg['target']} 사라짐 — 처음부터 다시 셈")
            elif ev == "success":
                self.log(f"[성공 판단] 성공 — {self.rule.summary()}")
                self.succeeded.set()
                return
            if self.rule.streak_start is not None and now - last_print >= 0.5:
                last_print = now
                self.log(f"[성공 판단] {self.rule.summary()}")
            time.sleep(max(0.0, period - (time.perf_counter() - start)))
