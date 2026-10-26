"""Send bounded training progress updates through an existing local Discord webhook."""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import json

from .common import read_json, utc_now, write_json

TERMINAL = {"completed", "incomplete", "failed", "stopped", "budget_reached"}


def alive(pid):
    """Distinguish active supervisor and worker processes from exited or zombie processes."""
    try:
        return Path(f"/proc/{int(pid)}/stat").read_text().split()[2] != "Z"
    except (OSError, TypeError, ValueError):
        return False


def snapshot(run):
    """Read durable status and the last log portion without loading any model or secret."""
    run = Path(run)
    state = read_json(run / "status.json")
    act044 = state.get("lerobot_version") == "0.4.4"
    simulation_path = run / "mujoco_comparison/status.json"
    simulation = read_json(simulation_path) if simulation_path.exists() else None
    if simulation:
        training_state = state
        state = {
            **simulation,
            "deadline_epoch": training_state["deadline_epoch"],
            "publication": "보고서 작성·게시 상태 별도 확인",
        }
    current = state.get("current_job")
    progress = {"step": None, "maximum": None}
    for kind in ["native", "trials", "final", "jobs"]:
        job = run / kind / str(current)
        if not current or not job.exists():
            continue
        status = read_json(job / "status.json") if (job / "status.json").exists() else {}
        progress.update(step=status.get("step"), upstream_alive=alive(status.get("upstream_pid")))
        for name in ["worker.pid", "process.pid"]:
            if (job / name).exists():
                progress["worker_alive"] = alive((job / name).read_text().strip())
        log = job / "upstream.log"
        if log.exists():
            with log.open("rb") as stream:
                stream.seek(max(0, log.stat().st_size - 32768))
                matches = re.findall(r"(\d+)/(\d+)\s*\[", stream.read().decode(errors="replace"))
            if matches:
                progress.update(step=int(matches[-1][0]), maximum=int(matches[-1][1]))
        break
    counts = {}
    for kind in ["native", "trials", "final", "jobs"]:
        results = [read_json(p) for p in (run / kind).glob("*/result.json")]
        counts[kind] = {
            "finished": len(results),
            "completed": sum(r["status"] == "completed" for r in results),
        }
    now = datetime.now(timezone.utc)
    elapsed = (now - datetime.fromisoformat(state["started_at"])).total_seconds()
    supervisor_alive = alive(state.get("pid"))
    terminal = state["status"] in TERMINAL and not supervisor_alive
    deadline = state.get("deadline_epoch")
    expired = deadline is not None and now.timestamp() > deadline + 3600 and not supervisor_alive
    marker = [
        current,
        progress["step"],
        state.get("completed_rollouts", sum(c["finished"] for c in counts.values())),
    ]
    previous_path = run / "discord_notification.json"
    previous = read_json(previous_path) if previous_path.exists() else {}
    stalled = previous.get("progress_marker") == marker and current is not None
    label = "종료" if terminal else "진행 중" if supervisor_alive else "감독 프로세스 중단 확인 필요"
    lines = [
        f"**OMX {'ACT 0.4.4 학습·검증' if act044 else 'MuJoCo 비교' if simulation else '재학습'} · {label}**",
        f"확인 시각: {now.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"누적 실행: {int(elapsed // 3600)}시간 {int(elapsed % 3600 // 60)}분 / "
        + ("시간 제한 없음" if deadline is None else "최대 12시간"),
        (
            f"학습 실행 완료 {counts['jobs']['completed']}/{state.get('expected_jobs', 12)} · "
            f"검증 비교 {state.get('completed_comparisons', 0)}/{state.get('expected_comparison_cells', 44)}"
            if act044
            else f"공식 ACT 완료 {counts['native']['completed']}/8 · "
            f"경량 완료 {counts['trials']['completed']}/48 · "
            f"전체 시연 재학습 완료 {counts['final']['completed']}/2"
        ),
        f"현재 작업: {current or '없음'}",
    ]
    if simulation:
        lines.append(
            f"신규 MuJoCo 실행: {state['completed_rollouts']}/{state['expected_rollouts']}회 · "
            f"기록 명령 재생 {state['completed_replays']}/6회"
        )
    if progress["step"] is not None:
        total = progress["maximum"]
        lines.append(
            f"현재 단계: {progress['step']:,}"
            + (f"/{total:,} ({progress['step'] / total:.1%})" if total else "")
        )
    if supervisor_alive:
        lines.append("자동 실행 감독기: 정상 실행 중")
    if progress.get("upstream_alive"):
        lines.append("공식 학습 프로세스: 실행 중")
    elif current and progress.get("worker_alive"):
        lines.append("작업 프로세스: 실행 중 (준비·저장·검증 단계일 수 있음)")
    limited = sum(c["finished"] - c["completed"] for c in counts.values())
    lines.append(f"작업 실패 기록: {len(state.get('failures', []))}건 · 완료 외 종료 상태: {limited}건")
    if stalled:
        lines.append(
            "⚠ 이전 알림 이후 작업·기록된 스텝 변화가 없습니다. 검증 중인지 정체인지 확인이 필요합니다."
        )
    if terminal or expired:
        lines.append(f"최종 상태: {state['status']} · Git 게시: {state.get('publication', '확인 필요')}")
        lines.append("이 실행의 30분 정기 알림을 종료합니다.")
    report = state.get("report_path", "lerobot044/report.html" if act044 else "report.html")
    lines.append(
        "보고서: https://github.com/kernel-robot-8th/kernel-robot-repo-4/blob/"
        f"feature/manipulation-mujoco-validation/docs/mujoco_validation/{report}"
    )
    return "\n".join(lines), {"progress_marker": marker, "terminal": terminal or expired}


def send(run, webhook_path, timer_unit=None, dry_run=False):
    """Confirm delivery and keep credentials out of logs, arguments, and repository files."""
    content, record = snapshot(run)
    if dry_run:
        print(content)
        return
    url = Path(webhook_path).read_text().strip()
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"discord.com", "discordapp.com"}:
        raise ValueError("Expected an existing Discord HTTPS webhook configuration")
    if not parsed.path.startswith("/api/webhooks/"):
        raise ValueError("Invalid webhook path")
    query = dict(parse_qsl(parsed.query))
    query["wait"] = "true"
    request = Request(
        urlunsplit(parsed._replace(query=urlencode(query))),
        data=json.dumps({"content": content, "allowed_mentions": {"parse": []}}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "OMX-Training-Progress/1.0"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        raise RuntimeError(f"Discord delivery failed: HTTP {error.code}") from None
    except Exception as error:
        raise RuntimeError(f"Discord delivery failed: {type(error).__name__}") from None
    record.update(sent_at=utc_now(), message_id=result["id"], notifier_pid=os.getpid())
    write_json(Path(run) / "discord_notification.json", record)
    print("DISCORD_PROGRESS_DELIVERED", record["sent_at"], record["message_id"], flush=True)
    if record["terminal"] and timer_unit:
        subprocess.run(["systemctl", "--user", "disable", "--now", timer_unit], check=True)


def main():
    """Run once from the user's training progress timer."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--webhook-file", default=str(Path.home() / ".local/share/codex-discord/webhook"))
    parser.add_argument("--timer-unit")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    send(args.run, args.webhook_file, args.timer_unit, args.dry_run)


if __name__ == "__main__":
    main()
