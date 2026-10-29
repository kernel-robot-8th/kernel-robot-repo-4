"""Merge several eval_open_loop.py output dirs into one dir that render_comparison.py can read.

Each source dir may come from a different dataset (e.g. omx_heart_box vs omx_heart_box_phases, which share
the same frames but differ in task text); the recorded actions must match, which is checked.

Usage: python -I sim/merge_eval.py --out outputs/eval/cmp_merged outputs/eval/cmp_holdout outputs/eval/cmp_phases
"""

import argparse
import json
import shutil
from pathlib import Path

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    metas = [(Path(s), json.loads((Path(s) / "metrics.json").read_text())) for s in args.sources]
    episodes = sorted(set.intersection(*(set(m["episodes"]) for _, m in metas)))
    if not episodes:
        raise SystemExit("no common episodes")

    ref = metas[0][0]
    for ep in episodes:
        gt = np.load(ref / f"gt_ep{ep:03d}.npy")
        for src, _ in metas[1:]:
            other = np.load(src / f"gt_ep{ep:03d}.npy")
            if gt.shape != other.shape or not np.allclose(gt, other):
                raise SystemExit(f"ep{ep:03d}: recorded actions differ between {ref} and {src}")
        np.save(out / f"gt_ep{ep:03d}.npy", gt)

    results, sources = {}, {}
    for src, m in metas:
        for name, r in m["results"].items():
            if name in results:
                raise SystemExit(f"model name '{name}' appears in more than one source")
            for ep in episodes:
                shutil.copy(src / f"pred_{name}_ep{ep:03d}.npy", out / f"pred_{name}_ep{ep:03d}.npy")
            r = dict(r, per_episode={k: v for k, v in r["per_episode"].items() if int(k) in episodes})
            results[name] = r
            sources[name] = {"eval_dir": str(src), "task_override": m.get("task_override")}

    meta = {"chunk": metas[0][1]["chunk"], "episodes": episodes, "units": metas[0][1]["units"],
            "sources": sources, "results": results}
    (out / "metrics.json").write_text(json.dumps(meta, indent=2))
    print(f"merged {list(results)} on episodes {episodes} -> {out}")
    for name, r in results.items():
        print(f"  {name:>10}: MAE mean {r['mae_mean']:.3f}  {r['mae_per_joint']}")


if __name__ == "__main__":
    main()
