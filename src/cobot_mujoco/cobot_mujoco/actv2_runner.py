"""Run all new-data ACT comparisons to completion, with no elapsed-time cutoff."""

import argparse
import fcntl
import html
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import traceback

from .act044_training import command, provenance
from .actv2_data import SPLIT, plan, prepare
from .actv2_evaluate import score
from .common import REPOSITORY, read_json, utc_now, write_json
from .runner import publish_report


def checkpoints(upstream):
    """Read only fully committed saves behind the upstream last marker."""
    last = Path(upstream) / "checkpoints/last"
    if not last.exists():
        return []
    maximum = int(last.resolve().name)
    return sorted(
        [
            p
            for p in last.parent.glob("*/pretrained_model")
            if p.parent.name.isdigit()
            and int(p.parent.name) <= maximum
            and (p / "policy_postprocessor.json").exists()
        ],
        key=lambda p: int(p.parent.name),
    )


def prune(upstream):
    """Keep comparison saves and latest recovery save to bound checkpoint disk use."""
    ready = checkpoints(upstream)
    if not ready:
        return
    keep = {10000, 20000, 40000, int(ready[-1].parent.name)}
    for path in ready:
        if int(path.parent.name) not in keep:
            shutil.rmtree(path.parent)


def render(run, state):
    """Publish a live, explicit comparison table without claiming robot success."""
    run = Path(run)
    root = REPOSITORY / "docs/mujoco_validation/lerobot044_v2"
    root.mkdir(parents=True, exist_ok=True)
    measurements, results = [], []
    for job in (run / "jobs").glob("*"):
        if (job / "measurements.json").exists():
            measurements.extend(read_json(job / "measurements.json"))
        if (job / "result.json").exists():
            results.append(read_json(job / "result.json"))
    state.update(
        completed_jobs=sum(r["status"] == "completed" for r in results),
        completed_comparisons=len(measurements),
        updated_at=utc_now(),
    )
    write_json(run / "status.json", state)
    for name in [
        "plan.json",
        "provenance.json",
        "source_manifest.json",
        "status.json",
        "selected.json",
        "heldout.json",
    ]:
        if (run / name).exists():
            shutil.copyfile(run / name, root / name)
    write_json(root / "comparison_measurements.json", measurements)
    write_json(root / "job_results.json", results)
    rows = []
    for row in measurements:
        cfg, val = row["config"], row["validation"]
        metrics = [v["ensemble001"] for v in val["per_episode"].values()]
        grip = sum(v["gripper_mae"] for v in metrics) / len(metrics)
        missed = sum(v["missed_open"] for v in metrics)
        rows.append(
            f"<tr><td>{html.escape(cfg['name'])}</td><td>{row['step']:,}</td>"
            f"<td>{val['control_mae']:.4f}</td><td>{grip:.4f}</td><td>{missed}</td>"
            f"<td>{row['gap']:.4f}</td></tr>"
        )
    content = f"""<!doctype html><html lang="ko"><meta charset="utf-8"><title>1026 v2 ACT 비교</title>
<style>body{{font:16px/1.7 system-ui;margin:40px;color:#182236}}
table{{border-collapse:collapse}}td,th{{padding:10px;border:1px solid #ccd3df}}
th{{background:#edf2fa}}</style>
<h1>1026 JiHyeok v2 · ACT 0.4.4 재학습</h1>
<p>갱신 {state["updated_at"]} · 상태 {state["status"]} · 현재 {state.get("current_job") or "없음"}</p>
<p>학습 완료 {state["completed_jobs"]}/25 · 비교 {len(measurements)}/75 · 시간 제한 없음</p>
<p>구조 일반형·경량형 × 전류 미포함·그리퍼 전류 포함 × 배치 8·16 × chunk 32·64·100.
각 실행 10,000·20,000·40,000 step 비교. 같은 step에서 배치 16은 배치 8보다 샘플 노출이 2배다.</p>
<p>추가 마지막 실험: 일반형·전류 포함·chunk32·배치32. 메모리 부족 시 배치를 바꿔 실행하지 않고 실패를 기록한다.</p>
<p>원본 성공 9회 / 5,671프레임. 학습 [0,1,3,4,5,7] 3,820프레임,
검증 [2,6] 1,235프레임, 평가용 보류 [8] 616프레임. 전류는 raw signed 그리퍼 Present_Current 1개를 상태 뒤에 추가.</p>
<p>검증 전체 프레임에서 앞 10스텝 MAE를 계산하며 에피소드별 동일 가중 평균으로 선택한다.
별도로 실행 구간 1의 그리퍼 MAE·열림/닫힘 시점과 누락을 앙상블 OFF/계수 0.01에서 비교한다.
기록 영상 기반 평가이며 실물 성공률이 아니다. 보류 에피소드는 선택 확정 후 한 번 평가한다.</p>
<p>주 학습률/백본 학습률 1e-5, 감쇠 1e-4, dropout 0.1, seed 17, 원본 영상 640×480 두 개.
일반형 512/3200/4층, 경량형 128/512/2층. 증강 OFF. Init 이동·로봇 구동 없음.</p>
<p>매 1,000 step 저장하되 디스크를 위해 비교 10k/20k/40k와 최신 복구 저장본만 보존한다.
12시간 및 작업별 시간 종료 없음. STOP 파일은 사용자의 수동 중지에만 사용한다.</p>
<table><tr><th>학습</th><th>step</th><th>검증 앞10 MAE</th><th>앙상블 그리퍼 MAE</th>
<th>열림 누락</th><th>검증−학습 MAE</th></tr>{"".join(rows)}</table>
<p>실패 기록: {html.escape(str(state.get("failures", [])))}</p></html>"""
    (root / "report.html").write_text(content)
    return root


def training_command(root, output, cfg):
    """Use the original 0.4.4 trainer with an explicit local data identity."""
    args = command(root, output, cfg)
    return ["--dataset.repo_id=local/omx1026_v2" if a.startswith("--dataset.repo_id=") else a for a in args]


def job(run, cfg, state):
    """Resume official optimizer checkpoints, then score the three comparison saves."""
    output = run / "jobs" / cfg["name"]
    output.mkdir(parents=True, exist_ok=True)
    root = run / "datasets" / ("current" if cfg["current"] else "position")
    write_json(output / "config.json", cfg)
    saved = checkpoints(output / "upstream")
    if not saved or int(saved[-1].parent.name) < cfg["steps"]:
        args = training_command(root, output / "upstream", cfg)
        if saved:
            args += [f"--config_path={saved[-1] / 'train_config.json'}", "--resume=true"]
        elif (output / "upstream").exists():
            (output / "upstream").rename(output / f"upstream_incomplete_{time.time_ns()}")
        write_json(output / "command.json", args)
        with (output / "upstream.log").open("a") as log:
            process = subprocess.Popen(
                args,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={**os.environ, "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4"},
            )
            write_json(output / "status.json", {"status": "training", "upstream_pid": process.pid})
            while process.poll() is None:
                if (run / "STOP").exists():
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=30)
                    raise InterruptedError("User STOP request")
                prune(output / "upstream")
                render(run, state)
                time.sleep(15)
        if process.returncode:
            raise RuntimeError(f"Upstream trainer exited {process.returncode}: {output / 'upstream.log'}")
    prune(output / "upstream")
    measurements = read_json(output / "measurements.json") if (output / "measurements.json").exists() else []
    for step in cfg["comparison_steps"]:
        if any(r["step"] == step for r in measurements):
            continue
        if (run / "STOP").exists():
            raise InterruptedError("User STOP request")
        checkpoint = output / "upstream/checkpoints" / f"{step:06d}/pretrained_model"
        state.update(phase="validation", current_step=step)
        render(run, state)
        write_json(output / "status.json", {"status": "validating", "step": step})
        validation = score(checkpoint, root, SPLIT["validation"])
        fitted = score(checkpoint, root, SPLIT["train"], stride=24)
        measurements.append(
            {
                "step": step,
                "checkpoint": str(checkpoint),
                "config": cfg,
                "validation": validation,
                "training_probe": fitted,
                "gap": validation["control_mae"] - fitted["control_mae"],
            }
        )
        write_json(output / "measurements.json", measurements)
        render(run, state)
    write_json(
        output / "result.json",
        {"status": "completed", "config": cfg, "actual_steps": 40000, "finished_at": utc_now()},
    )


def main():
    """Supervise every planned job, survive restarts, and publish the complete comparison."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    run = args.run
    run.mkdir(parents=True, exist_ok=True)
    lock = (run / "supervisor.lock").open("w")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    frozen_plan = plan()
    if (run / "plan.json").exists() and read_json(run / "plan.json") != frozen_plan:
        raise ValueError("Frozen plan differs")
    write_json(run / "plan.json", frozen_plan)
    write_json(run / "provenance.json", provenance())
    prepare(args.source, run)
    if args.prepare_only:
        return
    prior = read_json(run / "status.json") if (run / "status.json").exists() else {}
    state = {
        "status": "running",
        "phase": "training",
        "pid": os.getpid(),
        "started_at": prior.get("started_at", utc_now()),
        "deadline_epoch": None,
        "time_limit": None,
        "lerobot_version": "0.4.4",
        "expected_jobs": 25,
        "expected_comparison_cells": 75,
        "report_path": "lerobot044_v2/report.html",
        "current_job": None,
        "failures": [],
        "publication": "pending",
    }
    try:
        for cfg in frozen_plan["trials"]:
            if (run / "STOP").exists():
                raise InterruptedError("User STOP request")
            output = run / "jobs" / cfg["name"]
            if (output / "result.json").exists():
                continue
            state.update(current_job=cfg["name"], phase="training")
            render(run, state)
            for attempt in range(2):
                try:
                    job(run, cfg, state)
                    break
                except InterruptedError:
                    raise
                except Exception:
                    (output / f"error_attempt_{attempt + 1}.log").write_text(traceback.format_exc())
                    if attempt:
                        state["failures"].append(cfg["name"])
            root = render(run, state)
            try:
                publish_report(root)
                state["publication"] = "pushed"
            except Exception as error:
                state["publication"] = str(error)
        if not state["failures"]:
            selected = {}
            for architecture in ["standard", "light"]:
                for current in [False, True]:
                    rows = []
                    for cfg in frozen_plan["trials"]:
                        if cfg["architecture"] == architecture and cfg["current"] == current:
                            rows.extend(read_json(run / "jobs" / cfg["name"] / "measurements.json"))
                    selected[f"{architecture}_{'current' if current else 'position'}"] = min(
                        rows, key=lambda r: r["validation"]["control_mae"]
                    )
            write_json(run / "selected.json", selected)
            heldout = read_json(run / "heldout.json") if (run / "heldout.json").exists() else {}
            for name, row in selected.items():
                if name in heldout:
                    continue
                state.update(current_job=row["config"]["name"], phase="heldout_evaluation")
                render(run, state)
                root = run / "datasets" / ("current" if row["config"]["current"] else "position")
                heldout[name] = score(row["checkpoint"], root, SPLIT["test"])
                write_json(run / "heldout.json", heldout)
        state["status"] = "incomplete" if state["failures"] else "completed"
    except InterruptedError:
        state["status"] = "stopped"
    finally:
        state.update(current_job=None, finished_at=utc_now(), phase="finished")
        root = render(run, state)
        try:
            publish_report(root)
            state["publication"] = "pushed"
        except Exception as error:
            state["publication"] = str(error)
        render(run, state)


if __name__ == "__main__":
    main()
