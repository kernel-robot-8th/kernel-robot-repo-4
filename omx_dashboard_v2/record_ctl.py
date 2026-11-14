#!/usr/bin/env python3
"""lerobot-record (LeRobot 0.4.4) 를 대시보드 버튼으로 조종하기 위한 래퍼.

lerobot-record 는 키보드(→ ← Esc)로만 에피소드를 넘기거나 다시 찍을 수 있는데,
Wayland 화면이나 터미널 없이 띄운 프로그램에서는 키보드 감지가 안 됨.
여기서는 키보드 대신 표준입력(stdin)으로 명령을 받음 — 대시보드 서버가 한 줄씩 보냄.

  next          → (→) 지금 단계(녹화/정리)를 끝내고 다음으로. 녹화 중이면 그 에피소드는 저장
  rerecord      → (←) 지금 에피소드를 버리고 다시 찍기
  stop          → (Esc) 지금 에피소드까지 저장하고 종료
  discard_stop  → 지금 에피소드는 버리고 종료

사용법: lerobot-record 와 같은 인자.  python record_ctl.py --robot.type=omx_follower ...
"""

import os
import sys
import threading
import time

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.scripts import lerobot_record


def _stdin_listener():
    events = {"exit_early": False, "rerecord_episode": False, "stop_recording": False}

    def reader():
        for line in sys.stdin:
            cmd = line.strip()
            if cmd == "next":
                events["exit_early"] = True
            elif cmd == "rerecord":
                events["rerecord_episode"] = True
                events["exit_early"] = True
            elif cmd == "stop":
                events["stop_recording"] = True
                events["exit_early"] = True
            elif cmd == "discard_stop":
                events["rerecord_episode"] = True
                events["stop_recording"] = True
                events["exit_early"] = True
            else:
                continue
            print(f"[대시보드] {cmd}", flush=True)

    threading.Thread(target=reader, daemon=True).start()
    return None, events  # listener=None 이면 lerobot이 종료 때 listener.stop()을 건너뜀


_orig_save = LeRobotDataset.save_episode
_orig_clear = LeRobotDataset.clear_episode_buffer


def _save_episode(self, *args, **kwargs):
    self._omx_saving = True  # save_episode 안에서도 clear_episode_buffer 를 부르므로 그때는 '버림' 표시 안 함
    try:
        out = _orig_save(self, *args, **kwargs)
    finally:
        self._omx_saving = False
    print(f"[저장 완료] 데이터셋 에피소드 {self.num_episodes}개", flush=True)
    return out


def _clear_episode_buffer(self, *args, **kwargs):
    out = _orig_clear(self, *args, **kwargs)
    if not getattr(self, "_omx_saving", False):
        print("[버림] 이번 에피소드는 저장하지 않음", flush=True)
    return out


lerobot_record.init_keyboard_listener = _stdin_listener
LeRobotDataset.save_episode = _save_episode
LeRobotDataset.clear_episode_buffer = _clear_episode_buffer


# ---- 대시보드에 카메라 화면 보내기 ----------------------------------------------------
# 녹화 중엔 카메라를 lerobot이 쓰고 있어서 대시보드가 따로 못 염. 로봇이 받은 프레임을 옆에서
# 받아 OMX_FRAME_DIR/<카메라이름>.jpg 로 1초에 몇 번씩 저장 (녹화 루프는 막지 않음).
FRAME_DIR = os.environ.get("OMX_FRAME_DIR")
if FRAME_DIR:
    import cv2
    from lerobot.robots.omx_follower.omx_follower import OmxFollower

    _latest: dict = {}
    _orig_obs = OmxFollower.get_observation

    def _get_observation(self, *args, **kwargs):
        obs = _orig_obs(self, *args, **kwargs)
        for name in getattr(self, "cameras", {}):
            if name in obs:
                _latest[name] = obs[name]
        return obs

    def _frame_writer():
        os.makedirs(FRAME_DIR, exist_ok=True)
        sent = {}
        while True:
            for name, img in list(_latest.items()):
                if sent.get(name) is img:
                    continue
                sent[name] = img
                try:
                    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if ok:
                        tmp = os.path.join(FRAME_DIR, f".{name}.jpg.tmp")
                        with open(tmp, "wb") as f:
                            f.write(buf.tobytes())
                        os.replace(tmp, os.path.join(FRAME_DIR, f"{name}.jpg"))
                except Exception:  # 화면 전송이 실패해도 녹화는 계속
                    pass
            time.sleep(0.1)

    OmxFollower.get_observation = _get_observation
    threading.Thread(target=_frame_writer, daemon=True).start()

if __name__ == "__main__":
    lerobot_record.main()
