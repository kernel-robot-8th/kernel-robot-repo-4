"""Fit a deployment candidate on all collected data without inventing a held-out score."""

import argparse
from pathlib import Path
import time

import torch
from torch.utils.data import DataLoader, WeightedRandomSampler

from .common import read_json, utc_now, write_json
from .data import RecordingDataset, correction_sample_weights
from .learning import make_policy, prepare_batch, seed_everything
from .train import save_checkpoint


def refit_all(cache, config, output, budget_s=1800):
    """Use every declared training recording for a fixed validation-selected step count."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    seed_everything(config["seed"])
    split = config["split_plan"]
    if split["validation"] or split["test"]:
        raise ValueError("All-data refit must explicitly declare no independent evaluation set")
    data = RecordingDataset(cache, split["train"], config["horizon"], stride=3, split_plan=split)
    sampler = None
    if config.get("sampling") == "correction_balanced":
        sampler = WeightedRandomSampler(
            correction_sample_weights(data, config["correction_train_ids"]), len(data), replacement=True
        )
    loader = DataLoader(data, batch_size=config["batch_size"], sampler=sampler, shuffle=sampler is None)
    model = make_policy(config).cuda().train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["lr"], weight_decay=config["weight_decay"])
    started = time.monotonic()
    rows = []
    iterator = iter(loader)
    completed_step = 0
    for step in range(1, config["max_steps"] + 1):
        if time.monotonic() - started >= budget_s:
            break
        try:
            raw = next(iterator)
        except StopIteration:
            iterator = iter(loader)
            raw = next(iterator)
        batch = prepare_batch(
            raw, "cuda", augment=config.get("augmentation", False), state_noise=config.get("state_noise", 0.0)
        )
        loss, _ = model(batch)
        if not torch.isfinite(loss):
            raise RuntimeError("Non-finite all-data refit loss")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
        optimizer.step()
        completed_step = step
        if step == 1 or step % 250 == 0:
            row = {"step": step, "training_loss": loss.item(), "elapsed_s": time.monotonic() - started}
            rows.append(row)
            write_json(output / "status.json", {"status": "training_all_data", **row})
            save_checkpoint(output / "last.pt", model, optimizer, config, data.statistics, step)
            print(f"ALL_DATA_REFIT step={step} loss={loss.item():.4f}", flush=True)
    if completed_step == 0:
        raise RuntimeError("All-data fitting produced no optimizer updates")
    save_checkpoint(output / "final.pt", model, optimizer, config, data.statistics, completed_step)
    write_json(output / "normalization.json", data.statistics)
    result = {
        "status": "completed" if completed_step == config["max_steps"] else "budget_exhausted",
        "finished_at": utc_now(),
        "config": config,
        "steps": completed_step,
        "checkpoint": str(output / "final.pt"),
        "normalization_statistics": data.statistics,
        "training_recordings": split["train"],
        "independent_test_available": False,
        "elapsed_s": time.monotonic() - started,
        "history": rows,
        "scope": "All-data candidate, not a validated real-robot policy",
    }
    write_json(output / "result.json", result)
    return result


def main():
    """Launch all-data fitting in an isolated process."""
    p = argparse.ArgumentParser()
    p.add_argument("--cache", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--budget-s", type=float, default=1800)
    args = p.parse_args()
    refit_all(args.cache, read_json(args.config), args.output, args.budget_s)


if __name__ == "__main__":
    main()
