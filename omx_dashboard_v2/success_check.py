#!/usr/bin/env python3
"""성공 판단을 녹화 영상에 돌려 보는 검증 도구 (로봇 필요 없음).

연속 실행 때와 같은 규칙(success_judge.py)과 같은 YOLO 모델로, 녹화된 에피소드 영상을 처음부터 흘려보내서
몇 초에 '성공'이 뜨는지 확인한다. 성공 에피소드라면 끝나기 몇 초 전에 성공이 떠야 정상.

  source ~/venv/il/bin/activate
  cd ~/il_ws/omx_act_1027/dashboard_v2

  # LeRobot 데이터셋 (로컬 폴더 또는 HF 캐시에 받아 둔 repo id) — 에피소드 전부 / 일부
  python success_check.py --config ~/il_ws/omx_shoebox_d/success.json --dataset Yuzriha00/shoebox_D --episodes all
  python success_check.py --config ~/il_ws/omx_shoebox_d/success.json --dataset Yuzriha00/shoebox_D --episodes 0,5 --out ~/il_ws/outputs/judge

  # mp4 하나
  python success_check.py --config ~/il_ws/omx_shoebox_d/success.json --video some_top.mp4

--model 로 success.json 의 model 대신 다른 .pt 를 시험할 수 있음. --out 을 주면 검출 결과를 그린 영상을 저장.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from success_judge import Detector, SuccessRule, describe, load_config  # noqa: E402


def parse_args():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--config", required=True, help="번들의 success.json")
    a.add_argument("--model", default=None, help="success.json 의 model 대신 쓸 .pt")
    src = a.add_mutually_exclusive_group(required=True)
    src.add_argument("--video", help="mp4 파일 하나")
    src.add_argument("--dataset", help="LeRobot 데이터셋 폴더 또는 HF 캐시에 있는 repo id (예: Yuzriha00/shoebox_D)")
    a.add_argument("--episodes", default="all", help="all 또는 0,3,7 (--dataset 일 때)")
    a.add_argument("--camera", default=None, help="데이터셋 카메라 이름 (기본: success.json 의 camera)")
    a.add_argument("--device", default="cuda")
    a.add_argument("--out", default=None, help="검출 결과 영상을 저장할 폴더")
    a.add_argument("--quiet", action="store_true", help="에피소드별 진행 로그 생략, 요약만")
    return a.parse_args()


# ---------------------------------------------------------------- 영상 읽기
def iter_frames(path, start=0.0, end=None):
    """(영상 기준 초, RGB 프레임). PyAV(lerobot 이 쓰는 AV1 영상도 읽힘) 우선, 없으면 OpenCV."""
    try:
        import av
    except ImportError:
        av = None
    if av is not None:
        with av.open(str(path)) as c:
            st = c.streams.video[0]
            if start > 0:
                c.seek(int(start / st.time_base), stream=st, backward=True, any_frame=False)
            for fr in c.decode(st):
                t = float(fr.pts * st.time_base) if fr.pts is not None else None
                if t is None or t < start - 1e-3:
                    continue
                if end is not None and t >= end - 1e-3:
                    break
                yield t, fr.to_ndarray(format="rgb24")
        return
    import cv2

    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    i = 0
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        t = start + i / fps
        i += 1
        if end is not None and t >= end - 1e-3:
            break
        yield t, bgr[..., ::-1]
    cap.release()


def dataset_root(spec):
    p = Path(spec).expanduser()
    if (p / "meta" / "info.json").is_file():
        return p
    for base in (Path.home() / ".cache/huggingface/lerobot", Path.home() / "il_ws/datasets"):
        q = base / spec
        if (q / "meta" / "info.json").is_file():
            return q
    raise SystemExit(f"데이터셋을 못 찾음: {spec} (폴더 경로를 주거나 HF 캐시에 받아줘)")


def dataset_episodes(root, camera):
    """[(에피소드 번호, mp4 경로, 시작 초, 끝 초)] — LeRobot v3 (에피소드 여러 개가 mp4 하나에 이어 붙어 있음)."""
    import pandas as pd

    info = json.loads((root / "meta" / "info.json").read_text())
    key = f"observation.images.{camera}"
    if key not in info.get("features", {}):
        cams = [k.split(".")[-1] for k in info.get("features", {}) if k.startswith("observation.images.")]
        raise SystemExit(f"데이터셋에 '{camera}' 카메라가 없음 (있는 것: {cams})")
    files = sorted((root / "meta" / "episodes").glob("**/*.parquet"))
    if not files:
        raise SystemExit(f"{root}/meta/episodes 가 비어 있음 (LeRobot v3 데이터셋이 아님?)")
    df = pd.concat([pd.read_parquet(f) for f in files]).sort_values("episode_index")
    tmpl = info["video_path"]
    out = []
    for _, r in df.iterrows():
        path = root / tmpl.format(video_key=key, chunk_index=int(r[f"videos/{key}/chunk_index"]),
                                  file_index=int(r[f"videos/{key}/file_index"]))
        out.append((int(r["episode_index"]), path, float(r[f"videos/{key}/from_timestamp"]),
                    float(r[f"videos/{key}/to_timestamp"])))
    return out


# ---------------------------------------------------------------- 판단
def run_one(det, cfg, frames, label, writer_path=None, quiet=False):
    """영상 하나(에피소드 하나)를 흘려보냄. 반환: {length, armed_at, success_at, summary}."""
    rule = SuccessRule(cfg)
    period = 1.0 / float(cfg["hz"])
    t0 = None
    last = -1e9
    armed_at = success_at = None
    writer = None
    t = 0.0
    for ts, rgb in frames:
        if t0 is None:
            t0 = ts
        t = ts - t0
        if t - last < period - 1e-6 or success_at is not None:
            continue
        last = t
        found, res = det.detect(rgb, return_result=True)
        ev = rule.update(t, set(found))
        if ev == "armed":
            armed_at = t
        if ev == "success":
            success_at = t
        if ev and not quiet:
            print(f"  {t:6.1f}s  {ev:8s} {rule.summary()}  검출 {', '.join(f'{k} {v:.2f}' for k, v in sorted(found.items())) or '-'}")
        if writer_path is not None:
            import cv2

            img = res.plot()  # BGR, 마스크·박스 그려짐
            state = "SUCCESS" if success_at is not None else ("armed" if rule.armed else "arming")
            cv2.putText(img, f"{t:5.1f}s {state} {rule.summary().replace('진행', 'hold')}", (8, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 230, 40) if success_at is not None else (255, 255, 255), 1)
            if writer is None:
                h, w = img.shape[:2]
                writer = cv2.VideoWriter(str(writer_path), cv2.VideoWriter_fourcc(*"mp4v"), float(cfg["hz"]), (w, h))
            writer.write(img)
    if writer is not None:
        writer.release()
    # 성공 뒤 남은 프레임은 건너뛰었으므로 길이는 마지막으로 읽은 시각
    r = rule.ratios()
    holding = (rule.streak_start is not None and r[cfg["target"]] >= cfg["min_ratio"]
               and all(r[k] <= v for k, v in cfg["forbid"].items()))
    return {"label": label, "length": t, "armed_at": armed_at, "success_at": success_at,
            "summary": rule.summary(), "holding": holding}


def main():
    args = parse_args()
    cfg_path = Path(args.config).expanduser()
    cfg = load_config(cfg_path.parent)
    if cfg is None or cfg_path.name != "success.json":
        raise SystemExit("--config 는 번들 폴더의 success.json 이어야 해")
    if args.model:
        cfg["model"] = str(Path(args.model).expanduser().resolve())
    if not cfg["model"]:
        raise SystemExit("success.json 의 model 이 비어 있음 — --model 로 .pt 를 주거나 success.json 에 넣어줘")
    print(f"판단 규칙: {describe(cfg)}")
    print(f"모델: {cfg['model']}")
    det = Detector(cfg, args.device)
    out_dir = Path(args.out).expanduser() if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    if args.video:
        print(f"\n[{args.video}]")
        results.append(run_one(det, cfg, iter_frames(args.video), Path(args.video).name,
                               out_dir / f"{Path(args.video).stem}_judge.mp4" if out_dir else None, args.quiet))
    else:
        root = dataset_root(args.dataset)
        eps = dataset_episodes(root, args.camera or cfg["camera"])
        if args.episodes != "all":
            want = {int(x) for x in args.episodes.split(",") if x.strip()}
            eps = [e for e in eps if e[0] in want]
        for ep, path, start, end in eps:
            if not args.quiet:
                print(f"\n[에피소드 {ep}] {end - start:.1f}s")
            results.append(run_one(det, cfg, iter_frames(path, start, end), f"ep {ep}",
                                   out_dir / f"ep{ep:03d}_judge.mp4" if out_dir else None, args.quiet))

    print("\n=== 요약 ===")
    ok = 0
    for r in results:
        if r["success_at"] is not None:
            ok += 1
            print(f"{r['label']:>10}  성공 {r['success_at']:5.1f}s  (시작 확인 {r['armed_at']:.1f}s)")
        else:
            if r["armed_at"] is None:
                why = f"{cfg['arm_class']} 확인 못 함"
            elif r["holding"]:
                why = f"끝날 때 {cfg['target']} 유지 중이었음 — 영상이 끝나서 {cfg['hold_s']:g}초를 못 채움 ({r['summary']})"
            else:
                why = r["summary"]
            print(f"{r['label']:>10}  성공 안 남 (영상 {r['length']:.1f}s) — {why}")
    print(f"성공 {ok}/{len(results)}")
    if out_dir:
        print(f"검출 영상: {out_dir}")


if __name__ == "__main__":
    main()
