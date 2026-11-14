#!/usr/bin/env python3
"""YOLO 라벨링용 프레임 뽑기 — LeRobot 데이터셋의 top 카메라 영상에서 jpg 로 저장 (로봇 필요 없음).

뽑는 시점 (에피소드마다):
  1. 구간별 무작위 (--per-episode, 기본 8장): 에피소드를 8등분해서 구간마다 무작위로 1장.
     시작(열린 상자 + 신발 2개) ~ 끝(닫힌 상자)이 고르게 들어가고, 에피소드마다 시점이 조금씩 달라서 장면이 다양해짐.
  2. 그리퍼 움직임 (--grip-events, 기본 2장): observation.state 의 그리퍼 값이 가장 크게 변하는 순간
     (신발을 잡거나 상자 안에 놓는 순간). 팔이 상자를 가리는, 모델이 제일 헷갈리는 장면을 더 넣으려는 것.
  0.5초(--min-gap) 안에 겹치는 시점은 하나만 씀.

검증용 에피소드 (--val, 기본 10개)는 무작위로 따로 빼서 프레임을 뽑지 않음 → split.json 에 기록.
학습에 안 쓴 이 에피소드로 success_check.py 를 돌려야 실제 성능을 볼 수 있음.

  source ~/venv/il/bin/activate
  cd ~/il_ws/omx_act_1027/dashboard_v2
  HF_HUB_DISABLE_XET=1 python extract_frames.py --dataset Yuzriha00/shoebox_D --download

결과 (기본 ~/il_ws/judge_data/<데이터셋 이름>/):
  images/ep012_031.40s.jpg …   라벨링 도구에 올릴 사진
  manifest.csv                  사진마다 에피소드·시각·뽑은 이유
  split.json                    학습/검증 에피소드 목록
"""

import argparse
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from success_check import dataset_episodes, dataset_root  # noqa: E402


def parse_args():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--dataset", required=True, help="LeRobot 데이터셋 폴더 또는 repo id (예: Yuzriha00/shoebox_D)")
    a.add_argument("--download", action="store_true", help="로컬에 없으면 HF 에서 받기")
    a.add_argument("--camera", default="top")
    a.add_argument("--out", default=None, help="저장 폴더 (기본 ~/il_ws/judge_data/<데이터셋 이름>)")
    a.add_argument("--per-episode", type=int, default=8, help="구간별 무작위 장수")
    a.add_argument("--grip-events", type=int, default=2, help="그리퍼 움직임 순간 장수")
    a.add_argument("--val", type=int, default=10, help="검증용으로 빼 둘 에피소드 수")
    a.add_argument("--min-gap", type=float, default=0.5, help="이 시간(초) 안에 겹치는 시점은 하나만")
    a.add_argument("--seed", type=int, default=0)
    a.add_argument("--quality", type=int, default=95, help="jpg 품질")
    return a.parse_args()


def find_root(spec, download):
    try:
        return dataset_root(spec)
    except SystemExit:
        if not download or Path(spec).expanduser().exists():
            raise
    from huggingface_hub import snapshot_download

    root = Path.home() / ".cache/huggingface/lerobot" / spec
    print(f"HF 에서 받는 중: {spec} → {root}  (멈추면 HF_HUB_DISABLE_XET=1 을 앞에 붙여서 다시)")
    snapshot_download(spec, repo_type="dataset", local_dir=str(root))
    return dataset_root(str(root))


# ---------------------------------------------------------------- 시점 고르기
def gripper_tracks(root):
    """{에피소드: (시각 배열, 그리퍼 값 배열)} — 그리퍼 값을 못 찾으면 빈 dict."""
    import numpy as np
    import pandas as pd

    info = json.loads((root / "meta" / "info.json").read_text())
    names = info.get("features", {}).get("observation.state", {}).get("names") or []
    if isinstance(names, dict):  # {"motors": [...]} 같은 형식
        names = next(iter(names.values()), [])
    idx = next((i for i, n in enumerate(names) if "gripper" in str(n)), None)
    if idx is None:
        print("[알림] observation.state 에서 그리퍼를 못 찾음 — 그리퍼 순간 프레임은 건너뜀")
        return {}
    files = sorted((root / "data").glob("**/*.parquet"))
    df = pd.concat([pd.read_parquet(f, columns=["episode_index", "timestamp", "observation.state"]) for f in files])
    out = {}
    for ep, g in df.groupby("episode_index"):
        g = g.sort_values("timestamp")
        out[int(ep)] = (g["timestamp"].to_numpy(float), np.array([s[idx] for s in g["observation.state"]], float))
    return out


def grip_event_times(t, g, n, fps=30.0, sep=2.0, edge=1.0):
    """그리퍼 값이 가장 빨리 변하는 시각 n개 (서로 sep 초 이상 떨어지게, 처음·끝 edge 초 제외)."""
    import numpy as np

    if n <= 0 or len(t) < 10:
        return []
    k = max(1, int(0.25 * fps))
    sm = np.convolve(g, np.ones(5) / 5, mode="same")
    speed = np.zeros_like(sm)
    speed[k:-k] = np.abs(sm[2 * k:] - sm[:-2 * k])
    order = np.argsort(-speed)
    picked = []
    for i in order:
        if speed[i] <= 0:
            break
        ti = t[i]
        if ti < t[0] + edge or ti > t[-1] - edge or any(abs(ti - p) < sep for p in picked):
            continue
        picked.append(float(ti))
        if len(picked) == n:
            break
    return picked


def pick_times(length, n_strata, events, rng, min_gap, fps=30.0):
    """[(에피소드 안 시각, 이유)] — 그리퍼 순간을 먼저 넣고, 구간별 무작위는 겹치지 않을 때만."""
    out = [(t, "gripper") for t in events]
    last = max(0.0, length - 1.0 / fps)
    for i in range(n_strata):
        lo, hi = i * length / n_strata, min((i + 1) * length / n_strata, last)
        t = rng.uniform(lo, hi) if hi > lo else lo
        if all(abs(t - u) >= min_gap for u, _ in out):
            out.append((t, f"segment{i + 1}"))
    return sorted(out)


# ---------------------------------------------------------------- 저장
def save_frames(path, targets, quality):
    """한 mp4 에서 targets [(영상 기준 초, 저장 경로)] 를 뽑아 저장. 가까운 건 이어서 디코딩, 멀면 seek."""
    import av
    import cv2

    targets = sorted(targets)
    saved = 0
    with av.open(str(path)) as c:
        st = c.streams.video[0]
        fps = float(st.average_rate or 30)
        half = 0.5 / fps
        frames = None
        cur = -1e9
        for ts, out in targets:
            if frames is None or ts < cur - half or ts - cur > 3.0:
                c.seek(int(max(ts - 0.1, 0) / st.time_base), stream=st, backward=True, any_frame=False)
                frames = c.decode(st)
                cur = -1e9
            img = None
            for fr in frames:
                cur = float(fr.pts * st.time_base)
                if cur >= ts - half:
                    img = fr.to_ndarray(format="bgr24")
                    break
            if img is None:
                print(f"[경고] {path.name} {ts:.2f}s 프레임을 못 찾음")
                frames = None
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, quality])
            saved += 1
    return saved


def main():
    args = parse_args()
    root = find_root(args.dataset, args.download)
    out = Path(args.out).expanduser() if args.out else Path.home() / "il_ws/judge_data" / root.name
    eps = dataset_episodes(root, args.camera)
    rng = random.Random(args.seed)

    all_ids = [e[0] for e in eps]
    val = sorted(rng.sample(all_ids, min(args.val, max(len(all_ids) - 1, 0))))
    train = [e for e in eps if e[0] not in val]
    out.mkdir(parents=True, exist_ok=True)
    (out / "split.json").write_text(json.dumps({"dataset": str(root), "camera": args.camera, "seed": args.seed,
                                                "train": [e[0] for e in train], "val": val}, indent=1))
    print(f"데이터셋 {root} · 에피소드 {len(eps)}개 → 학습용 {len(train)}개, 검증용 {len(val)}개 {val}")

    grips = gripper_tracks(root) if args.grip_events > 0 else {}
    plan = {}  # mp4 경로 → [(영상 기준 초, 저장 경로)]
    rows = []
    for ep, path, start, end in train:
        events = []
        if ep in grips:
            t, g = grips[ep]
            events = grip_event_times(t, g, args.grip_events)
        for t, why in pick_times(end - start, args.per_episode, events, rng, args.min_gap):
            f = out / "images" / f"ep{ep:03d}_{t:06.2f}s.jpg"
            plan.setdefault(path, []).append((start + t, f))
            rows.append({"file": f.name, "episode": ep, "time_s": round(t, 2), "reason": why,
                         "episode_length_s": round(end - start, 2)})

    total = 0
    for path, targets in plan.items():
        print(f"{path.relative_to(root)}: {len(targets)}장")
        total += save_frames(path, targets, args.quality)

    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["file"])
        w.writeheader()
        w.writerows(rows)
    n_grip = sum(r["reason"] == "gripper" for r in rows)
    print(f"\n저장 {total}장 (구간별 {len(rows) - n_grip}, 그리퍼 순간 {n_grip}) → {out / 'images'}")
    print(f"검증용 에피소드: {','.join(map(str, val))}")
    print("라벨: closed_box, inside_box(상자 안쪽·뚜껑 안쪽 빨간 면), shoe")


if __name__ == "__main__":
    main()
