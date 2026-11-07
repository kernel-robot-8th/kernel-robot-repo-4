import json
from pathlib import Path

from .recorder import KINDS


def whoami() -> str | None:
    try:
        from huggingface_hub import HfApi

        return HfApi().whoami()["name"]
    except Exception:  # noqa: BLE001
        return None


def login(token: str) -> str | None:
    from huggingface_hub import login as hf_login

    hf_login(token=token, add_to_git_credential=False)
    return whoami()


def push_task(task_dir: Path, task_name: str, user: str, private: bool, log=print) -> list[str]:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    pushed = []
    for kind in KINDS:
        root = Path(task_dir) / kind
        info = root / "meta" / "info.json"
        if not info.exists() or json.loads(info.read_text()).get("total_episodes", 0) == 0:
            log(f"[HF] {kind}: 에피소드 없음, 건너뜀")
            continue
        repo_id = f"{user}/{task_name}_{kind}"
        log(f"[HF] {repo_id} 업로드 시작 (private={private})")
        ds = LeRobotDataset(repo_id, root=root)
        ds.push_to_hub(private=private, tags=["omx", "lerobot", kind])
        pushed.append(repo_id)
        log(f"[HF] {repo_id} 업로드 완료")
    return pushed
